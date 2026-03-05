<script setup lang="ts">
import { ref } from 'vue';
import { ElMessage } from 'element-plus';
import type { UploadFile, UploadRawFile } from 'element-plus';

const fileList = ref<UploadFile[]>([]);
const isUploading = ref(false);

const beforeUpload = (file: UploadRawFile) => {
  const isTxt = file.name.endsWith('.txt');
  const isLt10M = file.size / 1024 / 1024 < 10;

  if (!isTxt) {
    ElMessage.error('只能上传 .txt 文件');
    return false;
  }
  if (!isLt10M) {
    ElMessage.error('文件大小不能超过 10MB');
    return false;
  }
  fileList.value = [{ ...file, status: 'ready' } as UploadFile];
  return true;
};

const handleExceed = () => {
  ElMessage.warning('只能上传一个文件');
};

const uploadFile = async () => {
  const file = fileList.value[0];
  if (!file || !file.raw) {
    ElMessage.warning('请先选择文件');
    return;
  }

  isUploading.value = true;
  const formData = new FormData();
  formData.append('file', file.raw);

  try {
    const response = await fetch('/api/upload', {
      method: 'POST',
      body: formData
    });

    const result = await response.json();

    if (response.ok) {
      ElMessage.success(result.message || '上传成功');
    } else {
      ElMessage.error(result.detail || '上传失败');
    }
  } catch (error) {
    ElMessage.error('上传失败: ' + (error instanceof Error ? error.message : String(error)));
  } finally {
    isUploading.value = false;
  }
};

const handleRemove = () => {
  fileList.value = [];
};
</script>

<template>
  <el-card class="upload-card">
    <template #header>
      <div class="card-header">
        <span class="title">上传文档</span>
        <el-tag type="info">仅支持 .txt 格式</el-tag>
      </div>
    </template>

    <el-upload
      ref="uploadRef"
      v-model:file-list="fileList"
      class="upload-demo"
      action="#"
      :auto-upload="false"
      :limit="1"
      :before-upload="beforeUpload"
      :on-exceed="handleExceed"
      :on-remove="handleRemove"
      accept=".txt"
    >
      <el-button type="primary">
        <el-icon class="el-icon--left"><Upload /></el-icon>
        选择文件
      </el-button>
      <template #tip>
        <div class="el-upload__tip">
          文件大小不超过 10MB
        </div>
      </template>
    </el-upload>

    <div class="upload-actions">
      <el-button
        type="success"
        :loading="isUploading"
        :disabled="fileList.length === 0"
        @click="uploadFile"
      >
        <el-icon v-if="!isUploading" class="el-icon--left"><UploadFilled /></el-icon>
        {{ isUploading ? '上传中...' : '开始上传' }}
      </el-button>
    </div>
  </el-card>
</template>

<style scoped>
.upload-card {
  max-width: 600px;
  margin: 20px auto;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.title {
  font-size: 18px;
  font-weight: 600;
}

.upload-demo {
  margin-bottom: 20px;
}

.el-upload__tip {
  margin-top: 10px;
  color: #999;
}

.upload-actions {
  display: flex;
  justify-content: flex-end;
  padding-top: 10px;
  border-top: 1px solid #eee;
}
</style>
