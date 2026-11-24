<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {openProtected} from './api'
import QuestionContent from './QuestionContent.vue'
import {renderMarkdown} from './htmlArtifacts'
import './quiz-attempt.css'
import ToastStack from './ToastStack.vue'
import {useToasts} from './useToasts'
const props=defineProps<{
  attempt:any;isTeacher:boolean;answers:Record<string,any>;scores:Record<string,string>;feedback:Record<string,string>;reason:string;
  remaining:number;saveState:string;dirty:boolean;saving:boolean;busy:boolean;aiBusy:boolean;aiStatus:string;aiElapsed:number;
  aiItems:{question_id:number;score:string|null;feedback:string;needs_reference:boolean}[];aiReady:boolean;error:string;notice:string;
  suggestions:{id:number;status:string;body:string;model:string}[]
}>()
const emit=defineEmits<{back:[];changed:[];save:[];submit:[];refresh:[];review:[];suggest:[];adopt:[id:number];reason:[value:string];upload:[question:any,event:Event]}>()
const {toasts,notify,dismiss}=useToasts()
watch(()=>props.saveState,(value,old)=>{if(value==='已保存到服务器'&&old!==value)notify('答案已保存','success',2000)})
const index=ref(0),confirmSubmit=ref(false)
const kinds:Record<string,string>={single:'单选题',multiple:'多选题',boolean:'判断题',blank:'填空题',short:'简答题'}
const question=computed(()=>props.attempt.paper[index.value])
const editing=computed(()=>!props.isTeacher&&props.attempt.status==='in_progress')
const currentSuggestion=computed(()=>props.aiItems.find(i=>i.question_id===question.value?.id))
function answered(id:number){const v=props.answers[id];return Array.isArray(v)?v.length>0:typeof v==='object'&&v!==null?!!v.text?.trim()||!!v.image_ids?.length:v!==undefined&&v!==null&&String(v).trim()!==''}
const answeredCount=computed(()=>props.attempt.paper.filter((q:any)=>answered(q.id)).length)
const gradedCount=computed(()=>props.attempt.paper.filter((q:any)=>props.scores[q.id]!==''&&props.scores[q.id]!=null).length)
const draftTotal=computed(()=>props.attempt.paper.reduce((n:number,q:any)=>n+(Number(props.scores[q.id])||0),0).toFixed(2))
function shortAnswer(){const id=question.value.id;if(!props.answers[id])props.answers[id]={text:'',image_ids:[]};return props.answers[id]}
function label(q:any,value:any){if(value==null)return '未作答';if(q.kind==='short')return value.text||'未填写文字';if(q.kind==='multiple')return value.map((v:string)=>String.fromCharCode(65+Number(v))).join('、')||'未作答';if(q.kind==='single')return String.fromCharCode(65+Number(value));if(q.kind==='boolean')return value==='true'?'正确':'错误';return String(value)}
watch(()=>props.attempt.id,()=>{index.value=0;confirmSubmit.value=false})
watch(()=>props.attempt.status,()=>confirmSubmit.value=false)
</script>

<template>
<section class="quiz-attempt-page" :aria-label="isTeacher?'教师批改工作台':'测验答题工作台'">
  <header class="attempt-topbar"><button class="secondary" :disabled="aiBusy" @click="emit('back')">← 返回答卷列表</button><div><small>{{isTeacher?'批改工作台':editing?'正在答题':'答卷回顾'}}</small><h2>第 {{attempt.number}} 次作答<span v-if="attempt.student_name"> · {{attempt.student_name}}</span></h2></div><div class="attempt-top-status"><strong v-if="editing">{{Math.floor(remaining/60).toString().padStart(2,'0')}}:{{(remaining%60).toString().padStart(2,'0')}}</strong><span>{{editing?saveState:attempt.grading_status==='finalized'?'评分完成':'已交卷 · 待教师复核'}}</span></div></header>
  <p v-if="error" class="attempt-banner error" role="alert">{{error}}</p><p v-if="notice" class="attempt-banner" role="status">{{notice}}</p>
  <div class="attempt-layout">
    <aside class="answer-sheet"><h3>{{isTeacher?'批改进度':'答题卡'}}</h3><p>{{isTeacher?gradedCount:answeredCount}} / {{attempt.paper.length}} {{isTeacher?'已填分':'已作答'}}</p><div class="question-grid"><button v-for="(q,i) in (attempt.paper as any[])" :key="q.id" :aria-label="`第 ${i+1} 题`" :aria-current="index===i?'step':undefined" :class="{current:index===i,done:isTeacher?scores[q.id]!==''&&scores[q.id]!=null:answered(q.id)}" @click="index=i">{{Number(i)+1}}</button></div><p class="muted">{{isTeacher?'绿色表示已填入得分；确认保存后才形成正式成绩。':'绿色表示已填写。服务器保存成功后，刷新可恢复作答。'}}</p><button class="secondary" :disabled="busy||saving||aiBusy" @click="emit('refresh')">从服务器刷新</button>
      <template v-if="isTeacher"><div class="grade-total"><small>评分草稿合计</small><strong>{{draftTotal}} <small>分</small></strong></div><p>客观题按开考时的答案键自动判分；无答案键和简答题需要复核。</p><button class="primary" :disabled="busy||aiBusy" @click="emit('suggest')">{{aiBusy?'AI 正在评阅…':'AI 辅助批改'}}</button><div v-if="aiStatus" class="ai-progress" role="status"><span v-if="aiBusy" class="activity-dot"></span>{{aiStatus}}<small v-if="aiBusy">已等待 {{aiElapsed}} 秒 · {{aiItems.length}} / {{attempt.paper.length}} 题</small></div></template>
    </aside>
    <main v-if="question" class="attempt-question">
      <section v-if="question.group" class="shared-material"><h3>{{question.group.title}}</h3><QuestionContent :text="question.group.material"/></section>
      <div class="question-heading"><span>第 {{index+1}} 题 · {{kinds[question.kind]}}</span><strong>{{question.score}} 分</strong></div><QuestionContent :text="question.body"/>
      <fieldset v-if="question.kind==='single'||question.kind==='multiple'" class="answer-options" :disabled="!editing"><legend>{{editing?'请选择答案':'题目选项'}}</legend><label v-for="(option,i) in (question.options as string[])" :key="i" :class="{selected:question.kind==='single'?answers[question.id]===String(i):(answers[question.id]||[]).includes(String(i))}"><input v-if="question.kind==='single'" v-model="answers[question.id]" type="radio" :name="'q'+question.id" :value="String(i)" :aria-label="option" @change="emit('changed')"><input v-else type="checkbox" :aria-label="option" :checked="(answers[question.id]||[]).includes(String(i))" @change="answers[question.id]=($event.target as HTMLInputElement).checked?[...(answers[question.id]||[]),String(i)]:(answers[question.id]||[]).filter((v:string)=>v!==String(i));emit('changed')"><span class="option-letter">{{String.fromCharCode(65+i)}}</span><QuestionContent :text="option"/></label></fieldset>
      <template v-else-if="editing"><label v-if="question.kind==='boolean'" class="answer-input">你的答案<select v-model="answers[question.id]" @change="emit('changed')"><option :value="undefined">请选择</option><option value="true">正确</option><option value="false">错误</option></select></label><label v-else-if="question.kind==='blank'" class="answer-input">你的答案<input v-model="answers[question.id]" maxlength="2000" placeholder="填写答案" @input="emit('changed')"></label><label v-else class="answer-input">你的作答<textarea :value="answers[question.id]?.text||''" rows="9" maxlength="10000" placeholder="写下解题过程，也可以上传手写图片" @input="shortAnswer().text=($event.target as HTMLTextAreaElement).value;emit('changed')"></textarea></label></template>
      <section v-if="!editing" class="student-answer"><h3>学生作答</h3><QuestionContent :text="label(question,attempt.answers[question.id])"/></section>
      <div v-if="question.kind==='short'" class="handwritten-answers"><label v-if="editing">上传手写图片（每张不超过 5 MB，最多 3 张）<input type="file" accept="image/png,image/jpeg,image/webp" :disabled="busy||(answers[question.id]?.image_ids?.length||0)>=3" @change="emit('upload',question,$event)"></label><button v-for="(id,i) in (answers[question.id]?.image_ids||[] as number[])" :key="id" class="secondary" @click="openProtected('/api/quiz-images/'+id+'/')">查看手写图片 {{Number(i)+1}}</button></div>
      <section v-if="question.answer" class="reference-answer"><h3>参考答案</h3><QuestionContent :text="question.answer.values.length?question.answer.values.map((v:string)=>question.kind==='single'||question.kind==='multiple'?String.fromCharCode(65+Number(v)):question.kind==='boolean'?(v==='true'?'正确':'错误'):v).join('；'):'尚未设置参考答案，请教师核对后评分。'"/><QuestionContent :text="question.explanation||''"/></section>
      <section v-if="isTeacher&&attempt.status==='submitted'" class="question-grading"><div class="grading-fields"><label>正式得分<input v-model="scores[question.id]" type="number" min="0" :max="question.score" step="0.01" :aria-label="`第 ${index+1} 题得分`"></label><label>教师评语<textarea v-model="feedback[question.id]" rows="4" maxlength="5000" :aria-label="`第 ${index+1} 题评语`"></textarea></label></div><section v-if="currentSuggestion" class="ai-suggestion"><h3>AI 评阅建议 <span v-if="currentSuggestion.score!==null">{{currentSuggestion.score}} / {{question.score}} 分</span></h3><QuestionContent :text="currentSuggestion.feedback"/><p v-if="currentSuggestion.needs_reference" class="muted">本题缺少参考答案，请重点核对 AI 判断。</p><button class="secondary" :disabled="!aiReady||aiBusy||currentSuggestion.score===null" @click="emit('adopt',question.id)">采纳本题建议到评分草稿</button><small v-if="!aiReady">全部评阅完成后可采纳，正式分数尚未改变。</small></section><p v-else-if="aiBusy" role="status">正在评阅本卷，完成本题后会在这里显示建议…</p></section>
      <template v-else-if="attempt.status==='submitted'"><p v-if="attempt.scores?.[question.id]!=null">本题得分：{{attempt.scores[question.id]}}</p><QuestionContent v-if="attempt.feedback?.[question.id]" :text="attempt.feedback[question.id]"/><p v-if="attempt.total!=null">已公开总分：{{attempt.total}}</p><p v-else>分数尚未公开或仍待教师复核。</p></template>
      <div class="question-pagination"><button class="secondary" :disabled="index===0" @click="index--">上一题</button><span>{{index+1}} / {{attempt.paper.length}}</span><button class="secondary" :disabled="index===attempt.paper.length-1" @click="index++">下一题</button></div>
      <details v-if="isTeacher" class="grading-history"><summary>评阅和评分历史</summary><article v-for="s in suggestions" :key="s.id"><p>{{s.status==='failed'?'此前评阅未完成':'此前 AI 评阅'}} · {{s.model}}</p><p v-if="s.status==='failed'">{{s.body}}</p><div v-else-if="!s.body.trim().startsWith('{')" v-html="renderMarkdown(s.body)"></div></article><p v-for="h in attempt.grade_history" :key="h.revision">评分版本 {{h.revision}} · {{h.reason}}</p></details>
    </main>
  </div>
  <ToastStack :items="toasts" @dismiss="dismiss"/><footer class="attempt-footer"><template v-if="editing"><span role="status">{{saveState}}</span><button class="secondary" :disabled="saving||!dirty" @click="emit('save')">{{saving?'保存中…':'立即保存'}}</button><button class="primary" :disabled="busy||saving" @click="confirmSubmit=true">保存并交卷</button></template><form v-else-if="isTeacher&&attempt.status==='submitted'" @submit.prevent="emit('review')"><label>评分说明<input :value="reason" required maxlength="500" placeholder="例如：已核对参考答案及 AI 建议" @input="emit('reason',($event.target as HTMLInputElement).value)"></label><button class="primary" :disabled="busy||aiBusy">保存正式评分</button></form><span v-else>已交卷，答案不可再修改</span></footer>
  <div v-if="confirmSubmit" class="attempt-confirm-backdrop"><section role="dialog" aria-modal="true" aria-label="确认交卷"><h3>确认交卷？</h3><p>共 {{attempt.paper.length}} 题，已填写 {{answeredCount}} 题，{{attempt.paper.length-answeredCount}} 题未填写。交卷后不能修改。</p><p>系统先保存答案，再完成交卷。</p><button class="secondary" @click="confirmSubmit=false">继续作答</button><button class="primary" :disabled="busy||saving" @click="emit('submit')">确认保存并交卷</button></section></div>
</section>
</template>
