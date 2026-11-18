<script setup lang="ts">
import {computed} from 'vue'
const props=defineProps<{message:string;status?:number;busy?:boolean;detail?:string}>()
defineEmits<{retry:[];back:[]}>()
const blocked=computed(()=>props.status===403||props.status===404)
const title=computed(()=>props.status===403?'当前没有访问权限':props.status===404?'内容已不可访问':props.status===409?'内容已更新，请重新核对':'暂时无法完成请求')
</script>
<template><section class="request-error-panel" role="alert"><h3>{{title}}</h3><p>{{message}}</p><p>{{detail||(blocked?'请返回列表重新选择；如需访问，请联系任课教师核对权限。':'未保存的当前输入仍保留。重试加载前请先确认是否需要保留修改。')}}</p><button v-if="!blocked" class="secondary" :disabled="busy" @click="$emit('retry')">重新加载</button><button class="secondary" :disabled="busy" @click="$emit('back')">返回列表</button></section></template>
<style scoped>.request-error-panel{border:1px solid #dca6a6;border-radius:12px;padding:1rem;margin:1rem 0;background:#fff7f7;color:#7f1d1d;overflow-wrap:anywhere}.request-error-panel h3{margin-top:0}.request-error-panel button{margin:.3rem .5rem .3rem 0}</style>
