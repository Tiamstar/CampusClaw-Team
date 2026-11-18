<script setup lang="ts">
import type {ToastLevel} from './useToasts'
defineProps<{items:{id:number;text:string;level:ToastLevel}[]}>()
defineEmits<{dismiss:[id:number]}>()
const labels={success:'成功',warning:'注意',error:'操作失败',info:'提示'}
</script>
<template><div class="toast-stack" aria-label="操作通知"><div v-for="item in items" :key="item.id" class="toast-item" :class="item.level" :role="item.level==='error'?'alert':'status'"><div><strong>{{labels[item.level]}}</strong><p>{{item.text}}</p></div><button type="button" aria-label="关闭提示" @click="$emit('dismiss',item.id)">×</button></div></div></template>
<style scoped>
.toast-stack{position:fixed;right:20px;bottom:20px;z-index:3000;display:grid;gap:8px;width:min(390px,calc(100vw - 32px));pointer-events:none}.toast-item{pointer-events:auto;display:flex;gap:12px;align-items:start;background:#fff;color:#334155;border:1px solid #cbd5e1;border-left:4px solid #3b82f6;border-radius:10px;padding:12px;box-shadow:0 8px 24px #0f172a20;overflow-wrap:anywhere}.toast-item>div{flex:1;min-width:0}.toast-item p{margin:4px 0 0}.toast-item button{border:0;background:transparent;font-size:22px;cursor:pointer;color:inherit}.toast-item.error{border-left-color:#dc2626}.toast-item.warning{border-left-color:#d97706}.toast-item.success{border-left-color:#16a34a}@media(max-width:600px){.toast-stack{right:16px;bottom:16px}}
</style>
