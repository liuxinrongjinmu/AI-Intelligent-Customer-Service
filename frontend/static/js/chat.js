/**
 * 消费者聊天页 SSE 交互逻辑
 *
 * 聚宝赞端始终传递 session_id 和 user_id：
 * - session_id 已存在 → 继续对话
 * - session_id 不存在 → 自动创建新会话
 */
(function() {
    const TID = document.querySelector('meta[name="tenant-id"]')?.content || '';

    // 安全访问 localStorage（隐私模式/无痕浏览可能不可用）
    let sessionId = '';
    let storageAvailable = true;
    try {
        sessionId = localStorage.getItem('session_' + TID) || '';
    } catch (e) {
        storageAvailable = false;
    }

    // 优先从 URL 参数获取 user_id（由聚宝赞端传入），否则生成临时 ID
    const USER_ID = new URLSearchParams(window.location.search).get('user_id')
        || 'u_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    let isStreaming = false;
    let currentAIBubble = null;
    let hasReceivedAIReply = false;

    const chatArea = document.getElementById('chatArea');
    const messageInput = document.getElementById('messageInput');
    const sendBtn = document.getElementById('sendBtn');
    const newSessionBtn = document.getElementById('newSessionBtn');
    const typingIndicator = document.getElementById('typingIndicator');
    const statusText = document.getElementById('statusText');
    const quickQuestions = document.getElementById('quickQuestions');

    const STATUS_MAP = {
        'classify_intent': '正在分析问题...',
        'retrieve_knowledge': '正在查找知识库...',
        'generate_answer': '正在生成回答...',
        'greeting_answer': '正在响应...',
        'order_query_node': '正在查询订单...',
        'logistics_query_node': '正在查询物流...',
        'complaint_node': '正在转接人工...',
        'human_service_node': '正在转接人工...'
    };

    function scrollToBottom() {
        chatArea.scrollTop = chatArea.scrollHeight;
    }

    function createMessageBubble(role, content) {
        var div = document.createElement('div');
        div.className = 'message ' + role;
        div.innerHTML = role === 'user'
            ? '<div class="message-bubble user-bubble">' + escapeHtml(content) + '</div>'
            : '<div class="message-avatar">AI</div><div class="message-bubble ai-bubble">' + escapeHtml(content) + '</div>';
        chatArea.appendChild(div);
        scrollToBottom();
        return div;
    }

    function showTyping() {
        if (!typingIndicator) return;
        typingIndicator.style.display = 'flex';
        scrollToBottom();
    }

    function hideTyping() {
        if (!typingIndicator) return;
        typingIndicator.style.display = 'none';
    }

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML.replace(/\n/g, '<br>');
    }

    function generateSessionId() {
        try {
            return 'sess_' + crypto.randomUUID();
        } catch (e) {
            return 'sess_' + Date.now() + '_' + Math.random().toString(36).substr(2, 10);
        }
    }

    function saveSessionId(id) {
        if (!storageAvailable) return;
        try { localStorage.setItem('session_' + TID, id); } catch (e) {}
    }

    function showQuickQuestions() {
        if (quickQuestions) quickQuestions.classList.add('visible');
    }

    function hideQuickQuestions() {
        if (quickQuestions) quickQuestions.classList.remove('visible');
    }

    function attachRetryButton(messageDiv, message, aiBubble) {
        if (!messageDiv) return;
        messageDiv.querySelectorAll('.message-retry').forEach(function(b) { b.remove(); });

        var retryBtn = document.createElement('button');
        retryBtn.className = 'message-retry';
        retryBtn.type = 'button';
        retryBtn.textContent = '重试';
        retryBtn.addEventListener('click', async function() {
            if (isStreaming) return;
            isStreaming = true;
            sendBtn.disabled = true;
            retryBtn.classList.add('loading');
            retryBtn.textContent = '重试中...';
            if (aiBubble) aiBubble.innerHTML = '';
            showTyping();
            var ok = await streamAssistantResponse(message, aiBubble, messageDiv);
            if (ok) {
                messageDiv.querySelectorAll('.message-retry').forEach(function(b) { b.remove(); });
            } else {
                var loadingBtn = messageDiv.querySelector('.message-retry.loading');
                if (loadingBtn) {
                    loadingBtn.classList.remove('loading');
                    loadingBtn.textContent = '重试';
                }
            }
            isStreaming = false;
            sendBtn.disabled = false;
            hideTyping();
            messageInput.focus();
        });
        messageDiv.appendChild(retryBtn);
    }

    async function streamAssistantResponse(message, aiBubble, messageDiv) {
        var streamTimeoutId = null;
        var timeoutId = null;
        var abortController = null;
        var fullText = '';
        var succeeded = false;

        try {
            abortController = new AbortController();
            timeoutId = setTimeout(function() { abortController.abort(); }, 120000);

            var resp = await fetch('/api/v1/chat/' + TID + '/stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: message, session_id: sessionId, user_id: USER_ID }),
                signal: abortController.signal
            });

            if (!resp.ok) {
                var errText = await resp.text();
                throw new Error(errText);
            }

            clearTimeout(timeoutId);

            var reader = resp.body.getReader();
            var decoder = new TextDecoder();
            var buffer = '';
            var lastDataTime = Date.now();
            streamTimeoutId = setInterval(function() {
                if (Date.now() - lastDataTime > 60000) {
                    if (aiBubble && !fullText) {
                        aiBubble.innerHTML = '<span style="color:#FF7675;">服务响应超时，请稍后重试</span>';
                    }
                    reader.cancel();
                }
            }, 5000);

            while (true) {
                var chunk = await reader.read();
                if (chunk.done) break;

                lastDataTime = Date.now();
                buffer += decoder.decode(chunk.value, { stream: true });
                var lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (var i = 0; i < lines.length; i++) {
                    var trimmed = lines[i].trim();
                    if (!trimmed.startsWith('data: ')) continue;

                    try {
                        var event = JSON.parse(trimmed.slice(6));

                        if (event.type === 'text') {
                            hideTyping();
                            fullText += event.content;
                            if (aiBubble) {
                                aiBubble.innerHTML = escapeHtml(fullText).replace(/\n/g, '<br>');
                            }
                            if (!hasReceivedAIReply) {
                                hasReceivedAIReply = true;
                                hideQuickQuestions();
                            }
                            scrollToBottom();
                        } else if (event.type === 'status') {
                            if (event.action === 'start') {
                                if (statusText) {
                                    statusText.textContent = STATUS_MAP[event.node] || '处理中...';
                                }
                            } else if (event.action === 'end') {
                                if (statusText) statusText.textContent = '';
                            }
                        } else if (event.type === 'done') {
                            succeeded = true;
                            if (event.session_id) {
                                sessionId = event.session_id;
                                saveSessionId(sessionId);
                            }
                            if (messageDiv) {
                                messageDiv.querySelectorAll('.message-retry').forEach(function(b) { b.remove(); });
                            }
                        } else if (event.type === 'error') {
                            if (aiBubble) {
                                aiBubble.innerHTML = '<span style="color:#FF7675;">' + escapeHtml(event.message) + '</span>';
                            }
                            attachRetryButton(messageDiv, message, aiBubble);
                        }
                    } catch (e) {
                        // SSE 解析异常，跳过该行继续
                    }
                }
            }
        } catch (e) {
            clearTimeout(timeoutId);
            if (aiBubble) {
                var errMsg = e.name === 'AbortError' ? '请求超时，请稍后重试' : '服务暂时不可用，请稍后重试';
                aiBubble.innerHTML = '<span style="color:#FF7675;">' + errMsg + '</span>';
            }
            attachRetryButton(messageDiv, message, aiBubble);
        } finally {
            clearTimeout(timeoutId);
            if (streamTimeoutId) clearInterval(streamTimeoutId);
        }
        return succeeded;
    }

    async function loadHistory() {
        if (!sessionId) {
            showQuickQuestions();
            return;
        }
        try {
            var resp = await fetch('/api/v1/chat/' + TID + '/history/' + sessionId + '?user_id=' + encodeURIComponent(USER_ID), {
                headers: {}
            });
            if (!resp.ok) {
                showQuickQuestions();
                return;
            }
            var data = await resp.json();
            chatArea.innerHTML = '';
            if (data.messages && data.messages.length) {
                for (var i = 0; i < data.messages.length; i++) {
                    createMessageBubble(data.messages[i].role, data.messages[i].content);
                }
                hasReceivedAIReply = true;
                scrollToBottom();
            } else {
                showQuickQuestions();
            }
        } catch (e) {
            showQuickQuestions();
        }
    }

    async function sendMessage() {
        var message = messageInput.value.trim();
        if (!message || isStreaming) return;

        if (!sessionId) {
            sessionId = generateSessionId();
            saveSessionId(sessionId);
        }

        isStreaming = true;
        sendBtn.disabled = true;
        messageInput.value = '';
        createMessageBubble('user', message);
        showTyping();

        var aiDiv = document.createElement('div');
        aiDiv.className = 'message assistant';
        aiDiv.innerHTML = '<div class="message-avatar">AI</div><div class="message-bubble ai-bubble"></div>';
        chatArea.appendChild(aiDiv);
        currentAIBubble = aiDiv.querySelector('.ai-bubble');

        try {
            await streamAssistantResponse(message, currentAIBubble, aiDiv);
        } finally {
            isStreaming = false;
            sendBtn.disabled = false;
            hideTyping();
            currentAIBubble = null;
            messageInput.focus();
        }
    }

    sendBtn.addEventListener('click', sendMessage);
    messageInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    newSessionBtn.addEventListener('click', function() {
        sessionId = generateSessionId();
        saveSessionId(sessionId);
        chatArea.innerHTML = '';
        if (statusText) statusText.textContent = '';
        hasReceivedAIReply = false;
        showQuickQuestions();
        messageInput.focus();
    });

    if (quickQuestions) {
        quickQuestions.addEventListener('click', function(e) {
            var btn = e.target.closest('.quick-question-btn');
            if (!btn) return;
            var q = btn.getAttribute('data-q');
            if (!q) return;
            messageInput.value = q;
            sendMessage();
        });
    }

    loadHistory();
    messageInput.focus();
})();
