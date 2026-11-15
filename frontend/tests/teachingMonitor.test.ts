// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import TeachingWorkspace from '../src/TeachingWorkspace.vue'
import { api } from '../src/api'
vi.mock('../src/api',()=>({api:vi.fn()}))
const config={guidance_enabled:true,grading_enabled:true,explanation_enabled:true,revision:0}
const task={id:6,question:'How to integrate?',status:'succeeded',revision:1,current:true,skill_id:'problem-guidance@1.0.0',settings_revision:0,error:'',result:{explanation:'Try $x^2$. <img src=x onerror=alert(1)>',citations:[{material_id:1,chunk_id:2,title:'Book',excerpt:'integral'}]}}
function responses(teacher=false,rows:any[]=[]){vi.mocked(api).mockImplementation(async path=>path.includes('settings')?{...config}:path.includes('skill-monitor')?{monitor_stale:true,monitor_evaluated_at:null,usage_note:'Unreported is unknown',curve_interval:'minute_sample',skills:[{kind:'guidance',skill_id:'problem-guidance@1.0.0',calls:0,usage_coverage:null,input_tokens:null,output_tokens:null,total_tokens:null,p95_ms:null,failure_rate:null,oldest_queue_seconds:0}],queue_curve:[],alerts:[],events:[]}:rows as any);return mount(TeachingWorkspace,{props:{courseId:7,isTeacher:teacher}})}
afterEach(()=>{vi.resetAllMocks();vi.useRealTimers()})
it('student requests private guide; renders sanitized math and real references without monitoring',async()=>{
 const v=responses(false,[task]);await flushPromises();expect(v.find('.katex').exists()).toBe(true);expect(v.find('img[onerror]').exists()).toBe(false);expect(v.text()).toContain('[m1:c2]');expect(v.text()).not.toContain('运行监控');expect(vi.mocked(api).mock.calls.every(c=>!c[0].includes('monitor'))).toBe(true)
 await v.find('textarea').setValue('Give a hint');await v.find('form').trigger('submit');await flushPromises();expect(api).toHaveBeenCalledWith('courses/7/guidance-tasks/','POST',expect.objectContaining({question:'Give a hint',request_key:expect.any(String)}));v.unmount()
})
it('teacher has three switches and unknown usage stays unknown',async()=>{
 const v=responses(true);await flushPromises();expect(v.findAll('input[type=checkbox]')).toHaveLength(3);expect(v.text()).toContain('未上报');expect(v.text()).toContain('已过期或尚未启动');expect(v.text()).toContain('暂无队列采样');v.unmount()
})
it('network retry preserves request identity; unmount stops polling',async()=>{
 vi.useFakeTimers();const v=responses();await flushPromises();await v.find('textarea').setValue('hint');vi.mocked(api).mockRejectedValue(new Error('offline'))
 await v.find('form').trigger('submit');await flushPromises();await v.find('form').trigger('submit');await flushPromises();const calls=vi.mocked(api).mock.calls.filter(c=>c[1]==='POST');expect(calls[0]![2]).toEqual(calls[1]![2]);expect(v.text()).toContain('offline');v.unmount();const count=vi.mocked(api).mock.calls.length;await vi.advanceTimersByTimeAsync(30000);expect(vi.mocked(api).mock.calls).toHaveLength(count)
})
it('disabled guidance and active queue prevent duplicate form submission',async()=>{
 const v=responses(false,[{...task,status:'queued',result:{}}]);await flushPromises();await v.find('textarea').setValue('hint');expect(v.find('button.primary').attributes('disabled')).toBeDefined();expect(v.text()).toContain('取消任务');v.unmount()
})

it('background refresh preserves unsaved teacher switches',async()=>{
 vi.useFakeTimers();const v=responses(true);await flushPromises();await v.find('input[type=checkbox]').setValue(false);await vi.advanceTimersByTimeAsync(10000);await flushPromises();expect((v.find('input[type=checkbox]').element as HTMLInputElement).checked).toBe(false);v.unmount()
})

it('explicit refresh discards stale settings draft so configuration conflicts can recover',async()=>{
 const v=responses(true);await flushPromises();await v.find('input[type=checkbox]').setValue(false);await v.findAll('button').find(b=>b.text()==='刷新记录')!.trigger('click');await flushPromises();expect((v.find('input[type=checkbox]').element as HTMLInputElement).checked).toBe(true);v.unmount()
})
