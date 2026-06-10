/**
 * 消费者聊天页 SSE 交互逻辑
 *
 * 聚宝赞端始终传递 session_id 和 user_id：
 * - session_id 已存在 → 继续对话
 * - session_id 不存在 → 自动创建新会话
 */
(function() {
    const TID = window.TENANT_ID;
    const USER_ID = window.USER_ID || localStorage.getItem(`user_${TID}`) || '';
    let sessionId = localStorage.getItem(`session_${TID}`) || '';
    let isStreaming = false;
    let currentAIBubble = null;

    const chatArea = document.getElementById('chatArea');
    const messageInput = document.getElementById('messageInput');
    const sendBtn = document.getElementById('sendBtn');
    const newSessionBtn = document.getElementById('newSessionBtn');
    const typingIndicator = document.getElementById('typingIndicator');
    const statusText = document.getElementById('statusText');

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
        return 'sess_' + Date.now() + '_' + Math.random().toString(36).substring(2, 10);
    }

    async function loadHistory() {
        if (!sessionId) return;
        try {
            const resp = await fetch(`/api/v1/chat/${TID}/history/${sessionId}?user_id=${encodeURIComponent(USER_ID)}`, {
                headers: { 'X-Gateway-Verified': 'true' }
            });
            if (!resp.ok) return;
            const data = await resp.json();
            chatArea.innerHTML = '';
            for (const msg of data.messages) {
                createMessageBubble(msg.role, msg.content);
            }
            scrollToBottom();
        } catch (e) {
            console.error('加载历史失败:', e);
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

        let streamTimeoutId = null;
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
            var abortController = new AbortController();
            var timeoutId = setTimeout(function() { abortController.abort(); }, 120000);

            const resp = await fetch(`/api/v1/chat/${TID}/stream`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Gateway-Verified': 'true'
                },
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
            let fullText = '';
            let lastDataTime = Date.now();
            streamTimeoutId = setInterval(function() {
                if (Date.now() - lastDataTime > 60000) {
                    if (currentAIBubble && !fullText) {
                        currentAIBubble.innerHTML = '<span style="color:#FF7675;">服务响应超时，请稍后重试</span>';
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
                            if (currentAIBubble) {
                                currentAIBubble.innerHTML = escapeHtml(fullText).replace(/\n/g, '<br>');
                            }
                            scrollToBottom();
                        } else if (event.type === 'status') {
                            if (event.action === 'start') {
                                if (statusText) {
                                    statusText.textContent = { 'classify_intent': '正在分析问题...', 'retrieve_knowledge': '正在查找知识库...', 'generate_answer': '正在生成回答...', 'greeting_answer': '正在响应...', 'order_query_node': '正在查询订单...', 'logistics_query_node': '正在查询物流...', 'complaint_node': '正在转接人工...', 'human_service_node': '正在转接人工...' }[event.node] || '处理中...';
                                }
                            } else if (event.action === 'end') {
                                if (statusText) statusText.textContent = '';
                            }
                        } else if (event.type === 'done') {
                            if (event.session_id) {
                                sessionId = event.session_id;
                                localStorage.setItem(`session_${TID}`, sessionId);
                            }
                        } else if (event.type === 'error') {
                            if (currentAIBubble) {
                                currentAIBubble.innerHTML = `<span style="color:#FF7675;">${escapeHtml(event.message)}</span>`;
                            }
                        }
                    } catch (e) {
                        console.warn('SSE解析异常:', e, trimmed.slice(0, 100));
                    }
                }
            }
        } catch (e) {
            console.error('发送消息失败:', e);
            clearTimeout(timeoutId);
            if (currentAIBubble) {
                var errMsg = e.name === 'AbortError' ? '请求超时，请稍后重试' : '服务暂时不可用，请稍后重试';
                currentAIBubble.innerHTML = '<span style="color:#FF7675;">' + errMsg + '</span>';
            }
        } finally {
            clearTimeout(timeoutId);
            if (streamTimeoutId) clearInterval(streamTimeoutId);
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
        messageInput.focus();
    });

    loadHistory();
    messageInput.focus();
})();
