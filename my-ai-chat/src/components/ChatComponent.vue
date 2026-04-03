<!--
 * @Author: e0042176 e0042176@ceic.com
 * @Date: 2026-03-04 16:31:49
 * @LastEditors: e0042176 e0042176@ceic.com
 * @LastEditTime: 2026-03-31 11:21:56
 * @FilePath: \ai\my-ai-chat\src\components\ChatComponent.vue
 * @Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
-->
<template>
  <div class="flex flex-col h-full">
    <!-- 消息列表区域 -->
    <div class="flex-1 overflow-y-auto p-4 space-y-6 scroll-smooth" ref="chatContainer">
      <div v-if="messages.length === 0" class="h-full flex flex-col items-center justify-center text-gray-400">
        <div class="text-4xl mb-4">🤖</div>
        <p>开始提问，或上传知识库让我学习吧！</p>
      </div>

      <div
        v-for="msg in messages"
        :key="msg.id"
        class="flex gap-4 w-full"
        :class="msg.role === 'user' ? 'flex-row-reverse' : ''"
      >
        <!-- 头像 -->
        <div class="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center"
            :class="msg.role === 'user' ? 'bg-blue-600' : 'bg-green-600'">
          {{ msg.role === 'user' ? '👤' : '🤖' }}
        </div>

        <!-- 消息气泡 -->
        <div class="group relative" :class="msg.role === 'user' ? 'items-end' : 'items-start'" :style="editingId === msg.id ? 'flex: 1;' : ''">
          <!-- 编辑模式 -->
          <div v-if="editingId === msg.id" class="flex flex-col gap-2 w-full" :class="msg.role === 'assistant' ? 'max-w-[calc(100%-2.5rem)]' : ''">
            <textarea
              v-model="editText"
              class="w-full p-2 border rounded-md focus:ring-2 focus:ring-blue-500 outline-none"
              rows="3"
            ></textarea>
            <div class="flex gap-2" :class="msg.role === 'user' ? 'justify-end' : ''">
              <button @click="saveEdit(msg)" class="px-3 py-1 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 flex items-center gap-1">
                <el-icon><Promotion /></el-icon> 发送
              </button>
              <button @click="cancelEdit" class="px-3 py-1 bg-gray-300 text-sm rounded hover:bg-gray-400 flex items-center gap-1">
                取消
              </button>
            </div>
          </div>

          <!-- 显示模式 -->
          <div v-else class="prose prose-sm p-3 rounded-lg max-w-[100%]"
              :class="msg.role === 'user' ? 'bg-blue-50 border border-blue-100' : ''">
            <!-- 使用 v-html 渲染 Markdown (需配合 markdown-it 插件) -->
            <div v-if="msg.content" class="chat-img" v-html="renderMarkdown(msg.content)"></div>
            <div v-else-if="msg.role === 'assistant'" class="flex items-center gap-1">
              <span class="flex gap-1">
                <span class="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 0ms;"></span>
                <span class="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 150ms;"></span>
                <span class="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 300ms;"></span>
              </span>
            </div>
          </div>

          <!-- 操作按钮 (Hover 显示，编辑状态下不显示) -->
          <div v-if="editingId !== msg.id" class="absolute -bottom-6 left-0 flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity text-xs text-gray-500">
            <span v-if="msg.role === 'assistant'" class="cursor-pointer hover:text-blue-600" @click="copyText(msg.content)">
              <el-icon><DocumentCopy /></el-icon>
            </span>
            <span v-if="msg.role === 'user'" class="cursor-pointer hover:text-blue-600" @click="startEdit(msg)">
              <el-icon><Edit /></el-icon>
            </span>
            <span class="cursor-pointer hover:text-red-600" @click="deleteMessage(msg)">
              <el-icon><Delete /></el-icon>
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 输入框区域 -->
    <div class="border-t bg-gray-50 p-4 flex-shrink-0">
      <div class="mx-auto" style="max-width: calc(100% - 2rem);">
        <div
          class="bg-white border border-gray-200 rounded-2xl focus-within:ring-2 focus-within:ring-blue-500 transition-shadow p-3"
        >
          <!-- 图片预览 -->
          <div v-if="uploadedImages.length > 0" class="mt-2 pt-2">
            <div class="flex gap-2 flex-wrap">
              <div v-for="(img, idx) in uploadedImages" :key="idx" class="relative">
                <img :src="img" class="w-12 h-12 object-cover rounded-lg border shadow-sm" />
                <button @click="uploadedImages.splice(idx, 1)" class="absolute -top-2 -right-2 bg-red-500 text-white rounded-full w-5 h-5 flex items-center justify-center text-xs hover:bg-red-600">
                  ×
                </button>
              </div>
            </div>
          </div>
          <!-- 输入框 -->
          <textarea
            v-model="inputText"
            @keydown.enter.exact.prevent="sendMessage"
            placeholder="向千问提问"
            class="w-full bg-transparent border-none outline-none resize-none overflow-y-auto p-2"
            rows="1"
            ref="inputRef"
            style="max-height: 120px; min-height: 24px;"
          ></textarea>

          <!-- 功能按钮区域 -->
          <div class="flex items-center justify-between mt-2 pt-2 border-t border-gray-100">
            <!-- 左侧功能按钮 -->
            <div class="flex gap-3">
              <button class="flex items-center gap-1 text-sm text-gray-600 hover:text-blue-600 transition-colors">
                <span class="w-4 h-4 inline-flex items-center justify-center">⚙️</span>
                <span>任务助理</span>
              </button>
              <button class="flex items-center gap-1 text-sm text-gray-600 hover:text-blue-600 transition-colors">
                <span class="w-4 h-4 inline-flex items-center justify-center">💭</span>
                <span>深度思考</span>
              </button>
              <button class="flex items-center gap-1 text-sm text-gray-600 hover:text-blue-600 transition-colors">
                <span class="w-4 h-4 inline-flex items-center justify-center">🔍</span>
                <span>深度研究</span>
              </button>
              <button class="flex items-center gap-1 text-sm text-gray-600 hover:text-blue-600 transition-colors">
                <span class="w-4 h-4 inline-flex items-center justify-center">💻</span>
                <span>代码</span>
              </button>
              <!-- 图片上传按钮 -->
              <ImageUploader v-model="uploadedImages">
                <template #default="{ handleClick }">
                  <button @click="handleClick" class="flex items-center gap-1 text-sm text-gray-600 hover:text-blue-600 transition-colors">
                    <span class="w-4 h-4 inline-flex items-center justify-center">🖼️</span>
                    <span>图像</span>
                  </button>
                </template>
              </ImageUploader>
              <button class="flex items-center gap-1 text-sm text-gray-600 hover:text-blue-600 transition-colors">
                <span class="w-4 h-4 inline-flex items-center justify-center">⋮</span>
                <span>更多</span>
              </button>
            </div>

            <!-- 右侧发送按钮 -->
            <div class="flex gap-2 items-center">
              <button
                v-if="!isThinking"
                @click="sendMessage"
                :disabled="!inputText.trim()"
                class="p-2 bg-blue-600 text-white rounded-full disabled:opacity-50 disabled:cursor-not-allowed hover:bg-blue-700 transition-colors"
              >
                <el-icon><Promotion /></el-icon>
              </button>
              <button
                v-else
                @click="stopGeneration"
                :disabled="isStopping"
                class="p-2 bg-red-600 text-white rounded-full hover:bg-red-700 transition-colors"
              >
                <el-icon><VideoPlay /></el-icon>
              </button>
            </div>
          </div>
        </div>
      </div>
      <div class="text-center text-xs text-gray-400 mt-2">
        AI 生成的内容可能不准确，请核实重要信息。
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { Message } from '@/types';
import { Delete, DocumentCopy, Edit, Promotion, VideoPlay } from '@element-plus/icons-vue';
import hljs from 'highlight.js';
import 'highlight.js/styles/github.css';
import MarkdownIt from 'markdown-it';
import { nextTick, onMounted, ref, watch } from 'vue';
import ImageUploader from './ImageUploader.vue';

const md = new MarkdownIt({ highlight: (str, lang) => {
  if (lang && hljs.getLanguage(lang)) {
    return hljs.highlight(str, { language: lang }).value;
  }
  return '';
}});

const props = defineProps<{
  sessionId: number | null;
}>();
const emit = defineEmits(['updateTitle', 'sessionCreated', 'refreshSessions']);

const API_BASE = import.meta.env.VITE_API_BASE;
const messages = ref<Message[]>([]);
const inputText = ref('');
const isThinking = ref(false);
const isStopping = ref(false);
let abortController: AbortController | null = null;
const editingId = ref<string | number | null>(null);
const editText = ref('');
const inputRef = ref<HTMLTextAreaElement | null>(null);
const uploadedImages = ref<string[]>([]);
const chatContainer = ref<HTMLElement | null>(null);

const renderMarkdown = (text: string) => md.render(text || '');

const scrollToBottom = async () => {
  await nextTick();
  if (chatContainer.value) {
    chatContainer.value.scrollTop = chatContainer.value.scrollHeight;
  }
};

const loadHistory = async (sessionId: number) => {
  if (!sessionId) return;
  editingId.value = null;
  editText.value = '';
  try {
    const res = await fetch(`${API_BASE}/session/${sessionId}`);
    if (!res.ok) {
      console.error('加载历史失败:', res.status, await res.text());
      return;
    }
    const data = await res.json();
    console.log('加载历史记录:', sessionId, '消息数:', data.length, data);

    if (!Array.isArray(data)) {
      console.error('返回数据不是数组:', data);
      return;
    }

    messages.value = data.map((msg: { role: string; content: string; images?: string[] }, idx: number) => {
      let content = msg.content;
      // 如果有图片，将图片 URL 转换为 Markdown 格式
      if (msg.images && msg.images.length > 0) {
        const imageMarkdown = msg.images.map(img => `![图片](${img})\n`).join('');
        content = imageMarkdown + content;
      }
      return {
        role: msg.role as 'user' | 'assistant' | 'system',
        content,
        id: `history-${sessionId}-${idx}-${Date.now()}`
      };
    });

  // 更新标题：取第一条用户消息的前20个字，或者默认
  if (messages.value.length > 0) {
     const firstUserMsg = messages.value.find(m => m.role === 'user');
     if (firstUserMsg) {
       emit('updateTitle', firstUserMsg.content.slice(0, 20) + (firstUserMsg.content.length > 20 ? '...' : ''));
     }
  }
  scrollToBottom();
  } catch (error) {
    console.error('加载历史记录出错:', error);
  }
};

watch(() => props.sessionId, (newId) => {
  if (newId) {
    inputText.value = '';
    loadHistory(newId);
  } else {
    // 新建对话时清空消息
    messages.value = [];
    inputText.value = '';
  }
});

const sendMessage = async (event?: MouseEvent | KeyboardEvent | string | null) => {
  if (event && typeof event === 'object' && 'key' in event) {
    event.preventDefault();
  }
  const textToSend = typeof event === 'string' ? event : inputText.value;
  if (!textToSend.trim()) return;

  // 如果没有 sessionId，先创建会话
  let currentSessionId = props.sessionId;
  if (!currentSessionId) {
    let title = textToSend.slice(0, 20);
    if (title.length >= 20) title += '...';
    try {
      const res = await fetch(`${API_BASE}/session`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title })
      });
      const data = await res.json();
      currentSessionId = data.id; // 直接使用返回的sessionId
      emit('sessionCreated', currentSessionId);
      emit('refreshSessions');
    } catch (e) {
      console.error('创建会话失败', e);
      return;
    }
  }

  if (!currentSessionId) {
    console.error('sessionId 未更新，无法发送消息');
    return;
  }

  if (typeof event !== 'string') inputText.value = '';

  // 保存图片用于显示
  const imagesToSend = [...uploadedImages.value];
  uploadedImages.value = [];

  // 如果是编辑模式，先清除编辑状态
  editingId.value = null;

  // 如果是第一条用户消息，更新标题
  const hasUserMessages = messages.value.some(m => m.role === 'user');
  if (!hasUserMessages) {
    let title = textToSend.slice(0, 20);
    if (title.length >= 20) title += '...';
    emit('updateTitle', title);
  }

  // 显示图片
  let userContent = textToSend;
  if (imagesToSend.length > 0) {
    userContent = imagesToSend.map(img => `![图片](${img})\n`).join('') + textToSend;
  }
  const tempUserMsg: Message = { role: 'user', content: userContent, id: Date.now() };
  messages.value.push(tempUserMsg);
  messages.value.push({ role: 'assistant', content: '', id: Date.now() + 1 });
  isThinking.value = true;
  isStopping.value = false;
  scrollToBottom();

  abortController = new AbortController();

  try {
    // 构建请求体
    interface ChatRequestBody {
      sessionId: number;
      message: string;
      images?: string[];
    }
    const requestBody: ChatRequestBody = { sessionId: currentSessionId, message: textToSend };
    if (imagesToSend.length > 0) {
      requestBody.images = imagesToSend;
    }

    const response = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody),
      signal: abortController.signal
    });

    if (!response.body) {
      throw new Error('Response body is null');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let fullReply = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value, { stream: true });
      const lines = chunk.split('\n');

      for (const line of lines) {
        if (line.startsWith('data:')) {
          const jsonStr = line.substring(5).trim();
          if (jsonStr === '[DONE]') {
            isThinking.value = false;
            break;
          }
          if (jsonStr) {
            try {
              const data = JSON.parse(jsonStr);
              if (data.error) throw new Error(data.error);
              if (data.content) {
                // 累加增量内容（后端发送的是增量）
                fullReply += data.content;
                const latestMsg = messages.value[messages.value.length - 1];
                if (latestMsg) {
                  latestMsg.content = fullReply;
                }
                scrollToBottom();
              }
            } catch {
              // 忽略 JSON 解析错误
            }
          }
        }
      }
    }
  } catch (error: unknown) {
    if (error instanceof Error && error.name === 'AbortError') {
      const lastMsg = messages.value[messages.value.length - 1];
      if (lastMsg && !lastMsg.content) {
        lastMsg.content = '已停止生成';
      }
    } else {
      const errMsg = error instanceof Error ? error.message : String(error);
      const lastMsg = messages.value[messages.value.length - 1];
      if (lastMsg) {
        lastMsg.content = `❌ 错误: ${errMsg}`;
      }
    }
    isThinking.value = false;
    isStopping.value = false;
    abortController = null;
  }
};

// --- 停止生成 ---
const stopGeneration = () => {
  if (abortController) {
    isStopping.value = true;
    abortController.abort();
  }
};

// --- 编辑功能逻辑 ---
const startEdit = (msg: Message) => {
  editingId.value = msg.id;
  editText.value = msg.content;
};

const cancelEdit = () => {
  editingId.value = null;
  editText.value = '';
};

const deleteMessage = async (msg: Message) => {
  const msgIndex = messages.value.findIndex(m => m.id === msg.id);
  if (msgIndex === -1) return;

  // 找到对应的另一条消息（用户消息删除AI回复，AI回复删除用户消息）
  const deleteIndex1 = msgIndex;
  let deleteIndex2 = -1;

  if (msg.role === 'user') {
    // 删除用户消息和下一条AI回复
    deleteIndex2 = msgIndex + 1;
  } else if (msg.role === 'assistant') {
    // 删除AI回复和上一条用户消息
    deleteIndex2 = msgIndex - 1;
  }

  // 构建要删除的消息ID列表
  const idsToDelete: (string | number | undefined)[] = [messages.value[deleteIndex1]?.id];
  if (deleteIndex2 >= 0 && deleteIndex2 < messages.value.length) {
    idsToDelete.push(messages.value[deleteIndex2]?.id);
  }

  // 调用后端删除
  for (const id of idsToDelete) {
    if (id && typeof id === 'number') {  // 只删除数字ID的消息（数据库中存在的）
      try {
        await fetch(`${API_BASE}/msg/${id}`, { method: 'DELETE' });
      } catch (e) {
        console.error('删除消息失败', e);
      }
    }
  }

  // 本地UI更新：删除这两条消息
  const indicesToDelete = new Set([deleteIndex1, deleteIndex2].filter(i => i >= 0));
  messages.value = messages.value.filter((_, index) => !indicesToDelete.has(index));
};

const saveEdit = async (msg: Message) => {
  if (!editText.value.trim()) return;

  // 1. 调用后端删除该消息及之后的所有消息
  await fetch(`${API_BASE}/message/${msg.id}`, { method: 'DELETE' });

  // 2. 本地 UI 截断：保留该消息之前的所有消息
  const msgIndex = messages.value.findIndex(m => m.id === msg.id);
  if (msgIndex !== -1) {
    messages.value = messages.value.slice(0, msgIndex);
  }

  // 3. 重新发送修改后的消息
  editingId.value = null;
  await sendMessage(editText.value);
};

const copyText = (text: string) => {
  navigator.clipboard.writeText(text);
  alert('已复制到剪贴板');
};

onMounted(() => {
  if (props.sessionId) loadHistory(props.sessionId);

  // 自动调整 textarea 高度
  inputRef.value?.addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = (this.scrollHeight) + 'px';
    if(this.value === '') this.style.height = 'auto';
  });
});
</script>

<style scoped>
/* 简单的滚动条美化 */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #94a3b8; }

/* 聊天中的图片大小限制 */
:deep(.chat-img img) {
  max-width: 100px;
  max-height: 100px;
  border-radius: 8px;
}
</style>
