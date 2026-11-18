<script setup lang="ts">
import {onMounted,onUnmounted,ref} from 'vue'
import {RouterLink} from 'vue-router'
import {Bell} from 'lucide-vue-next'
import {api} from './api'
const count=ref<number|null>(null),failed=ref(false)
let timer:ReturnType<typeof setInterval>|undefined,active=true,generation=0
async function refresh(){
 const current=++generation
 try{const result=await api<{unread_count:number}>('notifications/unread-count/');if(!Number.isInteger(result.unread_count)||result.unread_count<0)throw new Error();if(active&&current===generation){count.value=result.unread_count;failed.value=false}}
 catch{if(active&&current===generation)failed.value=true}
}
function visibleRefresh(){if(document.visibilityState==='visible')void refresh()}
onMounted(()=>{void refresh();timer=setInterval(visibleRefresh,60000);document.addEventListener('visibilitychange',visibleRefresh);window.addEventListener('campusclaw:notifications-read',refresh)})
onUnmounted(()=>{active=false;generation++;if(timer)clearInterval(timer);document.removeEventListener('visibilitychange',visibleRefresh);window.removeEventListener('campusclaw:notifications-read',refresh)})
</script>
<template><RouterLink :to="{name:'notifications'}" class="notification-indicator" :aria-label="failed?'通知（未读数量暂不可用）':count===null?'通知':`通知（${count}条未读）`" :title="failed?'未读数量刷新失败，打开通知中心重试':'成绩通知'"><Bell :size="19"/><span>通知</span><strong v-if="count!==null&&count>0">{{count>99?'99+':count}}</strong><span v-if="failed" aria-hidden="true">!</span></RouterLink></template>
<style scoped>.notification-indicator{display:inline-flex;align-items:center;gap:.3rem;color:var(--red);text-decoration:none;flex-shrink:0;padding:.4rem;border-radius:8px}.notification-indicator strong{font-size:.75rem;min-width:1.2rem;padding:.1rem .2rem;text-align:center;color:#fff;background:var(--red);border-radius:1rem}.notification-indicator:focus-visible{outline:2px solid currentColor}</style>
