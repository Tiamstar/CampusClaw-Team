<script setup lang="ts">
import {computed} from 'vue'
type Evidence={attempt_id:number;question_id:number;score:string;maximum:string}
type Point={id:number;name:string;mastery:string|null;band:string;evidence?:Evidence[]}
const props=defineProps<{points:Point[]}>()
const emit=defineEmits<{showEvidence:[id:number]}>()
const bands=[{key:'consolidate',label:'待巩固'},{key:'developing',label:'发展中'},{key:'secure',label:'较稳固'},{key:'unknown',label:'未知'}]
const distribution=computed(()=>bands.map(b=>({...b,count:props.points.filter(p=>(p.mastery===null?'unknown':p.band)===b.key).length})))
const evidence=computed(()=>[...new Map(props.points.flatMap(p=>p.evidence??[]).map(e=>[`${e.attempt_id}:${e.question_id}`,e])).values()])
const rate=computed(()=>{
  const total=evidence.value.reduce((n,e)=>n+Number(e.maximum),0)
  return total>0?(100*evidence.value.reduce((n,e)=>n+Number(e.score),0)/total).toFixed(1)+'%':'未知'
})
const priorities=computed(()=>props.points.filter(p=>p.mastery!==null&&Number(p.mastery)<.8).sort((a,b)=>Number(a.mastery)-Number(b.mastery)).slice(0,3))
</script>
<template>
<section class="learning-summary" aria-label="学习概览">
  <h4>学习概览</h4>
  <div class="summary-metrics">
    <p><strong>{{points.filter(p=>p.mastery!==null).length}} / {{points.length}}</strong><span>有评分证据的知识点</span></p>
    <p><strong>{{evidence.length}}</strong><span>有效评分题次（跨标签去重）</span></p>
    <p><strong>{{rate}}</strong><span>关联题目得分率</span></p>
  </div>
  <p class="summary-note">仅统计当前窗口内关联知识点的正式评分；同一答卷同一题不因多个标签重复计分，不代表整门课程成绩。</p>
  <div class="summary-bands" aria-label="知识点分布">
    <div v-for="band in distribution" :key="band.key" :data-band="band.key"><span>{{band.label}} · {{band.count}} 个</span><progress :value="band.count" :max="Math.max(points.length,1)" :aria-label="band.label+'知识点 '+band.count+' 个'"/></div>
  </div>
  <div v-if="priorities.length" class="summary-next"><h4>优先复习</h4><p>从得分率较低的知识点开始，结合下方评分证据回查错因。</p><ol><li v-for="p in priorities" :key="p.id"><button type="button" @click="emit('showEvidence',p.id)">{{p.name}} · {{(Number(p.mastery)*100).toFixed(1)}}%</button></li></ol></div>
  <p v-else-if="!evidence.length">还没有有效评分证据。完成有关联知识点的测验并收到正式评分后，这里会显示学习概览；未知不代表零分。</p>
  <p v-else>当前有证据的知识点均达到较稳固区间，可继续练习并关注尚无证据的知识点。</p>
</section>
</template>
<style scoped>
.learning-summary{padding:1rem;border:1px solid #dfe7e2;border-radius:12px;background:#f7faf8;margin:1rem 0;overflow-wrap:anywhere}.learning-summary h4{margin:0 0 .75rem}.summary-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.75rem}.summary-metrics p{display:grid;gap:.35rem;margin:0;padding:.8rem;background:white;border-radius:8px}.summary-metrics strong{font-size:1.5rem;color:#215c43}.summary-metrics span,.summary-note{font-size:.85rem;color:#526459}.summary-bands{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.8rem}.summary-bands div{display:grid;gap:.35rem}.summary-bands progress{width:100%;accent-color:#8b9290}.summary-bands [data-band=secure] progress{accent-color:#287d59}.summary-bands [data-band=developing] progress{accent-color:#b98018}.summary-bands [data-band=consolidate] progress{accent-color:#bc5f41}.summary-next{margin-top:1rem}.summary-next button{color:#215c43;text-decoration:underline;border:0;background:transparent;font:inherit;cursor:pointer;padding:.35rem 0;text-align:left}@media(max-width:540px){.summary-metrics,.summary-bands{grid-template-columns:1fr}}
</style>
