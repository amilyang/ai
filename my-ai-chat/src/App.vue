<!--
 * @Author: e0042176 e0042176@ceic.com
 * @Date: 2026-03-03 10:33:14
 * @LastEditors: e0042176 e0042176@ceic.com
 * @LastEditTime: 2026-03-10 10:20:50
 * @FilePath: \ai\my-ai-chat\src\App.vue
 * @Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
-->
<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router';
</script>

<template>
  <nav style="margin-bottom: 20px;">
    <RouterLink to="/upload" style="margin-right: 15px;">上传页面</RouterLink>
    <RouterLink to="/chat-stream">流式问答页面</RouterLink>
  </nav>
  <RouterView />
</template>

<style scoped>
nav a {
  color: #0066cc;
  text-decoration: none;
}
nav a.router-link-active {
  font-weight: bold;
  color: #ff6600;
}
</style>
