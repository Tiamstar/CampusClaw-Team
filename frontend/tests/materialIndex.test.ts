// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import MaterialIndexStatus from '../src/MaterialIndexStatus.vue'
import { api } from '../src/api'
vi.mock('../src/api',()=>({api:vi.fn()}))
afterEach(()=>vi.resetAllMocks())
const task={id:1,material_id:2,status:'running',phase:'embed',revision:3,error:'',error_code:'',retry_of_id:null,events:[{phase:'queued',at:'2026-11-16T00:00:00Z'}],result:{},created_at:'',started_at:null,finished_at:null}
it('students see true state without task management or history',async()=>{
  const view=mount(MaterialIndexStatus,{props:{materialId:2,status:'queued',isTeacher:false}})
  expect(view.text()).toContain('排队中');expect(view.findAll('button')).toHaveLength(0)
  await view.setProps({status:'failed',error:'知识索引未完成，请联系任课教师'})
  expect(view.text()).toContain('联系任课教师');expect(api).not.toHaveBeenCalled();view.unmount()
})
it('teachers cancel the displayed revision and refresh on completion',async()=>{
  vi.mocked(api).mockResolvedValue({} as any)
  const view=mount(MaterialIndexStatus,{props:{materialId:2,status:'running',task,isTeacher:true}})
  await view.get('.index-actions button').trigger('click');await flushPromises()
  expect(api).toHaveBeenCalledWith('index-tasks/1/','POST',expect.objectContaining({action:'cancel',expected_revision:3}))
  expect(view.emitted('changed')).toHaveLength(1);expect(view.text()).toContain('迟到结果不会生效');view.unmount()
})
it('failed retry reports server errors without inventing success and refreshes stale metadata',async()=>{
  vi.mocked(api).mockRejectedValue(new Error('任务状态已变化，请刷新后重试'))
  const view=mount(MaterialIndexStatus,{props:{materialId:2,status:'failed',task:{...task,status:'failed'},isTeacher:true}})
  await view.get('.index-actions button').trigger('click');await flushPromises()
  expect(view.text()).toContain('状态已变化');expect(view.text()).not.toContain('已排队，后台执行')
  expect(view.emitted('changed')).toHaveLength(1);view.unmount()
})
it('untracked legacy materials are explicit and teachers can inspect empty history',async()=>{
  vi.mocked(api).mockResolvedValue({results:[],has_more:false} as any)
  const view=mount(MaterialIndexStatus,{props:{materialId:2,status:'untracked',isTeacher:true}})
  expect(view.text()).toContain('尚未建立索引')
  await view.findAll('.index-actions button')[1]!.trigger('click');await flushPromises()
  expect(view.text()).toContain('暂无任务记录');view.unmount()
})

it('clears the previous queue notice when automatic refresh reports completion',async()=>{
  vi.mocked(api).mockResolvedValue({} as any)
  const view=mount(MaterialIndexStatus,{props:{materialId:2,status:'failed',task:{...task,status:'failed'},isTeacher:true}})
  await view.get('.index-actions button').trigger('click');await flushPromises()
  expect(view.text()).toContain('已排队，后台执行结果会自动更新')
  await view.setProps({status:'ready',task:{...task,status:'succeeded'}})
  expect(view.text()).not.toContain('已排队，后台执行结果会自动更新')
  expect(view.text()).toContain('已建立知识索引');view.unmount()
})
