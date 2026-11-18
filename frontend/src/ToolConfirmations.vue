<script setup lang="ts">
import { ref, watch } from 'vue'
import { api } from './api'
const props = defineProps<{threadId:number|null;refreshKey?:unknown;disabled?:boolean}>()
const emit = defineEmits<{done:[]}>()
type Confirmation = {id:string;tool_name:string;arguments:unknown;status:string;expires_at:string;result:unknown;error:string;uncertain:boolean}
const rows=ref<Confirmation[]>([]), loading=ref(false), busy=ref(''), error=ref('')
let generation=0
const labels:Record<string,string>={pending:'等待确认 · 尚未执行',executing:'正在执行 · 请勿重复操作',succeeded:'调用完成',failed:'调用失败 · 请核对外部状态',rejected:'已取消',expired:'已过期 · 尚未执行'}
async function load(){
  const current=++generation, thread=props.threadId
  rows.value=[];error.value=''
  if(!thread)return
  loading.value=true
  try{const result=await api<Confirmation[]>(`agent/threads/${thread}/confirmations/`);if(current===generation)rows.value=result}
  catch(e){if(current===generation)error.value=e instanceof Error?e.message:'无法读取确认记录'}
  finally{if(current===generation)loading.value=false}
}
async function act(row:Confirmation,action:'confirm'|'reject'){
  const thread=props.threadId, current=generation
  if(!thread||busy.value||props.disabled)return
  busy.value=row.id;error.value=''
  try{
    await api(`agent/threads/${thread}/confirmations/${row.id}/`,'POST',{action})
    if(current===generation){await load();emit('done')}
  }catch(e){
    if(current===generation){await load();error.value=e instanceof Error?e.message:'操作失败，请刷新核对状态'}
  }finally{busy.value=''}
}
watch(()=>[props.threadId,props.refreshKey],load,{immediate:true})
</script>

<template>
<section v-if="threadId&&(rows.length||error)" class="confirmations" aria-label="工具确认记录">
  <div class="confirmation-head"><strong>工具确认记录</strong><button class="secondary" :disabled="loading||!!busy||disabled" @click="load">刷新</button></div>
  <p v-if="loading" role="status">正在读取确认记录…</p>
  <p v-if="error" role="alert">{{error}}</p>
  <p v-if="!loading&&!error&&!rows.length">暂无待确认的工具调用。</p>
  <article v-for="row in rows" :key="row.id" class="confirmation-card">
    <strong>{{row.tool_name}}</strong><p role="status">{{labels[row.status]||row.status}}</p>
    <template v-if="row.status==='pending'"><p>MCP 工具可能访问网络或修改外部数据。请核对完整参数；本次确认仅允许尝试执行一次，5 分钟后失效。</p><p>有效期至 {{new Date(row.expires_at).toLocaleString('zh-CN')}}</p></template>
    <details :open="row.status==='pending'"><summary>完整调用参数</summary><pre>{{JSON.stringify(row.arguments,null,2)}}</pre></details>
    <div v-if="row.status==='pending'" class="confirmation-actions"><button class="primary" :disabled="!!busy||disabled" @click="act(row,'confirm')">{{busy===row.id?'处理中…':'确认并执行'}}</button><button class="secondary" :disabled="!!busy||disabled" @click="act(row,'reject')">取消调用</button></div>
    <p v-if="row.error" role="alert">{{row.error}}</p><p v-if="row.uncertain">执行状态未能确认，请先核对外部结果；系统不会自动重试。</p>
    <details v-if="['succeeded','failed'].includes(row.status)"><summary>真实工具结果</summary><pre>{{JSON.stringify(row.result,null,2)}}</pre></details>
  </article>
</section>
</template>

<style scoped>
.confirmations{margin:12px 0;padding:12px;border:1px solid var(--line);border-radius:10px;min-width:0;font-size:13px;max-height:46vh;overflow:auto}
.confirmation-head,.confirmation-actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.confirmation-head{justify-content:space-between}.confirmation-card{border-top:1px solid var(--line);padding:12px 0;overflow-wrap:anywhere}.confirmation-card p{line-height:1.6}.confirmation-card pre{max-height:260px;overflow:auto;white-space:pre;background:var(--bg,#f7f7f7);padding:10px}.confirmation-actions{margin-top:12px}summary{cursor:pointer}
</style>
