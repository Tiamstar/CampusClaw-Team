// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import CourseworkAI from '../src/CourseworkAI.vue'
import { api } from '../src/api'
import {confirmReviewNotesLeave,hasUnsavedReviewNotes} from '../src/unsavedReviewNotes'
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

it('persists self-review with grade and record revisions without altering grades',async()=>{
 vi.mocked(api).mockImplementation(async(path,method)=>{
  if(path.includes('settings'))return config
  if(path.includes('wrong-answer-reviews'))return method==='POST'?{item_id:'c1',status:'mastered',note:'',revision:1}:{}
  return []
 })
 const w=mount(CourseworkAI,{props:{...props,isTeacher:false,version:{...props.version,grade_published:true,grade:{revision:2,reviewed_items:[item]}} as any}});await flushPromises()
 await w.findAll('button').find(b=>b.text()==='标记已掌握')!.trigger('click');await flushPromises()
 expect(api).toHaveBeenCalledWith('submission-versions/3/wrong-answer-reviews/','POST',{item_id:'c1',status:'mastered',note:'',expected_revision:0,grade_revision:2})
 expect(w.get('.review-badge').text()).toBe('已掌握')
 expect(vi.mocked(api).mock.calls.some(([p])=>p.includes('/grade/'))).toBe(false);w.unmount()
})

it('does not let a late polling result undo a newly saved self-review',async()=>{
 vi.useFakeTimers()
 let reads=0,finish!:(value:unknown)=>void
 vi.mocked(api).mockImplementation(async(path,method)=>{
  if(path.includes('settings'))return config
  if(path.includes('wrong-answer-reviews')){
   if(method==='POST')return {item_id:'c1',status:'mastered',note:'',revision:1}
   if(++reads===2)return new Promise(resolve=>finish=resolve)
   return {}
  }
  return [{...task,status:'queued',result:{}}]
 })
 const w=mount(CourseworkAI,{props:{...props,isTeacher:false,version:{...props.version,grade_published:true,grade:{revision:2,reviewed_items:[item]}} as any}});await flushPromises()
 await vi.advanceTimersByTimeAsync(3000);await flushPromises()
 await w.findAll('button').find(b=>b.text()==='标记已掌握')!.trigger('click');await flushPromises()
 finish({});await flushPromises()
 expect(w.get('.review-badge').text()).toBe('已掌握')
 expect(w.text()).toContain('已保存：自评已掌握')
 w.unmount();vi.useRealTimers()
})

it('keeps private note input after failure and saves it without changing mastery',async()=>{
 let fail=true
 vi.mocked(api).mockImplementation(async(path,method,data)=>{
  if(path.includes('settings'))return config
  if(path.includes('wrong-answer-reviews')){
   if(method==='POST'){if(fail)throw new Error('网络失败');return {item_id:'c1',status:'mastered',note:(data as any).note,revision:3}}
   return {c1:{status:'mastered',note:'原备注',revision:2}}
  }
  return []
 })
 const w=mount(CourseworkAI,{props:{...props,isTeacher:false,version:{...props.version,grade_published:true,grade:{revision:2,reviewed_items:[item]}} as any}});await flushPromises()
 const note=w.get('textarea');expect((note.element as HTMLTextAreaElement).value).toBe('原备注')
 await note.setValue('先检查上下限')
 const save=w.findAll('button').find(b=>b.text()==='保存复习备注')!
 await save.trigger('click');await flushPromises()
 expect((note.element as HTMLTextAreaElement).value).toBe('先检查上下限');expect(w.text()).toContain('备注尚未保存')
 fail=false;await save.trigger('click');await flushPromises()
 expect(api).toHaveBeenLastCalledWith('submission-versions/3/wrong-answer-reviews/','POST',{item_id:'c1',status:'mastered',note:'先检查上下限',expected_revision:2,grade_revision:2})
 expect(w.text()).not.toContain('备注尚未保存');expect(w.get('.review-badge').text()).toBe('已掌握');w.unmount()
})

it('protects unsaved notes and unregisters the guard when the component leaves',async()=>{
 vi.mocked(api).mockImplementation(async(path)=>path.includes('settings')?config:path.includes('wrong-answer-reviews')?{}:[])
 const w=mount(CourseworkAI,{props:{...props,isTeacher:false,version:{...props.version,grade_published:true,grade:{revision:2,reviewed_items:[item]}} as any}});await flushPromises()
 expect(hasUnsavedReviewNotes()).toBe(false)
 await w.get('textarea').setValue('待保存的反思')
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(false)
 expect(confirmReviewNotesLeave()).toBe(false)
 expect(confirm).toHaveBeenCalledOnce()
 const unload=new Event('beforeunload',{cancelable:true});window.dispatchEvent(unload);expect(unload.defaultPrevented).toBe(true)
 await w.get('textarea').setValue('');expect(hasUnsavedReviewNotes()).toBe(false)
 await w.get('textarea').setValue('仍未保存');w.unmount()
 expect(hasUnsavedReviewNotes()).toBe(false);confirm.mockRestore()
})
