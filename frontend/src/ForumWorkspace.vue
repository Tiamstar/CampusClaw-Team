<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { api, openProtected } from './api'
import { renderMarkdown } from './htmlArtifacts'
import './forum.css'

type Point={id:number;name:string}
type Post={id:number;title:string;body:string;anonymous:boolean;author:{id?:number;name:string};points:Point[];mentions:Point[];pinned:boolean;featured:boolean;reply_count:number;created_at:string;is_mine?:boolean;resolved_reply_id?:number|null;resolved_at?:string|null;revision?:number;teacher_answered?:boolean}
type Citation={chunk_id:number;material_id:number;title:string;label:string;excerpt:string;chunk_index:number;preview_url:string;content_hash:string;current?:boolean}
type Draft={id:number;status:string;body:string;error:string;citations:Citation[];model:string;skill_version:string;created_at:string}
type Reply={id:number;body:string;author:Point;teacher_answer:boolean;draft_id:number|null;citations:Citation[];model:string;skill_version:string;created_at:string}
type Todo={id:number;post_id:number;title:string;reason:string;closed_at:string|null}
type Page<T>={items:T[];next_page:number|null}
type Config={draft_enabled:boolean;wait_hours:number;timezone:string;revision:number}
const props=defineProps<{courseId:number;isTeacher:boolean;ownerId?:number;initialPostId?:number}>()
const emit=defineEmits<{postChange:[id:number|undefined]}>()
const base=`courses/${props.courseId}/forum/`
const busy=ref(false),loading=ref(true),error=ref(''),notice=ref('')
const posts=ref<Post[]>([]),post=ref<Post|null>(null),replies=ref<Reply[]>([]),drafts=ref<Draft[]>([])
const points=ref<Point[]>([]),teachers=ref<Point[]>([]),todos=ref<Todo[]>([]),todoNext=ref<number|null>(null)
const next=ref<number|null>(null),replyNext=ref<number|null>(null),draftNext=ref<number|null>(null)
const filterStatus=ref(''),filterAuthor=ref('')
const query=ref(''),filterPoint=ref(''),creating=ref(false),title=ref(''),body=ref(''),anonymous=ref(false)
const pointIds=ref<number[]>([]),mentionIds=ref<number[]>([]),reply=ref(''),newPoint=ref('')
const candidates=ref<Point[]>([]),similarState=ref(''),draftEdits=ref<Record<number,string>>({}),confirmed=ref<Record<number,boolean>>({})
const config=ref<Config>({draft_enabled:true,wait_hours:24,timezone:'Asia/Shanghai',revision:0})
const statuses:Record<string,string>={running:'生成中',awaiting_review:'待教师审核',no_evidence:'资料未覆盖',failed:'生成失败',published:'已发布'}
const storageNotice=ref('')
const questionKey=props.ownerId?`campusclaw.forum.${props.ownerId}.${props.courseId}.question`:null
const editKey=props.ownerId&&props.isTeacher?`campusclaw.forum.${props.ownerId}.${props.courseId}.edits`:null
const storedEdits:Record<string,{original:string;text:string}>={}
try{
 if(questionKey){const raw=JSON.parse(sessionStorage.getItem(questionKey)||'null');if(raw&&typeof raw.title==='string'&&typeof raw.body==='string'){title.value=raw.title.slice(0,200);body.value=raw.body.slice(0,20000);anonymous.value=raw.anonymous===true;pointIds.value=Array.isArray(raw.pointIds)?raw.pointIds.filter(Number.isSafeInteger).slice(0,20):[];mentionIds.value=Array.isArray(raw.mentionIds)?raw.mentionIds.filter(Number.isSafeInteger).slice(0,20):[];storageNotice.value='已恢复本标签页保存的未发布问题，点击发布问题继续编辑'}}
 if(editKey){const raw=JSON.parse(sessionStorage.getItem(editKey)||'{}');for(const [id,value] of Object.entries(raw).slice(-30)){const v=value as any;if(/^\d+$/.test(id)&&typeof v.original==='string'&&typeof v.text==='string'&&v.text.length<=20000)storedEdits[id]=v}}
}catch{storageNotice.value='浏览器草稿读取失败，请勿依赖刷新恢复'}
function saveQuestion(){if(!questionKey)return;try{if(!title.value.trim()&&!body.value.trim())sessionStorage.removeItem(questionKey);else sessionStorage.setItem(questionKey,JSON.stringify({title:title.value,body:body.value,anonymous:anonymous.value,pointIds:pointIds.value,mentionIds:mentionIds.value}));}catch{storageNotice.value='浏览器无法保存问题草稿，请勿刷新'}}
watch([title,body,anonymous,pointIds,mentionIds],saveQuestion,{deep:true})
function saveDraftEdits(){if(!editKey)return;try{for(const d of drafts.value){if(d.status==='awaiting_review'&&typeof draftEdits.value[d.id]==='string'&&draftEdits.value[d.id]!==d.body)storedEdits[d.id]={original:d.body,text:draftEdits.value[d.id]};else delete storedEdits[d.id]}const entries=Object.entries(storedEdits).slice(-30);sessionStorage.setItem(editKey,JSON.stringify(Object.fromEntries(entries)))}catch{storageNotice.value='浏览器无法保存回复编辑，请复制内容后再刷新'}}
watch(draftEdits,saveDraftEdits,{deep:true})
function discardQuestion(){if(!confirm('清空未发布问题？已有帖子和回复不会删除。'))return;title.value='';body.value='';pointIds.value=[];mentionIds.value=[];anonymous.value=false;creating.value=false;storageNotice.value=''}
async function run(action:()=>Promise<void>){busy.value=true;error.value='';notice.value='';try{await action()}catch(e){error.value=e instanceof Error?e.message:'操作失败，请重试'}finally{busy.value=false}}
async function list(page=1){const data=await api<Page<Post>>(base+`posts/?page=${page}&q=${encodeURIComponent(query.value)}&point=${filterPoint.value}&status=${filterStatus.value}&author_role=${filterAuthor.value}`);posts.value=page===1?data.items:[...posts.value,...data.items];next.value=data.next_page}
async function loadTodos(page=1){if(!props.isTeacher)return;const data=await api<Page<Todo>>(base+`todos/?page=${page}`);todos.value=page===1?data.items:[...todos.value,...data.items];todoNext.value=data.next_page}
async function loadReplies(page=1){if(!post.value)return;const id=post.value.id,generation=postGeneration;const data=await api<Page<Reply>>(`forum/posts/${id}/replies/?page=${page}`);if(post.value?.id!==id||generation!==postGeneration)return;replies.value=page===1?data.items:[...replies.value,...data.items];replyNext.value=data.next_page}
async function loadDrafts(page=1){if(!post.value||!props.isTeacher)return;const id=post.value.id,generation=postGeneration;const data=await api<Page<Draft>>(`forum/posts/${id}/drafts/?page=${page}`);if(post.value?.id!==id||generation!==postGeneration)return;drafts.value=page===1?data.items:[...drafts.value,...data.items];draftNext.value=data.next_page;for(const d of data.items)if(!(d.id in draftEdits.value))draftEdits.value[d.id]=storedEdits[d.id]?.original===d.body?storedEdits[d.id].text:d.body}
let postGeneration=0
async function open(id:number,sync=true){const generation=++postGeneration;busy.value=true;error.value='';post.value=null;replies.value=[];drafts.value=[];creating.value=false
 try{const result=await api<Post>(`forum/posts/${id}/`);if(generation!==postGeneration)return;post.value=result;reply.value='';if(sync)emit('postChange',id);await loadReplies();if(generation!==postGeneration)return;await loadDrafts()}
 catch(e){if(generation===postGeneration)error.value=e instanceof Error?e.message:'讨论读取失败'}
 finally{if(generation===postGeneration)busy.value=false}
}
function backToList(){postGeneration++;post.value=null;returnToQuestion.value=false;emit('postChange',undefined);void run(()=>list())}
watch(()=>props.initialPostId,id=>{if(id!==undefined&&id===post.value?.id)return;if(id)void open(id,false);else{postGeneration++;post.value=null;replies.value=[];drafts.value=[];busy.value=false}})

const similarBusy=ref(false),similarConfirmed=ref(false),checkedTitle=ref(''),returnToQuestion=ref(false)
let similarTimer:ReturnType<typeof setTimeout>|undefined,similarGeneration=0
async function checkSimilar(){
 if(similarTimer)clearTimeout(similarTimer)
 const text=title.value.trim(),generation=++similarGeneration
 similarConfirmed.value=false
 if(text.length<2){candidates.value=[];similarState.value='';checkedTitle.value='';return}
 similarBusy.value=true;similarState.value='searching'
 try{const data=await api<{status:string;items:{id:number;title:string}[]}>(base+`similar/?q=${encodeURIComponent(text)}`);if(generation!==similarGeneration||text!==title.value.trim())return;candidates.value=data.items.slice(0,5).map(p=>({id:p.id,name:p.title}));similarState.value=data.status;checkedTitle.value=text}
 catch{if(generation===similarGeneration){candidates.value=[];similarState.value='unavailable';checkedTitle.value=text}}
 finally{if(generation===similarGeneration)similarBusy.value=false}
}
watch(title,()=>{++similarGeneration;if(similarTimer)clearTimeout(similarTimer);similarBusy.value=false;similarConfirmed.value=false;checkedTitle.value='';candidates.value=[];similarState.value='';if(creating.value&&title.value.trim().length>=2)similarTimer=setTimeout(()=>void checkSimilar(),500)})
onUnmounted(()=>{postGeneration++;++similarGeneration;if(similarTimer)clearTimeout(similarTimer)})
function beginQuestion(){if(props.initialPostId)emit('postChange',undefined);creating.value=true;post.value=null;returnToQuestion.value=false;if(title.value.trim().length>=2)void checkSimilar()}
async function inspectCandidate(id:number){returnToQuestion.value=true;await open(id)}
function resumeQuestion(){if(props.initialPostId)emit('postChange',undefined);post.value=null;creating.value=true;returnToQuestion.value=false}
async function publish(){if(title.value.trim().length>=2&&checkedTitle.value!==title.value.trim()){await checkSimilar();if(checkedTitle.value!==title.value.trim())return}if(candidates.value.length&&!similarConfirmed.value){error.value='请先查看相似讨论，并确认问题仍未解决';return}await run(async()=>{const item=await api<Post>(base+'posts/','POST',{title:title.value,body:body.value,anonymous:anonymous.value,point_ids:pointIds.value,mention_ids:mentionIds.value});title.value='';body.value='';pointIds.value=[];mentionIds.value=[];anonymous.value=false;creating.value=false;post.value=item;emit('postChange',item.id);await list();await loadReplies();await loadDrafts();await loadTodos();storageNotice.value='';notice.value='问题已发布'})}
async function sendReply(){await run(async()=>{await api(`forum/posts/${post.value!.id}/replies/`,'POST',{body:reply.value});reply.value='';await loadReplies();await loadTodos();notice.value='回复已发布'})}
async function moderate(key:'pinned'|'featured'){await run(async()=>{post.value=await api<Post>(`forum/posts/${post.value!.id}/`,'PATCH',{[key]:!post.value![key]});await list()})}
async function resolve(replyId:number|null){await run(async()=>{post.value=await api<Post>(`forum/posts/${post.value!.id}/`,'PATCH',{resolved_reply_id:replyId,expected_revision:post.value!.revision});await list();notice.value=replyId?'已标记解决，可随时重新打开讨论':'已重新打开讨论'})}
async function generate(){await run(async()=>{const data=await api<Draft>(`forum/posts/${post.value!.id}/drafts/`,'POST',{});await loadDrafts();notice.value=data.status==='awaiting_review'?'草稿已生成，尚未公开':'已记录生成结果，尚未公开'})}
async function publishDraft(d:Draft){await run(async()=>{await api(`forum/drafts/${d.id}/publish/`,'POST',{body:draftEdits.value[d.id],confirm:confirmed.value[d.id]===true});delete storedEdits[d.id];delete draftEdits.value[d.id];saveDraftEdits();await loadDrafts();await loadReplies();await loadTodos();notice.value='教师确认的答疑已公开'})}
async function saveConfig(){await run(async()=>{config.value=await api<Config>(base+'settings/','PUT',{...config.value,expected_revision:config.value.revision});notice.value='论坛设置已保存'})}
async function addPoint(){await run(async()=>{await api(base+'points/','POST',{name:newPoint.value});newPoint.value='';points.value=await api<Point[]>(base+'points/')})}
async function source(c:Citation){await run(async()=>{await openProtected(c.preview_url)})}
onMounted(async()=>{await run(async()=>{await list();config.value=await api<Config>(base+'settings/');points.value=await api<Point[]>(base+'points/');const people=await api<{id:number;name:string;role:string}[]>(`courses/${props.courseId}/members/`);teachers.value=people.filter(p=>p.role==='teacher');await loadTodos();if(props.initialPostId)await open(props.initialPostId,false)});loading.value=false})
</script>

<template>
  <section class="forum-workspace" aria-label="课程答疑论坛">
    <div class="section-head"><div><h2>答疑论坛</h2><p>交流问题，查阅资料，保留教师确认的答复。</p></div><button class="primary" :disabled="busy" @click="beginQuestion">发布问题</button></div>
    <p v-if="storageNotice" role="status">{{storageNotice}}</p><p v-if="ownerId" class="muted">未发布问题和回复编辑仅保存在当前标签页，退出登录清除；公开前仍须重新核对。</p><p v-if="error" class="error" role="alert">{{error}}</p><div v-if="initialPostId&&!post&&!busy&&!loading"><button class="secondary" @click="open(initialPostId,false)">重新读取讨论</button><button class="secondary" @click="backToList">返回讨论列表</button></div><p v-if="notice" role="status">{{notice}}</p><p v-if="loading||busy&&!post" role="status">正在加载讨论…</p>
    <details v-if="isTeacher" class="forum-settings"><summary>教师设置与待办</summary>
      <form class="forum-config" @submit.prevent="saveConfig"><label><input v-model="config.draft_enabled" type="checkbox">启用答疑草稿技能</label><label>未答复等待时间（小时）<input v-model.number="config.wait_hours" type="number" min="1" max="720" required></label><label>显示时区<input v-model="config.timezone" required></label><button class="secondary" :disabled="busy">保存设置</button></form>
      <form class="forum-config" @submit.prevent="addPoint"><label>新增课程知识点<input v-model="newPoint" required maxlength="100"></label><button class="secondary" :disabled="busy">添加知识点</button></form>
      <h3>我的答疑待办</h3><button class="secondary" :disabled="busy" @click="run(()=>loadTodos())">刷新待办</button><p v-if="!todos.length">暂无待办。</p>
      <div v-for="t in todos" :key="t.id" class="forum-todo"><button @click="open(t.post_id)">{{t.title}}</button><span>{{t.closed_at?'已关闭':'待答复'}} · {{t.reason==='mention'?'被提及':'到期未答复'}}</span></div><button v-if="todoNext" class="secondary" :disabled="busy" @click="run(()=>loadTodos(todoNext!))">更多待办</button>
    </details>
    <form v-if="creating" class="forum-card forum-form" @submit.prevent="publish"><h3>发布新问题</h3><label>标题<input v-model="title" required maxlength="200"></label><button type="button" class="secondary" :disabled="busy||similarBusy||title.trim().length<2" @click="checkSimilar">查找相似问题</button>
      <div v-if="similarState"><p>{{similarState==='searching'?'正在查找相似讨论…':similarState==='unavailable'?'相似帖检索暂不可用，仍可发布':candidates.length?'这些讨论可能有帮助，也可以继续提问':'未找到相似问题，可以继续发布'}}</p><button v-for="c in candidates" :key="c.id" type="button" class="forum-link" @click="inspectCandidate(c.id)">{{c.name}}</button></div>
      <label v-if="candidates.length"><input v-model="similarConfirmed" type="checkbox">我已看过上述讨论，问题仍未解决</label><label>问题内容（支持 Markdown 和公式）<textarea v-model="body" rows="7" required maxlength="20000"></textarea></label><label><input v-model="anonymous" type="checkbox">对同学匿名（教师仍可识别作者）</label>
      <fieldset v-if="points.length"><legend>关联知识点</legend><label v-for="p in points" :key="p.id"><input v-model="pointIds" type="checkbox" :value="p.id">{{p.name}}</label></fieldset>
      <fieldset><legend>@ 任课教师</legend><label v-for="t in teachers" :key="t.id"><input v-model="mentionIds" type="checkbox" :value="t.id">{{t.name}}</label></fieldset>
      <div class="forum-actions"><button class="primary" :disabled="busy||similarBusy||(candidates.length>0&&!similarConfirmed)">发布问题</button><button type="button" class="secondary" @click="creating=false;storageNotice='问题草稿已保留，可继续编辑'">收起并保留草稿</button><button type="button" class="secondary" @click="discardQuestion">清空草稿</button></div>
    </form>
    <template v-else-if="post">
      <button v-if="returnToQuestion" class="secondary" @click="resumeQuestion">返回继续编辑我的问题</button><button class="back" @click="backToList">← 返回讨论列表</button>
      <article class="forum-card"><h3>{{post.title}}</h3><p class="muted">{{post.author.name}} · {{new Date(post.created_at).toLocaleString('zh-CN',{timeZone:config.timezone})}} <span v-if="post.anonymous&&isTeacher">（对同学匿名）</span></p><span v-if="post.resolved_reply_id" class="role">已解决</span><span v-else class="role">待解决</span><span v-if="post.teacher_answered" class="role">教师已答复</span><button v-if="post.resolved_reply_id&&(isTeacher||post.is_mine)" class="secondary" :disabled="busy" @click="resolve(null)">重新打开讨论</button><span v-if="post.pinned" class="role">置顶</span><span v-if="post.featured" class="role">精华</span><span v-for="p in post.points" :key="p.id" class="role">{{p.name}}</span><p v-if="post.mentions.length">提及教师：{{post.mentions.map(t=>t.name).join('、')}}</p><div class="markdown-body" v-html="renderMarkdown(post.body)"></div><div v-if="isTeacher" class="forum-actions"><button class="secondary" :disabled="busy" @click="moderate('pinned')">{{post.pinned?'取消置顶':'置顶'}}</button><button class="secondary" :disabled="busy" @click="moderate('featured')">{{post.featured?'取消精华':'设为精华'}}</button></div></article>
      <section v-if="isTeacher" class="forum-drafts"><h3>教师专用答疑草稿</h3><p>草稿不会自动公开。请逐项核对资料、编辑回答后确认发布。</p><button class="secondary" :disabled="busy||!config.draft_enabled" @click="generate">{{busy?'处理中…':'根据课程资料生成草稿'}}</button><button class="secondary" :disabled="busy" @click="run(()=>loadDrafts())">刷新草稿</button><p v-if="!config.draft_enabled">该课程已停用答疑草稿技能。</p><p v-if="!drafts.length">暂无草稿。</p>
        <article v-for="d in drafts" :key="d.id" class="forum-card"><strong>{{statuses[d.status]||d.status}}</strong><small> · {{d.skill_version}} {{d.model}}</small><p v-if="d.error" role="alert">{{d.error}}</p><div class="markdown-body" v-html="renderMarkdown(d.body)"></div>
          <details v-for="c in d.citations" :key="c.chunk_id"><summary>{{c.label}} · {{c.title}} · 片段 {{c.chunk_index+1}}</summary><p v-if="c.current===false" class="error">资料已变化或失效；以下为生成时的引用快照。</p><p>{{c.excerpt}}</p><button class="secondary" :disabled="busy||c.current===false" @click="source(c)">回查资料</button></details>
          <template v-if="d.status==='awaiting_review'"><label>编辑待发布回复<textarea v-model="draftEdits[d.id]" rows="6" maxlength="20000"></textarea></label><label><input v-model="confirmed[d.id]" type="checkbox">我已核对回答及引用，确认公开</label><button class="primary" :disabled="busy||!confirmed[d.id]||!draftEdits[d.id]?.trim()" @click="publishDraft(d)">确认并公开回复</button></template>
        </article><button v-if="draftNext" class="secondary" :disabled="busy" @click="run(()=>loadDrafts(draftNext!))">更多草稿</button>
      </section>
      <h3>公开回复</h3><p v-if="!replies.length">还没有回复，欢迎分享思路。</p>
      <article v-for="r in replies" :key="r.id" class="forum-card"><p v-if="post.resolved_reply_id===r.id" class="role">已采纳为解决方案</p><button v-else-if="isTeacher||post.is_mine" class="secondary" :disabled="busy" @click="resolve(r.id)">此回复解决了问题</button><p><strong>{{r.author.name}}</strong> <span v-if="r.teacher_answer" class="role">教师答复</span> <span v-if="r.draft_id" class="role">AI 草稿 · 教师已确认</span></p><div class="markdown-body" v-html="renderMarkdown(r.body)"></div><details v-for="c in r.citations" :key="c.chunk_id"><summary>{{c.label}} · {{c.title}}</summary><p v-if="c.current===false" class="error">资料已变化或失效；以下为生成时的引用快照。</p><p>{{c.excerpt}}</p><button class="secondary" :disabled="busy||c.current===false" @click="source(c)">回查资料</button></details><small v-if="r.draft_id">{{r.skill_version}} · {{r.model}}</small></article><button v-if="replyNext" class="secondary" :disabled="busy" @click="run(()=>loadReplies(replyNext!))">更多回复</button>
      <form class="forum-card forum-form" @submit.prevent="sendReply"><label>回复（支持 Markdown 和公式）<textarea v-model="reply" rows="4" required maxlength="20000"></textarea></label><button class="primary" :disabled="busy||!reply.trim()">发布回复</button></form>
    </template>
    <template v-else-if="!initialPostId"><form class="forum-search" @submit.prevent="run(()=>list())"><input v-model="query" aria-label="搜索讨论" placeholder="搜索标题、正文和公开回复" maxlength="200"><select v-model="filterStatus" aria-label="筛选讨论状态"><option value="">全部状态</option><option value="open">待解决</option><option value="resolved">已解决</option><option value="answered">教师已答复</option></select><select v-model="filterAuthor" aria-label="筛选发布者"><option value="">全部发布者</option><option value="teacher">教师</option><option value="student">同学</option></select><select v-model="filterPoint" aria-label="筛选知识点"><option value="">全部知识点</option><option v-for="p in points" :key="p.id" :value="p.id">{{p.name}}</option></select><button class="secondary" :disabled="busy">搜索</button></form><p v-if="!loading&&!posts.length">还没有匹配的讨论，可以发布第一个问题。</p><button v-for="p in posts" :key="p.id" class="forum-card forum-post" @click="open(p.id)"><div><span class="role">{{p.resolved_reply_id?'已解决':'待解决'}}</span><span v-if="p.teacher_answered" class="role">教师已答复</span><span v-if="p.pinned" class="role">置顶</span><span v-if="p.featured" class="role">精华</span><strong>{{p.title}}</strong></div><small>{{p.author.name}} · {{p.reply_count}} 条回复</small><span v-for="point in p.points" :key="point.id" class="muted">{{point.name}} </span></button><button v-if="next" class="secondary" :disabled="busy" @click="run(()=>list(next!))">更多讨论</button></template>
  </section>
</template>
