<script setup lang="ts">
import { ref, watch } from 'vue'
import { api, type IndexTask } from './api'
const props = defineProps<{materialId:number;status?:string;error?:string;task?:IndexTask|null;isTeacher:boolean}>()
const emit = defineEmits<{changed:[]}>()
const busy=ref(false), notice=ref(''), history=ref<IndexTask[]>([]), historyOpen=ref(false), page=ref(1), hasMore=ref(false)
let requestKey=crypto.randomUUID()
watch(()=>props.status,(status,previous)=>{if(status!==previous&&['ready','failed','cancelled'].includes(status||''))notice.value=''})
const labels:Record<string,string>={untracked:'尚未建立索引',pending:'等待建立索引',queued:'排队中',running:'正在建立索引',ready:'已建立知识索引',failed:'未建立索引',cancelled:'索引已取消'}
const phases:Record<string,string>={queued:'等待后台执行',read_source:'读取资料',extract:'提取文本',embed:'生成文本向量',succeeded:'索引完成',failed:'执行失败',cancelled:'已取消'}
async function action(kind:'reindex'|'cancel'|'retry'){
  busy.value=true;notice.value=''
  try{
    if(kind==='reindex')await api(`materials/${props.materialId}/reindex/`,'POST',{request_key:requestKey})
    else if(props.task)await api(`index-tasks/${props.task.id}/`,'POST',{action:kind,expected_revision:props.task.revision,request_key:requestKey})
    requestKey=crypto.randomUUID();emit('changed');notice.value=kind==='cancel'?'已取消，迟到结果不会生效':'已排队，后台执行结果会自动更新'
    if(historyOpen.value)await loadHistory()
  }catch(e){notice.value=e instanceof Error?e.message:'操作失败';emit('changed')}
  finally{busy.value=false}
}
async function loadHistory(){
  busy.value=true;notice.value=''
  try{const data=await api<{results:IndexTask[];has_more:boolean}>(`materials/${props.materialId}/index-tasks/?page=${page.value}`);history.value=data.results;hasMore.value=data.has_more;historyOpen.value=true}
  catch(e){notice.value=e instanceof Error?e.message:'历史加载失败'}finally{busy.value=false}
}
async function turnPage(change:number){page.value+=change;await loadHistory()}
</script>
<template>
  <div class="index-state">
    <p :class="status==='ready'?'index-ready':status==='failed'?'index-failed':'index-pending'" role="status">{{labels[status||'untracked']||'状态未知'}}<span v-if="error">：{{error}}</span></p>
    <template v-if="isTeacher">
      <p v-if="task" class="hint">任务 #{{task.id}} · {{phases[task.phase]||task.phase}}<span v-if="task.result?.chunks"> · {{task.result.chunks}} 个片段</span></p>
      <div class="index-actions">
        <button v-if="!['queued','running'].includes(status||'')" :disabled="busy" class="secondary" @click="action(task&&['failed','cancelled'].includes(task.status)?'retry':'reindex')">{{task&&['failed','cancelled'].includes(task.status)?'重试索引':'重新建立索引'}}</button>
        <button v-else-if="task" :disabled="busy" class="secondary" @click="action('cancel')">取消索引</button>
        <button :disabled="busy" class="secondary" @click="loadHistory">索引任务历史</button>
      </div>
      <div v-if="historyOpen" class="index-history">
        <p v-if="!history.length">暂无任务记录，旧资料可手动建立索引。</p>
        <details v-for="item in history" :key="item.id"><summary>#{{item.id}} · {{phases[item.status]||labels[item.status]||item.status}}{{item.retry_of_id?` · 重试自 #${item.retry_of_id}`:''}}</summary><p v-if="item.error">{{item.error}}</p><ol><li v-for="(event,i) in item.events" :key="i">{{phases[event.phase]||event.phase}} · {{new Date(event.at).toLocaleString('zh-CN')}}</li></ol><p v-if="item.result?.content_hash">来源 SHA-256：{{item.result.content_hash}}</p></details>
        <button :disabled="busy||page<=1" @click="turnPage(-1)">上一页</button><span>第 {{page}} 页</span><button :disabled="busy||!hasMore" @click="turnPage(1)">下一页</button>
      </div>
    </template>
    <p v-if="busy" class="hint">正在处理，请稍候…</p><p v-if="notice" role="status">{{notice}}</p>
  </div>
</template>
<style scoped>
.index-state{font-size:12px;overflow-wrap:anywhere}.index-actions{display:flex;gap:8px;flex-wrap:wrap}.index-actions button{font-size:12px;padding:6px 10px}.index-history{margin-top:12px;padding:12px;background:var(--line-soft);border-radius:8px}.index-history details{margin:8px 0}.index-history button{margin:5px}.index-history ol{padding-left:20px}
</style>
