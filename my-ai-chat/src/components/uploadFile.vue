<script setup lang="ts">
import type { UploadFile, UploadRawFile } from 'element-plus';
import { ElMessage, ElProgress } from 'element-plus';
import { ref } from 'vue';

const fileList = ref<UploadFile[]>([]);
const isUploading = ref(false);
const uploadStatus = ref<'idle' | 'uploading' | 'success' | 'error'>('idle');
const uploadProgress = ref(0);

const beforeUpload = (file: UploadRawFile) => {
  const isSupported = file.name.endsWith('.txt') ||
                     file.name.endsWith('.md') ||
                     file.name.endsWith('.json') ||
                     file.name.endsWith('.csv') ||
                     file.name.endsWith('.pdf') ||
                     file.name.endsWith('.docx') ||
                     file.name.endsWith('.jpg') ||
                     file.name.endsWith('.jpeg') ||
                     file.name.endsWith('.png') ||
                     file.name.endsWith('.gif');
  const isLt50M = file.size / 1024 / 1024 < 50;

  if (!isSupported) {
    ElMessage.error('支持的文件类型: .txt, .md, .json, .csv, .pdf, .docx, .jpg, .jpeg, .png, .gif');
    return false;
  }
  if (!isLt50M) {
    ElMessage.error('文件大小不能超过 50MB');
    return false;
  }
  uploadStatus.value = 'idle';
  uploadProgress.value = 0;
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
  uploadProgress.value = 0;
  ElMessage.info('正在处理文件...');

  const formData = new FormData();
  formData.append('file', file.raw);

  try {
    const response = await fetch('/api/upload', {
      method: 'POST',
      body: formData,
      // 添加上传进度监听
      /* 注意：fetch API 不直接支持上传进度，需要使用 XMLHttpRequest 或 axios 来实现 */
      // 这里使用模拟进度，实际项目中可以使用 axios 来获取真实进度
    });

    // 模拟上传进度
    const progressInterval = setInterval(() => {
      if (uploadProgress.value < 90) {
        uploadProgress.value += 10;
      }
    }, 200);

    const result = await response.json();
    clearInterval(progressInterval);
    uploadProgress.value = 100;

    if (response.ok) {
      uploadStatus.value = 'success';
      if (result.duplicate) {
        ElMessage.success('✅ 文件已存在，无需重复上传！');
      } else {
        ElMessage.success(`✅ 上传成功！成功处理 ${result.processed_chunks || 0} 个知识片段。`);
      }
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
  uploadProgress.value = 0;
};
</script>

<template>
  <el-card class="upload-card">
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
      accept=".txt,.md,.json,.csv,.pdf,.docx,.jpg,.jpeg,.png,.gif"
    >
      <el-button type="primary">
        <el-icon class="el-icon--left"><Upload /></el-icon>
        选择文件
      </el-button>
      <template #tip>
        <div class="el-upload__tip">
          支持的文件类型: .txt, .md, .json, .csv, .pdf, .docx, .jpg, .jpeg, .png, .gif<br>
          文件大小不超过 50MB
        </div>
      </template>
    </el-upload>

    <div class="upload-status" v-if="uploadStatus !== 'idle'">
      <el-alert
        :title="uploadStatus === 'uploading' ? '正在处理文件...' :
                uploadStatus === 'success' ? '上传成功！' :
                '上传失败'"
        :type="uploadStatus === 'uploading' ? 'info' :
               uploadStatus === 'success' ? 'success' : 'error'"
        :closable="false"
        show-icon
      />

      <el-progress v-if="uploadStatus === 'uploading'" :percentage="uploadProgress" :format="() => '处理中...'" />
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
  line-height: 1.5;
}

.upload-status {
  margin-bottom: 20px;
}

.upload-actions {
  margin-top: 20px;
}

.el-progress {
  margin-top: 10px;
}
</style>
