// @vitest-environment jsdom
import {beforeEach,describe,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import GraphWorkspace from '../src/GraphWorkspace.vue'
import {api} from '../src/api'
vi.mock('../src/api',()=>({api:vi.fn(),openProtected:vi.fn()}))
const graph={revision:2,learning_version:'1234567890abcdef',window:{},include_unpublished:false,nodes:[{id:3,name:'积分',active:true,revision:1,metric:{mastery:'.6',band:'developing',sample_size:1,evidence:[]}},{id:4,name:'函数',active:true,revision:1,metric:{mastery:null,band:'unknown',sample_size:0,evidence:[]}}],edges:[{id:1,prerequisite_id:4,target_id:3,sources:[]}],resources:[]}
beforeEach(()=>{vi.clearAllMocks();vi.mocked(api).mockImplementation(async path=>path.includes('/resources/')?{materials:[],questions:[],posts:[],my_incomplete_answers:[{attempt_id:7,question_id:8,score:'6',maximum:'10',grade_revision:2}]}:graph)})
describe('graph authorized metrics',()=>{
 it('shows color, unknown, prerequisites and personal evidence without private candidates',async()=>{
  const w=mount(GraphWorkspace,{props:{courseId:1,isTeacher:false}});await flushPromises()
  expect(w.text()).toContain('60.0%');expect(w.text()).toContain('函数 → 积分');expect(w.find('[data-band=unknown]').text()).toContain('未知')
  await w.get('[data-band=developing]').trigger('click');await flushPromises()
  expect(w.text()).toContain('评分 v2');expect(w.text()).not.toContain('生成带出处候选');expect(w.text()).not.toContain('关联题库');w.unmount()
 })
 it('reports loading failures honestly',async()=>{
  vi.mocked(api).mockRejectedValue(new Error('课程不可访问'))
  const w=mount(GraphWorkspace,{props:{courseId:1,isTeacher:false}});await flushPromises()
  expect(w.get('[role=alert]').text()).toContain('课程不可访问');w.unmount()
 })
 it('lets teachers correct candidate names and confirm evidence without exposing JSON editing',async()=>{
  const proposal={nodes:[{key:'n1',name:'候选积分',source_ids:[5]}],edges:[]}
  vi.mocked(api).mockImplementation(async path=>{
   if(path.includes('candidates/'))return {items:[{id:2,status:'awaiting_review',sources:[{chunk_id:5,title:'讲义',current:true,excerpt:'内容'}],proposal,skill:'knowledge-extraction@1.0.0'}],next_page:null}
   if(path.includes('config/'))return {extraction_enabled:true,revision:0}
   if(path.includes('materials/'))return []
   return graph
  })
  const w=mount(GraphWorkspace,{props:{courseId:1,isTeacher:true}});await flushPromises()
  expect(w.find('textarea').exists()).toBe(false)
  await w.get('input[placeholder="请说明校对结果及批准/拒绝原因"]').setValue('已回查讲义')
  const field=w.findAll('input').find(i=>(i.element as HTMLInputElement).value==='候选积分')!
  await field.setValue('定积分')
  await w.findAll('button').find(b=>b.text()==='确认批准入图谱')!.trigger('click');await flushPromises()
  expect(api).toHaveBeenCalledWith('graph/candidates/2/review/','POST',expect.objectContaining({action:'approve',reason:'已回查讲义',expected_revision:2,proposal:{nodes:[{key:'n1',name:'定积分',source_ids:[5]}],edges:[]}}));w.unmount()
 })
})
