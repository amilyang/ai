/*
 * @Author: e0042176 e0042176@ceic.com
 * @Date: 2026-03-03 10:33:14
 * @LastEditors: e0042176 e0042176@ceic.com
 * @LastEditTime: 2026-03-09 15:35:53
 * @FilePath: \ai\my-ai-chat\vite.config.ts
 * @Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
 */
import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'
import vueDevTools from 'vite-plugin-vue-devtools'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    vueDevTools(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    },
  },
  server: {
    proxy: {
      '/api': {
        // target: 'https://ai-ftex.onrender.com',
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  }
})
