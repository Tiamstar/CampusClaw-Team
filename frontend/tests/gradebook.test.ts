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
