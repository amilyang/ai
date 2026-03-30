<script setup lang="ts">
import type { UploadFile, UploadRawFile } from 'element-plus';
import { ElMessage } from 'element-plus';
import { ref } from 'vue';

const fileList = ref<UploadFile[]>([]);
const isUploading = ref(false);
const uploadStatus = ref<'idle' | 'uploading' | 'success' | 'error'>('idle');

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
  uploadStatus.value = 'idle';
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
  uploadStatus.value = 'uploading';
  ElMessage.info('正在向量化...');

  const formData = new FormData();
  formData.append('file', file.raw);

  try {
    const response = await fetch('/api/upload', {
      method: 'POST',
      body: formData
    });

    const result = await response.json();

    if (response.ok) {
      uploadStatus.value = 'success';
      ElMessage.success('✅ 学习完成！现在可以问我关于这个文档的问题了。');
    } else {
      uploadStatus.value = 'error';
      ElMessage.error('❌ 上传失败: ' + (result.detail || '未知错误'));
    }
  } catch (error) {
    uploadStatus.value = 'error';
    console.error('Upload error:', error);
    ElMessage.error('❌ 网络错误');
  } finally {
    isUploading.value = false;
  }
};

const handleRemove = () => {
  fileList.value = [];
  uploadStatus.value = 'idle';
};
</script>

<template>
  <el-card class="upload-card">
    <template #header>
      <div class="card-header">
        <span class="title">上传文档</span>
        <el-tag type="info">仅支持 .txt, .md, .pdf 格式</el-tag>
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
      accept=".txt,.md,.pdf"
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

    <div class="upload-status" v-if="uploadStatus !== 'idle'">
      <el-alert
        :title="uploadStatus === 'uploading' ? '正在向量化...' :
                uploadStatus === 'success' ? '学习完成！现在可以问我关于这个文档的问题了。' :
                '上传失败'"
        :type="uploadStatus === 'uploading' ? 'info' :
               uploadStatus === 'success' ? 'success' : 'error'"
        :closable="false"
        show-icon
      />
    </div>

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

.upload-status {
  margin-bottom: 20px;
}

.upload-actions {
  margin-top: 20px;
}
</style>
