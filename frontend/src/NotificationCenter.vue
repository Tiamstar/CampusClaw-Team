<script setup lang="ts">
import {onMounted,onUnmounted,ref} from 'vue'
import {RouterLink} from 'vue-router'
import {api,ApiError} from './api'
import RequestErrorPanel from './RequestErrorPanel.vue'
import WorkspaceSkeleton from './WorkspaceSkeleton.vue'
type Notice={id:number;course_id:number;course_name:string;title:string;kind:'assignment'|'quiz';number:number;assignment_id:number|null;attempt_id:number|null;created_at:string;read_at:string|null;availability:'available'|'updated';score:string|null;maximum:string|null}
const items=ref<Notice[]>([]),loading=ref(false),busy=ref(false),error=ref(''),status=ref<number>(),notice=ref(''),unread=ref<number|null>(null),next=ref<number|null>(null)
let generation=0,requestedPage=1
function announceRead(){window.dispatchEvent(new Event('campusclaw:notifications-read'))}
async function load(page=1){
 const current=++generation;requestedPage=page;loading.value=true;error.value='';status.value=undefined
 if(page===1){items.value=[];next.value=null;unread.value=null}
 try{const data=await api<{items:Notice[];next_page:number|null;unread_count:number}>(`notifications/?page=${page}`);if(current===generation){items.value=page===1?data.items:[...items.value,...data.items];next.value=data.next_page;unread.value=data.unread_count}}
 catch(e){if(current===generation){error.value=e instanceof Error?e.message:'通知加载失败';status.value=e instanceof ApiError?e.status:undefined}}
 finally{if(current===generation)loading.value=false}
}
async function markRead(id?:number){
 if(busy.value)return
 const current=generation;busy.value=true;notice.value=''
 try{await api(id?`notifications/${id}/read/`:'notifications/read-all/','POST',{});announceRead();if(current===generation){notice.value=id?'已标为已读':'已将当前有权访问的通知标为已读';await load()}}
 catch(e){if(current===generation)notice.value=e instanceof Error?e.message:'已读状态未保存，请重试'}
 finally{if(current===generation||loading.value===false)busy.value=false}
}
onMounted(()=>load())
onUnmounted(()=>generation++)
</script>
<template><section class="notification-center"><header><div><h1>通知中心</h1><p>成绩发布后在这里查看。通知保留在账号中，已读状态跨设备保存。</p></div><button class="secondary" :disabled="loading||busy" @click="load()">刷新通知</button></header><p>当前有权访问的未读通知：{{unread===null?'正在读取':unread}} 条</p><p>分数按当前公开状态显示。撤回、重新评分或补交后，旧通知会提示查看最新状态。更早发布的成绩仍可在原作业或测验中查看。</p><button class="secondary" :disabled="loading||busy||!unread" @click="markRead()">全部标为已读</button><p v-if="notice" role="status">{{notice}}</p><RequestErrorPanel v-if="error" :message="error" :status="status" detail="通知未能更新，未成功保存的已读状态不会显示为成功。" @retry="load(requestedPage)" @back="$router.push({name:'courses'})"/><WorkspaceSkeleton v-if="loading" kind="list"/><p v-if="!loading&&!error&&!items.length" class="notification-empty">暂无成绩通知。教师今后发布作业或测验成绩后，会在这里收到记录。</p><ol v-if="!error"><li v-for="item in items" :key="item.id" :class="{unread:!item.read_at}"><div class="notification-meta"><span>{{item.course_name}}</span><strong v-if="!item.read_at">未读</strong><span v-else>已读</span></div><h2>{{item.title}}</h2><p v-if="item.availability==='available'">第 {{item.number}} {{item.kind==='quiz'?'次测验答卷':'版作业提交'}}成绩已发布：<strong>{{item.score}} / {{item.maximum}}</strong> 分</p><p v-else>成绩状态已更新；可能已撤回、重新评分或出现新提交，请打开详情核对。</p><small>记录于 {{new Date(item.created_at).toLocaleString('zh-CN')}}</small><div class="notification-actions"><RouterLink :to="item.kind==='quiz'?{name:'attempt',params:{courseId:item.course_id,attemptId:item.attempt_id}}:{name:'assignment',params:{courseId:item.course_id,assignmentId:item.assignment_id}}">查看批改详情 →</RouterLink><button v-if="!item.read_at" class="secondary" :disabled="busy||loading" @click="markRead(item.id)">标为已读</button></div></li></ol><button v-if="next&&!error" class="secondary" :disabled="loading||busy" @click="load(next!)">加载更多通知</button></section></template>
<style scoped>.notification-center{max-width:960px;margin:auto;min-width:0;overflow-wrap:anywhere}.notification-center header{display:flex;justify-content:space-between;align-items:flex-start;gap:1rem}.notification-center header h1{margin-top:0}.notification-center p,.notification-center small{color:var(--ink-2);line-height:1.65}.notification-center ol{list-style:none;padding:0}.notification-center li{border:1px solid var(--line);border-radius:12px;margin:1rem 0;padding:1.1rem;background:var(--surface)}.notification-center li.unread{border-left:4px solid var(--red)}.notification-center h2{font-size:1.1rem;margin:.65rem 0}.notification-meta{display:flex;justify-content:space-between;gap:1rem;color:var(--muted);font-size:.85rem}.notification-meta strong{color:var(--red)}.notification-actions{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:.8rem;margin-top:1rem}.notification-center a{color:var(--red)}.notification-empty{padding:2rem 0}@media(max-width:600px){.notification-center header{display:block}.notification-center header button{margin-bottom:.7rem}.notification-meta{flex-wrap:wrap}.notification-center li{padding:.85rem}}</style>
