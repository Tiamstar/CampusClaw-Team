<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed, watch, nextTick } from 'vue'
import {confirmReviewNotesLeave} from './unsavedReviewNotes'
import {asyncWorkspace} from './asyncWorkspace'
import {useRouter,useRoute} from 'vue-router'
import type {CourseModule} from './router'
const AssistantStudio=asyncWorkspace(()=>import('./AssistantStudio.vue'))
import ToolConfirmations from './ToolConfirmations.vue'
import MaterialIndexStatus from './MaterialIndexStatus.vue'
const ForumWorkspace=asyncWorkspace(()=>import('./ForumWorkspace.vue'))
const QuizWorkspace=asyncWorkspace(()=>import('./QuizWorkspace.vue'))
const GradebookWorkspace=asyncWorkspace(()=>import('./GradebookWorkspace.vue'))
const LearningWorkspace=asyncWorkspace(()=>import('./LearningWorkspace.vue'))
const CourseOverview=asyncWorkspace(()=>import('./CourseOverview.vue'))
const NotificationCenter=asyncWorkspace(()=>import('./NotificationCenter.vue'))
import NotificationIndicator from './NotificationIndicator.vue'
import WorkspaceSkeleton from './WorkspaceSkeleton.vue'
import RequestErrorPanel from './RequestErrorPanel.vue'
const GraphWorkspace=asyncWorkspace(()=>import('./GraphWorkspace.vue'))
const ReviewWorkspace=asyncWorkspace(()=>import('./ReviewWorkspace.vue'))
const DiagnosticWorkspace=asyncWorkspace(()=>import('./DiagnosticWorkspace.vue'))
import AgentResponse from './AgentResponse.vue'
import HtmlPreview from './HtmlPreview.vue'
const GradingCenter=asyncWorkspace(()=>import('./GradingCenter.vue'))
const AssignmentWorkspace=asyncWorkspace(()=>import('./AssignmentWorkspace.vue'))
const TeachingWorkspace=asyncWorkspace(()=>import('./TeachingWorkspace.vue'))
const WrongAnswerWorkspace=asyncWorkspace(()=>import('./WrongAnswerWorkspace.vue'))
import FileCard from './FileCard.vue'
import FilePreview from './FilePreview.vue'
import './homework.css'
import { renderMarkdown, type HtmlFile } from './htmlArtifacts'
import CourseNavigation from './CourseNavigation.vue'
import ToastStack from './ToastStack.vue'
import {useToasts} from './useToasts'
import { BookOpen, FolderOpen, ClipboardList, Users, LogOut, Plus, Download, RefreshCw, Upload, ChevronLeft, KeyRound, MessageSquare, Send, Square, Paperclip, FileText, ExternalLink, X, Code2, Eye, Wrench, PanelLeft, Menu } from 'lucide-vue-next'
import { api, download, openProtected, protectedObjectUrl, streamAgent, uploadAgentAttachment, type Me, type Course, type Material, type Assignment, type Member, type FileInfo, type AgentThread, type AgentMessage, type AgentCitation, type AgentArtifact } from './api'
import { clearTokens, hasStoredAuth, logoutAuth, restoreAuth, saveTokens, type TokenPair } from './auth'

const authRestoring=ref(hasStoredAuth())
const me = ref<Me|null>(null), courses = ref<Course[]>([]), selected = ref<Course|null>(null)
const navigationOpen = ref(window.innerWidth > 900), threadsOpen = ref(true)
const materials = ref<Material[]>([]), assignments = ref<Assignment[]>([]), members = ref<Member[]>([])
const currentAssignment = ref<Assignment|null>(null)
const quizWorkspace = ref<{canLeave:()=>boolean}|null>(null)
const canLeaveQuiz = () => (quizWorkspace.value?.canLeave() ?? true)&&confirmReviewNotesLeave()
const router=useRouter(),route=useRoute(),routeError=ref('')
const removeNavigationGuard=router.beforeEach((to,from)=>!me.value||to.fullPath===from.fullPath||canLeaveQuiz())
onUnmounted(removeNavigationGuard)
function leaveCourse() { void router.push({name:'courses'}) }
const businessPreview = ref<FileInfo|null>(null)
const statusLabels = {unsubmitted:"未提交",submitted:"已提交",pending_review:"待批改",graded:"已批改"}
const tab = ref<CourseModule>('overview'), authMode = ref<'login'|'register'|'reset'>('login')
watch([() => selected.value?.id, tab, me], () => businessPreview.value = null)
const email = ref(''), password = ref(''), displayName = ref(''), code = ref(''), invite = ref('')
const courseName = ref(''), courseIcon = ref<File|null>(null), joinCode = ref(''), materialTitle = ref(''), materialFile = ref<File|null>(null)
const assignmentTitle = ref(''), description = ref(''), dueAt = ref(''), allowLate = ref(false), extensions = ref(''), maxMb = ref(50), assignmentFile = ref<File|null>(null), maxScore = ref(100)
const {toasts,notify,dismiss}=useToasts()
const busy = ref(false), panel = ref<'none'|'create'|'join'|'invite'|'material'|'assignment'>('none')
const agentThreads = ref<AgentThread[]>([]), activeThread = ref<AgentThread|null>(null), agentMessages = ref<AgentMessage[]>([])
const agentDraft = ref(''), agentUseMaterials = ref(false), agentBusy = ref(false), agentStreaming = ref(''), agentRunId = ref<number|null>(null)
const agentFiles = ref<File[]>([]), agentAttachments = ref<{id:number;name:string;size:number;mime_type:string}[]>([])
const previewFile = ref<HtmlFile|null>(null), previewExpanded = ref(false)
function closePreview() { previewFile.value = null; previewExpanded.value = false }
watch([() => activeThread.value?.id, () => selected.value?.id, tab, me], closePreview)
const courseIcons = ref<Record<number,string>>({})
const courseSearch=ref(''),quizFocus=ref(false),initialAttemptId=ref<number|undefined>()
const filteredCourses=computed(()=>courses.value.filter(c=>c.name.toLowerCase().includes(courseSearch.value.trim().toLowerCase())||String(c.id)===courseSearch.value.trim()))
const isTeacher = computed(() => selected.value?.role === 'teacher')
const dueState = (a: Assignment) => new Date(a.due_at).getTime() >= Date.now() ? {text:'进行中', cls:'open'} : a.allow_late ? {text:'可迟交', cls:'late'} : {text:'已截止', cls:'closed'}
const starters = ['帮我梳理本课程资料的重点', '根据课程资料出 5 道自测题', '帮我规划一份复习提纲']
const messagesEl = ref<HTMLElement|null>(null)
watch([agentMessages, agentStreaming, () => activeThread.value?.id], async () => { await nextTick(); if (messagesEl.value) messagesEl.value.scrollTop = agentMessages.value.length || agentStreaming.value ? messagesEl.value.scrollHeight : 0 }, { deep:true })
// 中文输入法选词时按回车不应直接发送
function onComposerEnter(event: KeyboardEvent) { if (event.isComposing || event.keyCode === 229) return; event.preventDefault(); void sendAgent() }
const fmt = (date: string) => new Date(date).toLocaleString('zh-CN', { dateStyle: 'medium', timeStyle: 'short' })
const size = (bytes: number) => bytes < 1024 * 1024 ? `${Math.ceil(bytes/1024)} KB` : `${(bytes/1024/1024).toFixed(1)} MB`
async function run(task: () => Promise<void>) { busy.value = true; try { await task() } catch(e) { notify(e instanceof Error ? e.message : '操作失败','error') } finally { busy.value = false } }
async function loadCourseIcons() {
  Object.values(courseIcons.value).forEach(URL.revokeObjectURL)
  courseIcons.value = {}
  await Promise.all(courses.value.filter(c => c.icon).map(async c => {
    try { courseIcons.value[c.id] = await protectedObjectUrl(c.icon!) } catch { /* icon is optional */ }
  }))
}
async function refreshUser() { me.value = await api<Me>('me/'); courses.value = await api<Course[]>('courses/'); await loadCourseIcons() }
const assignmentLoading=ref(false),assignmentLoadError=ref('')
let navigationGeneration=0
async function applyRoute(){
  if(!me.value)return
  const generation=++navigationGeneration
  routeError.value='';panel.value='none';currentAssignment.value=null;assignmentLoading.value=false;assignmentLoadError.value=''
  if(['courses','grading','notifications'].includes(String(route.name))){selected.value=null;return}
  const course=courses.value.find(c=>c.id===Number(route.params.courseId))
  if(route.name==='not-found'||!course){selected.value=null;routeError.value=route.name==='not-found'?'这个页面地址不存在，请从课程列表重新进入。':'无法访问这个课程，请确认账号及课程成员资格。';return}
  let module:CourseModule=route.name==='forum-post'?'forum':route.name==='attempt'?'quiz':route.name==='assignment'?'assignments':route.params.module as CourseModule
  if(course.role!=='teacher'&&['bank','exams'].includes(module)){notify('题库和试卷管理仅任课教师可用','warning');await router.replace({name:'course-module',params:{courseId:course.id,module:'quiz'}});return}
  if(window.innerWidth<=900)navigationOpen.value=false
  const changed=selected.value?.id!==course.id||tab.value!==module
  selected.value=course;initialAttemptId.value=route.name==='attempt'?Number(route.params.attemptId):undefined;tab.value=module
  if(changed){materials.value=[];assignments.value=[];members.value=[];if(module==='agent'){activeThread.value=null;agentThreads.value=[];agentMessages.value=[]}}
  assignmentLoading.value=module==='assignments'
  try{await loadTab()}
  catch(e){if(generation===navigationGeneration&&module==='assignments'){assignmentLoadError.value=e instanceof Error?e.message:'作业读取失败';return}throw e}
  finally{if(generation===navigationGeneration)assignmentLoading.value=false}
  if(generation!==navigationGeneration)return
  if(route.name==='assignment'){
    currentAssignment.value=assignments.value.find(a=>a.id===Number(route.params.assignmentId))??null
    if(!currentAssignment.value)routeError.value='这个作业不存在或已不可访问，请返回作业列表。'
  }
}
watch(()=>route.fullPath,()=>{if(me.value)void run(applyRoute)})
async function start() { try { if (!hasStoredAuth()) return; try { await restoreAuth(); await refreshUser() } catch { me.value = null;return } await run(applyRoute) } finally { authRestoring.value=false } }
onMounted(start)
async function authenticate() { await run(async () => { let tokens: TokenPair; if (authMode.value === 'register') tokens = await api<TokenPair>('auth/register/', 'POST', { email:email.value, display_name:displayName.value, password:password.value, code:code.value }); else if (authMode.value === 'reset') { await api('auth/reset/', 'POST', { email:email.value, password:password.value, code:code.value }); clearTokens(); authMode.value = 'login'; notify('密码已重置，请登录','success'); return } else tokens = await api<TokenPair>('auth/login/', 'POST', { email:email.value, password:password.value }); saveTokens(tokens); await refreshUser(); await applyRoute() }) }
async function sendCode() { await run(async () => { await api('auth/code/', 'POST', { email:email.value, purpose:authMode.value === 'reset' ? 'reset' : 'register' }); notify('验证码已发送，请查看邮箱','success') }) }
async function signOut() { if(!canLeaveQuiz())return; await run(async () => { try { await logoutAuth() } finally { me.value = null; selected.value = null; navigationGeneration++; routeError.value=''; await router.replace({name:'courses'}); Object.values(courseIcons.value).forEach(URL.revokeObjectURL); courseIcons.value = {} } }) }
async function selectCourse(course: Course) { await router.push({name:'course-module',params:{courseId:course.id,module:'overview'}}) }
async function loadTab() {
  if (!selected.value) return
  const id=selected.value.id,module=tab.value,generation=navigationGeneration
  const current=()=>generation===navigationGeneration&&selected.value?.id===id&&tab.value===module
  if(module==='materials')await refreshMaterials()
  if(module==='assignments'){const rows=await api<Assignment[]>(`courses/${id}/assignments/`);if(current())assignments.value=rows}
  if(module==='members'){const rows=await api<Member[]>(`courses/${id}/members/`);if(current())members.value=rows}
  if(module==='agent')await loadAgent()
}
function syncForumPost(id:number|undefined){if(!selected.value||tab.value!=='forum')return;const target=id?{name:'forum-post',params:{courseId:selected.value.id,postId:id}}:{name:'course-module',params:{courseId:selected.value.id,module:'forum'}};if(router.resolve(target).fullPath!==route.fullPath)void router.push(target)}
async function switchTab(value:CourseModule) { if(selected.value)await router.push({name:'course-module',params:{courseId:selected.value.id,module:value}}) }
function syncAttempt(id:number|undefined){
  if(!selected.value||tab.value!=='quiz')return
  const target=id?{name:'attempt',params:{courseId:selected.value.id,attemptId:id}}:{name:'course-module',params:{courseId:selected.value.id,module:'quiz'}}
  if(router.resolve(target).fullPath!==route.fullPath)void router.push(target)
}
const materialRefreshError=ref('')
let materialUploadKey=crypto.randomUUID()
watch([materialTitle,materialFile],()=>{materialUploadKey=crypto.randomUUID()})
async function refreshMaterials(){
  const courseId=selected.value?.id
  if(!courseId)return
  try{const rows=await api<Material[]>(`courses/${courseId}/materials/`);if(selected.value?.id===courseId&&tab.value==='materials'){materials.value=rows;materialRefreshError.value=''}}
  catch(e){if(selected.value?.id===courseId&&tab.value==='materials')materialRefreshError.value=e instanceof Error?e.message:'状态刷新失败'}
}
let materialPoll:ReturnType<typeof setTimeout>|undefined
let materialPollGeneration=0
watch([()=>selected.value?.id,tab,me],()=>{
  if(materialPoll)clearTimeout(materialPoll)
  const generation=++materialPollGeneration
  const poll=async()=>{
    if(generation!==materialPollGeneration||tab.value!=='materials'||!selected.value||!me.value)return
    if(materials.value.some(m=>['queued','running','pending'].includes(m.index_status||'')))await refreshMaterials()
    if(generation===materialPollGeneration)materialPoll=setTimeout(poll,4000)
  }
  if(tab.value==='materials'&&selected.value&&me.value)materialPoll=setTimeout(poll,4000)
})
onUnmounted(()=>{materialPollGeneration++;if(materialPoll)clearTimeout(materialPoll)})
let agentLoadGeneration=0
async function loadAgent() {
  if(!selected.value)return
  const id=selected.value.id,userId=me.value?.id,generation=++agentLoadGeneration
  const assistantConfig=await api<{use_knowledge:boolean}>(`courses/${id}/assistant/`)
  const rows=await api<AgentThread[]>('agent/threads/')
  const courseThreads=rows.filter(t=>t.course_id===id)
  const thread=courseThreads.find(t=>t.id===activeThread.value?.id)||courseThreads[0]||null
  const messages=thread?await api<AgentMessage[]>(`agent/threads/${thread.id}/messages/`):[]
  if(generation!==agentLoadGeneration||selected.value?.id!==id||me.value?.id!==userId||!['agent','studio'].includes(tab.value))return
  agentUseMaterials.value=assistantConfig.use_knowledge;agentThreads.value=courseThreads;activeThread.value=thread;agentMessages.value=messages
}
async function newAgentThread() { if (!selected.value) return; activeThread.value = await api<AgentThread>('agent/threads/', 'POST', { course_id: selected.value.id }); agentThreads.value.unshift(activeThread.value); agentMessages.value = [] }
function agentFileFrom(event: Event) { const files = Array.from((event.target as HTMLInputElement).files || []); agentFiles.value.push(...files); (event.target as HTMLInputElement).value = '' }
function removeAgentFile(index: number) { agentFiles.value.splice(index, 1) }
async function sendAgent() { if (!selected.value || !agentDraft.value.trim() || agentBusy.value) return; agentBusy.value = true; try { if (!activeThread.value) await newAgentThread(); for (const file of agentFiles.value) agentAttachments.value.push(await uploadAgentAttachment(file, selected.value.id)); agentFiles.value = []; const content = agentDraft.value.trim(); agentDraft.value = ''; agentStreaming.value = ''; const attachments = agentAttachments.value.map(item => item.id); const attached = [...agentAttachments.value]; agentAttachments.value = []; agentMessages.value.push({id:Date.now(),role:'user',content, citations:[], attachments:attached.map(item => ({id:item.id,name:item.name,mime_type:item.mime_type})), metadata:{},created_at:new Date().toISOString()}); await streamAgent(`agent/threads/${activeThread.value!.id}/messages/stream/`, { content, use_course_materials: agentUseMaterials.value, attachments }, { onEvent: (type, payload) => { if (type === 'message_start') agentRunId.value = payload.run_id; if (type === 'delta') agentStreaming.value += payload.text || ''; if (type === 'message_end') notify('回答已完成','success'); if (type === 'artifact') notify('已生成文件','success'); if (type === 'tool_call') notify('正在查阅资料并处理请求…'); if (type === 'error') notify(payload.error || '生成失败','error') } }); await loadAgent(); agentStreaming.value = '' } catch (error) { notify(error instanceof Error ? error.message : '生成失败','error'); await loadAgent().catch(() => {}); agentStreaming.value = '' } finally { agentBusy.value = false; agentRunId.value = null } }
async function stopAgent() { if (!agentRunId.value) return; await api(`agent/runs/${agentRunId.value}/cancel/`, 'POST'); notify('已请求停止生成，正在保存已生成内容','success') }
async function createAgentArtifact(kind: 'pdf'|'docx') { if (!activeThread.value || !agentMessages.value.length) return; const latest = [...agentMessages.value].reverse().find(item => item.role === 'assistant'); if (!latest) return; const preview = window.open('', '_blank'); await run(async () => { try { const artifact = await api<AgentArtifact>(`agent/threads/${activeThread.value!.id}/artifacts/`, 'POST', { kind, title: latest.content.slice(0, 40), content: latest.content }); await openProtected(artifact.preview_url, preview) } catch (error) { preview?.close(); throw error } }) }
async function createCourse() { await run(async () => { const form = new FormData(); form.append('name', courseName.value); if (courseIcon.value) form.append('icon', courseIcon.value); const c = await api<Course>('courses/', 'POST', form); courses.value.unshift(c); await loadCourseIcons(); panel.value = 'none'; courseName.value = ''; courseIcon.value = null; await selectCourse(c) }) }
async function joinCourse() { await run(async () => { const c = await api<Course>('courses/join/', 'POST', {code:joinCode.value}); courses.value.unshift(c); panel.value = 'none'; joinCode.value = ''; await selectCourse(c) }) }
async function redeem() { await run(async () => { await api('teacher-invite/redeem/', 'POST', {code:invite.value}); await refreshUser(); panel.value = 'none'; invite.value = ''; notify('教师资格已开通','success') }) }
async function resetCode() { if (!selected.value || !confirm('重置后旧课程码立即失效，确定继续？')) return; await run(async () => { const result = await api<{join_code:string}>(`courses/${selected.value!.id}/code/reset/`, 'POST'); selected.value!.join_code = result.join_code; notify('课程码已重置','success') }) }
function fileFrom(event: Event, target: 'icon'|'material'|'assignment') { const f = (event.target as HTMLInputElement).files?.[0] || null; if (target === 'icon') courseIcon.value = f; else if (target === 'material') materialFile.value = f; else if (target === 'assignment') assignmentFile.value = f }
async function uploadMaterial() { if (!selected.value || !materialFile.value) { notify('请选择文件','warning'); return } await run(async () => { const form = new FormData(); form.append('file', materialFile.value!); form.append('title', materialTitle.value); form.append('request_key', materialUploadKey); await api(`courses/${selected.value!.id}/materials/`, 'POST', form); materialTitle.value = ''; materialFile.value = null; panel.value = 'none'; await loadTab() }) }
async function publish() { if (!selected.value) return; await run(async () => { const form = new FormData(); form.append('title', assignmentTitle.value); form.append('description', description.value); form.append('due_at', new Date(dueAt.value).toISOString()); form.append('allow_late', String(allowLate.value)); form.append('allowed_extensions', extensions.value); form.append('max_file_size_mb', String(maxMb.value)); form.append('max_score', String(maxScore.value)); if (assignmentFile.value) form.append('file', assignmentFile.value); await api(`courses/${selected.value!.id}/assignments/`, 'POST', form); assignmentTitle.value = ''; description.value = ''; assignmentFile.value = null; panel.value = 'none'; await loadTab() }) }
function openAssignment(a: Assignment) { if(selected.value)void router.push({name:'assignment',params:{courseId:selected.value.id,assignmentId:a.id}}) }
async function backToAssignments() { await switchTab('assignments') }
async function getFile(file: FileInfo) { await run(async () => download(file)) }
async function openCourseFile(url: string) { await run(async () => openProtected(url)) }
async function openCitation(citation: AgentCitation) { await run(async () => openProtected(citation.preview_url || `/api/materials/${citation.material_id}/preview/`)) }
async function downloadCitation(citation: AgentCitation) { await run(async () => download({id: citation.attachment_id || citation.material_id, name: citation.file_name || `${citation.title}.txt`, size: 0, created_at: '', download_url: citation.download_url})) }
function handleProtectedLink(event: MouseEvent) {
  const link = (event.target as HTMLElement).closest<HTMLAnchorElement>('a[href^="/api/"]')
  if (link) { event.preventDefault(); void openCourseFile(link.href) }
}
</script>

<template>
  <div class="app-shell" :class="{'logged-out':!me, 'signed-in':me, 'navigation-open':me && navigationOpen, 'conversation-page':me && selected && tab==='agent','assessment-page':quizFocus}" @click.capture="handleProtectedLink" @keydown.esc="navigationOpen=false;threadsOpen=false">
    <button v-if="me && navigationOpen" class="navigation-scrim" aria-label="关闭课程导航" @click="navigationOpen=false"></button>
    <aside v-if="!me || navigationOpen" id="course-navigation" class="sidebar">
      <button v-if="me" class="navigation-close" aria-label="收起课程导航" @click="navigationOpen=false"><PanelLeft :size="20"/></button>
      <div class="brand"><span class="brand-mark">C</span><span>CampusClaw</span></div>
      <template v-if="me">
        <button v-if="courses.some(c=>c.role==='teacher')" class="secondary" @click="router.push({name:'grading'})">批改中心</button><div class="sidebar-section">我的课程 <span>{{ courses.length }}</span></div>
        <nav class="course-nav"><button v-for="c in courses" :key="c.id" :class="{active:selected?.id===c.id}" @click="selectCourse(c)"><BookOpen :size="17"/><span>{{ c.name }}</span></button></nav>
        <div class="sidebar-actions"><button @click="panel='join'"><Plus :size="17"/> 加入课程</button><button v-if="me.can_create_course" @click="panel='create'"><Plus :size="17"/> 创建课程</button><button v-else @click="panel='invite'"><KeyRound :size="17"/> 兑换教师邀请码</button></div>
        <template v-if="selected">
          <div v-if="tab==='agent'" class="sidebar-history"><button class="history-heading" :aria-expanded="threadsOpen" aria-controls="conversation-navigation" @click="threadsOpen=!threadsOpen">对话记录 <ChevronLeft :size="15" :class="{'history-expanded':threadsOpen}"/></button><nav v-if="threadsOpen" id="conversation-navigation"><button v-for="thread in agentThreads" :key="thread.id" class="history-item" :class="{active:activeThread?.id===thread.id}" @click="activeThread=thread; api<AgentMessage[]>(`agent/threads/${thread.id}/messages/`).then(value=>agentMessages=value)"><MessageSquare :size="15"/><span>{{ thread.title }}</span></button><p v-if="!agentThreads.length">还没有对话</p></nav></div>
        </template>        <div class="sidebar-user"><div class="avatar">{{ me.display_name.slice(0,1) }}</div><div class="user-copy"><strong>{{ me.display_name }}</strong><small>{{ me.email }}</small></div><button title="退出登录" aria-label="退出登录" @click="signOut"><LogOut :size="18"/></button></div>
      </template>
      <div v-else class="sidebar-hero"><h2>课程学习，<br>从这里开始</h2><p>资料、作业与 AI 课程助手，集中在一个安静、有序的工作空间里。</p></div>
    </aside>
    <main class="main"><p v-if="me&&routeError" role="alert" class="error">{{routeError}} <button class="secondary" @click="route.name==='assignment'?switchTab('assignments'):leaveCourse()">{{route.name==='assignment'?'返回作业列表':'返回课程列表'}}</button></p>
      <div v-if="me" class="workspace-bar"><button class="sidebar-toggle" aria-label="切换侧边栏" title="显示或隐藏侧边栏" aria-controls="course-navigation" :aria-expanded="navigationOpen" @click="navigationOpen=!navigationOpen"><PanelLeft :size="21"/></button><span class="workspace-title">{{ selected?.name || 'CampusClaw' }}</span><NotificationIndicator :key="me.id"/><div v-if="selected && tab==='agent'" class="workspace-actions"><button class="sidebar-toggle" title="技能与工具" aria-label="技能与工具" @click="switchTab('studio')"><Wrench :size="19"/></button><button class="sidebar-toggle" title="新建对话" aria-label="新建对话" @click="newAgentThread"><Plus :size="21"/></button></div></div>
      <div v-if="authRestoring" class="auth-wrap" role="status">正在恢复登录与页面…</div><template v-else-if="!me"><div class="auth-wrap"><div class="auth-heading"><h1>{{ authMode==='login'?'登录 CampusClaw':authMode==='register'?'创建账号':'重置密码' }}</h1><p>进入你的课程空间</p></div><form @submit.prevent="authenticate"><label>邮箱<input v-model="email" type="email" required autocomplete="email" placeholder="name@example.com"></label><label v-if="authMode==='register'">姓名<input v-model="displayName" required maxlength="80" placeholder="你的姓名"></label><label v-if="authMode!=='login'">验证码<div class="inline-input"><input v-model="code" required inputmode="numeric" maxlength="6" placeholder="6 位验证码"><button type="button" class="secondary" :disabled="busy || !email" @click="sendCode">发送验证码</button></div></label><label>密码<input v-model="password" type="password" required minlength="8" autocomplete="current-password" placeholder="至少 8 位"></label><button class="primary full" :disabled="busy">{{ authMode==='login'?'登录':authMode==='register'?'注册':'重置密码' }}</button></form><div class="auth-links"><button :class="{active:authMode==='login'}" @click="authMode='login'">登录</button><button :class="{active:authMode==='register'}" @click="authMode='register'">注册</button><button :class="{active:authMode==='reset'}" @click="authMode='reset'">忘记密码</button></div></div></template>
      <GradingCenter v-else-if="route.name==='grading'" @open="(item:{course_id:number;assignment_id:number;student_id:number;attempt_id?:number})=>item.attempt_id?router.push({name:'attempt',params:{courseId:item.course_id,attemptId:item.attempt_id}}):router.push({name:'assignment',params:{courseId:item.course_id,assignmentId:item.assignment_id},query:{student:String(item.student_id)}})"/><NotificationCenter v-else-if="route.name==='notifications'" :key="me.id"/><template v-else-if="!selected"><header class="page-header"><div><h1>我的课程</h1><p>选择课程后，教师可直接进入题库、试卷识别和测验。</p></div><button class="primary" @click="panel='join'"><Plus :size="17"/> 加入课程</button></header><label class="course-search">查找课程<input v-model="courseSearch" type="search" placeholder="输入课程名称或编号"></label><p v-if="courses.length&&!filteredCourses.length" role="status">没有找到匹配的课程。</p><div v-if="courses.length" class="course-grid"><button v-for="c in filteredCourses" :key="c.id" class="course-tile" @click="selectCourse(c)"><span class="course-icon"><img v-if="courseIcons[c.id]" :src="courseIcons[c.id]" alt=""><template v-else>{{ c.name.slice(0,1) }}</template></span><strong>{{ c.name }}</strong><small>课程 #{{c.id}} · {{ c.role==='teacher'?'教师':'学生' }} · {{ c.member_count }} 位成员</small></button></div><div v-else class="empty"><BookOpen :size="34"/><h2>还没有课程</h2><p>输入课程码加入，或兑换邀请码后创建课程。</p></div></template>
      <template v-else><header class="page-header course-header"><div><button class="back" @click="leaveCourse"><ChevronLeft :size="16"/> 所有课程</button><h1>{{ selected.name }}</h1><p>课程 #{{selected.id}} · {{ isTeacher?'教师':'学生' }} · {{ selected.member_count }} 位成员</p></div><div v-if="isTeacher" class="join-code"><span>课程码</span><strong>{{ selected.join_code }}</strong><button title="重置课程码" aria-label="重置课程码" @click="resetCode"><RefreshCw :size="16"/></button></div></header>
        <CourseNavigation :active="tab" :is-teacher="isTeacher" @select="switchTab"/>
        <CourseOverview v-if="tab==='overview'" :key="selected.id" :course-id="selected.id"/>
        <GraphWorkspace v-if="tab==='graph'" :key="selected.id" :course-id="selected.id" :is-teacher="isTeacher"/>
        <TeachingWorkspace v-if="tab==='teaching'" :key="selected.id" :course-id="selected.id" :is-teacher="isTeacher"/><WrongAnswerWorkspace v-if="tab==='wrongs'" :key="selected.id" :course-id="selected.id"/><ReviewWorkspace v-if="tab==='review' && selected" :key="selected.id" :course-id="selected.id" :is-teacher="isTeacher"/>
        <DiagnosticWorkspace v-if="tab==='diagnostic' && selected" :key="selected.id" :course-id="selected.id" :is-teacher="isTeacher"/>
        <LearningWorkspace v-if="tab==='learning'" :key="selected.id" :course-id="selected.id" :is-teacher="isTeacher"/>
        <GradebookWorkspace v-if="tab==='gradebook'" :key="selected.id" :course-id="selected.id" :is-teacher="isTeacher"/>
        <QuizWorkspace :owner-id="me.id" ref="quizWorkspace" v-if="['quiz','bank','exams'].includes(tab)" :key="selected.id+tab" :course-id="selected.id" :is-teacher="isTeacher" :initial-view="tab==='exams'?'exams':tab==='bank'?'bank':undefined" :initial-attempt-id="initialAttemptId" @focus-change="quizFocus=$event" @attempt-change="syncAttempt"/>
        <ForumWorkspace :initial-post-id="route.name==='forum-post'?Number(route.params.postId):undefined" @post-change="syncForumPost" :owner-id="me.id" v-if="tab==='forum'" :key="selected.id" :course-id="selected.id" :is-teacher="isTeacher"/>
        <AssistantStudio v-if="tab==='studio'" :key="selected.id" :course-id="selected.id" :thread-id="activeThread?.course_id===selected.id?activeThread.id:null" @saved="loadAgent" @chat="(starter:string)=>{agentDraft=starter;switchTab('agent')}"/>
        <section v-if="tab==='agent'" class="agent-workspace" :class="{'has-preview':previewFile, 'preview-expanded':previewExpanded, 'threads-open':threadsOpen}">
          <div class="agent-chat">
            <div v-if="!activeThread" class="empty"><MessageSquare :size="34"/><h2>开始课程 Agent 对话</h2><button class="primary" @click="newAgentThread">新建对话</button></div>
            <template v-else>
              <div class="agent-chat-head"><div><h2>{{ activeThread.title }}</h2><p>{{ selected.name }} · 课程助手</p></div><div class="agent-actions"><button class="secondary" @click="switchTab('studio')"><Wrench :size="16"/>技能与工具</button><button class="secondary" @click="createAgentArtifact('pdf')"><FileText :size="16"/> PDF</button><button class="secondary" @click="createAgentArtifact('docx')"><FileText :size="16"/> Word</button></div></div>
              <div ref="messagesEl" class="agent-messages">
                <div v-if="!agentMessages.length && !agentStreaming" class="agent-welcome"><div class="agent-role">AI</div><h2>有什么可以帮你？</h2><p>可以基于课程资料提问，也可以让我生成文档。</p><div class="starter-chips"><button v-for="text in starters" :key="text" @click="agentDraft=text">{{ text }}</button></div></div>
                <article v-for="item in agentMessages.filter(item=>item.role!=='tool')" :key="item.id" class="agent-message" :class="item.role">
                  <div class="agent-role">{{ item.role==='user'?'你':item.role==='assistant'?'AI':'工具' }}</div>
                  <div class="agent-content">
                    <AgentResponse v-if="item.role==='assistant'" :message="item" @open="previewFile=$event"/>
                    <div v-else-if="item.role==='tool'" class="tool-result"><Wrench :size="14"/> {{ item.metadata.name }} · 工具返回（执行状态见确认记录）</div>
                    <div v-else class="message-source">{{ item.content }}</div>
                    <div v-if="item.attachments?.length" class="message-attachments"><span v-for="attachment in item.attachments" :key="attachment.id"><Paperclip :size="13"/> {{ attachment.name }}</span></div>

                    <div v-if="item.citations?.length" class="citations"><div v-for="(citation,index) in item.citations" :key="citation.chunk_id" class="citation"><strong>[{{ index+1 }}] {{ citation.title }} · 第 {{ citation.chunk_index + 1 }} 片</strong><span>{{ citation.excerpt.slice(0, 180) }}{{ citation.excerpt.length > 180 ? '…' : '' }}</span><div class="citation-actions"><button @click="openCitation(citation)"><Eye :size="13"/> 预览资料</button><button @click="downloadCitation(citation)"><Download :size="13"/> 下载原文件</button></div></div></div>
                  </div>
                </article>
                <article v-if="agentBusy&&!agentStreaming" class="agent-message assistant"><div class="agent-content agent-waiting" role="status"><span class="activity-dot"></span>正在思考并准备回复…</div></article><article v-if="agentStreaming" class="agent-message assistant"><div class="agent-role">AI</div><div class="agent-content streaming markdown-body" v-html="renderMarkdown(agentStreaming)"></div></article>
              </div>
              <ToolConfirmations :thread-id="activeThread.id" :refresh-key="agentBusy" :disabled="agentBusy" @done="loadAgent"/>
              <div class="agent-composer">
                <div class="composer-box">
                  <div v-if="agentFiles.length" class="pending-files"><span v-for="(file,index) in agentFiles" :key="`${file.name}-${index}`"><Paperclip :size="13"/> {{ file.name }} <small>{{ size(file.size) }}</small><button title="移除附件" :aria-label="`移除 ${file.name}`" @click="removeAgentFile(index)"><X :size="13"/></button></span></div>
                  <textarea v-model="agentDraft" rows="1" placeholder="输入消息…" @keydown.enter.exact="onComposerEnter"></textarea>
                  <div class="composer-bar">
                    <div class="agent-options"><label class="check"><input v-model="agentUseMaterials" type="checkbox"> 参考课程资料</label><label class="attach-button" title="添加附件"><Paperclip :size="16"/><input type="file" multiple accept=".txt,.md,.pdf,.docx,image/*" @change="agentFileFrom">添加附件</label></div>
                    <div class="composer-actions"><button v-if="agentBusy" class="secondary" @click="stopAgent"><Square :size="15"/> 停止</button><button class="primary send-button" :disabled="agentBusy || !agentDraft.trim()" @click="sendAgent"><Send :size="16"/> {{ agentBusy ? '生成中…' : '发送' }}</button></div>
                  </div>
                </div>
                <p class="composer-hint">Enter 发送 · Shift + Enter 换行</p>
              </div>
            </template>
          </div>
          <HtmlPreview v-if="previewFile" :file="previewFile" @close="closePreview" @expand="previewExpanded=$event"/>
        </section>
        <section v-if="tab==='materials'"><div class="section-head"><div><h2>课程资料</h2><p>预览或下载课程文件；知识索引由后台执行</p><p v-if="materialRefreshError" role="alert">{{materialRefreshError}} <button @click="refreshMaterials">重试刷新</button></p></div><button v-if="isTeacher" class="primary" @click="panel='material'"><Upload :size="17"/> 上传资料</button></div><div v-if="materials.length" class="homework-materials"><article v-for="m in materials" :key="m.id" class="pane"><h3 v-if="m.title!==m.attachment.name">{{m.title}}</h3><FileCard :file="m.attachment" @preview="businessPreview=$event"/><p class="hint">{{fmt(m.created_at)}}</p><MaterialIndexStatus :material-id="m.id" :status="m.index_status" :error="m.index_error" :task="m.index_task" :is-teacher="isTeacher" @changed="refreshMaterials"/></article></div><div v-else class="empty"><FolderOpen :size="32"/><h2>暂无课程资料</h2></div></section>
        <section v-if="tab==='assignments'">
          <div class="section-head"><div><h2>作业</h2><p>查看要求与提交记录</p></div><button v-if="isTeacher" class="primary" @click="panel='assignment'"><Plus :size="17"/> 发布作业</button></div>
          <WorkspaceSkeleton v-if="assignmentLoading" label="正在读取作业…"/><RequestErrorPanel v-else-if="assignmentLoadError" :message="assignmentLoadError" detail="作业尚未读取成功，不能据此判断是否有作业。请重试或返回列表。" @retry="run(applyRoute)" @back="switchTab('assignments')"/><AssignmentWorkspace v-else-if="currentAssignment" :key="currentAssignment.id" :assignment-id="currentAssignment.id" :initial-student-id="Number(route.query.student)||undefined" :is-teacher="isTeacher" @back="backToAssignments" @preview="businessPreview=$event"/>
          <div v-else-if="assignments.length" class="list"><button v-for="a in assignments" :key="a.id" class="list-row assignment-row" @click="openAssignment(a)"><div class="file-icon"><ClipboardList :size="19"/></div><div class="row-copy"><strong>{{ a.title }}</strong><small>截止 {{ fmt(a.due_at) }} · {{ a.allow_late?'允许迟交':'截止后关闭' }}</small></div><span v-if="!isTeacher" class="homework-status" :class="a.submission_status">{{ statusLabels[a.submission_status || 'unsubmitted'] }}</span><span class="due-badge" :class="dueState(a).cls">{{ dueState(a).text }}</span><span class="row-arrow">›</span></button></div>
          <div v-else class="empty"><ClipboardList :size="32"/><h2>暂无作业</h2></div>
        </section>
        <section v-if="tab==='members'"><div class="section-head"><div><h2>课程成员</h2><p>{{ members.length }} 位成员</p></div></div><div class="list"><div v-for="m in members" :key="m.id" class="list-row"><div class="avatar small">{{ m.name.slice(0,1) }}</div><div class="row-copy"><strong>{{ m.name }}</strong><small v-if="m.email">{{ m.email }}</small></div><span class="role" :class="m.role">{{ m.role==='teacher'?'教师':'学生' }}</span></div></div></section>
      </template>
      <ToastStack :items="toasts" @dismiss="dismiss"/>
    </main>
    <FilePreview v-if="businessPreview" :file="businessPreview" @close="businessPreview=null"/>
    <div v-if="panel!=='none'" class="modal-backdrop" @click.self="panel='none'"><div class="modal"><div class="modal-head"><h2>{{ {create:'创建课程',join:'加入课程',invite:'教师邀请码',material:'上传资料',assignment:'发布作业'}[panel] }}</h2><button aria-label="关闭" @click="panel='none'">×</button></div><form v-if="panel==='create'" @submit.prevent="createCourse"><label>课程名称<input v-model="courseName" required maxlength="120" autofocus></label><label>课程图标（可选）<input type="file" accept="image/png,image/jpeg,image/webp" @change="fileFrom($event,'icon')"></label><button class="primary full" :disabled="busy">创建课程</button></form><form v-if="panel==='join'" @submit.prevent="joinCourse"><label>课程码<input v-model="joinCode" required maxlength="12" placeholder="输入教师提供的课程码"></label><button class="primary full" :disabled="busy">加入课程</button></form><form v-if="panel==='invite'" @submit.prevent="redeem"><label>教师邀请码<input v-model="invite" required></label><button class="primary full" :disabled="busy">兑换</button></form><form v-if="panel==='material'" @submit.prevent="uploadMaterial"><label>资料标题<input v-model="materialTitle" placeholder="留空则使用文件名"></label><label>文件<input type="file" required @change="fileFrom($event,'material')"></label><button class="primary full" :disabled="busy">上传资料</button></form><form v-if="panel==='assignment'" @submit.prevent="publish"><label>作业标题<input v-model="assignmentTitle" required maxlength="200"></label><label>作业说明<textarea v-model="description" rows="3"></textarea></label><label>截止时间<input v-model="dueAt" type="datetime-local" required></label><label>允许格式（逗号分隔，留空为全部常见格式）<input v-model="extensions" placeholder="doc,docx,pdf,zip"></label><label>单文件上限（MB）<input v-model.number="maxMb" type="number" min="1" max="50"></label><label>满分<input v-model.number="maxScore" type="number" min="0.01" max="99999.99" step="0.01" required></label><label>题目附件（可选）<input type="file" @change="fileFrom($event,'assignment')"></label><label class="check"><input v-model="allowLate" type="checkbox"> 允许迟交</label><button class="primary full" :disabled="busy">发布作业</button></form></div></div>
  </div>
</template>
