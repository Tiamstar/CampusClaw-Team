<script setup lang="ts">
import {computed,onUnmounted,ref,watch} from 'vue'
import {protectedObjectUrl} from './api'
import {renderMarkdown} from './htmlArtifacts'
const props=defineProps<{text:string}>()
const urls=ref<Record<string,string>>({}),errors=ref<Record<string,boolean>>({}),enlarged=ref<string|null>(null)
const parts=computed(()=>props.text.split(/(\{\{asset:\d+\}\})/g).filter(Boolean).map(text=>({text,id:text.match(/^\{\{asset:(\d+)\}\}$/)?.[1]})))
let controller:AbortController|undefined
watch(()=>props.text,async()=>{
  controller?.abort();controller=new AbortController();const current=controller
  const ids=new Set(parts.value.flatMap(p=>p.id?[p.id]:[]))
  for(const id of Object.keys(urls.value))if(!ids.has(id)){URL.revokeObjectURL(urls.value[id]);delete urls.value[id]}
  errors.value={}
  await Promise.all([...ids].filter(id=>!urls.value[id]).map(async id=>{
    try{const url=await protectedObjectUrl(`/api/question-assets/${id}/`,current.signal);if(current.signal.aborted)URL.revokeObjectURL(url);else urls.value[id]=url}
    catch{if(!current.signal.aborted)errors.value[id]=true}
  }))
},{immediate:true})
onUnmounted(()=>{controller?.abort();Object.values(urls.value).forEach(url=>URL.revokeObjectURL(url))})
</script>
<template>
<div class="question-content">
  <template v-for="(part,i) in parts" :key="i">
    <template v-if="part.id"><button v-if="urls[part.id]" type="button" class="question-picture" @click="enlarged=urls[part.id]"><img :src="urls[part.id]" alt="题目配图，点击放大" loading="lazy"></button><p v-else role="status">{{errors[part.id]?'配图加载失败，请刷新重试':'正在加载配图…'}}</p></template>
    <div v-else class="markdown-body" v-html="renderMarkdown(part.text)"></div>
  </template>
  <dialog :open="!!enlarged" class="question-image-dialog" @keydown.esc="enlarged=null"><button type="button" class="secondary" @click="enlarged=null">关闭图片</button><img v-if="enlarged" :src="enlarged" alt="放大的题目配图"></dialog>
</div>
</template>
<style scoped>
.question-content{min-width:0;overflow-wrap:anywhere}.question-picture{display:block;max-width:100%;padding:4px;background:transparent;border:1px solid #d5e0db;border-radius:8px}.question-picture img{display:block;max-width:100%;max-height:420px;object-fit:contain}.question-image-dialog[open]{position:fixed;inset:3vh 3vw;margin:auto;z-index:1100;width:94vw;max-width:1200px;height:94vh;max-height:94vh;overflow:auto;background:#fff;border:1px solid #a6b9af;border-radius:12px;box-shadow:0 0 0 100vmax #0009}.question-image-dialog img{display:block;max-width:100%;height:auto;margin:15px auto}
</style>
