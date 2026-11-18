// @vitest-environment jsdom
import {beforeEach,afterEach,describe,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import {createMemoryHistory} from 'vue-router'
import {createAppRouter} from '../src/router'
import App from '../src/App.vue'
import {api} from '../src/api'
const state=vi.hoisted(()=>({allow:true,loggedIn:true,role:'teacher'}))
vi.mock('../src/auth',()=>({hasStoredAuth:()=>state.loggedIn,restoreAuth:vi.fn(),saveTokens:vi.fn(),clearTokens:vi.fn(),logoutAuth:vi.fn()}))
vi.mock('../src/api',async importOriginal=>({...await importOriginal<object>(),api:vi.fn()}))
vi.mock('../src/asyncWorkspace',async()=>{
  const {defineComponent,h}=await import('vue')
  return {asyncWorkspace:()=>defineComponent({name:'TestWorkspace',props:['initialAttemptId','initialPostId'],emits:['attemptChange','postChange'],setup(props,{expose}){expose({canLeave:()=>state.allow});return()=>h('p','工作区 '+(props.initialAttemptId??props.initialPostId??''))}})}
})
let cleanup:()=>void
beforeEach(()=>{
  state.allow=true;state.loggedIn=true;state.role='teacher';vi.clearAllMocks()
  vi.mocked(api).mockImplementation(async(path:string)=>{
    if(path==='me/')return {id:1,display_name:'验收用户',email:'private@example.test'}
    if(path==='courses/')return [{id:6,name:'验收课程',role:state.role,member_count:2,icon:null}]
    if(path.endsWith('/assignments/'))return [{id:8,title:'作业八',due_at:'2026-12-01T00:00:00Z',submission_status:'unsubmitted'}]
    return []
  })
})
afterEach(()=>cleanup?.())
async function open(path:string){
  const router=createAppRouter(createMemoryHistory())
  await router.push(path);await router.isReady()
  const wrapper=mount(App,{global:{plugins:[router]}})
  cleanup=()=>wrapper.unmount();await flushPromises()
  return {router,wrapper}
}
describe('course locations and history',()=>{
  it('opens the overview by default while retaining existing module links',async()=>{
    const {router,wrapper}=await open('/courses/6')
    expect(router.currentRoute.value.fullPath).toBe('/courses/6/overview')
    expect(wrapper.get('[aria-current=page]').text()).toBe('课程首页')
    await router.push('/courses');await flushPromises()
    await wrapper.get('.course-tile').trigger('click');await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/courses/6/overview')
  })
  it('restores a linked module and synchronizes navigation with back and forward',async()=>{
    const {router,wrapper}=await open('/courses/6/learning')
    expect(wrapper.text()).toContain('验收课程')
    expect(wrapper.get('[aria-current=page]').text()).toContain('学情分析')
    await wrapper.get('[aria-label=课程功能]').findAll('button').find(b=>b.text()==='课程资料')!.trigger('click');await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/courses/6/materials')
    router.back();await vi.waitFor(()=>expect(router.currentRoute.value.fullPath).toBe('/courses/6/learning'));await flushPromises()
    expect(wrapper.get('[aria-current=page]').text()).toContain('学情分析')
    router.forward();await vi.waitFor(()=>expect(router.currentRoute.value.fullPath).toBe('/courses/6/materials'))
  })
  it('rejects browser history and clicks when the workspace refuses leaving',async()=>{
    const {router,wrapper}=await open('/courses/6/materials')
    await router.push('/courses/6/exams');await flushPromises();state.allow=false
    router.back();await new Promise(resolve=>setTimeout(resolve,20));await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/courses/6/exams')
    await router.push('/courses');await flushPromises()
    expect(wrapper.text()).toContain('验收课程');expect(router.currentRoute.value.fullPath).toBe('/courses/6/exams')
    state.allow=true;await router.push('/courses');await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/courses')
  })
  it('retains attempt links and routes internal attempt opening without a history API bypass',async()=>{
    const {router,wrapper}=await open('/courses/6/attempts/7')
    expect(wrapper.text()).toContain('工作区 7')
    wrapper.findComponent({name:'TestWorkspace'}).vm.$emit('attemptChange',9);await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/courses/6/attempts/9')
    expect(wrapper.text()).toContain('工作区 9')
  })
  it('restores an assignment and gives an actionable error for a missing assignment',async()=>{
    const {router,wrapper}=await open('/courses/6/assignments/8')
    expect(wrapper.get('[aria-current=page]').text()).toBe('作业')
    expect(api).toHaveBeenCalledWith('courses/6/assignments/')
    await router.push('/courses/6/assignments/999');await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toContain('这个作业不存在')
  })
  it('does not load another course or a student-only forbidden management module',async()=>{
    state.role='student'
    const {router,wrapper}=await open('/courses/6/exams')
    await flushPromises();expect(router.currentRoute.value.fullPath).toBe('/courses/6/quiz')
    await router.push('/courses/999/members');await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toContain('无法访问这个课程')
    expect(api).not.toHaveBeenCalledWith('courses/999/members/')
    await router.push('/bad-link');await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toContain('这个页面地址不存在')
  })
  it('keeps the deep link while showing login when unauthenticated',async()=>{
    state.loggedIn=false
    const {router,wrapper}=await open('/courses/6/forum')
    expect(wrapper.text()).toContain('登录 CampusClaw')
    expect(router.currentRoute.value.fullPath).toBe('/courses/6/forum')
    expect(api).not.toHaveBeenCalled()
  })
})

it('shows assignment loading rather than empty data and retains an actionable failure',async()=>{
  const original=vi.mocked(api).getMockImplementation()!
  let reject!:(reason:Error)=>void
  const {wrapper,router}=await open('/courses/6/overview')
  vi.mocked(api).mockImplementation(async(path,...args)=>path==='courses/6/assignments/'?new Promise((_,r)=>reject=r):original(path,...args))
  await router.push('/courses/6/assignments/8');await flushPromises()
  expect(wrapper.text()).toContain('正在读取作业')
  expect(wrapper.text()).not.toContain('暂无作业')
  reject(new Error('网络暂时不可用'));await flushPromises()
  expect(wrapper.text()).toContain('网络暂时不可用')
  expect(wrapper.text()).not.toContain('暂无作业')
  vi.mocked(api).mockImplementation(original)
  await wrapper.findAll('button').find(b=>b.text()==='重新加载')!.trigger('click');await flushPromises()
  expect(wrapper.text()).not.toContain('网络暂时不可用')
  expect(wrapper.text()).not.toContain('暂无作业')
})

it('restores forum post deep links and synchronizes post navigation',async()=>{
 const {wrapper,router}=await open('/courses/6/forum/posts/12')
 expect(wrapper.text()).toContain('工作区 12')
 wrapper.findComponent({name:'TestWorkspace'}).vm.$emit('postChange',15);await flushPromises()
 expect(router.currentRoute.value.fullPath).toBe('/courses/6/forum/posts/15')
 wrapper.findComponent({name:'TestWorkspace'}).vm.$emit('postChange',undefined);await flushPromises()
 expect(router.currentRoute.value.fullPath).toBe('/courses/6/forum')
 router.back();await vi.waitFor(()=>expect(router.currentRoute.value.fullPath).toBe('/courses/6/forum/posts/15'));await flushPromises()
 expect(wrapper.text()).toContain('工作区 15')
})
