<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {House,MessageSquare,FolderOpen,ClipboardList,MessagesSquare,GraduationCap,Settings} from 'lucide-vue-next'
import type {CourseModule as Tab} from './router'
const props=defineProps<{active:Tab;isTeacher:boolean}>()
const emit=defineEmits<{select:[value:Tab]}>()
const expanded=ref('')
const primary=[{id:'overview' as Tab,label:'课程首页',icon:House},{id:'agent' as Tab,label:'AI 助手',icon:MessageSquare},{id:'materials' as Tab,label:'课程资料',icon:FolderOpen},{id:'assignments' as Tab,label:'作业',icon:ClipboardList},{id:'quiz' as Tab,label:'测验',icon:GraduationCap},{id:'forum' as Tab,label:'答疑论坛',icon:MessagesSquare}]
const groups=computed(()=>[
 {id:'learning',label:'学习中心',icon:GraduationCap,items:[{id:'gradebook' as Tab,label:'成绩册'},{id:'learning' as Tab,label:'学情分析'},{id:'graph' as Tab,label:'知识图谱'},{id:'review' as Tab,label:'复习路径'},{id:'diagnostic' as Tab,label:'诊断报告'},...(!props.isTeacher?[{id:'wrongs' as Tab,label:'我的作业错题'}]:[])]},
 {id:'management',label:props.isTeacher?'课程管理':'课程设置',icon:Settings,items:[...(props.isTeacher?[{id:'bank' as Tab,label:'题库'},{id:'exams' as Tab,label:'试卷识别'}]:[]),{id:'studio' as Tab,label:'助手设置'},{id:'teaching' as Tab,label:'教学技能'},{id:'members' as Tab,label:'成员'}]}
])
watch(()=>props.active,value=>{expanded.value=groups.value.find(g=>g.items.some(i=>i.id===value))?.id||''},{immediate:true})
</script>
<template>
<nav class="course-navigation" aria-label="课程功能">
 <div class="primary-navigation">
  <button v-for="item in primary" :key="item.id" :class="{active:active===item.id}" :aria-current="active===item.id?'page':undefined" @click="emit('select',item.id)"><component :is="item.icon" :size="17"/>{{item.label}}</button>
  <button v-for="group in groups" :key="group.id" :class="{active:group.items.some(i=>i.id===active)}" :aria-expanded="expanded===group.id" :aria-controls="'navigation-'+group.id" @click="expanded=expanded===group.id?'':group.id"><component :is="group.icon" :size="17"/>{{group.label}}<span aria-hidden="true">⌄</span></button>
 </div>
 <template v-for="group in groups" :key="group.id"><div v-if="expanded===group.id" :id="'navigation-'+group.id" class="secondary-navigation" :aria-label="group.label"><button v-for="item in group.items" :key="item.id" :class="{active:active===item.id}" :aria-current="active===item.id?'page':undefined" @click="emit('select',item.id)">{{item.label}}</button></div></template>
</nav>
</template>
<style scoped>
.course-navigation{margin:0 0 1.2rem;min-width:0;border-bottom:1px solid #e2e8f0}.primary-navigation,.secondary-navigation{display:flex;flex-wrap:wrap;gap:.35rem;padding:.5rem 0}.course-navigation button{display:inline-flex;align-items:center;gap:.4rem;border:0;border-radius:8px;background:transparent;padding:.65rem .85rem;color:#475569;font:inherit;cursor:pointer}.course-navigation button.active{background:#e0edff;color:#1648a0;font-weight:600}.course-navigation button:hover{background:#edf2f7}.course-navigation button:focus-visible{outline:2px solid #2563eb;outline-offset:2px}.secondary-navigation{background:#f8fafc;padding:.5rem;border-radius:10px;margin-bottom:.5rem}@media(max-width:600px){.primary-navigation{display:grid;grid-template-columns:repeat(3,minmax(0,1fr))}.course-navigation button{justify-content:center;padding:.65rem .3rem;font-size:.85rem}.secondary-navigation{display:grid;grid-template-columns:repeat(3,minmax(0,1fr))}}
</style>
