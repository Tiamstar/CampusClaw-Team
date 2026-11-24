// @vitest-environment jsdom
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest'
import {flushPromises,mount,type VueWrapper} from '@vue/test-utils'
import {createMemoryHistory} from 'vue-router'
import {createAppRouter} from '../src/router'
import {api,ApiError} from '../src/api'
import CourseOverview from '../src/CourseOverview.vue'

vi.mock('../src/api',async original=>({...await original<object>(),api:vi.fn()}))
const student={role:'student',generated_at:'2026-11-18T06:00:00Z',counts:{assignments_to_submit:2,missed_assignments:1,open_quizzes:1,upcoming_quizzes:1},assignments:[{id:8,title:'积分作业',due_at:'2026-11-19T06:00:00Z',allow_late:false},{id:9,title:'补交作业',due_at:'2026-11-17T06:00:00Z',allow_late:true}],quizzes:[{id:3,title:'微积分测验',opens_at:'2026-11-18T05:00:00Z',closes_at:'2026-11-19T06:00:00Z'}],active_attempts:[{id:5,quiz__title:'未交卷测验',deadline:'2026-11-18T05:00:00Z'}],recent_posts:[{id:4,title:'<script>unsafe</script>',created_at:'2026-11-18T05:00:00Z',resolved_reply_id:null}]}
let wrapper:VueWrapper
beforeEach(()=>{vi.clearAllMocks();vi.mocked(api).mockResolvedValue(structuredClone(student))})
afterEach(()=>wrapper?.unmount())
async function open(){const router=createAppRouter(createMemoryHistory());await router.push('/courses/6/overview');await router.isReady();wrapper=mount(CourseOverview,{props:{courseId:6},global:{plugins:[router]}});return router}

describe('course overview',()=>{
 it('shows deadlines with exact assignment and attempt links and no teacher actions',async()=>{
  const router=await open();await flushPromises()
  expect(wrapper.text()).toContain('尚可提交的未交作业');expect(wrapper.text()).toContain('已逾期 · 允许迟交')
  expect(wrapper.text()).toContain('核对答卷状态 · 未交卷测验');expect(wrapper.text()).not.toContain('继续作答 · 未交卷测验')
  expect(wrapper.text()).not.toContain('管理题库');expect(wrapper.find('script').exists()).toBe(false)
  expect(wrapper.findAll('a').find(a=>a.text()==='积分作业')!.attributes('href')).toBe('/courses/6/assignments/8')
  await wrapper.findAll('a').find(a=>a.text().includes('核对答卷状态'))!.trigger('click');await flushPromises()
  expect(router.currentRoute.value.fullPath).toBe('/courses/6/attempts/5')
 })
 it('shows actual teacher pending counts and all-course grading shortcut',async()=>{
  vi.mocked(api).mockResolvedValue({...student,role:'teacher',counts:{assignment_reviews:7,quiz_reviews:4,open_quizzes:1,upcoming_quizzes:0},active_attempts:[]})
  await open();await flushPromises()
  expect(wrapper.text()).toContain('本课程作业待批改');expect(wrapper.text()).toContain('管理题库与组卷')
  expect(wrapper.findAll('a').find(a=>a.text().includes('全部任教课程'))!.attributes('href')).toBe('/grading')
  expect(wrapper.text()).not.toContain('尚未交卷的答卷')
 })
 it('shows loading and honest empty states',async()=>{
  let resolve!:(value:unknown)=>void
  vi.mocked(api).mockReturnValue(new Promise(r=>resolve=r));await open()
  expect(wrapper.get('[role=status]').text()).toContain('正在加载')
  resolve({...student,assignments:[],quizzes:[],active_attempts:[],recent_posts:[]});await flushPromises()
  expect(wrapper.text()).toContain('当前没有尚可提交的未交作业');expect(wrapper.text()).toContain('还没有课程讨论')
 })
 it('retries transient errors and returns to courses when access is revoked',async()=>{
  vi.mocked(api).mockRejectedValueOnce(new ApiError('服务暂时不可用',503));const router=await open();await flushPromises()
  expect(wrapper.get('[role=alert]').text()).toContain('课程概览未能加载')
  await wrapper.findAll('button').find(b=>b.text()==='重新加载')!.trigger('click');await flushPromises()
  expect(wrapper.text()).toContain('积分作业')
  vi.mocked(api).mockRejectedValueOnce(new ApiError('无权访问课程',403))
  await wrapper.findAll('button').find(b=>b.text()==='刷新概览')!.trigger('click');await flushPromises()
  expect(wrapper.text()).not.toContain('积分作业');expect(wrapper.text()).not.toContain('重新加载')
  await wrapper.findAll('button').find(b=>b.text()==='返回列表')!.trigger('click');await flushPromises()
  expect(router.currentRoute.value.fullPath).toBe('/courses')
 })
 it('discards a late response from the previous course',async()=>{
  let resolve!:(value:unknown)=>void
  vi.mocked(api).mockReturnValueOnce(new Promise(r=>resolve=r));await open()
  vi.mocked(api).mockResolvedValue({...student,assignments:[]});await wrapper.setProps({courseId:7});await flushPromises()
  resolve(student);await flushPromises()
  expect(wrapper.text()).not.toContain('积分作业');expect(api).toHaveBeenLastCalledWith('courses/7/overview/')
 })
})
