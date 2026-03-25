<script setup lang="ts">
import { ref } from 'vue';

interface Props {
  modelValue: string[];
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: () => []
});

const emit = defineEmits<{
  (e: 'update:modelValue', value: string[]): void;
}>();

const fileInput = ref<HTMLInputElement | null>(null);

const compressImage = (file: File): Promise<string> => {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const img = new Image();
      img.onload = () => {
        const canvas = document.createElement('canvas');
        const maxSize = 1024;
        let width = img.width;
        let height = img.height;

        if (width > height) {
          if (width > maxSize) {
            height = (height * maxSize) / width;
            width = maxSize;
          }
        } else {
          if (height > maxSize) {
            width = (width * maxSize) / height;
            height = maxSize;
          }
        }

        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        ctx?.drawImage(img, 0, 0, width, height);
        resolve(canvas.toDataURL('image/jpeg', 0.7));
      };
      img.src = e.target?.result as string;
    };
    reader.readAsDataURL(file);
  });
};

const handleFiles = async (files: FileList | null) => {
  if (!files) return;

  const newImages: string[] = [];
  for (const file of files) {
    if (file.type.startsWith('image/')) {
      const compressed = await compressImage(file);
      newImages.push(compressed);
    }
  }

  emit('update:modelValue', [...props.modelValue, ...newImages]);
};

const handleClick = () => {
  fileInput.value?.click();
};

const handleFileChange = (e: Event) => {
  const target = e.target as HTMLInputElement;
  handleFiles(target.files);
  target.value = '';
};

defineExpose({
  handleClick
});
</script>

<template>
  <div class="image-uploader">
    <slot :handleClick="handleClick">
      <button @click="handleClick" class="p-2 text-gray-500 hover:text-blue-600 transition-colors">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" class="w-5 h-5">
          <rect x="3" y="3" width="18" height="18" rx="2" ry="2" stroke-width="2"/>
          <circle cx="8.5" cy="8.5" r="1.5" stroke-width="2"/>
          <polyline points="21 15 16 10 5 21" stroke-width="2"/>
        </svg>
      </button>
    </slot>

    <input
      ref="fileInput"
      type="file"
      accept="image/*"
      multiple
      class="hidden"
      @change="handleFileChange"
    />
  </div>
</template>

<style scoped>
.hidden {
  display: none;
}
</style>
