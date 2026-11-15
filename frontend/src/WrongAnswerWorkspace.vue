<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { api, type Assignment, type Version } from './api'
import CourseworkAI from './CourseworkAI.vue'
const props=defineProps<{courseId:number}>()
const rows=ref<{assignment:Assignment;version:Version}[]>([]),loading=ref(false),error=ref(''),page=ref(1),more=ref(false)
let alive=true
async function load(){loading.value=true;error.value='';try{
  const data=await api<{results:typeof rows.value;has_more:boolean}>(`courses/${props.courseId}/wrong-answers/?page=${page.value}`)
  if(alive){rows.value=data.results;more.value=data.has_more}
}catch(e){if(alive)error.value=e instanceof Error?e.message:'加载失败'}finally{if(alive)loading.value=false}}
onMounted(load);onBeforeUnmount(()=>alive=false)
</script>
<template><section class="pane"><h2>我的作业错题</h2><p>仅收录本人最新提交中教师已复核并公开的未满分评分项；撤回公开、补交或改为整体评分后不再收录。</p><button class="secondary" :disabled="loading" @click="load">刷新错题</button><p v-if="error" role="alert">{{error}}</p><p v-if="loading" role="status">正在加载错题…</p><template v-else><p v-if="!rows.length&&!error">本页暂无已公开的作业错题。</p><article v-for="r in rows" :key="r.version.id+':'+r.version.grade?.revision"><h3>{{r.assignment.title}} · 第 {{r.version.number}} 版</h3><CourseworkAI :assignment="r.assignment" :version="r.version" :is-teacher="false"/></article></template><button v-if="page>1" class="secondary" :disabled="loading" @click="page--;load()">上一页</button><span>第 {{page}} 页</span><button v-if="more" class="secondary" :disabled="loading" @click="page++;load()">下一页</button></section></template>
