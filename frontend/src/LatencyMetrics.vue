<script setup lang="ts">
import { computed, ref } from 'vue'
import LatencyChart from './LatencyChart.vue'
import type { HttpLatency, HttpRoute, DurationCurves } from './latency'
const props=defineProps<{http?:HttpLatency;durations?:DurationCurves;skills:{kind:string;skill_id:string}[]}>()
const selected=ref('')
const names:Record<string,string>={guidance:'解题引导',grading:'作业批改',explanation:'错题讲解'}
function key(r:Pick<HttpRoute,'route'|'method'|'streaming'>){return JSON.stringify([r.method,r.route,r.streaming])}
function number(n:number|null){return n==null?'未知':n.toLocaleString('zh-CN',{maximumFractionDigits:1})}
const route=computed(()=>props.http?.routes.find(r=>key(r)===selected.value)||props.http?.routes[0])
const points=computed(()=>props.http?.curve.filter(p=>route.value&&key(p)===key(route.value))||[])
</script>
<template>
<section class="latency-metrics" aria-label="接口与技能耗时">
<h4>接口完整耗时</h4><p v-if="!http">尚无接口耗时统计。</p>
<template v-else><p>{{http.note}}</p><p v-if="!http.routes.length">当前窗口暂无归属本课程的请求记录；升级前数据不回填。</p>
<template v-else>
<label>查看接口<select :value="route?key(route):''" @change="selected=($event.target as HTMLSelectElement).value"><option v-for="r in http.routes" :key="key(r)" :value="key(r)">{{r.method}} {{r.route}} {{r.streaming?'（流式）':''}}</option></select></label>
<template v-if="route"><p>{{route.streaming?'流式响应完整耗时':'普通HTTP响应耗时'}} · 请求 {{route.requests}} / 消费完成 {{route.completed}} / 提前关闭 {{route.closed}} / 传输异常 {{route.transport_errors}}</p><p>HTTP 4xx {{route.client_errors}} / 5xx {{route.server_errors}} · 平均 {{number(route.avg_ms)}} ms / P95 {{number(route.p95_ms)}} ms</p>
<LatencyChart title="接口耗时随时间变化" :points="points" :interval="http.interval"/></template>
<p v-if="http.routes_truncated">只展示请求最多的50组接口，其余组未列出。</p>
</template></template>
<h4>三项技能耗时曲线</h4><p v-if="!durations">尚无技能耗时统计。</p>
<template v-else><p>{{durations.note}}</p>
<details v-for="s in skills" :key="s.skill_id" :open="s.kind==='guidance'"><summary>{{names[s.kind]||s.kind}} · 模型与任务耗时</summary>
<LatencyChart :title="(names[s.kind]||s.kind)+' · 真实模型调用'" :points="durations.model.filter(p=>p.skill_id===s.skill_id)" :interval="durations.interval"/>
<LatencyChart :title="(names[s.kind]||s.kind)+' · 任务总耗时（含排队）'" :points="durations.task.filter(p=>p.skill_id===s.skill_id)" :interval="durations.interval"/>
<LatencyChart :title="(names[s.kind]||s.kind)+' · 领取后的处理耗时'" :points="durations.task.filter(p=>p.skill_id===s.skill_id).map(p=>({time:p.time,samples:p.processing_samples,avg_ms:p.processing_avg_ms,p95_ms:p.processing_p95_ms}))" :interval="durations.interval"/>
<LatencyChart :title="(names[s.kind]||s.kind)+' · 排队等待耗时'" :points="durations.task.filter(p=>p.skill_id===s.skill_id).map(p=>({time:p.time,samples:p.processing_samples,avg_ms:p.queue_avg_ms,p95_ms:p.queue_p95_ms}))" :interval="durations.interval"/>
</details></template>
</section>
</template>
<style scoped>
.latency-metrics{border-top:1px solid #d9e3dd;padding-top:12px;min-width:0;margin-top:20px}.latency-metrics label{display:block}.latency-metrics select{display:block;width:100%;max-width:100%;box-sizing:border-box;margin-top:8px}.latency-metrics p{font-size:13px;line-height:1.7;overflow-wrap:anywhere}.latency-metrics details{margin:14px 0;min-width:0}.latency-metrics summary{cursor:pointer}
</style>
