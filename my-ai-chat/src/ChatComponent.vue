<script setup lang="ts">
import hljs from 'highlight.js';
import 'highlight.js/styles/github.css';
import type MarkdownItType from 'markdown-it';
import MarkdownIt from 'markdown-it';
import { nextTick, onMounted, ref } from 'vue';

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
const currentSessionId = ref('');
const sendMessage = async () => {
  if (!inputText.value.trim() || isLoading.value) return;

  // 1. 初始化 AbortController (用于停止生成)
  abortController.value = new AbortController();
  const signal = abortController.value.signal;

  const userQuery = inputText.value;
  inputText.value = '';
  isLoading.value = true;
  isThinking.value = true; // 开始思考

  messages.value.push({ role: 'user', content: userQuery });
  const aiMessageIndex = messages.value.push({ role: 'assistant', content: '' }) - 1;
  let currentReply = '';

  try {
    // 构造 Payload (同 Day 3)
    const userQuery = inputText.value;

    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sessionId: currentSessionId.value, // 确保这是个数字
        message: userQuery
      })
    });

    if (!response.ok) {
      if (response.status === 400 && signal.aborted) {
        // 用户主动停止，不报错
        if(messages.value[aiMessageIndex])
        messages.value[aiMessageIndex].content += "\n\n*(已停止生成)*";
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
              const content = data.output?.choices?.[0]?.message?.content || '';
              if (content) {
                currentReply = content;
                if(messages.value[aiMessageIndex])
                messages.value[aiMessageIndex].content = currentReply;
                scrollToBottom();
              }
            } catch { /* ignore parse errors */ }
          } else {
            isThinking.value = false;
            break;
          }
        }
      }
    }

  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      if(messages.value[aiMessageIndex])
      messages.value[aiMessageIndex].content += "\n\n*(用户已停止)*";
    } else {
      console.error(error);
      const errorMessage = error instanceof Error ? error.message : String(error);
      if(messages.value[aiMessageIndex])
      messages.value[aiMessageIndex].content = `❌ 错误: ${errorMessage}`;
    }
  } finally {
    isLoading.value = false;
    isThinking.value = false;
    abortController.value = null;
  }
};

const createSession = async () => {
  const response = await fetch('/api/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({})
  });
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  const data = await response.json();
  currentSessionId.value = data.sessionId || '';
};

// 停止生成函数
const stopGeneration = () => {
  if (abortController.value) {
    abortController.value.abort();
  }
};

const scrollToBottom = () => {
  nextTick(() => {
    const container = document.querySelector('.chat-container');
    if (container) {
      // 平滑滚动
      container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
    }
  });
  onMounted(() => {
    createSession();
  });
};
</script>

<template>
  <div class="chat-wrapper">
    <div class="chat-container">
      <div v-for="(msg, index) in messages" :key="index" class="message" :class="msg.role">
        <div class="avatar">{{ msg.role === 'user' ? '👤' : '🤖' }}</div>
        <div class="content" v-html="md.render(msg.content)"></div>
      </div>

      <!-- 思考中动画 -->
      <div v-if="isThinking" class="message assistant">
        <div class="avatar">🤖</div>
        <div class="thinking-bubble">
          <span class="dot"></span><span class="dot"></span><span class="dot"></span>
        </div>
      </div>
    </div>

    <div class="input-area">
      <!-- 停止按钮：仅在生成中显示 -->
      <button
        v-if="isLoading && !isThinking"
        @click="stopGeneration"
        class="stop-btn"
      >
        ⏹ 停止生成
      </button>

      <div class="input-box">
        <input
          v-model="inputText"
          @keyup.enter="sendMessage"
          :disabled="isLoading"
          placeholder="输入问题..."
        />
        <button @click="sendMessage" :disabled="isLoading && !isThinking" class="send-btn">
          {{ isLoading && !isThinking ? '生成中...' : '发送' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-container {
  height: 60vh;
  overflow-y: auto;
  padding: 20px;
  background: #f9f9f9;
  border-radius: 8px;
}
.message {
  display: flex;
  margin-bottom: 20px;
  align-items: flex-start;
}
.message.user { flex-direction: row-reverse; }
.avatar {
  font-size: 24px;
  margin: 0 10px;
}
.content {
  max-width: 70%;
  padding: 12px 16px;
  border-radius: 12px;
  background: white;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  line-height: 1.6;
}
.message.user .content {
  background: #007bff;
  color: white;
}
/* 代码块样式修正 */
:deep(pre) {
  background: #2d2d2d;
  padding: 10px;
  border-radius: 6px;
  overflow-x: auto;
  color: #ccc;
}
:deep(code) { font-family: 'Consolas', monospace; }

/* 思考动画 */
.thinking-bubble {
  background: white;
  padding: 10px 15px;
  border-radius: 20px;
  display: flex;
  gap: 5px;
}
.dot {
  width: 8px;
  height: 8px;
  background: #bbb;
  border-radius: 50%;
  animation: bounce 1.4s infinite ease-in-out both;
}
.dot:nth-child(1) { animation-delay: -0.32s; }
.dot:nth-child(2) { animation-delay: -0.16s; }

@keyframes bounce {
  0%, 80%, 100% { transform: scale(0); }
  40% { transform: scale(1); }
}

.input-area {
  margin-top: 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.stop-btn {
  align-self: center;
  background: #ff4d4f;
  color: white;
  border: none;
  padding: 6px 16px;
  border-radius: 20px;
  cursor: pointer;
  font-size: 12px;
  transition: opacity 0.3s;
}
.stop-btn:hover { opacity: 0.8; }

.input-box {
  display: flex;
  gap: 10px;
}
input {
  flex: 1;
  padding: 12px;
  border: 1px solid #ddd;
  border-radius: 8px;
  outline: none;
}
input:disabled { background: #f0f0f0; }
.send-btn {
  padding: 0 24px;
  background: #007bff;
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
}
.send-btn:disabled { background: #ccc; cursor: not-allowed; }
</style>
