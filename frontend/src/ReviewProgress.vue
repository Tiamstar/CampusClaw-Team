<script setup lang="ts">
import {computed,ref} from 'vue'
const props=defineProps<{plan:{status:string;stale:boolean;steps:{point_id:number;name:string;prerequisite_ids:number[]}[];reminders:{point_id:number;state:string;schedule_revision:number;due_at:string;due?:boolean}[]}}>()
const minutes=ref(10)
const current=computed(()=>{const revision=Math.max(0,...props.plan.reminders.map(r=>r.schedule_revision));return props.plan.reminders.filter(r=>r.schedule_revision===revision&&r.state!=='cancelled')})
const done=computed(()=>current.value.filter(r=>r.state==='completed').length)
const pending=computed(()=>current.value.filter(r=>r.state==='scheduled'))
const percent=computed(()=>current.value.length?Math.round(done.value/current.value.length*100):0)
function progress(id:number){const rows=current.value.filter(r=>r.point_id===id);return rows.length?rows.filter(r=>r.state==='completed').length/rows.length:0}
const suggested=computed(()=>props.plan.steps.find(s=>progress(s.point_id)<.8&&s.prerequisite_ids.every(id=>progress(id)>=.8)&&current.value.some(r=>r.point_id===s.point_id)))
const estimate=computed(()=>Number.isFinite(minutes.value)&&minutes.value>=1&&minutes.value<=240?pending.value.length*minutes.value:null)
</script>
<template>
<section v-if="plan.reminders.length" class="review-progress" aria-label="复习完成进度">
 <h4>当前轮次 · 复习进度</h4>
 <p v-if="plan.stale||plan.status!=='active'">{{plan.stale?'依据已变化，请重新生成计划后继续。':'计划未启用，历史完成记录不代表当前待办。'}}</p>
 <template v-else>
 <p v-if="plan.reminders.length>=500" role="status">提醒列表可能截断，以下仅统计已加载的当前轮次，不能代表完整计划。</p>
 <progress :value="done" :max="current.length||1" aria-label="当前轮次已完成提醒"/>
 <p>已完成 {{done}} / {{current.length}} 次 · {{percent}}% · 待复习 {{pending.length}} 次 · 已到期 {{pending.filter(r=>r.due).length}} 次</p>
 <p v-if="suggested">建议下一步：{{suggested.name}}。先修步骤达到 80% 提醒完成度后推荐后续步骤。</p><p v-else-if="current.length&&pending.length===0">本轮复习待办已完成。</p>
 <label>每次复习预计分钟数<input v-model.number="minutes" type="number" min="1" max="240" step="1"></label><p v-if="estimate!==null">按你的预估，剩余约 {{estimate}} 分钟。此为计划估算，不是实际学习时长或掌握度。</p>
 <ul><li v-for="step in plan.steps.filter(s=>current.some(r=>r.point_id===s.point_id))" :key="step.point_id">{{step.name}} · 提醒完成度 {{Math.round(progress(step.point_id)*100)}}%</li></ul>
 <p class="muted">仅统计最新排期轮次，取消项不计入；完成待办不等于答题正确或知识已掌握。</p>
 </template>
</section>
</template>
<style scoped>.review-progress{padding:16px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;margin:16px 0}.review-progress h4{margin:0 0 10px}.review-progress progress{width:100%;height:14px;accent-color:#2563eb}.review-progress label{display:flex;flex-wrap:wrap;gap:10px;align-items:center}.review-progress input{width:90px}.review-progress ul{padding-left:22px}</style>
