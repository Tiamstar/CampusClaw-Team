<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { ChevronLeft, Upload, X, RefreshCw, Check, Eye, EyeOff } from 'lucide-vue-next'
import FileCard from './FileCard.vue'
import { api, type Assignment, type FileInfo, type Submission, type SubmissionStatus, type Version } from './api'

const props = defineProps<{assignmentId:number;isTeacher:boolean}>()
const emit = defineEmits<{back:[];preview:[file:FileInfo]}>()
const assignment = ref<Assignment|null>(null), roster = ref<Submission[]>([])
const loading = ref(true), busy = ref(false), error = ref(''), notice = ref('')
const answer = ref(''), attachments = ref<File[]>([]), submissionKey = ref('')
const activeStudent = ref<number|null>(null), filter = ref('all')
const score = ref<string|number>(''), feedback = ref(''), reason = ref(''), publish = ref(false)
const labels:Record<SubmissionStatus,string> = {unsubmitted:'未提交',submitted:'已提交',pending_review:'待批改',graded:'已批改'}
const fmt = (date:string) => new Date(date).toLocaleString('zh-CN',{dateStyle:'medium',timeStyle:'short'})
const bytes = (value:number) => value < 1048576 ? `${Math.ceil(value/1024)} KB` : `${(value/1048576).toFixed(1)} MB`
const student = computed(() => roster.value.find(row => row.student.id === activeStudent.value) || null)
const latest = computed(() => student.value?.versions[0] || null)
const visibleStudents = computed(() => roster.value.filter(row => filter.value === 'all' || row.status === filter.value))
const myVersions = computed(() => assignment.value?.my_versions || [])
const myLatest = computed(() => myVersions.value[0] || null)
const now = ref(Date.now())
const deadlineTimer = window.setInterval(() => now.value = Date.now(),1000)
onBeforeUnmount(() => window.clearInterval(deadlineTimer))
const deadlinePassed = computed(() => !!assignment.value && now.value >= new Date(assignment.value.due_at).getTime())
const canSubmit = computed(() => !!assignment.value && (!deadlinePassed.value || assignment.value.allow_late))
const accept = computed(() => assignment.value?.allowed_extensions.map(value => '.'+value).join(',') || undefined)
const totalBytes = computed(() => attachments.value.reduce((sum,file) => sum+file.size,0))

function fillGrade() {
  score.value = latest.value?.grade?.score ?? ''
  feedback.value = latest.value?.grade?.feedback || ''
  publish.value = latest.value?.grade_published || false
  reason.value = ''
}
watch(latest,fillGrade)
async function load() {
  loading.value = true; error.value = ''
  try {
    const [detail, rows] = await Promise.all([
      api<Assignment>(`assignments/${props.assignmentId}/`),
      props.isTeacher ? api<Submission[]>(`assignments/${props.assignmentId}/submissions/`) : Promise.resolve([]),
    ])
    assignment.value = detail; roster.value = rows
    if (!rows.some(row => row.student.id === activeStudent.value)) activeStudent.value = rows[0]?.student.id ?? null
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '加载作业失败' }
  finally { loading.value = false }
}
async function action(task:()=>Promise<void>) {
  busy.value = true; error.value = ''; notice.value = ''
  try { await task() }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '操作失败，请重试' }
  finally { busy.value = false }
}
function addFiles(event:Event) {
  const input = event.target as HTMLInputElement
  const existing = [...attachments.value]
  for (const file of Array.from(input.files || [])) {
    if (!existing.some(item => item.name === file.name && item.size === file.size && item.lastModified === file.lastModified)) existing.push(file)
  }
  input.value = ''
  if (!assignment.value) return
  const limits = assignment.value.submission_limits
  if (existing.length > limits.max_files || existing.reduce((sum,file)=>sum+file.size,0) > limits.max_total_bytes) {
    error.value = `最多 ${limits.max_files} 个附件，合计不能超过 ${bytes(limits.max_total_bytes)}`; return
  }
  if (existing.some(file => file.size === 0 || file.size > assignment.value!.max_file_size_mb * 1048576)) {
    error.value = '附件不能为空，且每个文件须符合大小限制'; return
  }
  attachments.value = existing; submissionKey.value = ''; error.value = ''
}
function removeFile(index:number) { attachments.value.splice(index,1); submissionKey.value = '' }
async function submit() {
  if (!answer.value.trim() && !attachments.value.length) { error.value = '请填写文字作答或添加附件'; return }
  await action(async () => {
    if (!submissionKey.value) submissionKey.value = crypto.randomUUID()
    const form = new FormData()
    form.append('text_content',answer.value); form.append('submission_key',submissionKey.value)
    for (const file of attachments.value) form.append('files',file)
    await api<Version>(`assignments/${props.assignmentId}/submit/`,'POST',form)
    answer.value = ''; attachments.value = []; submissionKey.value = ''
    await load(); notice.value = '作业已提交，后续补交会保留为新版本'
  })
}
async function beginReview() {
  if (!latest.value) return
  await action(async () => {
    await api(`submission-versions/${latest.value!.id}/review/`,'POST')
    await load(); notice.value = '已进入批改，学生端显示待批改'
  })
}
async function saveGrade() {
  if (!latest.value) return
  if (String(score.value).trim() === '') { error.value = '请填写分数'; return }
  await action(async () => {
    await api(`submission-versions/${latest.value!.id}/grade/`,'POST',{
      score:String(score.value), feedback:feedback.value, reason:reason.value,
      published:publish.value, expected_revision:latest.value!.grading_revision || 0,
    })
    await load(); notice.value = publish.value ? '批改已保存，成绩与评语已公开' : '批改已保存，成绩与评语暂不公开'
  })
}
async function setPublication(published:boolean) {
  if (!latest.value?.grade) return
  await action(async () => {
    await api(`submission-versions/${latest.value!.id}/publication/`,'POST',{
      published, expected_revision:latest.value!.grading_revision || 0,
    })
    await load(); notice.value = published ? '成绩与评语已向该学生公开' : '已撤回公开，学生端不再显示分数与评语'
  })
}
onMounted(load)
</script>

<template>
  <div class="homework-workspace">
    <div class="homework-toolbar"><button class="back" @click="emit('back')"><ChevronLeft :size="17"/>返回作业列表</button><button class="secondary" :disabled="busy||loading" @click="load"><RefreshCw :size="15"/>刷新状态</button></div>
    <p v-if="error" class="homework-alert error" role="alert">{{error}}</p>
    <p v-if="notice" class="homework-alert" role="status">{{notice}}</p>
    <div v-if="loading" class="pane" role="status">正在加载作业…</div>
    <template v-else-if="assignment">
      <header class="assignment-hero"><h2>{{assignment.title}}</h2><div class="chips"><span class="chip" :class="deadlinePassed?'closed':'open'">{{deadlinePassed?(assignment.allow_late?'允许迟交':'已截止'):'进行中'}}</span><span class="chip">截止 {{fmt(assignment.due_at)}}</span><span class="chip">满分 {{assignment.max_score}}</span><span v-if="!isTeacher" class="chip">{{labels[assignment.submission_status || 'unsubmitted']}}</span></div></header>
      <section class="pane homework-instructions"><h3>作业说明</h3><p class="description">{{assignment.description || '教师未填写额外说明'}}</p><FileCard v-if="assignment.attachment" :file="assignment.attachment" @preview="emit('preview',$event)"/></section>

      <div v-if="!isTeacher" class="homework-student-layout">
        <section class="pane"><h3>{{myVersions.length?'补交新版本':'提交作业'}}</h3>
          <form @submit.prevent="submit">
            <label>文字作答<textarea v-model="answer" rows="10" :maxlength="assignment.submission_limits.max_text_length" :disabled="busy||!canSubmit" placeholder="可以直接填写答案，也可以搭配附件提交" @input="submissionKey=''"></textarea></label>
            <label>附件（可多选）<input type="file" multiple :accept="accept" :disabled="busy||!canSubmit" aria-label="添加作业附件" @change="addFiles"></label>
            <div class="homework-pending-files"><div v-for="(file,index) in attachments" :key="file.name+file.lastModified"><span>{{file.name}} <small>{{bytes(file.size)}}</small></span><button type="button" class="icon-button" :disabled="busy" :aria-label="`移除 ${file.name}`" @click="removeFile(index)"><X :size="17"/></button></div></div>
            <p class="hint">最多 {{assignment.submission_limits.max_files}} 个附件，单个 ≤ {{assignment.max_file_size_mb}} MB，合计 ≤ {{bytes(assignment.submission_limits.max_total_bytes)}}。文字和附件至少填写一项。</p>
            <p v-if="attachments.length" class="hint">已选择 {{attachments.length}} 个文件 · {{bytes(totalBytes)}}</p>
            <p v-if="!canSubmit" class="homework-alert">作业已截止，当前不允许继续提交。</p>
            <button class="primary full" :disabled="busy||!canSubmit"><Upload :size="17"/>{{busy?'正在提交…':myVersions.length?'提交新版本':'提交作业'}}</button>
          </form>
        </section>
        <section class="pane"><h3>提交与批改</h3>
          <div class="homework-status-line"><span class="homework-status" :class="assignment.submission_status">{{labels[assignment.submission_status || 'unsubmitted']}}</span><span v-if="myLatest">第 {{myLatest.number}} 版 · {{fmt(myLatest.submitted_at)}}</span></div>
          <div v-if="myLatest?.grade" class="homework-result"><span>本次得分</span><strong>{{myLatest.grade.score}} <small>/ {{assignment.max_score}}</small></strong><p>{{myLatest.grade.feedback || '教师未填写评语'}}</p></div>
          <p v-else-if="myLatest?.status==='graded'" class="homework-alert">教师已完成批改，成绩与评语暂未公开。</p>
          <p v-else-if="myLatest" class="muted">{{myLatest.status==='pending_review'?'教师正在批改，请等待结果。':'已收到提交，等待教师开始批改。'}}</p>
          <p v-else class="muted">尚未提交。提交后可在这里查看版本、批改状态和已公开成绩。</p>
          <h3 class="sub">提交记录</h3>
          <details v-for="(version,index) in myVersions" :key="version.id" class="homework-version" :open="index===0"><summary>第 {{version.number}} 版 · {{fmt(version.submitted_at)}} <span v-if="version.is_late" class="late-tag">迟交</span><span class="homework-status" :class="version.status">{{labels[version.status]}}</span></summary>
            <p v-if="version.text_content" class="homework-answer">{{version.text_content}}</p>
            <FileCard v-for="file in version.files" :key="file.id" :file="file" @preview="emit('preview',$event)"/>
            <p v-if="index>0&&version.grade" class="hint">历史成绩 {{version.grade.score}} / {{assignment.max_score}} · {{version.grade.feedback}}</p>
          </details>
        </section>
      </div>

      <div v-else class="homework-teacher-layout">
        <aside class="pane homework-roster"><h3>学生作业 <span class="count">{{roster.length}}</span></h3>
          <select v-model="filter" aria-label="筛选提交状态"><option value="all">全部状态</option><option v-for="(label,status) in labels" :key="status" :value="status">{{label}}（{{roster.filter(row=>row.status===status).length}}）</option></select>
          <button v-for="row in visibleStudents" :key="row.student.id" class="homework-student" :class="{active:row.student.id===activeStudent}" :disabled="busy" @click="activeStudent=row.student.id"><strong>{{row.student.name}}</strong><small>{{row.student.email}}</small><span class="homework-status" :class="row.status">{{labels[row.status]}}</span></button>
          <p v-if="!visibleStudents.length" class="muted">{{roster.length?'该状态下暂无学生':'暂无学生加入课程'}}</p>
        </aside>
        <section class="pane homework-review"><template v-if="student"><h3>{{student.student.name}}的作业</h3>
          <div class="homework-status-line"><span class="homework-status" :class="student.status">{{labels[student.status]}}</span><span v-if="latest">第 {{latest.number}} 版 · {{fmt(latest.submitted_at)}} <span v-if="latest.is_late" class="late-tag">迟交</span></span></div>
          <template v-if="latest">
            <div v-if="latest.text_content" class="homework-answer">{{latest.text_content}}</div>
            <FileCard v-for="file in latest.files" :key="file.id" :file="file" @preview="emit('preview',$event)"/>
            <div class="homework-review-heading"><h3>教师批改</h3><button v-if="latest.status==='submitted'" class="secondary" :disabled="busy" @click="beginReview">开始批改</button><span v-if="latest.grade" class="muted">{{latest.grade_published?'成绩已公开':'成绩未公开'}}</span></div>
            <form class="homework-grade-form" @submit.prevent="saveGrade">
              <label>分数（满分 {{assignment.max_score}}）<input v-model="score" type="number" min="0" :max="assignment.max_score" step="0.01" required :disabled="busy" aria-label="作业分数"></label>
              <label>批改评语<textarea v-model="feedback" rows="5" maxlength="10000" :disabled="busy" placeholder="指出完成情况、具体问题和改进建议"></textarea></label>
              <label v-if="latest.grade">修改说明（改分时必填）<input v-model="reason" maxlength="500" :disabled="busy" placeholder="例如：复核后补计步骤分"></label>
              <label class="check"><input v-model="publish" type="checkbox" :disabled="busy">保存后向该学生公开成绩与评语</label>
              <div class="homework-grade-actions"><button class="primary" :disabled="busy"><Check :size="16"/>{{busy?'正在保存…':'保存批改'}}</button><button v-if="latest.grade" type="button" class="secondary" :disabled="busy" @click="setPublication(!latest.grade_published)"><EyeOff v-if="latest.grade_published" :size="16"/><Eye v-else :size="16"/>{{latest.grade_published?'撤回公开':'公开成绩'}}</button></div>
            </form>
            <details v-if="latest.grade_history?.length" class="homework-version"><summary>批改与公开记录（{{latest.grade_history.length}}）</summary><div v-for="entry in latest.grade_history" :key="entry.revision" class="homework-history">第 {{entry.revision}} 次 · {{entry.score}} 分 · {{entry.published?'公开':'未公开'}}<small>{{fmt(entry.created_at)}} {{entry.reason}}</small><p v-if="entry.feedback">{{entry.feedback}}</p></div></details>
            <details v-if="student.versions.length>1" class="homework-version"><summary>历史提交（{{student.versions.length-1}}）</summary><section v-for="version in student.versions.slice(1)" :key="version.id" class="homework-history"><strong>第 {{version.number}} 版 · {{fmt(version.submitted_at)}}</strong><p v-if="version.text_content" class="homework-answer">{{version.text_content}}</p><FileCard v-for="file in version.files" :key="file.id" :file="file" @preview="emit('preview',$event)"/><p v-if="version.grade">历史成绩 {{version.grade.score}} / {{assignment.max_score}}</p></section></details>
          </template>
          <p v-else class="muted">该学生尚未提交，提交后即可查看答案和批改。</p>
        </template><p v-else class="muted">请选择一位学生查看作业。</p></section>
      </div>
    </template>
    <button v-else-if="error" class="secondary" @click="load">重新加载</button>
  </div>
</template>
