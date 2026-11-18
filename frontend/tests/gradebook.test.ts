// @vitest-environment jsdom
import {describe,it,expect,vi,beforeEach} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import GradebookWorkspace from '../src/GradebookWorkspace.vue'
import {api} from '../src/api'
vi.mock('../src/api',()=>({api:vi.fn(),download:vi.fn()}))
beforeEach(()=>vi.clearAllMocks())
describe('published gradebook scope',()=>{
  it('shows only the published snapshot returned for the student',async()=>{
    vi.mocked(api).mockResolvedValue({snapshot:{id:3,policy_revision:1,created_at:'2026-11-15T00:00:00Z',items:[{title:'积分测验',weight:'100'}],rows:[{student_id:1,total:'96.00',entries:[{score:'48',max_score:'50',grade_revision:2}]}]}})
    const w=mount(GradebookWorkspace,{props:{courseId:6,isTeacher:false}});await flushPromises()
    expect(w.text()).toContain('我的总评：96.00');expect(w.text()).toContain('评分版本 2')
    expect(w.text()).not.toContain('导出');expect(api).toHaveBeenCalledTimes(1);w.unmount()
  })
  it('explains absent publication without fabricating zero',async()=>{
    vi.mocked(api).mockResolvedValue({snapshot:null})
    const w=mount(GradebookWorkspace,{props:{courseId:6,isTeacher:false}});await flushPromises()
    expect(w.text()).toContain('暂无可见的完整总评');expect(w.text()).not.toContain('0 / 100');w.unmount()
  })
  it('preserves error states',async()=>{
    vi.mocked(api).mockRejectedValue(new Error('权限已撤回'))
    const w=mount(GradebookWorkspace,{props:{courseId:6,isTeacher:true}});await flushPromises()
    expect(w.get('[role=alert]').text()).toContain('权限已撤回');w.unmount()
  })
})

it('validates enabled weights live and blocks invalid policy writes',async()=>{
 vi.mocked(api).mockImplementation(async(path:string)=>{
  if(path.endsWith('gradebook/'))return {current:{items:[],rows:[],policy_revision:0},snapshots:[]}
  if(path.endsWith('grade-policy/'))return {revision:0,items:[]}
  if(path.endsWith('assignments/'))return [{id:1,title:'作业一'},{id:2,title:'作业二'}]
  return []
 })
 const w=mount(GradebookWorkspace,{props:{courseId:6,isTeacher:true}});await flushPromises()
 for(const c of w.findAll('input[type=checkbox]'))await c.setValue(true)
 const weights=w.findAll('input[type=number]')
 await weights[0].setValue('33.33');await weights[1].setValue('66.66')
 expect(w.text()).toContain('99.99%')
 await w.get('form').trigger('submit');await flushPromises()
 expect(vi.mocked(api).mock.calls.some(c=>c[1]==='PUT')).toBe(false)
 await weights[1].setValue('66.67')
 expect(w.text()).toContain('100.00% · 可保存')
 expect(w.get('form button').attributes('disabled')).toBeUndefined()
 await weights[1].setValue('66.667')
 expect(w.get('form button').attributes('disabled')).toBeDefined()
 w.unmount()
})
