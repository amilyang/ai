<!-- App.vue -->
<template>
  <div class="flex h-screen bg-gray-50 text-gray-900 font-sans">
    <!-- 侧边栏 -->
    <aside
      class="bg-gray-900 text-white flex flex-col transition-all duration-300 ease-in-out"
      :class="isSidebarOpen ? 'w-64' : 'w-0 overflow-hidden'"
    >
      <div class="p-4 border-b border-gray-700 flex justify-between items-center">
        <h1 class="font-bold text-lg truncate">My AI Assistant</h1>
        <button @click="toggleSidebar" class="md:hidden text-gray-400">✕</button>
      </div>

      <!-- 新建对话按钮 -->
      <div class="p-4">
        <button
          @click="createNewSession"
          class="w-full flex items-center gap-2 px-4 py-3 bg-gray-800 hover:bg-gray-700 rounded-md border border-gray-600 transition-colors"
        >
          <span>+</span> 新建对话
        </button>
      </div>

      <!-- 会话列表 -->
      <div class="flex-1 overflow-y-auto px-2 space-y-1">
        <div
          v-for="session in sessions"
          :key="session.id"
          @click="loadSession(session.id)"
          class="group flex items-center justify-between px-3 py-2 rounded-md cursor-pointer hover:bg-gray-800 transition-colors"
          :class="currentSessionId === session.id ? 'bg-gray-800' : ''"
        >
          <span class="truncate text-sm flex-1">{{ session.title }}</span>

          <!-- 删除按钮 (仅 hover 显示) -->
          <button
            @click.stop="deleteSession(session.id)"
            class="opacity-0 group-hover:opacity-100 text-gray-500 hover:text-red-400 ml-2"
          >
            🗑️
          </button>
        </div>
      </div>

      <div class="p-4 border-t border-gray-700 text-xs text-gray-500">
        Powered by Qwen & RAG
      </div>
    </aside>

    <!-- 主聊天区域 -->
    <main class="flex-1 flex flex-col h-full relative">
      <!-- 顶部导航栏 (移动端打开侧边栏用) -->
      <header class="h-14 border-b bg-white flex items-center px-4 justify-between shadow-sm z-10">
        <button @click="toggleSidebar" class="text-gray-600 hover:text-gray-900">
          ☰
        </button>
        <span class="font-medium text-gray-700 truncate max-w-md">
          {{ currentSessionTitle || '新对话' }}
        </span>
        <div class="w-6"></div> <!-- 占位保持居中 -->
      </header>

      <!-- 聊天内容区 -->
      <div class="flex-1 overflow-hidden">
        <ChatComponent
          :sessionId="currentSessionId"
          @update-title="updateCurrentTitle"
          @session-created="onSessionCreated"
          @refresh-sessions="fetchSessions"
        />
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import ChatComponent from '@/components/ChatComponent.vue';
import { onMounted, ref, watch } from 'vue';
import type { Session } from '../types';

const API_BASE = import.meta.env.VITE_API_BASE;
const isSidebarOpen = ref(true);
const sessions = ref<Session[]>([]);
const currentSessionId = ref<number | null>(Number(localStorage.getItem('sessionId')) || null);
const currentSessionTitle = ref('新对话');

const toggleSidebar = () => isSidebarOpen.value = !isSidebarOpen.value;

watch(currentSessionId, (newId) => {
  if (newId) {
    localStorage.setItem('sessionId', String(newId));
  }
});

const fetchSessions = async () => {
  const res = await fetch(`${API_BASE}/sessions`);
  sessions.value = await res.json();
};

const createNewSession = () => {
  // 只创建本地会话，不调用后端
  currentSessionId.value = null;
  currentSessionTitle.value = '';
};

const loadSession = (id: number) => {
  currentSessionId.value = id;
  // 标题会在 ChatComponent 加载历史消息后通过事件更新，或者这里简单查找
  const session = sessions.value.find(s => s.id === id);
  if (session) currentSessionTitle.value = session.title;
  if (window.innerWidth < 768) isSidebarOpen.value = false; // 移动端选择后自动关闭
};

const deleteSession = async (id: number) => {
  if(!confirm('确定删除这个对话吗？')) return;
  await fetch(`${API_BASE}/session/${id}`, { method: 'DELETE' });
  await fetchSessions();
  if (currentSessionId.value === id) {
    currentSessionId.value = null;
    currentSessionTitle.value = '新对话';
  }
};

const updateCurrentTitle = (newTitle: string) => {
  currentSessionTitle.value = newTitle;
};

const onSessionCreated = (sessionId: number) => {
  currentSessionId.value = sessionId;
};

onMounted(async () => {
  await fetchSessions();
  // 如果没有当前会话，创建一个
  if (!currentSessionId.value) {
    await createNewSession();
  } else {
    // 有保存的 sessionId，加载对应的标题
    const session = sessions.value.find(s => s.id === currentSessionId.value);
    if (session) currentSessionTitle.value = session.title;
  }
});
</script>
