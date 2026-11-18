<script setup lang="ts">
import {defineAsyncComponent,onMounted,ref} from 'vue'
import WorkspaceLoadError from './WorkspaceLoadError.vue'
const QuestionComparison=defineAsyncComponent({loader:()=>import('./QuestionComparison.vue'),loadingComponent:WorkspaceSkeleton,errorComponent:WorkspaceLoadError,delay:120,timeout:30000})
const comparisonId=ref<number|null>(null)
const queueChanged=ref(false)
async function closeComparison(){comparisonId.value=null;if(queueChanged.value){queueChanged.value=false;await load()}}
import {api} from './api'
import WorkspaceSkeleton from './WorkspaceSkeleton.vue'
type Item={kind?:'quiz';attempt_id?:number;version_id:number;version_number:number;student_id:number;student_name:string;assignment_id:number;assignment_title:string;course_id:number;course_name:string;submitted_at:string;status:string}
defineEmits<{open:[item:Item]}>()
const kind=ref<'assignment'|'quiz'>('assignment')
const items=ref<Item[]>([]),loading=ref(false),error=ref(''),next=ref<number|null>(null)
async function load(page=1){loading.value=true;error.value='';try{const data=await api<{items:Item[];next_page:number|null}>(`grading-queue/?page=${page}${kind.value==='quiz'?'&kind=quiz':''}`);items.value=page===1?data.items:[...items.value,...data.items];next.value=data.next_page}catch(e){error.value=e instanceof Error?e.message:'加载失败'}finally{loading.value=false}}
function switchKind(value:'assignment'|'quiz'){if(loading.value)return;kind.value=value;items.value=[];void load()}
onMounted(()=>load())
</script>
<template><QuestionComparison v-if="comparisonId" :attempt-id="comparisonId" @back="closeComparison" @saved="queueChanged=true"/><section v-else class="grading-center"><h1>批改中心</h1><p>查看你任教课程的作业与测验待办，较早交卷的优先显示。</p><p>作业只列最新未评分提交；测验列已交卷且尚未完成正式评分的各次答卷。成绩公开仍需单独确认。</p><div><button class="secondary" :disabled="loading" :aria-pressed="kind==='assignment'" @click="switchKind('assignment')">作业待批改</button><button class="secondary" :disabled="loading" :aria-pressed="kind==='quiz'" @click="switchKind('quiz')">测验待批改</button></div><button class="secondary" :disabled="loading" @click="load()">刷新待批改</button><p v-if="error" role="alert">{{error}}</p><WorkspaceSkeleton v-if="loading" kind="cards"/><p v-if="!loading&&!error&&!items.length">当前类型暂无待批改记录。</p><article v-for="item in items" :key="item.version_id"><div><small>{{item.course_name}}</small><h3>{{item.assignment_title}}</h3><p>{{item.student_name}} · 第{{item.version_number}}版 · {{item.status==='pending_review'?'已开始批改':'等待批改'}}</p><small>{{new Date(item.submitted_at).toLocaleString('zh-CN')}}</small></div><button v-if="kind==='quiz'&&item.attempt_id" class="secondary" @click="comparisonId=item.attempt_id">按题对比批改</button><button class="primary" @click="$emit('open',item)">{{kind==='quiz'?'批改此答卷':'批改此作业'}}</button></article><button v-if="next" class="secondary" :disabled="loading" @click="load(next!)">加载更多待办</button></section></template>
<style scoped>.grading-center{max-width:1000px;margin:auto}.grading-center article{display:flex;justify-content:space-between;align-items:center;gap:1rem;padding:1rem;border:1px solid #d9e3dd;border-radius:12px;margin:1rem 0;overflow-wrap:anywhere}.grading-center h3{margin:.4rem 0}.grading-center small{color:#526459}@media(max-width:540px){.grading-center article{display:block}.grading-center article button{margin-top:.8rem}}</style>
