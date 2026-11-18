// @vitest-environment jsdom
import {mount,flushPromises} from '@vue/test-utils'
import {beforeEach,describe,it,expect,vi} from 'vitest'
import ReviewWorkspace from '../src/ReviewWorkspace.vue'
import {api} from '../src/api'
vi.mock('../src/api',()=>({api:vi.fn(),openProtected:vi.fn()}))
const step=(id:number,pre:number[]=[])=>({point_id:id,name:id===1?'函数':'积分',purpose:'general',mastery:null,sample_size:0,evidence_note:'暂无有效评分证据，提供一般复习建议',explanation:'先复习定义',prerequisite_ids:pre,evidence:[],materials:[],cited_refs:[]})
const plan=()=>({id:1,status:'awaiting_confirmation',revision:2,steps:[step(1),step(2,[1])],selected_ids:[],schedule:{},stale:false,error:'',window:{start:'2026-09-01T00:00:00Z',end:'2026-11-17T00:00:00Z'},reminders:[]})
beforeEach(()=>{vi.clearAllMocks();vi.mocked(api).mockResolvedValue({items:[plan()],next_page:null})})
describe('personal review confirmation',()=>{
 it('keeps prerequisite selection and requires explicit schedule confirmation',async()=>{
  const w=mount(ReviewWorkspace,{props:{courseId:6,isTeacher:false}});await flushPromises()
  expect(w.text()).toContain('暂无有效评分证据');expect(api).toHaveBeenCalledTimes(1)
  const checks=w.findAll('input[type=checkbox]');await checks[0].setValue(false)
  expect((checks[1].element as HTMLInputElement).checked).toBe(false)
  await checks[1].setValue(true);expect((checks[0].element as HTMLInputElement).checked).toBe(true)
  vi.mocked(api).mockResolvedValue({...plan(),status:'active',selected_ids:[1,2]})
  await w.findAll('form')[1].trigger('submit');await flushPromises()
  expect(api).toHaveBeenCalledWith('review-plans/1/action/','POST',expect.objectContaining({action:'confirm',expected_revision:2,point_ids:[2,1],schedule:expect.objectContaining({offset_days:[0,1,3,7]})}));w.unmount()
 })
 it('suspends a stale plan and displays real errors',async()=>{
  vi.mocked(api).mockResolvedValue({items:[{...plan(),stale:true}],next_page:null})
  const w=mount(ReviewWorkspace,{props:{courseId:6,isTeacher:false}});await flushPromises()
  expect(w.text()).toContain('请重新生成');expect(w.findAll('form')).toHaveLength(1)
  vi.mocked(api).mockRejectedValue(new Error('无课程权限'))
  await w.findAll('button').find(b=>b.text()==='刷新计划')!.trigger('click');await flushPromises()
  expect(w.text()).toContain('无课程权限');w.unmount()
 })
 it('does not request another student path for teachers',async()=>{
  const w=mount(ReviewWorkspace,{props:{courseId:6,isTeacher:true}});await flushPromises()
  expect(api).not.toHaveBeenCalled();expect(w.text()).toContain('学生个人功能');w.unmount()
 })
})
