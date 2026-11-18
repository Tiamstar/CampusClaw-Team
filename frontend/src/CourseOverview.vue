<script setup lang="ts">
import {computed,onUnmounted,ref,watch} from 'vue'
import {RouterLink} from 'vue-router'
import {api,ApiError} from './api'
import WorkspaceSkeleton from './WorkspaceSkeleton.vue'
import RequestErrorPanel from './RequestErrorPanel.vue'
import type {CourseModule} from './router'

type Overview={role:'teacher'|'student';generated_at:string;counts:{assignment_reviews?:number;quiz_reviews?:number;assignments_to_submit?:number;missed_assignments?:number;open_quizzes:number;upcoming_quizzes:number};assignments:{id:number;title:string;due_at:string;allow_late:boolean}[];quizzes:{id:number;title:string;opens_at:string;closes_at:string}[];active_attempts:{id:number;quiz__title:string;deadline:string}[];recent_posts:{id:number;title:string;created_at:string;resolved_reply_id:number|null}[]}
const props=defineProps<{courseId:number}>()
const data=ref<Overview|null>(null),loading=ref(false),error=ref(''),status=ref<number>()
let generation=0
const teacher=computed(()=>data.value?.role==='teacher')
const at=(value:string)=>new Date(value).toLocaleString('zh-CN',{dateStyle:'medium',timeStyle:'short'})
const beforeSnapshot=(value:string)=>!!data.value&&Date.parse(value)<Date.parse(data.value.generated_at)
const moduleLink=(module:CourseModule)=>({name:'course-module',params:{courseId:props.courseId,module}})
async function load(){
 const current=++generation,courseId=props.courseId
 loading.value=true;error.value='';status.value=undefined;data.value=null
 try{const result=await api<Overview>(`courses/${courseId}/overview/`);if(current===generation)data.value=result}
 catch(e){if(current===generation){error.value=e instanceof Error?e.message:'课程首页加载失败';status.value=e instanceof ApiError?e.status:undefined}}
 finally{if(current===generation)loading.value=false}
}
watch(()=>props.courseId,()=>void load(),{immediate:true})
onUnmounted(()=>generation++)
</script>

<template>
<section class="course-overview" aria-labelledby="overview-heading">
 <header><div><h2 id="overview-heading">课程首页</h2><p>从这里找到下一项任务，或继续课程学习。</p></div><button class="secondary" :disabled="loading" @click="load">刷新概览</button></header>
 <WorkspaceSkeleton v-if="loading" kind="cards"/>
 <RequestErrorPanel v-else-if="error" :message="error" :status="status" detail="课程概览未能加载，请重试或返回课程列表重新选择。" @retry="load" @back="$router.push({name:'courses'})"/>
 <template v-else-if="data">
  <p class="overview-timestamp">统计截至 {{at(data.generated_at)}}。截止时间和状态以打开详情时为准。</p>
  <div class="overview-metrics" aria-label="课程任务概览">
   <template v-if="teacher"><article><strong>{{data.counts.assignment_reviews}}</strong><span>本课程作业待批改</span></article><article><strong>{{data.counts.quiz_reviews}}</strong><span>本课程测验答卷待批改</span></article></template>
   <template v-else><article><strong>{{data.counts.assignments_to_submit}}</strong><span>尚可提交的未交作业</span></article><article><strong>{{data.counts.missed_assignments}}</strong><span>已截止且未提交</span></article></template>
   <article><strong>{{data.counts.open_quizzes}}</strong><span>开放中的测验</span><small>不代表剩余作答次数</small></article>
  </div>
  <nav class="overview-shortcuts" aria-label="首页快捷操作">
   <RouterLink :to="moduleLink('agent')">与 AI 助手交流</RouterLink><RouterLink :to="moduleLink('materials')">查看课程资料</RouterLink>
   <template v-if="teacher"><RouterLink :to="{name:'grading'}">进入批改中心（全部任教课程）</RouterLink><RouterLink :to="moduleLink('exams')">识别与整理试卷</RouterLink><RouterLink :to="moduleLink('bank')">管理题库与组卷</RouterLink></template>
   <template v-else><RouterLink :to="moduleLink('review')">继续复习计划</RouterLink><RouterLink :to="moduleLink('learning')">查看我的学情</RouterLink></template>
  </nav>
  <div class="overview-panels">
   <article class="overview-panel"><h3>{{teacher?'近期作业截止':'需要提交的作业'}}</h3><p>{{teacher?'按截止时间排列，最多显示5项。':'仅列未提交且仍可提交的作业，近期截止优先，最多显示5项。'}}</p>
    <ul v-if="data.assignments.length"><li v-for="a in data.assignments" :key="a.id"><RouterLink :to="{name:'assignment',params:{courseId,assignmentId:a.id}}">{{a.title}}</RouterLink><span :class="{'overview-overdue':beforeSnapshot(a.due_at)}">{{beforeSnapshot(a.due_at)?'已逾期 · 允许迟交':'截止'}} {{at(a.due_at)}}</span></li></ul>
    <p v-else class="overview-empty">{{teacher?'暂无未来截止的作业。':'当前没有尚可提交的未交作业。'}}</p><RouterLink :to="moduleLink('assignments')">查看全部作业 →</RouterLink>
   </article>
   <article class="overview-panel"><h3>测验安排</h3><p>{{data.counts.upcoming_quizzes}} 项尚未开放。下列最多5项，按关闭时间排列；剩余次数请到测验详情核对。</p>
    <ul v-if="data.quizzes.length"><li v-for="q in data.quizzes" :key="q.id"><strong>{{q.title}}</strong><span>{{beforeSnapshot(q.opens_at)?'开放中':'未开始'}} · {{at(q.opens_at)}} 至 {{at(q.closes_at)}}</span></li></ul>
    <p v-else class="overview-empty">暂无已发布且尚未关闭的测验。</p><RouterLink :to="moduleLink('quiz')">查看测验与答卷 →</RouterLink>
   </article>
   <article v-if="!teacher" class="overview-panel"><h3>尚未交卷的答卷</h3><p>最多显示5份；打开答卷时会再次核对截止状态。</p>
    <ul v-if="data.active_attempts.length"><li v-for="a in data.active_attempts" :key="a.id"><RouterLink :to="{name:'attempt',params:{courseId,attemptId:a.id}}">{{beforeSnapshot(a.deadline)?'核对答卷状态':'继续作答'}} · {{a.quiz__title}}</RouterLink><span>答卷截止 {{at(a.deadline)}}</span></li></ul>
    <p v-else class="overview-empty">没有尚未交卷的答卷。</p>
   </article>
   <article class="overview-panel"><h3>最近课程讨论</h3><p>按发帖时间显示最近3条，不作为未读消息统计。</p>
    <ul v-if="data.recent_posts.length"><li v-for="p in data.recent_posts" :key="p.id"><strong>{{p.title}}</strong><span>{{p.resolved_reply_id?'已解决':'待解决'}} · {{at(p.created_at)}}</span></li></ul>
    <p v-else class="overview-empty">还没有课程讨论，可以去论坛提出第一个问题。</p><RouterLink :to="moduleLink('forum')">打开答疑论坛 →</RouterLink>
   </article>
  </div>
 </template>
</section>
</template>

<style scoped>
.course-overview{max-width:1100px;margin:auto;min-width:0;overflow-wrap:anywhere}.course-overview header{display:flex;align-items:center;justify-content:space-between;gap:1rem}.course-overview h2{margin:.2rem 0}.course-overview p,.course-overview small{color:var(--text-muted,#64748b);line-height:1.6}.overview-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem;margin:1rem 0}.overview-metrics article{padding:1rem;border:1px solid var(--border,#e2e8f0);border-radius:12px;display:flex;flex-direction:column;gap:.3rem;background:var(--surface,#fff)}.overview-metrics strong{font-size:1.8rem;color:var(--red,#8b2432)}.overview-shortcuts{display:flex;flex-wrap:wrap;gap:.6rem;margin:1.2rem 0}.overview-shortcuts a{padding:.65rem .85rem;border:1px solid var(--border,#e2e8f0);border-radius:9px;background:var(--surface,#fff);text-decoration:none}.course-overview a{color:var(--red,#8b2432)}.course-overview a:focus-visible{outline:2px solid currentColor;outline-offset:3px}.overview-panels{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}.overview-panel{min-width:0;padding:1.1rem;border:1px solid var(--border,#e2e8f0);border-radius:12px;background:var(--surface,#fff)}.overview-panel h3{margin:0}.overview-panel ul{padding:0;list-style:none}.overview-panel li{display:flex;flex-direction:column;gap:.4rem;padding:.85rem 0;border-bottom:1px solid var(--border,#e2e8f0)}.overview-panel li span{font-size:.85rem;color:var(--text-muted,#64748b)}.overview-panel li .overview-overdue{color:#9a3412}.overview-empty{padding:.8rem 0}.overview-timestamp{font-size:.85rem}@media(max-width:600px){.overview-metrics{gap:.5rem}.overview-metrics article{padding:.7rem;font-size:.8rem}.overview-metrics strong{font-size:1.5rem}.overview-panels{grid-template-columns:1fr}.course-overview header{align-items:flex-start}.course-overview header button{flex-shrink:0}.overview-shortcuts a{flex:1 1 140px;text-align:center}}
</style>
