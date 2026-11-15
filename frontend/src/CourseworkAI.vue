<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, type Assignment, type Version, type ReviewedItem } from './api'
import { renderMarkdown } from './htmlArtifacts'
const props=defineProps<{assignment:Assignment;version:Version;isTeacher:boolean}>()
const emit=defineEmits<{adopt:[value:{task_id:number;items:ReviewedItem[]}|null]}>()
type Task={id:number;kind:string;status:string;phase:string;revision:number;current:boolean;skill_id:string;settings_revision:number;error:string;result:{items?:ReviewedItem[];explanation?:string};events:{phase:string;at:string}[]}
type Config={grading_enabled:boolean;explanation_enabled:boolean;revision:number}
const config=ref<Config|null>(null),tasks=ref<Task[]>([]),loading=ref(true),busy=ref(false),error=ref(''),notice=ref('')
const rubric=ref([{title:'解题过程与结论',reference:'',maximum:props.assignment.max_score}])
const reviewed=ref<ReviewedItem[]>([]),adopted=ref<number|null>(null)
const wrongs=computed(()=>props.version.grade_published?(props.version.grade?.reviewed_items||[]).filter(r=>Number(r.score)<Number(r.maximum)):[])
const labels:Record<string,string>={queued:'排队中',running:'执行中',draft:'待教师复核',succeeded:'讲解已生成',failed:'执行失败',cancelled:'已取消'}
const phases:Record<string,string>={queued:'等待后台',read_answer:'读取本次作答',read_attachments:'提取附件文本',generate_draft:'生成建议',awaiting_review:'等待教师复核',succeeded:'已完成',failed:'失败',cancelled:'已取消'}
let alive=true,timer:number|undefined
const keys=new Map<string,string>()
function key(id:string){if(!keys.has(id))keys.set(id,crypto.randomUUID());return keys.get(id)!}
async function load(){try{
  const [c,rows]=await Promise.all([api<Config>(`courses/${props.assignment.course_id}/coursework-settings/`),api<Task[]>(`submission-versions/${props.version.id}/ai-tasks/`)])
  if(!alive)return;config.value=c;tasks.value=rows;error.value=''
  if(adopted.value&&!rows.some(t=>t.id===adopted.value&&t.current&&t.status==='draft')){manual();notice.value='草稿依据已变化，请刷新作业或重新生成'}
}catch(e){if(alive)error.value=e instanceof Error?e.message:'加载失败'}finally{if(alive)loading.value=false}}
async function act(fn:()=>Promise<void>){busy.value=true;error.value='';notice.value='';try{await fn()}catch(e){error.value=e instanceof Error?e.message:'操作失败'}finally{busy.value=false}}
async function request(kind:string,item_id?:string){await act(async()=>{const id=kind+':'+(item_id||'');await api(`submission-versions/${props.version.id}/ai-tasks/`,'POST',{kind,item_id,rubric:rubric.value,request_key:key(id)});keys.delete(id);await load()})}
async function taskAction(t:Task,action:string){await act(async()=>{await api(`coursework-tasks/${t.id}/`,'POST',{action,expected_revision:t.revision,request_key:key(String(t.id))});keys.delete(String(t.id));await load()})}
async function saveSettings(){if(!config.value)return;await act(async()=>{config.value=await api<Config>(`courses/${props.assignment.course_id}/coursework-settings/`,'POST',{...config.value,expected_revision:config.value!.revision});await load();notice.value='技能配置已保存'})}
function adopt(t:Task){adopted.value=t.id;reviewed.value=JSON.parse(JSON.stringify(t.result.items||[]));changed();notice.value='已填入复核表，请逐项检查后在下方保存批改'}
function changed(){if(adopted.value)emit('adopt',{task_id:adopted.value,items:JSON.parse(JSON.stringify(reviewed.value))})}
function manual(){adopted.value=null;reviewed.value=[];emit('adopt',null)}
onMounted(async()=>{await load();if(alive)timer=window.setInterval(()=>{if(tasks.value.some(t=>['queued','running'].includes(t.status)))void load()},3000)})
onBeforeUnmount(()=>{alive=false;window.clearInterval(timer)})
</script>
<template>
<section class="coursework-ai">
  <h3>{{isTeacher?'AI 批改建议与逐项复核':'我的作业错题'}}</h3>
  <p class="hint">AI 建议需教师复核并公开后生效。仅解析文本附件，不识别图片；不支持的附件须人工批改。</p>
  <p v-if="loading" role="status">正在加载教学技能…</p>
  <p v-if="error" role="alert">{{error}} <button type="button" class="secondary" :disabled="busy" @click="load">刷新</button></p><p v-if="notice" role="status">{{notice}}</p>
  <template v-if="config">
    <details v-if="isTeacher"><summary>课程教学技能开关（版本 {{config.revision}}）</summary>
      <label class="check"><input v-model="config.grading_enabled" type="checkbox" :disabled="busy">作业批改</label><label class="check"><input v-model="config.explanation_enabled" type="checkbox" :disabled="busy">错题讲解</label>
      <button type="button" class="secondary" :disabled="busy" @click="saveSettings">保存技能开关</button>
    </details>
    <template v-if="isTeacher">
      <details><summary>填写评分标准并生成建议</summary>
        <div v-for="(r,i) in rubric" :key="i" class="coursework-criterion">
          <label>评分项 {{i+1}}<input v-model="r.title" maxlength="200" :disabled="busy" @input="keys.delete('grading:')"></label>
          <label>该项满分<input v-model="r.maximum" type="number" min="0.01" step="0.01" :disabled="busy" @input="keys.delete('grading:')"></label>
          <label>参考答案与给分规则<textarea v-model="r.reference" rows="3" maxlength="5000" :disabled="busy" @input="keys.delete('grading:')"></textarea></label>
          <button v-if="rubric.length>1" type="button" class="secondary" :disabled="busy" @click="rubric.splice(i,1);keys.delete('grading:')">移除此项</button>
        </div>
        <p class="hint">各项满分之和须为 {{assignment.max_score}}；仅发送本次作答、文本附件、题目和评分标准。</p>
        <button type="button" class="secondary" :disabled="busy||rubric.length>=20" @click="rubric.push({title:'',reference:'',maximum:'1'});keys.delete('grading:')">添加评分项</button>
        <button type="button" class="primary" :disabled="busy||!config.grading_enabled" @click="request('grading')">生成 AI 批改建议</button>
      </details>
      <div v-if="adopted" class="coursework-criterion"><h4>逐项教师复核 · 草稿 #{{adopted}}</h4>
        <div v-for="r in reviewed" :key="r.id"><strong>{{r.title}} / {{r.maximum}} 分</strong><label>复核得分<input v-model="r.score" type="number" min="0" :max="r.maximum" step="0.01" @input="changed"></label><label>复核反馈<textarea v-model="r.feedback" rows="3" maxlength="2000" @input="changed"></textarea></label></div>
        <p>保存并公开后，未满分项进入学生个人错题。</p><button type="button" class="secondary" @click="manual">改为人工整体评分</button>
      </div>
    </template>
    <template v-else>
      <p v-if="!wrongs.length">{{version.grade_published?'暂无已复核的逐项错题记录。整体评分不会自动推断错题。':'教师尚未公开本次批改，暂无可见错题。'}}</p>
      <div v-for="r in wrongs" :key="r.id" class="coursework-criterion"><strong>{{r.title}} · {{r.score}} / {{r.maximum}}</strong><div class="markdown-body" v-html="renderMarkdown(r.feedback)"></div><button type="button" class="secondary" :disabled="busy||!config.explanation_enabled" @click="request('explanation',r.id)">生成此题讲解</button></div>
    </template>
    <details v-if="tasks.length" open><summary>教学任务记录（最近 {{tasks.length}} 条）</summary>
      <article v-for="t in tasks" :key="t.id" class="coursework-criterion">
        <strong>#{{t.id}} {{t.kind==='grading'?'作业批改':'错题讲解'}} · {{t.status==='draft'&&!t.current?'历史评分草稿':labels[t.status]||t.status}}</strong><p>{{phases[t.phase]||t.phase}} · {{t.skill_id}} · 配置 v{{t.settings_revision}}{{t.current?'':' · 依据或权限已变化，结果失效'}}</p><p v-if="t.error">{{t.error}}</p>
        <div v-if="t.result.explanation" class="markdown-body" v-html="renderMarkdown(t.result.explanation)"></div>
        <template v-if="isTeacher&&t.result.items"><div v-for="r in t.result.items" :key="r.id"><strong>{{r.title}} {{r.score}} / {{r.maximum}}</strong><div class="markdown-body" v-html="renderMarkdown(r.feedback)"></div></div><button type="button" class="secondary" :disabled="busy||!t.current" @click="adopt(t)">采用为复核起点</button></template>
        <button v-if="['queued','running'].includes(t.status)" type="button" class="secondary" :disabled="busy" @click="taskAction(t,'cancel')">取消此任务</button><button v-if="['failed','cancelled'].includes(t.status)" type="button" class="secondary" :disabled="busy" @click="taskAction(t,'retry')">重试此任务</button>
        <details><summary>执行阶段</summary><p v-for="(e,i) in t.events" :key="i">{{phases[e.phase]||e.phase}} · {{new Date(e.at).toLocaleString('zh-CN')}}</p></details>
      </article>
    </details><p v-else-if="!loading" class="hint">暂无教学任务记录。</p>
  </template>
</section>
</template>
<style scoped>
.coursework-ai{border:1px solid #d9e3dd;border-radius:12px;padding:16px;margin:20px 0;min-width:0}.coursework-ai details{margin:14px 0}.coursework-ai summary{cursor:pointer}.coursework-criterion{padding:12px 0;border-top:1px solid #d9e3dd;overflow-wrap:anywhere;min-width:0}.coursework-ai label{display:block;margin:8px 0}.coursework-ai input:not([type=checkbox]),.coursework-ai textarea{width:100%;box-sizing:border-box}.coursework-ai button{margin:6px 8px 6px 0}.coursework-ai .check{display:flex;gap:8px}
</style>
