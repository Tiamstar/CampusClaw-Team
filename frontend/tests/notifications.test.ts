// @vitest-environment jsdom
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest'
import {flushPromises,mount,type VueWrapper} from '@vue/test-utils'
import {createMemoryHistory} from 'vue-router'
import {createAppRouter} from '../src/router'
import {api,ApiError} from '../src/api'
import NotificationCenter from '../src/NotificationCenter.vue'
import NotificationIndicator from '../src/NotificationIndicator.vue'
vi.mock('../src/api',async original=>({...await original<object>(),api:vi.fn()}))
const row={id:1,course_id:6,course_name:'课程',title:'积分测验',kind:'quiz',assignment_id:null,attempt_id:8,number:2,created_at:'2026-11-18T07:00:00Z',read_at:null,availability:'available',score:'85',maximum:'100'}
let wrapper:VueWrapper
beforeEach(()=>{vi.clearAllMocks();vi.mocked(api).mockResolvedValue({items:[row],next_page:null,unread_count:1})})
afterEach(()=>{wrapper?.unmount();vi.useRealTimers()})
async function open(indicator=false){const router=createAppRouter(createMemoryHistory());await router.push('/notifications');await router.isReady();wrapper=mount(indicator?NotificationIndicator:NotificationCenter,{global:{plugins:[router]}});await flushPromises();return router}
describe('persistent grade notifications',()=>{
 it('opens the exact attempt and does not mark notifications by reading',async()=>{
  const router=await open();expect(wrapper.text()).toContain('85 / 100')
  expect(vi.mocked(api).mock.calls.every(([,method])=>!method)).toBe(true)
  await wrapper.get('a').trigger('click');await flushPromises();expect(router.currentRoute.value.fullPath).toBe('/courses/6/attempts/8')
 })
 it('hides unavailable scores and links assignments to their detail',async()=>{
  vi.mocked(api).mockResolvedValue({items:[{...row,kind:'assignment',assignment_id:4,attempt_id:null,availability:'updated',score:'SECRET_OLD_SCORE'}],next_page:null,unread_count:1})
  await open();expect(wrapper.text()).toContain('成绩状态已更新');expect(wrapper.text()).not.toContain('SECRET_OLD_SCORE')
  expect(wrapper.get('a').attributes('href')).toBe('/courses/6/assignments/4')
 })
 it('saves explicit read state, refreshes and announces the badge update',async()=>{
  const event=vi.fn();window.addEventListener('campusclaw:notifications-read',event)
  vi.mocked(api).mockImplementation(async(path,method)=>method==='POST'?{}:{items:[{...row,read_at:path.includes('?')&&event.mock.calls.length?'2026-11-18':null}],next_page:null,unread_count:event.mock.calls.length?0:1})
  await open();await wrapper.findAll('button').find(b=>b.text()==='标为已读')!.trigger('click');await flushPromises()
  expect(api).toHaveBeenCalledWith('notifications/1/read/','POST',{});expect(event).toHaveBeenCalledTimes(1)
  expect(wrapper.text()).toContain('已标为已读');expect(wrapper.text()).toContain('未读通知：0 条')
  window.removeEventListener('campusclaw:notifications-read',event)
 })
 it('does not fake success on read failure and keeps the notification unread',async()=>{
  await open();vi.mocked(api).mockRejectedValueOnce(new ApiError('未能保存',503))
  await wrapper.findAll('button').find(b=>b.text()==='标为已读')!.trigger('click');await flushPromises()
  expect(wrapper.get('[role=status]').text()).toContain('未能保存');expect(wrapper.text()).not.toContain('已标为已读')
  expect(wrapper.findAll('button').some(b=>b.text()==='标为已读')).toBe(true)
 })
 it('retries the failed page instead of replacing it with page one',async()=>{
  vi.mocked(api).mockResolvedValueOnce({items:[row],next_page:2,unread_count:1});await open()
  vi.mocked(api).mockRejectedValueOnce(new ApiError('暂不可用',503))
  await wrapper.findAll('button').find(b=>b.text()==='加载更多通知')!.trigger('click');await flushPromises()
  vi.mocked(api).mockResolvedValueOnce({items:[],next_page:null,unread_count:1})
  await wrapper.findAll('button').find(b=>b.text()==='重新加载')!.trigger('click');await flushPromises()
  expect(api).toHaveBeenLastCalledWith('notifications/?page=2')
 })
 it('shows an empty inbox without claiming historic notifications were sent',async()=>{
  vi.mocked(api).mockResolvedValue({items:[],next_page:null,unread_count:0});await open()
  expect(wrapper.text()).toContain('暂无成绩通知');expect(wrapper.text()).toContain('更早发布的成绩仍可在原作业或测验中查看')
 })
 it('refreshes the unread indicator on explicit read and cleans up polling',async()=>{
  vi.useFakeTimers();vi.mocked(api).mockResolvedValue({unread_count:3});await open(true)
  expect(wrapper.get('a').attributes('aria-label')).toBe('通知（3条未读）')
  vi.mocked(api).mockResolvedValue({unread_count:0});window.dispatchEvent(new Event('campusclaw:notifications-read'));await flushPromises()
  expect(wrapper.get('a').attributes('aria-label')).toBe('通知（0条未读）')
  wrapper.unmount();const count=vi.mocked(api).mock.calls.length;await vi.advanceTimersByTimeAsync(120000)
  expect(api).toHaveBeenCalledTimes(count)
 })
 it('marks failed badge refresh as unknown rather than zero unread',async()=>{
  vi.mocked(api).mockRejectedValue(new ApiError('offline',503));await open(true)
  expect(wrapper.get('a').attributes('aria-label')).toBe('通知（未读数量暂不可用）')
 })
})
