<script setup lang="ts">
import uploadFile from '@/components/uploadFile.vue';
import { ElMessage } from 'element-plus';
import { onMounted, ref } from 'vue';
const API_BASE = import.meta.env.VITE_API_BASE;
interface FileInfo {
  filename: string;
  file_size: number;
  file_type: string;
  file_summary: string;
  upload_time: number;
}

const files = ref<FileInfo[]>([]);
const searchQuery = ref('');
const isLoading = ref(false);
const totalFiles = ref(0);
const uploadDialogVisible = ref(false);

const formatFileSize = (bytes: number): string => {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
};

const formatDateTime = (timestamp: number): string => {
  const date = new Date(timestamp * 1000);
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  });
};

const loadFiles = async () => {
  isLoading.value = true;
  try {
    const response = await fetch(`${API_BASE}/files`);
    if (response.ok) {
      const data = await response.json();
      files.value = data.files;
      totalFiles.value = data.total;
    } else {
      ElMessage.error('获取文件列表失败');
    }
  } catch (error) {
    console.error('Error loading files:', error);
    ElMessage.error('网络错误');
  } finally {
    isLoading.value = false;
  }
};

const searchFiles = async () => {
  if (!searchQuery.value.trim()) {
    await loadFiles();
    return;
  }

  isLoading.value = true;
  try {
    const response = await fetch(`${API_BASE}/files/search?query=${encodeURIComponent(searchQuery.value)}`);
    if (response.ok) {
      const data = await response.json();
      files.value = data.files;
      totalFiles.value = data.total;
    } else {
      ElMessage.error('搜索文件失败');
    }
  } catch (error) {
    console.error('Error searching files:', error);
    ElMessage.error('网络错误');
  } finally {
    isLoading.value = false;
  }
};

const clearSearch = async () => {
  searchQuery.value = '';
  await loadFiles();
};

// 组件挂载时加载文件列表
onMounted(() => {
  loadFiles();
});
</script>

<template>
  <el-card class="file-manager-card">
    <template #header>
      <div class="card-header">
        <span class="title">文件管理</span>
        <div class="header-actions">
          <el-button type="primary" @click="uploadDialogVisible = true">
            <el-icon><Upload /></el-icon>
            上传文件
          </el-button>
          <el-tag type="info">{{ totalFiles }} 个文件</el-tag>
        </div>
      </div>
    </template>

    <div class="search-box">
      <el-input
        v-model="searchQuery"
        placeholder="搜索文件内容..."
        clearable
        @clear="clearSearch"
        @keyup.enter="searchFiles"
      >
        <template #append>
          <el-button @click="searchFiles">
            <el-icon><Search /></el-icon>
          </el-button>
        </template>
      </el-input>
    </div>

    <el-table
      v-loading="isLoading"
      :data="files"
      style="width: 100%"
      empty-text="暂无文件"
    >
      <el-table-column prop="filename" label="文件名" min-width="200">
        <template #default="{ row }">
          <span class="filename">{{ row.filename }}</span>
        </template>
      </el-table-column>
      <el-table-column label="文件大小" width="120">
        <template #default="{ row }">
          {{ formatFileSize(row.file_size) }}
        </template>
      </el-table-column>
      <el-table-column label="文件类型" width="120">
        <template #default="{ row }">
          {{ row.file_type }}
        </template>
      </el-table-column>
      <el-table-column prop="file_summary" label="摘要" min-width="300">
        <template #default="{ row }">
          <span class="file-summary">{{ row.file_summary || '无摘要' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="上传时间" width="180">
        <template #default="{ row }">
          {{ formatDateTime(row.upload_time) }}
        </template>
      </el-table-column>
    </el-table>

    <div class="file-stats" v-if="files.length > 0">
      <el-descriptions :column="2" border>
        <el-descriptions-item label="总文件数">
          {{ totalFiles }}
        </el-descriptions-item>
        <el-descriptions-item label="总大小">
          {{ formatFileSize(files.reduce((sum, file) => sum + file.file_size, 0)) }}
        </el-descriptions-item>
      </el-descriptions>
    </div>
  </el-card>

  <!-- 上传文件对话框 -->
  <el-dialog
    v-model="uploadDialogVisible"
    title="上传文件"
    width="600px"
    destroy-on-close
  >
    <uploadFile />
  </el-dialog>
</template>

<style scoped>
.file-manager-card {
  max-width: 1000px;
  margin: 20px auto;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.title {
  font-size: 18px;
  font-weight: 600;
}

.search-box {
  margin-bottom: 20px;
}

.file-summary {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.4;
}

.file-stats {
  margin-top: 20px;
}

.filename {
  font-weight: 500;
}
</style>
