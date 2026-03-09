<script setup lang="ts">
import hljs from 'highlight.js';
import 'highlight.js/styles/github.css';
import type MarkdownItType from 'markdown-it';
import MarkdownIt from 'markdown-it';
import { nextTick, onMounted, ref } from 'vue';

const API_BASE = import.meta.env.VITE_API_BASE || '/api';

const md: MarkdownItType = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true,
  highlight: function (str: string, lang: string) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return '<pre class="hljs"><code>' +
               hljs.highlight(str, { language: lang, ignoreIllegals: true }).value +
               '</code></pre>';
      } catch { /* empty */ }
    }
    return '<pre class="hljs"><code>' + md.utils.escapeHtml(str) + '</code></pre>';
  }
});

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

const inputText = ref('');
const messages = ref<Message[]>([]);
const isLoading = ref(false);
const isThinking = ref(false);
const abortController = ref<AbortController | null>(null);
const currentSessionId = ref(localStorage.getItem('sessionId') || '');

const sendMessage = async () => {
  if (!inputText.value.trim() || isLoading.value) return;
  if (!currentSessionId.value) {
    console.error('sessionId is empty!');
    alert('会话未创建，请刷新页面');
    return;
  }

  abortController.value = new AbortController();
  const signal = abortController.value.signal;

  const userQuery = inputText.value;
  inputText.value = '';
  isLoading.value = true;
  isThinking.value = true;

  messages.value.push({ role: 'user', content: userQuery });
  const aiMessageIndex = messages.value.push({ role: 'assistant', content: '' }) - 1;
  let currentReply = '';

  try {
    const response = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: signal,
      body: JSON.stringify({
        sessionId: currentSessionId.value,
        message: userQuery
      })
    });

    if (!response.ok) {
      if (response.status === 400 && signal.aborted) {
        if (messages.value[aiMessageIndex]) {
          messages.value[aiMessageIndex].content += '\n\n*(已停止生成)*';
        }
        return;
      }
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    isThinking.value = false;

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('ReadableStream not supported');
    }
    const decoder = new TextDecoder('utf-8');

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value, { stream: true });
      const lines = chunk.split('\n');

      for (const line of lines) {
        if (line.startsWith('data:')) {
          const jsonStr = line.substring(5).trim();
          if (jsonStr && jsonStr !== '[DONE]') {
            try {
              const data = JSON.parse(jsonStr);
              const content = data.content || '';
              if (content) {
                currentReply = content;
                if (messages.value[aiMessageIndex]) {
                  messages.value[aiMessageIndex].content = currentReply;
                  if (isThinking.value) {
                    isThinking.value = false;
                  }
                }
                scrollToBottom();
              }
            } catch { /* ignore */ }
          } else {
            isThinking.value = false;
            break;
          }
        }
      }
    }
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      if (messages.value[aiMessageIndex]) {
        messages.value[aiMessageIndex].content += '\n\n*(用户已停止)*';
      }
    } else {
      console.error(error);
      const errorMessage = error instanceof Error ? error.message : String(error);
      if (messages.value[aiMessageIndex]) {
        messages.value[aiMessageIndex].content = `❌ 错误: ${errorMessage}`;
      }
    }
  } finally {
    isLoading.value = false;
    isThinking.value = false;
    abortController.value = null;
  }
};

const createSession = async () => {
  if (currentSessionId.value) {
    console.log('已有 sessionId:', currentSessionId.value);
    await loadHistory();
    return;
  }

  console.log('createSession');

  const response = await fetch(`${API_BASE}/session`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({})
  });
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  const data = await response.json();
  currentSessionId.value = data.sessionId || '';
  localStorage.setItem('sessionId', currentSessionId.value);
  console.log('sessionId:', currentSessionId.value);

  await loadHistory();
};

const loadHistory = async () => {
  if (!currentSessionId.value) return;

  try {
    const response = await fetch(`${API_BASE}/history/${currentSessionId.value}`);
    if (!response.ok) return;

    const history = await response.json();
    console.log('历史记录:', history);
    if (Array.isArray(history)) {
      messages.value = history.map((msg: { role: string; content: string }) => ({
        role: msg.role as 'user' | 'assistant',
        content: msg.content
      }));
    }
  } catch (error) {
    console.error('加载历史记录失败:', error);
  }
};

const stopGeneration = () => {
  if (abortController.value) {
    abortController.value.abort();
  }
};

const scrollToBottom = () => {
  nextTick(() => {
    const container = document.querySelector('.chat-container');
    if (container) {
      container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
    }
  });
};

onMounted(() => {
  createSession();
});
</script>

<template>
  <div class="chat-wrapper">
    <div class="chat-container">
      <div v-for="(msg, index) in messages" :key="index" class="message" :class="msg.role">
        <div class="avatar">{{ msg.role === 'user' ? '👤' : '🤖' }}</div>
        <div class="content">
          <div v-if="isThinking && msg.role === 'assistant' && !msg.content" class="thinking-bubble">
            <span class="dot"></span><span class="dot"></span><span class="dot"></span>
          </div>
          <span v-else v-html="md.render(msg.content)"></span>
        </div>
      </div>
    </div>

    <div class="input-area">
      <div class="input-box">
        <input
          v-model="inputText"
          @keyup.enter="sendMessage"
          :disabled="isLoading"
          placeholder="输入问题..."
        />
        <button v-if="!isLoading" @click="sendMessage" class="send-btn">
          发送
        </button>
        <button v-else-if="!isThinking" @click="stopGeneration" class="stop-btn">
          ⏹ 停止生成
        </button>
        <button v-else disabled class="send-btn loading">
          生成中...
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-wrapper {
  max-width: 900px;
  margin: 0 auto;
  padding: 20px;
}

.chat-container {
  height: 500px;
  overflow-y: auto;
  border: 1px solid #ddd;
  border-radius: 8px;
  padding: 20px;
  background: #fafafa;
  margin-bottom: 20px;
}

.message {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.message.user {
  flex-direction: row-reverse;
}

.message .avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: #007bff;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}

.message.assistant .avatar {
  background: #28a745;
}

.message .content {
  max-width: 70%;
  padding: 12px 16px;
  border-radius: 12px;
  background: white;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

.message.user .content {
  background: #007bff;
  color: white;
}

.thinking-bubble {
  display: flex;
  gap: 4px;
  padding: 12px 16px;
}

.thinking-bubble .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #999;
  animation: bounce 1.4s infinite ease-in-out both;
}

.thinking-bubble .dot:nth-child(1) { animation-delay: -0.32s; }
.thinking-bubble .dot:nth-child(2) { animation-delay: -0.16s; }

@keyframes bounce {
  0%, 80%, 100% { transform: scale(0); }
  40% { transform: scale(1); }
}

.input-area {
  display: flex;
  gap: 10px;
  align-items: center;
}

.input-box {
  display: flex;
  gap: 10px;
  flex: 1;
}

.input-box input {
  flex: 1;
  padding: 12px 16px;
  border: 1px solid #ddd;
  border-radius: 24px;
  outline: none;
  font-size: 14px;
}

.input-box input:focus {
  border-color: #007bff;
}

.send-btn {
  padding: 10px 24px;
  background: #007bff;
  color: white;
  border: none;
  border-radius: 24px;
  cursor: pointer;
  font-size: 14px;
}

.send-btn:disabled {
  background: #ccc;
  cursor: not-allowed;
}

.send-btn.loading {
  background: #6c757d;
  cursor: wait;
}

.stop-btn {
  padding: 10px 16px;
  background: #dc3545;
  color: white;
  border: none;
  border-radius: 24px;
  cursor: pointer;
  font-size: 14px;
}
</style>
