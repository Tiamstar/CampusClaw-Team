<script setup lang="ts">
import {confirmReviewNotesLeave} from './unsavedReviewNotes'
import WorkspaceSkeleton from './WorkspaceSkeleton.vue'
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { api, type Assignment, type Version } from './api'
import CourseworkAI from './CourseworkAI.vue'
const props=defineProps<{courseId:number}>()
const rows=ref<{assignment:Assignment;version:Version;reviews?:Record<string,{status:string;note:string;revision:number}>}[]>([]),loading=ref(false),error=ref(''),page=ref(1),more=ref(false)
const filter=ref<'all'|'recent'>('all')
const visibleRows=computed(()=>filter.value==='all'?rows.value:rows.value.filter(r=>r.version.submitted_at>=new Date(Date.now()-30*86400000).toISOString()))
const itemCount=computed(()=>rows.value.reduce((n,r)=>n+(r.version.grade?.reviewed_items||[]).filter(i=>Number(i.score)<Number(i.maximum)).length,0))
const weakest=computed(()=>[...rows.value].sort((a,b)=>ratio(a)-ratio(b))[0])
function ratio(row:{version:Version}){const items=(row.version.grade?.reviewed_items||[]).filter(i=>Number(i.maximum)>0);return items.length?items.reduce((n,i)=>n+Number(i.score)/Number(i.maximum),0)/items.length:1}
let alive=true
async function load(){loading.value=true;error.value='';try{
  const data=await api<{results:typeof rows.value;has_more:boolean}>(`courses/${props.courseId}/wrong-answers/?page=${page.value}`)
  if(alive){rows.value=data.results;more.value=data.has_more}
}catch(e){if(alive)error.value=e instanceof Error?e.message:'加载失败'}finally{if(alive)loading.value=false}}
function changeView(value:'all'|'recent'){if(confirmReviewNotesLeave())filter.value=value}
function refreshPage(next=page.value){if(confirmReviewNotesLeave()){page.value=next;void load()}}
onMounted(load);onBeforeUnmount(()=>alive=false)
</script>
<template><section class="pane wrong-workspace"><h2>我的作业错题</h2><p>仅收录本人最新提交中教师已复核并公开的未满分评分项；撤回公开、补交或改为整体评分后不再收录。</p><div class="wrong-summary" aria-label="错题概览"><strong>{{itemCount}}<small> 个本页未满分评分项</small></strong><span v-if="weakest">优先查看：{{weakest.assignment.title}}</span><span v-else>完成公开批改后会自动出现</span></div><div class="wrong-toolbar"><button class="secondary" :class="{active:filter==='all'}" @click="changeView('all')">本页全部</button><button class="secondary" :class="{active:filter==='recent'}" @click="changeView('recent')">最近30天</button><button class="secondary" :disabled="loading" @click="refreshPage()">刷新错题</button></div><p class="hint">点击每道错题中的“生成此题讲解”，先看教师公开反馈，再记录复习状态；整体分数不会被系统臆测成错题。</p><p v-if="error" role="alert">{{error}}</p><p v-if="loading" role="status">正在加载错题…</p><WorkspaceSkeleton kind="cards" v-if="loading"/><template v-else><p v-if="!visibleRows.length&&!error">{{filter==='recent'?'本页最近30天没有错题记录。':'本页暂无已公开的作业错题。'}}</p><article v-for="r in visibleRows" :key="r.version.id+':'+r.version.grade?.revision" class="wrong-card"><div class="wrong-card-head"><h3>{{r.assignment.title}} · 第 {{r.version.number}} 版</h3><span>{{new Date(r.version.submitted_at).toLocaleDateString('zh-CN')}}</span></div><CourseworkAI :assignment="r.assignment" :version="r.version" :is-teacher="false" :reviews="r.reviews"/></article></template><button v-if="page>1" class="secondary" :disabled="loading" @click="refreshPage(page-1)">上一页</button><span>第 {{page}} 页</span><button v-if="more" class="secondary" :disabled="loading" @click="refreshPage(page+1)">下一页</button></section></template>
<style scoped>
.wrong-summary{display:flex;align-items:center;gap:1rem;flex-wrap:wrap;padding:1rem;margin:1rem 0;background:#f7faf8;border:1px solid #d9e3dd;border-radius:10px}.wrong-summary strong{font-size:1.7rem;color:#9b4d32}.wrong-summary small{font-size:.85rem;font-weight:400;color:#526459}.wrong-summary span{color:#526459}.wrong-toolbar{display:flex;gap:.5rem;flex-wrap:wrap}.wrong-toolbar .active{background:#e0edff;color:#1648a0}.wrong-card{margin:1rem 0;padding:1rem;border:1px solid #d9e3dd;border-radius:12px}.wrong-card-head{display:flex;justify-content:space-between;gap:.75rem;align-items:baseline}.wrong-card-head h3{margin:0}.wrong-card-head span{font-size:.85rem;color:#526459}@media(max-width:540px){.wrong-card-head{display:block}.wrong-card-head span{display:block;margin-top:.35rem}}
</style>
