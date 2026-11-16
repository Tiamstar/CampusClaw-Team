<script setup lang="ts">
import { computed } from 'vue'
import type { LatencyPoint } from './latency'
const props=defineProps<{title:string;points:LatencyPoint[];interval:string}>()
const valid=computed(()=>props.points.filter(p=>p.samples>0&&(p.avg_ms!=null||p.p95_ms!=null)).sort((a,b)=>Date.parse(a.time)-Date.parse(b.time)))
const max=computed(()=>Math.max(1,...valid.value.flatMap(p=>[p.avg_ms||0,p.p95_ms||0])))
function number(n:number|null){return n==null?'未知':n.toLocaleString('zh-CN',{maximumFractionDigits:1})}
function time(t:string){return new Date(t).toLocaleString('zh-CN')}
function x(p:LatencyPoint){const first=Date.parse(valid.value[0]?.time||p.time),last=Date.parse(valid.value[valid.value.length-1]?.time||p.time);return last===first?310:45+(Date.parse(p.time)-first)/(last-first)*525}
function y(n:number){return 135-n/max.value*110}
function paths(field:'avg_ms'|'p95_ms'){
  const step=props.interval==='hour'?3600000:300000
  let last=-Infinity,open=false,path=''
  for(const p of valid.value){
    const value=p[field],stamp=Date.parse(p.time)
    if(value==null){open=false;continue}
    path+=`${open&&stamp-last<=step*1.1?'L':'M'}${x(p)},${y(value)} `;open=true;last=stamp
  }
  return path
}
</script>
<template>
<figure class="latency-chart"><figcaption>{{title}}</figcaption>
<p v-if="!valid.length">暂无完整耗时样本，未知值不补零。</p>
<template v-else>
<svg viewBox="0 0 600 165" role="img" :aria-label="title+'，平均与P95耗时曲线，单位毫秒'">
  <line x1="45" x2="575" y1="135" y2="135" stroke="#99a69e"/><line x1="45" x2="45" y1="20" y2="135" stroke="#99a69e"/>
  <text x="2" y="22">{{number(max)}} ms</text><text x="18" y="138">0</text>
  <path :d="paths('avg_ms')" fill="none" stroke="#39795b" stroke-width="2"/><path :d="paths('p95_ms')" fill="none" stroke="#436bb2" stroke-width="2"/>
  <template v-for="p in valid" :key="p.time"><circle v-if="p.avg_ms!=null" :cx="x(p)" :cy="y(p.avg_ms)" r="3.5" fill="#39795b" tabindex="0"><title>{{time(p.time)}} · {{p.samples}} 样本 · 平均 {{number(p.avg_ms)}} ms</title></circle><circle v-if="p.p95_ms!=null" :cx="x(p)" :cy="y(p.p95_ms)" r="3.5" fill="#436bb2" tabindex="0"><title>{{time(p.time)}} · {{p.samples}} 样本 · P95 {{number(p.p95_ms)}} ms</title></circle></template>
</svg>
<p class="legend"><span>绿色：平均</span><span>蓝色：P95</span> · {{interval==='hour'?'每小时':'每5分钟'}}分桶 · 缺少样本的间隔断线</p>
<p class="range">{{time(valid[0]!.time)}} — {{time(valid[valid.length-1]!.time)}}</p>
<details><summary>查看 {{valid.length}} 个时间桶的精确数值</summary><div class="table-scroll"><table><thead><tr><th>结束时间所在桶</th><th>样本数</th><th>平均 ms</th><th>P95 ms</th></tr></thead><tbody><tr v-for="p in valid" :key="p.time"><td>{{time(p.time)}}</td><td>{{p.samples}}</td><td>{{number(p.avg_ms)}}</td><td>{{number(p.p95_ms)}}</td></tr></tbody></table></div></details>
</template></figure>
</template>
<style scoped>
.latency-chart{margin:14px 0;padding:12px;border:1px solid #d9e3dd;border-radius:10px;min-width:0}.latency-chart figcaption{font-weight:600}.latency-chart svg{display:block;width:100%;height:auto;max-height:240px;margin-top:12px}.latency-chart text{font-size:10px;fill:#45554b}.legend,.range{font-size:12px;color:#526359}.legend span:first-child{color:#39795b}.legend span+span{color:#436bb2;margin-left:10px}.table-scroll{overflow-x:auto;max-height:280px}.table-scroll table{border-collapse:collapse;font-size:12px;width:100%}.table-scroll td,.table-scroll th{padding:7px;text-align:left;white-space:nowrap;border-bottom:1px solid #d9e3dd}summary{cursor:pointer}
</style>
