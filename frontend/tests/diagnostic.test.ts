// @vitest-environment jsdom
import {mount,flushPromises} from '@vue/test-utils'
import {beforeEach,describe,it,expect,vi} from 'vitest'
import DiagnosticWorkspace from '../src/DiagnosticWorkspace.vue'
import {api} from '../src/api'
vi.mock('../src/api',()=>({api:vi.fn(),openProtected:vi.fn()}))
function report(){return {id:1,student_id:2,student_name:'学生甲',status:'draft',phase:'awaiting_review',revision:1,current_version:1,stale:false,error:'',model:'test',skill:'learning-diagnosis@1.0.0',version:{number:1,content_hash:'hash',html_url:'/html/',pdf_url:'/pdf/',content:{limitations:'仅基于正式评分，不改变成绩',window:{start:'2026-09-01',end:'2026-11-17'},basis_version:'basis',metrics:[{id:3,name:'积分',mastery:'.6',sample_size:1}],point_names:{3:'积分'},claims:[{point_id:3,finding:'依据6/10观察',recommendation:'回看定义',refs:['a1:q1:g2']}],evidence:{'a1:q1:g2':{attempt_id:1,question_id:1,score:'6',maximum:'10',grade_revision:2}}}}}}
beforeEach(()=>{vi.clearAllMocks();vi.mocked(api).mockImplementation(async path=>path.includes('diagnostic-settings')?{enabled:true,revision:0}:path.includes('/members/')?[{id:2,name:'学生甲',role:'student'}]:{items:[report()],next_page:null})})
describe('diagnosis explicit review',()=>{
 it('requires checked evidence and reason before teacher review; publication is separate',async()=>{
  const w=mount(DiagnosticWorkspace,{props:{courseId:6,isTeacher:true}});await flushPromises()
  const review=w.findAll('button').find(b=>b.text()==='确认逐条复核')!
  expect(review.attributes('disabled')).toBeDefined();expect(w.text()).toContain('a1:q1:g2')
  expect(w.findAll('button').some(b=>b.text()==='发布给该学生')).toBe(false)
  await w.get('input[type=checkbox]').setValue(true)
  await w.findAll('textarea').at(-1)!.setValue('逐条回查正式评分与措辞')
  vi.mocked(api).mockResolvedValue({...report(),phase:'reviewed',revision:2})
  await review.trigger('click');await flushPromises()
  expect(api).toHaveBeenCalledWith('diagnostic-reports/1/action/','POST',expect.objectContaining({action:'review',expected_revision:1,checked_point_ids:[3]}))
  expect(w.text()).toContain('发布给该学生');w.unmount()
 })
 it('shows students the published version without teacher controls or settings calls',async()=>{
  vi.mocked(api).mockResolvedValue({items:[{...report(),status:'published',phase:'published'}],next_page:null})
  const w=mount(DiagnosticWorkspace,{props:{courseId:6,isTeacher:false}});await flushPromises()
  expect(w.text()).toContain('查看同版 PDF');expect(w.text()).not.toContain('生成诊断草稿');expect(w.find('textarea').exists()).toBe(false)
  expect(api).toHaveBeenCalledTimes(1);w.unmount()
 })
 it('handles stale drafts and failures honestly',async()=>{
  vi.mocked(api).mockResolvedValue({items:[{...report(),stale:true,version:null}],next_page:null})
  const w=mount(DiagnosticWorkspace,{props:{courseId:6,isTeacher:false}});await flushPromises()
  expect(w.text()).toContain('旧说明和导出已隐藏');expect(w.text()).not.toContain('查看同版 PDF')
  vi.mocked(api).mockRejectedValue(new Error('课程不可访问'))
  await w.findAll('button').find(b=>b.text()==='刷新报告')!.trigger('click');await flushPromises()
  expect(w.get('[role=alert]').text()).toContain('课程不可访问');w.unmount()
 })
})
