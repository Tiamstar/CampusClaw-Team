<script setup lang="ts">
import { ref, watch } from 'vue'
import { api } from './api'
const props=defineProps<{courseId:number}>()
type Event={id:number;created_at:string;actor_id:number|null;action:string;object_ref:string;status:string;request_id:string;skill_id:string;duration_ms:number;tokens:number|null}
const rows=ref<Event[]>([]),before=ref<number|null>(null),busy=ref(false),loaded=ref(false),error=ref('')
let serial=0
watch(()=>props.courseId,()=>{serial++;rows.value=[];before.value=null;loaded.value=false;busy.value=false;error.value=''})
async function load(more=false){
  const seq=++serial;busy.value=true;error.value=''
  try{
    const result=await api<{results:Event[];next_before:number|null}>(`courses/${props.courseId}/audit-events/?limit=30${more&&before.value?'&before='+before.value:''}`)
    if(seq!==serial)return
    rows.value=more?[...rows.value,...result.results]:result.results;before.value=result.next_before;loaded.value=true
  }catch(e){if(seq===serial)error.value=e instanceof Error?e.message:String(e)}
  finally{if(seq===serial)busy.value=false}
}
</script>
<template>
<section class="course-audit"><h3>课程操作审计</h3><p>仅任课教师可查看。记录身份编号、动作、结果和请求号，便于核对权限拒绝与工具调用。</p>
<button class="secondary" :disabled="busy" @click="load()">{{busy?'正在读取…':'读取最新记录'}}</button>
<p v-if="error" role="alert">{{error}}</p><p v-else-if="loaded&&!rows.length">暂无课程审计记录。</p>
<details v-for="row in rows" :key="row.id"><summary>{{new Date(row.created_at).toLocaleString('zh-CN')}} · {{row.action}} · {{row.status}}</summary>
<p>操作者 #{{row.actor_id??'匿名'}} · 对象 {{row.object_ref}} · 耗时 {{row.duration_ms}} ms</p><p>技能 {{row.skill_id||'—'}} · tokens {{row.tokens??'未上报'}} · 请求号 {{row.request_id}}</p></details>
<button v-if="before" class="secondary" :disabled="busy" @click="load(true)">加载更早记录</button>
</section>
</template>
<style scoped>.course-audit{margin-top:32px;border-top:1px solid #d9e3dd;padding-top:16px;overflow-wrap:anywhere}.course-audit details{padding:8px 0;border-bottom:1px solid #e2e8e4}.course-audit summary{cursor:pointer}</style>
