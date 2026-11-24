// @vitest-environment jsdom
import {beforeEach,describe,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import LearningWorkspace from '../src/LearningWorkspace.vue'
import {api} from '../src/api'
vi.mock('../src/api',()=>({api:vi.fn()}))
const result={data_version:'abcdef1234567890',policy:'v1',include_unpublished:false,window:{start:'2026-11-01T00:00:00Z',end:'2026-11-15T00:00:00Z',timezone:'UTC'},class_points:[],student_count:1,students:[{student_id:9,name:'本人',points:[{id:1,name:'积分',mastery:'.8',band:'secure',sample_size:1,earned:'8',maximum:'10',evidence:[{attempt_id:4,question_id:7,question_revision:2,quiz_id:3,grade_revision:5,score:'8',maximum:'10',submitted_at:'2026-11-10T00:00:00Z',published:true,points:[{id:1,name:'原积分'}]}]},{id:2,name:'无样本',mastery:null,band:'unknown',sample_size:0,earned:'0',maximum:'0',evidence:[]}],trend:[{start:'2026-11-01T00:00:00Z',end:'2026-11-08T00:00:00Z',score_rate:null,sample_size:0}]}]}
beforeEach(()=>{vi.clearAllMocks();vi.mocked(api).mockResolvedValue(result)})
describe('learning evidence',()=>{
  it('shows readable evidence and unknown values without a class view for students',async()=>{
    const w=mount(LearningWorkspace,{props:{courseId:6,isTeacher:false}});await flushPromises()
    expect(w.text()).toContain('80.0%');expect(w.text()).toContain('评分 v5');expect(w.text()).toContain('原积分')
    expect(w.text()).toContain('没有有效评分证据');expect(w.text()).not.toContain('班级知识点');expect(w.find('input[type=checkbox]').exists()).toBe(false);w.unmount()
  })
  it('supports teacher explicit unpublished scope and real error state',async()=>{
    const w=mount(LearningWorkspace,{props:{courseId:6,isTeacher:true}});await flushPromises()
    await w.get('input[type=checkbox]').setValue(true)
    vi.mocked(api).mockRejectedValueOnce(new Error('课程权限已撤回'))
    await w.get('form').trigger('submit');await flushPromises()
    expect(api).toHaveBeenLastCalledWith(expect.stringContaining('include_unpublished=true'))
    expect(w.get('[role=alert]').text()).toContain('课程权限已撤回');expect(w.text()).not.toContain('评分 v5');w.unmount()
  })
})
