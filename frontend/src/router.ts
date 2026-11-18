import {createRouter,createWebHashHistory,type RouterHistory} from 'vue-router'

export const courseModules=['overview','materials','assignments','members','agent','studio','forum','quiz','bank','exams','gradebook','learning','graph','review','diagnostic','wrongs','teaching'] as const
export type CourseModule=typeof courseModules[number]
// App retains the existing workspaces; named routes provide their stable location.
const WorkspaceRoute={render:()=>null}
export function createAppRouter(history:RouterHistory=createWebHashHistory()){
  return createRouter({history,routes:[
    {path:'/',redirect:{name:'courses'}},
    {path:'/grading',name:'grading',component:WorkspaceRoute},
    {path:'/notifications',name:'notifications',component:WorkspaceRoute},
    {path:'/courses',name:'courses',component:WorkspaceRoute},
    {path:'/courses/:courseId(\\d+)',redirect:to=>({name:'course-module',params:{courseId:to.params.courseId,module:'overview'}})},
    {path:'/courses/:courseId(\\d+)/forum/posts/:postId(\\d+)',name:'forum-post',component:WorkspaceRoute},
    {path:'/courses/:courseId(\\d+)/attempts/:attemptId(\\d+)',name:'attempt',component:WorkspaceRoute},
    {path:'/courses/:courseId(\\d+)/assignments/:assignmentId(\\d+)',name:'assignment',component:WorkspaceRoute},
    {path:'/courses/:courseId(\\d+)/:module('+courseModules.join('|')+')',name:'course-module',component:WorkspaceRoute},
    {path:'/:pathMatch(.*)*',name:'not-found',component:WorkspaceRoute}
  ]})
}
