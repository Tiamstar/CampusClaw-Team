<script setup lang="ts">
import {ref,onMounted} from 'vue'
import {api} from './api'
import WorkspaceSkeleton from './WorkspaceSkeleton.vue'
import LearningSummary from './LearningSummary.vue'
import './forum.css'
type Evidence={question_id:number;question_revision:number;attempt_id:number;quiz_id:number;grade_revision:number;score:string;maximum:string;published:boolean;submitted_at:string;points:{id:number;name:string}[]}
type Point={id:number;name:string;sample_size:number;mastery:string|null;band:string;earned?:string;maximum?:string;evidence?:Evidence[];students_with_data?:number}
type Student={student_id:number;name:string;points:Point[];trend:{start:string;end:string;sample_size:number;score_rate:string|null}[]}
type Analysis={data_version:string;policy:string;include_unpublished:boolean;window:{start:string;end:string;timezone:string};students:Student[];class_points:Point[];student_count:number}
const props=defineProps<{courseId:number;isTeacher:boolean}>()
const data=ref<Analysis|null>(null),loading=ref(false),error=ref(''),unpublished=ref(false)
const start=ref(new Date(Date.now()-90*86400000).toISOString().slice(0,10)),end=ref(new Date(Date.now()+86400000).toISOString().slice(0,10))
const labels:Record<string,string>={unknown:'未知',consolidate:'待巩固',developing:'发展中',secure:'较稳固'}
const percent=(v:string|null)=>v===null?'未知':(Number(v)*100).toFixed(1)+'%'
async function load(){loading.value=true;error.value='';try{const from=new Date(start.value+'T00:00:00Z').toISOString(),until=new Date(end.value+'T00:00:00Z').toISOString();data.value=await api<Analysis>(`courses/${props.courseId}/learning/?start=${encodeURIComponent(from)}&end=${encodeURIComponent(until)}&include_unpublished=${unpublished.value}`)}catch(e){error.value=e instanceof Error?e.message:'加载失败';data.value=null}finally{loading.value=false}}
function showEvidence(studentId:number,pointId:number){const target=document.getElementById(`learning-point-${studentId}-${pointId}`);target?.scrollIntoView({block:'start'});target?.focus({preventScroll:true})}
onMounted(load)
</script>
<template>
<section class="forum-workspace learning-workspace"><h2>学情分析</h2><p>按最近一次有效正式评分计算，同题只计一次。多知识点题分别计入各标签，这是基于标签的学习提示。</p><form class="forum-card learning-filters" @submit.prevent="load"><label>开始日期（UTC）<input v-model="start" type="date" required></label><label>结束日期（UTC，不含当日）<input v-model="end" type="date" required></label><label v-if="isTeacher"><input v-model="unpublished" type="checkbox">包含尚未公开的正式评分（仅教师）</label><button class="primary" :disabled="loading">查看此窗口</button></form>
<p v-if="loading" role="status">正在读取正式评分…</p><WorkspaceSkeleton kind="table" v-if="loading"/><p v-if="error" role="alert" class="error">{{error}}</p>
<template v-if="data"><p>数据版本 {{data.data_version.slice(0,16)}} · {{data.window.timezone}} · {{data.include_unpublished?'包含未公开评分，仅教师可见':'仅使用已公开评分'}}</p><p>图例：未知 = 无有效证据；低于 60% 待巩固，60%–不足 80% 发展中，80% 及以上较稳固。结果不作为能力的绝对判断。</p>
<article v-if="isTeacher" class="forum-card"><h3>班级知识点 · {{data.student_count}} 位学生</h3><p>按有数据学生的个人掌握度求均值，无数据者不当零分。</p><p v-if="!data.class_points.length">尚未建立知识点。</p><div v-for="p in data.class_points" :key="p.id" class="learning-point" :data-band="p.band"><strong>{{p.name}}</strong><span>{{percent(p.mastery)}} · {{labels[p.band]}}</span><span>有数据 {{p.students_with_data}} 人 · {{p.sample_size}} 题次</span></div></article>
<p v-if="!data.students.length">当前课程无可见学生记录。</p><article v-for="student in data.students" :key="student.student_id" class="forum-card"><h3>{{isTeacher?student.name:'我的学习证据'}}</h3><LearningSummary :points="student.points" @show-evidence="showEvidence(student.student_id,$event)"/><p v-if="!student.points.length">尚未建立知识点，已评分但未关联知识点的题目不计入指标。</p><section v-for="p in student.points" :key="p.id" :id="'learning-point-'+student.student_id+'-'+p.id" tabindex="-1" class="learning-point" :data-band="p.band"><strong>{{p.name}}</strong><span>{{percent(p.mastery)}} · {{labels[p.band]}}</span><span>{{p.sample_size}} 道有效题 · {{p.earned}} / {{p.maximum}}</span><details v-if="p.evidence?.length"><summary>回查评分证据</summary><p v-for="e in p.evidence" :key="e.attempt_id+'-'+e.question_id">测验 #{{e.quiz_id}} · 答卷 #{{e.attempt_id}} · 题 #{{e.question_id}}（题目 v{{e.question_revision}}）· {{e.score}} / {{e.maximum}} · 评分 v{{e.grade_revision}} · {{e.published?'已公开':'尚未公开'}}<br>提交 {{new Date(e.submitted_at).toLocaleString()}} · 当时标签：{{e.points.map(x=>x.name).join('、')}}</p></details><p v-else>没有有效评分证据，不能据此判断掌握不足。</p></section>
<h4>每 7 天得分率</h4><p>每个桶内同题取最近正式评分，只纳入有关联知识点的题；桶之间不是累计值。</p><ol class="learning-trend"><li v-for="bucket in student.trend" :key="bucket.start"><span>{{bucket.start.slice(0,10)}} 至 {{bucket.end.slice(0,10)}}（不含结束）</span><strong>{{percent(bucket.score_rate)}} · {{bucket.sample_size}} 题</strong><progress v-if="bucket.score_rate!==null" :value="Number(bucket.score_rate)" max="1" :aria-label="'该周得分率 '+percent(bucket.score_rate)"></progress></li></ol></article>
</template></section>
</template>
<style scoped>.learning-filters{display:flex;gap:1rem;flex-wrap:wrap;align-items:end}.learning-filters label{display:grid;gap:.5rem}.learning-point{display:flex;flex-direction:column;gap:.45rem;padding:1rem;margin:.7rem 0;border-left:4px solid #a5a5a5;background:#fafafa;overflow-wrap:anywhere}.learning-point[data-band=secure]{border-color:#287d59}.learning-point[data-band=developing]{border-color:#b98018}.learning-point[data-band=consolidate]{border-color:#bc5f41}.learning-trend{padding:0;list-style:none}.learning-trend li{display:flex;flex-wrap:wrap;gap:.6rem;padding:.65rem 0;border-bottom:1px solid #eee}.learning-trend progress{width:100%;height:.6rem;accent-color:#287d59}details p{font-size:.85rem}</style>
