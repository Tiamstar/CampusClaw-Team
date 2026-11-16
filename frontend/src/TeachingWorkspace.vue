<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from './api'
import { renderMarkdown } from './htmlArtifacts'
import CourseAudit from './CourseAudit.vue'
import LatencyMetrics from './LatencyMetrics.vue'
import type { HttpLatency, DurationCurves } from './latency'
const props=defineProps<{courseId:number;isTeacher:boolean}>()
type Config={guidance_enabled:boolean;grading_enabled:boolean;explanation_enabled:boolean;revision:number}
type Task={id:number;question:string;status:string;phase:string;revision:number;current:boolean;error:string;skill_id:string;settings_revision:number;result:{explanation?:string;citations?:{material_id:number;chunk_id:number;title:string;excerpt:string}[]}}
type Metric={kind:string;skill_id:string;calls:number;succeeded:number;failed:number;inflight:number;mock:number;usage_complete:number;usage_partial:number;usage_missing:number;usage_invalid:number;input_tokens:number|null;output_tokens:number|null;total_tokens:number|null;p95_ms:number|null;failure_rate:number|null;usage_coverage:number|null;queued:number;running:number;oldest_queue_seconds:number;finished_tasks:number;failed_tasks:number}
type Monitor={http_latency?:HttpLatency;duration_curves?:DurationCurves;monitor_stale:boolean;monitor_evaluated_at:string|null;usage_note:string;curve_interval:string;skills:Metric[];queue_curve:{time:string;skill_id:string;queued:number;running:number}[];alerts:{id:number;skill_id:string;rule:string;firing:boolean;value:number;threshold:number;sample_size:number}[];events:{id:number;alert__skill_id:string;alert__rule:string;firing:boolean;created_at:string}[]}
const config=ref<Config|null>(null),tasks=ref<Task[]>([]),monitor=ref<Monitor|null>(null)
const configDirty=ref(false)
const loading=ref(true),busy=ref(false),error=ref(''),notice=ref(''),question=ref(''),hours=ref(24)
const labels:Record<string,string>={guidance:'解题引导',grading:'作业批改',explanation:'错题讲解',queued:'排队中',running:'执行中',succeeded:'已完成',failed:'失败',cancelled:'已取消',failure_rate:'任务失败率',model_p95_ms:'模型 P95 耗时',queue_age_seconds:'排队等待时间'}
let alive=true,serial=0,timer:number|undefined,inflight=false
const keys=new Map<string,string>()
function key(id:string){if(!keys.has(id))keys.set(id,crypto.randomUUID());return keys.get(id)!}
function number(value:number|null|undefined){return value==null?'未上报':value.toLocaleString('zh-CN',{maximumFractionDigits:0})}
function percent(value:number|null){return value==null?'—':(value*100).toFixed(1)+'%'}
async function load(){const seq=++serial;try{
  const [c,t,m]=await Promise.all([api<Config>(`courses/${props.courseId}/coursework-settings/`),api<Task[]>(`courses/${props.courseId}/guidance-tasks/`),props.isTeacher?api<Monitor>(`courses/${props.courseId}/skill-monitor/?hours=${hours.value}`):Promise.resolve(null)])
  if(!alive||seq!==serial)return;if(!configDirty.value)config.value=c;tasks.value=t;monitor.value=m;error.value=''
}catch(e){if(alive&&seq===serial)error.value=e instanceof Error?e.message:'加载失败'}finally{if(alive&&seq===serial)loading.value=false}}
function refresh(){configDirty.value=false;void load()}
async function act(fn:()=>Promise<void>){busy.value=true;error.value='';notice.value='';try{await fn()}catch(e){if(alive)error.value=e instanceof Error?e.message:'操作失败'}finally{if(alive)busy.value=false}}
async function submit(){await act(async()=>{await api(`courses/${props.courseId}/guidance-tasks/`,'POST',{question:question.value,request_key:key('new')});keys.delete('new');if(alive){question.value='';notice.value='已进入后台队列';await load()}})}
async function taskAction(t:Task,action:string){await act(async()=>{await api(`coursework-tasks/${t.id}/`,'POST',{action,expected_revision:t.revision,request_key:key(String(t.id))});keys.delete(String(t.id));await load()})}
async function save(){if(!config.value)return;await act(async()=>{await api(`courses/${props.courseId}/coursework-settings/`,'POST',{...config.value,expected_revision:config.value!.revision});configDirty.value=false;await load();if(alive)notice.value='三项技能开关已保存；旧版本任务结果会失效'})}
onMounted(async()=>{await load();if(alive)timer=window.setInterval(async()=>{if(inflight||busy.value)return;inflight=true;try{await load()}finally{inflight=false}},10000)})
onBeforeUnmount(()=>{alive=false;serial++;window.clearInterval(timer)})
</script>
<template>
<section class="teaching-workspace">
<h2>教学技能</h2><p>解题引导使用本课程资料提供提示；作业批改与错题讲解请进入对应作业。AI 建议须教师复核后才能成为正式成绩。</p>
<p v-if="loading" role="status">正在加载教学技能…</p><p v-if="error" role="alert">{{error}}</p><p v-if="notice" role="status">{{notice}}</p><button class="secondary" :disabled="busy" @click="refresh">刷新记录</button>
<template v-if="config">
<details v-if="isTeacher"><summary>三项技能统一开关 · 配置 v{{config.revision}}</summary>
<label><input v-model="config.guidance_enabled" type="checkbox" :disabled="busy" @change="configDirty=true">解题引导</label><label><input v-model="config.grading_enabled" type="checkbox" :disabled="busy" @change="configDirty=true">作业批改</label><label><input v-model="config.explanation_enabled" type="checkbox" :disabled="busy" @change="configDirty=true">错题讲解</label><button class="secondary" :disabled="busy" @click="save">保存技能开关</button></details>
<h3>解题引导</h3><p v-if="!config.guidance_enabled">教师已停用解题引导。</p>
<form @submit.prevent="submit"><label for="guide-question">描述题目和你卡住的步骤</label><textarea id="guide-question" v-model="question" maxlength="10000" rows="4" :disabled="busy||!config.guidance_enabled" @input="keys.delete('new')"></textarea><button class="primary" :disabled="busy||!question.trim()||!config.guidance_enabled||tasks.some(t=>['queued','running'].includes(t.status))">提交引导任务</button></form>
<p class="hint">提问和讲解仅本人可见；教师监控只显示汇总。最近 30 条任务保留如下。</p>
<p v-if="!loading&&!tasks.length">暂无解题引导记录。</p>
<article v-for="t in tasks" :key="t.id" class="teaching-card"><strong>#{{t.id}} · {{labels[t.status]||t.status}}</strong><p>{{t.question}}</p><p class="hint">{{t.skill_id}} · 配置 v{{t.settings_revision}}{{t.current?'':' · 依据或权限已变化，结果失效'}}</p><p v-if="t.error" role="status">{{t.error}}</p><div v-if="t.result.explanation" class="markdown-body" v-html="renderMarkdown(t.result.explanation)"></div>
<details v-if="t.result.citations?.length"><summary>检索资料依据</summary><p v-for="c in t.result.citations" :key="c.chunk_id">[m{{c.material_id}}:c{{c.chunk_id}}] {{c.title}}：{{c.excerpt}}</p></details>
<button v-if="['queued','running'].includes(t.status)" class="secondary" :disabled="busy" @click="taskAction(t,'cancel')">取消任务</button><button v-if="['failed','cancelled'].includes(t.status)" class="secondary" :disabled="busy" @click="taskAction(t,'retry')">重试任务</button></article>
</template>
<section v-if="isTeacher" class="monitor"><h3>教学技能运行监控</h3><label>统计窗口<select v-model="hours" @change="load"><option :value="1">近 1 小时</option><option :value="6">近 6 小时</option><option :value="24">近 24 小时</option><option :value="168">近 7 天</option></select></label>
<template v-if="monitor"><p>{{monitor.usage_note}}</p><p :role="monitor.monitor_stale?'alert':'status'">监控采样{{monitor.monitor_stale?'已过期或尚未启动':'正常'}} · {{monitor.monitor_evaluated_at?new Date(monitor.monitor_evaluated_at).toLocaleString('zh-CN'):'暂无采样'}}</p>
<div class="metric-grid"><article v-for="m in monitor.skills" :key="m.skill_id" class="teaching-card"><h4>{{labels[m.kind]}}</h4><p>模型调用 {{m.calls}} · 成功 {{m.succeeded}} · 失败/取消/中断 {{m.failed}} · 进行中 {{m.inflight}}</p><p>演示调用 {{m.mock}} · 完整用量覆盖 {{percent(m.usage_coverage)}}</p><p>输入 {{number(m.input_tokens)}} / 输出 {{number(m.output_tokens)}} / 合计 {{number(m.total_tokens)}} tokens</p><p>部分上报 {{m.usage_partial}} · 未上报 {{m.usage_missing}} · 无效 {{m.usage_invalid}}</p><p>模型 P95 {{m.p95_ms==null?'—':number(m.p95_ms)+' ms'}} · 业务完成 {{m.finished_tasks}} / 失败 {{m.failed_tasks}} · 失败率 {{percent(m.failure_rate)}}</p><p>排队 {{m.queued}} · 执行 {{m.running}} · 最长等待 {{number(m.oldest_queue_seconds)}} 秒</p></article></div>
<h4>队列采样曲线（{{monitor.curve_interval==='hour_average'?'每小时平均':'每分钟采样'}}）</h4><p v-if="!monitor.queue_curve.length">暂无队列采样；后台启动后记录，不回填历史。</p><div v-for="m in monitor.skills" :key="m.skill_id"><p>{{labels[m.kind]}}</p><div class="queue-curve" :aria-label="labels[m.kind]+'队列采样'"><div v-for="(s,i) in monitor.queue_curve.filter(s=>s.skill_id===m.skill_id)" :key="i" class="sample" :title="new Date(s.time).toLocaleString('zh-CN')+' 排队 '+s.queued+' 执行 '+s.running"><span :style="{height:Math.min(80,s.queued*16)+'px'}"></span><i :style="{height:Math.min(80,s.running*16)+'px'}"></i></div></div></div><p class="hint">绿色：排队；蓝色：执行。每条采样可悬停查看时间与数值，高于 5 项的柱高封顶。</p>
<LatencyMetrics :http="monitor.http_latency" :durations="monitor.duration_curves" :skills="monitor.skills"/>
<h4>站内运行告警</h4><p>近 15 分钟：业务失败率 &gt;20%（至少 5 项）；模型 P95 &gt;15 秒（至少 5 次）；排队等待 &gt;60 秒。每次状态变化记录一次。</p><p v-if="!monitor.alerts.length">暂无触发记录。</p><p v-for="a in monitor.alerts" :key="a.id">{{a.skill_id}} · {{labels[a.rule]}} · {{a.firing?'触发中':'已恢复'}} · {{a.value.toFixed(2)}} / 阈值 {{a.threshold}} · 样本 {{a.sample_size}}</p><details><summary>告警状态历史（当前窗口最近 50 条）</summary><p v-if="!monitor.events.length">暂无状态变化。</p><p v-for="e in monitor.events" :key="e.id">{{new Date(e.created_at).toLocaleString('zh-CN')}} · {{e.alert__skill_id}} · {{labels[e.alert__rule]}} · {{e.firing?'触发':'恢复'}}</p></details>
</template></section>
<CourseAudit v-if="isTeacher" :course-id="courseId" />
</section>
</template>
<style scoped>
.teaching-workspace{padding:20px;min-width:0;max-width:1100px;margin:auto;overflow-wrap:anywhere}.teaching-workspace textarea{display:block;width:100%;box-sizing:border-box;margin:8px 0}.teaching-workspace details,.teaching-workspace label{display:block;margin:12px 0}.teaching-card{border:1px solid #d9e3dd;border-radius:12px;padding:16px;margin:12px 0;min-width:0}.metric-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr));gap:12px}.monitor{margin-top:32px;border-top:1px solid #d9e3dd;padding-top:16px}.queue-curve{display:flex;align-items:end;height:90px;overflow-x:auto;border-bottom:1px solid #819c8b;gap:3px}.sample{display:flex;align-items:end;gap:1px;min-width:8px;height:100%;border-bottom:2px solid #93b49c}.sample span{width:4px;background:#3d8c5e}.sample i{width:4px;background:#4f83c0}.teaching-workspace button{margin:6px 8px 6px 0}
</style>
