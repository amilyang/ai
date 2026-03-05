<script setup lang="ts">
import { ChatDotRound, Delete, Service, User } from '@element-plus/icons-vue';
import { ElMessage } from 'element-plus';
import MarkdownIt from 'markdown-it';
import { nextTick, ref } from 'vue';

const md = new MarkdownIt();

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

const inputText = ref('');
const messages = ref<Message[]>([]);
const isLoading = ref(false);
const chatContainerRef = ref<HTMLElement>();

const sendMessage = async () => {
  if (!inputText.value.trim() || isLoading.value) return;

  const userQuery = inputText.value;
  inputText.value = '';
  isLoading.value = true;

  messages.value.push({ role: 'user', content: userQuery });

  const aiMessageIndex = messages.value.push({ role: 'assistant', content: '正在思考中...' }) - 1;

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ query: userQuery })
    });

    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

    const data = await response.json();
    const answer = data.answer || '未收到有效回复';

    if (messages.value[aiMessageIndex]) {
      messages.value[aiMessageIndex].content = answer;
    }
    scrollToBottom();

  } catch (error) {
    console.error('请求失败:', error);
    if (messages.value[aiMessageIndex]) {
      messages.value[aiMessageIndex].content = "❌ 出错了：" + (error instanceof Error ? error.message : String(error));
    }
    ElMessage.error('请求失败，请检查网络');
  } finally {
    isLoading.value = false;
  }
};

const scrollToBottom = () => {
  nextTick(() => {
    if (chatContainerRef.value) {
      chatContainerRef.value.scrollTop = chatContainerRef.value.scrollHeight;
    }
  });
};

const clearChat = () => {
  messages.value = [];
  ElMessage.success('对话已清空');
};
</script>

<template>
  <el-card class="chat-card">
    <template #header>
      <div class="card-header">
        <div class="header-left">
          <el-icon class="header-icon"><ChatDotRound /></el-icon>
          <span class="title">AI 问答助手</span>
        </div>
        <el-button
          type="danger"
          size="small"
          :icon="Delete"
          plain
          :disabled="messages.length === 0"
          @click="clearChat"
        >
          清空对话
        </el-button>
      </div>
    </template>

    <div ref="chatContainerRef" class="chat-container">
      <el-empty v-if="messages.length === 0" description="暂无消息，开始提问吧！" />

      <div v-for="(msg, index) in messages" :key="index" class="message-wrapper" :class="msg.role">
        <div class="message-avatar">
          <el-icon v-if="msg.role === 'user'" class="avatar-icon"><User /></el-icon>
          <el-icon v-else class="avatar-icon"><Service /></el-icon>
        </div>
        <div class="message-content">
          <div class="message-header">
            <span class="sender-name">{{ msg.role === 'user' ? '我' : 'AI 助手' }}</span>
          </div>
          <div class="message-bubble">
            <div v-if="msg.content === '正在思考中...'" class="loading-dots">
              <span></span><span></span><span></span>
            </div>
            <span v-else v-html="msg.role === 'assistant' ? md.render(msg.content) : msg.content"></span>
          </div>
        </div>
      </div>
    </div>

    <div class="input-area">
      <el-input
        v-model="inputText"
        placeholder="请输入您的问题..."
        :disabled="isLoading"
        @keyup.enter="sendMessage"
        class="chat-input"
      >
        <template #append>
          <el-button
            type="primary"
            :loading="isLoading"
            @click="sendMessage"
          >
            <el-icon v-if="!isLoading"><ChatDotRound /></el-icon>
            {{ isLoading ? '' : '发送' }}
          </el-button>
        </template>
      </el-input>
    </div>
  </el-card>
</template>

<style scoped>
.chat-card {
  max-width: 900px;
  margin: 20px auto;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.header-icon {
  font-size: 22px;
  color: #409eff;
}

.title {
  font-size: 18px;
  font-weight: 600;
}

.chat-container {
  height: 450px;
  overflow-y: auto;
  padding: 10px;
  background-color: #f5f7fa;
  border-radius: 8px;
  margin-bottom: 15px;
}

.message-wrapper {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}

.message-wrapper.user {
  flex-direction: row-reverse;
}

.message-avatar {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: #fff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.message-wrapper.user .message-avatar {
  background-color: #409eff;
  color: #fff;
}

.message-wrapper.assistant .message-avatar {
  background-color: #67c23a;
  color: #fff;
}

.avatar-icon {
  font-size: 20px;
}

.message-content {
  max-width: 70%;
}

.message-header {
  margin-bottom: 4px;
}

.sender-name {
  font-size: 12px;
  color: #999;
}

.message-wrapper.user .sender-name {
  text-align: right;
}

.message-bubble {
  padding: 12px 16px;
  border-radius: 12px;
  background-color: #fff;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
  line-height: 1.6;
  word-break: break-word;
}

.message-wrapper.user .message-bubble {
  background-color: #409eff;
  color: #fff;
}

.message-wrapper.assistant .message-bubble {
  background-color: #fff;
}

.loading-dots {
  display: flex;
  gap: 4px;
}

.loading-dots span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: #999;
  animation: bounce 1.4s infinite ease-in-out both;
}

.loading-dots span:nth-child(1) {
  animation-delay: -0.32s;
}

.loading-dots span:nth-child(2) {
  animation-delay: -0.16s;
}

@keyframes bounce {
  0%, 80%, 100% {
    transform: scale(0);
  }
  40% {
    transform: scale(1);
  }
}

.input-area {
  display: flex;
  gap: 10px;
}

.chat-input {
  flex: 1;
}

:deep(.el-input-group__append) {
  background-color: #409eff;
  border-color: #409eff;
  color: #fff;
}

:deep(.el-input-group__append .el-button) {
  color: #fff;
}
</style>
