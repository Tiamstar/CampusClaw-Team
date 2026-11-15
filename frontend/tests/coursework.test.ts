// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import CourseworkAI from '../src/CourseworkAI.vue'
import { api } from '../src/api'
vi.mock('../src/api',()=>({api:vi.fn()}))
const config={grading_enabled:true,explanation_enabled:true,revision:2}
const item={id:'c1',title:'积分',reference:'x^2',maximum:'10.00',score:'5.00',feedback:'少计算下限'}
const task={id:8,kind:'grading',status:'draft',phase:'awaiting_review',revision:3,current:true,skill_id:'homework-grading@1.0.0',settings_revision:2,error:'',result:{items:[item]},events:[]}
const props={assignment:{id:1,course_id:2,max_score:'10.00'} as any,version:{id:3,grade_published:false,grade:null} as any,isTeacher:true}
afterEach(()=>vi.resetAllMocks())
function responses(rows:any[]){vi.mocked(api).mockImplementation(async(path)=>path.includes('settings')?config:rows as any)}
it('adopting a draft only fills review; never writes formal grades or publication',async()=>{
  responses([task]);const v=mount(CourseworkAI,{props});await flushPromises()
  await v.findAll('button').find(b=>b.text()==='采用为复核起点')!.trigger('click');await flushPromises()
  expect(v.emitted('adopt')?.[0]?.[0]).toEqual({task_id:8,items:[item]})
  expect(vi.mocked(api).mock.calls.every(c=>!c[0].includes('/grade/')&&!c[0].includes('/publication/'))).toBe(true)
  expect(v.text()).toContain('逐项教师复核');v.unmount()
})
it('student sees only published wrong items and can request a version-bound explanation',async()=>{
  responses([]);const v=mount(CourseworkAI,{props:{...props,isTeacher:false,version:{id:3,grade_published:true,grade:{reviewed_items:[item,{...item,id:'c2',score:'10.00'}]}} as any}});await flushPromises()
  expect(v.text()).not.toContain('技能开关');expect(v.text()).not.toContain('生成 AI 批改建议')
  const buttons=v.findAll('button').filter(b=>b.text()==='生成此题讲解');expect(buttons).toHaveLength(1)
  await buttons[0]!.trigger('click');await flushPromises()
  expect(api).toHaveBeenCalledWith('submission-versions/3/ai-tasks/','POST',expect.objectContaining({kind:'explanation',item_id:'c1',request_key:expect.any(String)}));v.unmount()
})
it('hidden grades do not render supplied wrong items or permit explanation',async()=>{
  responses([]);const v=mount(CourseworkAI,{props:{...props,isTeacher:false,version:{id:3,grade_published:false,grade:{reviewed_items:[item]}} as any}});await flushPromises()
  expect(v.text()).toContain('教师尚未公开');expect(v.text()).not.toContain('少计算下限');expect(v.text()).not.toContain('生成此题讲解');v.unmount()
})
it('errors keep request identity for network retry and never invent a result',async()=>{
  responses([]);const v=mount(CourseworkAI,{props});await flushPromises()
  vi.mocked(api).mockRejectedValue(new Error('网络失败'))
  const button=v.findAll('button').find(b=>b.text()==='生成 AI 批改建议')!
  await button.trigger('click');await flushPromises();await button.trigger('click');await flushPromises()
  const calls=vi.mocked(api).mock.calls.filter(c=>c[1]==='POST');expect(calls).toHaveLength(2)
  expect(calls[0]![2]).toEqual(calls[1]![2]);expect(v.text()).toContain('网络失败');expect(v.text()).not.toContain('待教师复核');v.unmount()
})
it('disabled or stale drafts cannot be adopted and malicious explanations are sanitized',async()=>{
  responses([{...task,current:false,result:{}},{...task,id:9,kind:'explanation',status:'succeeded',result:{explanation:'<img src=x onerror=alert(1)> $x^2$'}}]);const v=mount(CourseworkAI,{props});await flushPromises()
  expect(v.text()).not.toContain('采用为复核起点');expect(v.find('img[onerror]').exists()).toBe(false);expect(v.find('.katex').exists()).toBe(true);v.unmount()
})
