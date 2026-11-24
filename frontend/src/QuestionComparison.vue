<script setup lang="ts">
import {computed,onMounted,onBeforeUnmount,ref} from 'vue'
import RequestErrorPanel from './RequestErrorPanel.vue'
import {api,openProtected} from './api'
import QuestionContent from './QuestionContent.vue'
import WorkspaceSkeleton from './WorkspaceSkeleton.vue'
import {useBatchQuizReview} from './useBatchQuizReview'
import {registerReviewNotes} from './unsavedReviewNotes'
type Row={attempt_id:number;student_name:string;number:number;answer:any;score:string|null;feedback:string;grade_revision:number;grading_status:string;draftScore:string|number;draftFeedback:string;reason:string;baseline:string;saving:boolean;error:string;notice:string}
const props=defineProps<{attemptId:number}>()
const emit=defineEmits<{back:[];saved:[]}>()
const data=ref<any>(null),rows=ref<Row[]>([]),questionId=ref<number>(),currentPage=ref(1),loading=ref(false),error=ref('')
const loadStatus=ref<number>(),failedTarget=ref<{id:number|undefined;page:number}>()
function retryLoad(){const target=failedTarget.value;void load(target?.id??questionId.value,target?.page??currentPage.value)}
const batch=useBatchQuizReview()
const batchBusy=batch.busy,batchProgress=batch.progress,batchReviews=batch.reviews
function suggestion(r:Row){const review=batchReviews.value[r.attempt_id];return review?.revision===r.grade_revision&&!review.error&&review.ready?review.items.find(i=>i.question_id===questionId.value):undefined}
function adopt(r:Row){const item=suggestion(r);if(!item||item.score===null)return;r.draftScore=item.score;r.draftFeedback=item.feedback;r.reason||='教师核对并采用AI本题建议'}
const snapshot=(r:Row)=>JSON.stringify([String(r.draftScore),r.draftFeedback,r.reason])
const dirty=computed(()=>batchBusy.value||rows.value.some(r=>r.saving||snapshot(r)!==r.baseline))
const warning='按题批改尚未保存，继续会丢失当前评分修改。确定继续？'
const unregister=registerReviewNotes(()=>dirty.value,warning)
function canLeave(){return !dirty.value||window.confirm(warning)}
function unload(e:BeforeUnloadEvent){if(dirty.value){e.preventDefault();e.returnValue=''}}
window.addEventListener('beforeunload',unload)
onBeforeUnmount(()=>{batch.stopAfterCurrent();unregister();window.removeEventListener('beforeunload',unload)})
function back(){if(canLeave())emit('back')}
async function load(id=questionId.value,page=1){
 if(batchBusy.value)return
 if(!canLeave())return
 loading.value=true;error.value='';loadStatus.value=undefined;failedTarget.value={id,page}
 try{
  const result=await api<any>(`quiz-attempts/${props.attemptId}/comparison/?page=${page}${id?'&question_id='+id:''}`)
  rows.value=result.items.map((r:any)=>{const row={...r,draftScore:r.score??'',draftFeedback:r.feedback,reason:'',saving:false,error:'',notice:'',baseline:''};row.baseline=snapshot(row);return row})
  data.value=result;questionId.value=result.question.id;currentPage.value=page
 }catch(e){error.value=e instanceof Error?e.message:'加载失败';loadStatus.value=typeof (e as any)?.status==='number'?(e as any).status:undefined}finally{loading.value=false}
}
function answerLabel(value:any){
 const q=data.value.question
 if(value==null)return '未作答'
 if(q.kind==='short')return value.text||'未填写文字，请查看手写图片'
 if(q.kind==='single')return String.fromCharCode(65+Number(value))
 if(q.kind==='multiple')return value.map((v:string)=>String.fromCharCode(65+Number(v))).join('、')||'未作答'
 if(q.kind==='boolean')return value==='true'?'正确':'错误'
 return String(value)
}
async function save(r:Row){
 if(batchBusy.value||r.saving)return
 r.error='';r.notice=''
 if(!String(r.draftScore).trim()||!r.reason.trim()){r.error='请填写得分与评分说明';return}
 r.saving=true
 try{
  const result=await api<any>(`quiz-attempts/${r.attempt_id}/questions/${questionId.value}/review/`,'POST',{score:String(r.draftScore),feedback:r.draftFeedback,reason:r.reason,expected_revision:r.grade_revision})
  r.score=result.score;r.draftScore=result.score;r.feedback=result.feedback;r.grade_revision=result.grade_revision;r.grading_status=result.grading_status;r.reason='';r.baseline=snapshot(r)
  r.notice='本题评分已保存；整卷成绩已转为未公开。';emit('saved')
 }catch(e){r.error=e instanceof Error?e.message:'保存失败，输入已保留'}finally{r.saving=false}
}
onMounted(()=>load())
</script>
<template><section class="question-comparison"><header><button class="secondary" :disabled="loading||batchBusy||rows.some(r=>r.saving)" @click="back">返回批改中心</button><h2>按题对比批改<span v-if="data"> · {{data.quiz_title}}</span></h2><p>仅比较冻结内容完全相同的已交卷答卷，包含同一学生的不同作答次数。逐份保存正式分数，不自动套用他人的评分。所有题目有得分后该卷评分完成；公开成绩仍在测验管理中操作。</p></header>
<RequestErrorPanel v-if="error" :message="error" :status="loadStatus" :busy="loading||batchBusy" @retry="retryLoad" @back="back"/><WorkspaceSkeleton v-if="loading" kind="cards"/>
<template v-else-if="data"><nav aria-label="选择批改题目"><button v-for="(q,i) in data.questions" :key="q.id" class="secondary" :disabled="batchBusy||rows.some(r=>r.saving)" :aria-pressed="q.id===questionId" @click="load(q.id)">第 {{Number(i)+1}} 题</button><button class="secondary" :disabled="batchBusy||rows.some(r=>r.saving)" @click="load(questionId,currentPage)">刷新当前题</button></nav>
<section class="pane"><h3>批量 AI 辅助评阅</h3><p>为本页最多20份答卷依次分析整卷，已有当前评分版本的建议会恢复。可停止后续答卷；失败可再次启动重试。建议不会自动填入或保存分数。</p><button class="secondary" :disabled="batchBusy||rows.some(r=>r.saving)||!rows.length" @click="batch.run(rows)">评阅本页答卷</button><button v-if="batchBusy" class="secondary" @click="batch.stopAfterCurrent()">当前答卷完成后停止</button><p role="status">{{batchProgress}}</p></section><section class="pane"><section v-if="data.question.group"><h3>{{data.question.group.title}}</h3><QuestionContent :text="data.question.group.material"/></section><h3>题目 · {{data.question.score}} 分</h3><QuestionContent :text="data.question.body"/><div v-for="(option,i) in data.question.options" :key="i"><strong>{{String.fromCharCode(65+Number(i))}}.</strong><QuestionContent :text="option"/></div><details><summary>查看参考答案与解析</summary><QuestionContent :text="data.question.answer.values.map((v:string)=>['single','multiple'].includes(data.question.kind)?String.fromCharCode(65+Number(v)):data.question.kind==='boolean'?(v==='true'?'正确':'错误'):v).join('；')||'未设置参考答案，请重点核对。'"/><QuestionContent :text="data.question.explanation||''"/></details></section>
<p v-if="!rows.length">该冻结试卷暂无已交卷答卷。</p><div class="comparison-grid"><article v-for="r in rows" :key="r.attempt_id" class="pane"><h3>{{r.student_name}} · 第 {{r.number}} 次</h3><small>{{r.grading_status==='finalized'?'整卷已评分':'整卷仍待批改'}} · 当前评分版本 {{r.grade_revision}}</small><QuestionContent :text="answerLabel(r.answer)"/><button v-for="(id,i) in r.answer?.image_ids||[]" :key="id" class="secondary" @click="openProtected('/api/quiz-images/'+id+'/')">查看手写图片 {{Number(i)+1}}</button><section v-if="batchReviews[r.attempt_id]" class="pane"><p role="status">{{batchReviews[r.attempt_id]!.status}}</p><p v-if="batchReviews[r.attempt_id]!.error" role="alert">{{batchReviews[r.attempt_id]!.error}}</p><template v-if="suggestion(r)"><h4>AI 建议：{{suggestion(r)!.score??'无法可靠评分'}} / {{data.question.score}}</h4><QuestionContent :text="suggestion(r)!.feedback"/><p v-if="suggestion(r)!.needs_reference">缺少参考答案，请重点复核。</p><button class="secondary" :disabled="batchBusy||r.saving||suggestion(r)!.score===null" @click="adopt(r)">核对后采用本题建议</button></template></section><form @submit.prevent="save(r)"><fieldset :disabled="r.saving||batchBusy"><label>本题得分<input v-model="r.draftScore" type="number" min="0" :max="data.question.score" step="0.01" required :aria-label="r.student_name+'本题得分'"></label><label>本题评语<textarea v-model="r.draftFeedback" maxlength="5000" rows="4"></textarea></label><label>评分说明<input v-model="r.reason" maxlength="500" required placeholder="说明本题评分依据"></label><button class="primary">{{r.saving?'正在保存…':'保存本题正式评分'}}</button></fieldset></form><p v-if="r.error" role="alert">{{r.error}}</p><p v-if="r.notice" role="status">{{r.notice}}</p></article></div><footer><button class="secondary" :disabled="batchBusy||currentPage===1||rows.some(r=>r.saving)" @click="load(questionId,currentPage-1)">上一页</button><span>第 {{currentPage}} 页 · 每页最多20份</span><button class="secondary" :disabled="batchBusy||!data.next_page||rows.some(r=>r.saving)" @click="load(questionId,data.next_page)">下一页</button></footer></template></section></template>
<style scoped>.question-comparison{max-width:1200px;margin:auto;overflow-wrap:anywhere}.comparison-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem;margin-top:1rem}.question-comparison nav,.question-comparison footer{display:flex;flex-wrap:wrap;gap:.6rem;margin:1rem 0;align-items:center}.question-comparison fieldset{border:0;padding:0;min-width:0}.question-comparison label{display:grid;gap:.4rem;margin:.7rem 0}.question-comparison input,.question-comparison textarea{width:100%;box-sizing:border-box}.question-comparison [role=alert]{color:var(--red)}@media(max-width:700px){.comparison-grid{grid-template-columns:1fr}}</style>
