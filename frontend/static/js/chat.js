/**
 * 消费者聊天页 SSE 交互逻辑
 *
 * 聚宝赞端始终传递 session_id 和 user_id：
 * - session_id 已存在 → 继续对话
 * - session_id 不存在 → 自动创建新会话
 */
(function() {
    const TID = document.querySelector('meta[name="tenant-id"]')?.content || '';
    let sessionId = localStorage.getItem(`session_${TID}`) || '';

    // 优先从 URL 参数获取 user_id（由聚宝赞端传入），否则生成临时 ID
    const USER_ID = new URLSearchParams(window.location.search).get('user_id')
        || `u_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    let isStreaming = false;
    let currentAIBubble = null;
    let lastUserMessage = '';          // 上一条用户消息（用于重试）
    let hasReceivedAIReply = false;    // 是否已收到AI回复（控制快捷问题隐藏）

    const chatArea = document.getElementById('chatArea');
    const messageInput = document.getElementById('messageInput');
    const sendBtn = document.getElementById('sendBtn');
    const newSessionBtn = document.getElementById('newSessionBtn');
    const typingIndicator = document.getElementById('typingIndicator');
    const statusText = document.getElementById('statusText');
    const quickQuestions = document.getElementById('quickQuestions');

    // 状态文案映射表
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
        const div = document.createElement('div');
        div.className = `message ${role}`;
        div.innerHTML = role === 'user'
            ? `<div class="message-bubble user-bubble">${escapeHtml(content)}</div>`
            : `<div class="message-avatar">AI</div><div class="message-bubble ai-bubble">${escapeHtml(content)}</div>`;
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
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML.replace(/\n/g, '<br>');
    }

    function generateSessionId() {
        // 使用 crypto.randomUUID() 生成密码学安全的会话 ID
        return 'sess_' + crypto.randomUUID();
    }

    /**
     * 显示快捷问题引导区域
     */
    function showQuickQuestions() {
        if (quickQuestions) quickQuestions.classList.add('visible');
    }

    /**
     * 隐藏快捷问题引导区域
     */
    function hideQuickQuestions() {
        if (quickQuestions) quickQuestions.classList.remove('visible');
    }

    /**
     * 在AI消息旁挂载重试按钮
     * :param messageDiv: AI消息包裹元素（.message.assistant）
     * :param message: 需要重试发送的用户消息文本
     * :param aiBubble: AI气泡DOM元素
     */
    function attachRetryButton(messageDiv, message, aiBubble) {
        if (!messageDiv) return;
        // 先移除已有重试按钮，避免重复
        messageDiv.querySelectorAll('.message-retry').forEach(function(b) { b.remove(); });

        const retryBtn = document.createElement('button');
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
            const ok = await streamAssistantResponse(message, aiBubble, messageDiv);
            if (ok) {
                // 成功后移除重试按钮
                messageDiv.querySelectorAll('.message-retry').forEach(function(b) { b.remove(); });
            } else {
                // 失败时 streamAssistantResponse 已挂载新的重试按钮；
                // 兜底：重置可能残留的 loading 状态按钮
                const loadingBtn = messageDiv.querySelector('.message-retry.loading');
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

    /**
     * 流式获取AI回复并更新气泡
     * :param message: 用户消息文本
     * :param aiBubble: AI气泡DOM元素
     * :param messageDiv: 包裹AI消息的DOM元素（用于挂载重试按钮）
     * :return: Promise<boolean> 是否成功完成（收到done事件视为成功）
     */
    async function streamAssistantResponse(message, aiBubble, messageDiv) {
        let streamTimeoutId = null;
        let timeoutId = null;
        let abortController = null;
        let fullText = '';
        let succeeded = false;

        try {
            abortController = new AbortController();
            timeoutId = setTimeout(function() { abortController.abort(); }, 120000);

            const resp = await fetch(`/api/v1/chat/${TID}/stream`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: message, session_id: sessionId, user_id: USER_ID }),
                signal: abortController.signal
            });

            if (!resp.ok) {
                const errText = await resp.text();
                throw new Error(errText);
            }

            clearTimeout(timeoutId);

            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let lastDataTime = Date.now();
            streamTimeoutId = setInterval(function() {
                if (Date.now() - lastDataTime > 60000) {
                    if (aiBubble && !fullText) {
                        aiBubble.innerHTML = '<span style="color:#FF7675;">服务响应超时，请稍后重试</span>';
                    }
                    reader.cancel();
                }
            }, 5000);

            while (true) {
                const { done, value } = await reader.read();

                if (done) break;

                lastDataTime = Date.now();
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    const trimmed = line.trim();
                    if (!trimmed.startsWith('data: ')) continue;

                    try {
                        const event = JSON.parse(trimmed.slice(6));

                        if (event.type === 'text') {
                            hideTyping();
                            fullText += event.content;
                            if (aiBubble) {
                                aiBubble.innerHTML = escapeHtml(fullText).replace(/\n/g, '<br>');
                            }
                            // 收到第一条AI回复后隐藏快捷问题
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
                                localStorage.setItem(`session_${TID}`, sessionId);
                            }
                            // 成功完成后移除重试按钮
                            if (messageDiv) {
                                messageDiv.querySelectorAll('.message-retry').forEach(function(b) { b.remove(); });
                            }
                        } else if (event.type === 'error') {
                            if (aiBubble) {
                                aiBubble.innerHTML = `<span style="color:#FF7675;">${escapeHtml(event.message)}</span>`;
                            }
                            // AI回复失败时显示重试按钮
                            attachRetryButton(messageDiv, message, aiBubble);
                        }
                    } catch (e) {
                        console.warn('SSE解析异常:', e, trimmed.slice(0, 100));
                    }
                }
            }
        } catch (e) {
            console.error('发送消息失败:', e);
            clearTimeout(timeoutId);
            if (aiBubble) {
                const errMsg = e.name === 'AbortError' ? '请求超时，请稍后重试' : '服务暂时不可用，请稍后重试';
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
            // 新会话：展示快捷问题引导
            showQuickQuestions();
            return;
        }
        try {
            const resp = await fetch(`/api/v1/chat/${TID}/history/${sessionId}?user_id=${encodeURIComponent(USER_ID)}`, {
                headers: {}
            });
            if (!resp.ok) {
                showQuickQuestions();
                return;
            }
            const data = await resp.json();
            chatArea.innerHTML = '';
            if (data.messages && data.messages.length) {
                for (const msg of data.messages) {
                    createMessageBubble(msg.role, msg.content);
                }
                hasReceivedAIReply = true;
                scrollToBottom();
            } else {
                // 空会话：展示快捷问题引导
                showQuickQuestions();
            }
        } catch (e) {
            console.error('加载历史失败:', e);
            showQuickQuestions();
        }
    }

    async function sendMessage() {
        const message = messageInput.value.trim();
        if (!message || isStreaming) return;

        // 确保 session_id 存在（首次对话自动生成）
        if (!sessionId) {
            sessionId = generateSessionId();
            localStorage.setItem(`session_${TID}`, sessionId);
        }

        isStreaming = true;
        sendBtn.disabled = true;
        messageInput.value = '';
        createMessageBubble('user', message);
        showTyping();

        const currentAIBubbleDiv = document.createElement('div');
        currentAIBubbleDiv.className = 'message assistant';
        currentAIBubbleDiv.innerHTML = '<div class="message-avatar">AI</div><div class="message-bubble ai-bubble"></div>';
        chatArea.appendChild(currentAIBubbleDiv);
        currentAIBubble = currentAIBubbleDiv.querySelector('.ai-bubble');

        try {
            await streamAssistantResponse(message, currentAIBubble, currentAIBubbleDiv);
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
        // 生成新的 session_id 即为新会话
        sessionId = generateSessionId();
        localStorage.setItem(`session_${TID}`, sessionId);
        chatArea.innerHTML = '';
        if (statusText) statusText.textContent = '';
        hasReceivedAIReply = false;
        // 新会话展示快捷问题引导
        showQuickQuestions();
        messageInput.focus();
    });

    // 快捷问题按钮点击：自动填入输入框并发送
    if (quickQuestions) {
        quickQuestions.addEventListener('click', function(e) {
            const btn = e.target.closest('.quick-question-btn');
            if (!btn) return;
            const q = btn.getAttribute('data-q');
            if (!q) return;
            messageInput.value = q;
            sendMessage();
        });
    }

    loadHistory();
    messageInput.focus();
})();
