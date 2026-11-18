<script setup lang="ts">
function refresh(){if(confirm('刷新页面以重新加载功能？未保存的页面输入可能丢失。'))window.location.reload()}
</script>
<template><section class="workspace-load-error" role="alert"><h3>功能页面未能加载</h3><p>可能是网络中断，或页面更新后旧资源已失效。请先保留未保存的输入，再刷新重试。</p><button class="secondary" @click="refresh">刷新重试</button></section></template>
<style scoped>.workspace-load-error{padding:20px;border:1px solid #f0b6b6;border-radius:12px;background:#fff7f7;color:#7f1d1d}.workspace-load-error h3{margin-top:0}</style>
