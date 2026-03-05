/*
 * @Author: e0042176 e0042176@ceic.com
 * @Date: 2026-03-03 10:33:14
 * @LastEditors: e0042176 e0042176@ceic.com
 * @LastEditTime: 2026-03-04 16:50:53
 * @FilePath: \ai\my-ai-chat\src\router\index.ts
 * @Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
 */
import { createRouter, createWebHistory } from 'vue-router'
import AiChat from '../AiChat.vue'
import ChatComponent from '../ChatComponent.vue'
import uploadFile from '../uploadFile.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      redirect: '/chat'
    },
    {
      path: '/chat',
      name: 'chat',
      component: AiChat
    },
    {
      path: '/chat-stream',
      name: 'chat-stream',
      component: ChatComponent
    },
    {
      path: '/upload',
      name: 'upload',
      component: uploadFile
    }
  ]
})

export default router
