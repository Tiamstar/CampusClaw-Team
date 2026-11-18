// @vitest-environment jsdom
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import ExamWorkspace from '../src/ExamWorkspace.vue'
import QuestionContent from '../src/QuestionContent.vue'
import {api,protectedObjectUrl} from '../src/api'
vi.mock('../src/api',()=>({api:vi.fn(),openProtected:vi.fn(),protectedObjectUrl:vi.fn()}))
const source={id:5,name:'reading.pdf',status:'ready',revision:2,error:'',model:'test',download_url:'/api/exam-sources/5/file/',units:[{id:1,label:'第 1 页',text:'Original passage',asset_ids:[]}],mapping:[],draft:{groups:[{title:'Reading',material:'Shared $x^2$',source_units:[1],questions:[{kind:'single',body:'Question?',options:['One','Two'],answer:{values:[]},explanation:'',source_units:[1]}]}]}}
beforeEach(()=>{vi.clearAllMocks();vi.stubGlobal('confirm',vi.fn(()=>true));vi.mocked(api).mockImplementation(async(path,method,data)=>{
  if(path.includes('exam-sources/?'))return {items:[structuredClone(source)],next_page:null}
  if(path==='exam-sources/5/'&&method==='PUT')return {...structuredClone(source),revision:3,draft:(data as any).draft}
  if(path==='exam-sources/5/'&&method==='POST')return {...structuredClone(source),status:'committed',revision:4,mapping:[{group_id:9,question_id:12,source_units:[1]}]}
  if(path==='exam-sources/5/')return structuredClone(source)
  return {}
})})
afterEach(()=>{vi.unstubAllGlobals();vi.restoreAllMocks()})
async function open(){const wrapper=mount(ExamWorkspace,{props:{courseId:1}});await flushPromises();await wrapper.findAll('button').find(b=>b.text().startsWith('reading.pdf'))!.trigger('click');await flushPromises();return wrapper}
describe('exam source corrections and bank confirmation',()=>{
  it('allows missing answers, does not request bank scores, and saves edits before confirmation',async()=>{
    const w=await open();expect(w.find('input[type=number]').exists()).toBe(false)
    expect(w.text()).toContain('分值在组卷时设置');expect(w.find('.katex').exists()).toBe(true)
    const question=w.findAll('textarea').find(el=>(el.element as HTMLTextAreaElement).value==='Question?')!
    await question.setValue('Corrected question')
    expect(w.text()).toContain('有未保存修改')
    const commit=w.findAll('button').find(b=>b.text()==='确认加入我的题库')!
    expect(commit.attributes('disabled')).toBeDefined()
    await w.get('.exam-confirm input').setValue(true);await commit.trigger('click');await flushPromises()
    const calls=vi.mocked(api).mock.calls.filter(([path,method])=>path==='exam-sources/5/'&&['PUT','POST'].includes(method!))
    expect(calls.map(c=>c[1])).toEqual(['PUT','POST'])
    const payload=calls[0][2] as any;expect(payload.draft.groups[0].questions[0].answer.values).toEqual([])
    expect(payload.draft.groups[0].questions[0].score).toBeUndefined()
    expect(calls[1][2]).toEqual({action:'commit',expected_revision:3,confirmed:true})
    expect(w.text()).toContain('题目 #12');expect(w.emitted('changed')).toHaveLength(1)
    await w.findAll('button').find(b=>b.text().includes('按此原卷创建测验'))!.trigger('click')
    expect(w.emitted('assemble')).toEqual([[[12]]]);w.unmount()
  })
  it('keeps the teacher edits when saving fails and never confirms a failed save',async()=>{
    const w=await open();await w.findAll('textarea').find(el=>(el.element as HTMLTextAreaElement).value==='Question?')!.setValue('Unsaved edit')
    const original=vi.mocked(api).getMockImplementation()!
    vi.mocked(api).mockImplementation((path,method,data)=>method==='PUT'?Promise.reject(new Error('版本冲突')):original(path,method,data))
    await w.get('.exam-confirm input').setValue(true);await w.findAll('button').find(b=>b.text()==='确认加入我的题库')!.trigger('click');await flushPromises()
    expect(w.get('[role=alert]').text()).toContain('版本冲突')
    expect(w.findAll('textarea').some(el=>(el.element as HTMLTextAreaElement).value==='Unsaved edit')).toBe(true)
    expect(vi.mocked(api).mock.calls.some(([,method])=>method==='POST')).toBe(false);w.unmount()
  })
  it('loads only protected assets and releases object URLs after unmount',async()=>{
    vi.mocked(protectedObjectUrl).mockResolvedValue('blob:diagram');const revoke=vi.fn();vi.stubGlobal('URL',Object.assign(URL,{revokeObjectURL:revoke}))
    const w=mount(QuestionContent,{props:{text:'条件 $x^2$ {{asset:17}} <script>alert(1)</script>'}});await flushPromises()
    expect(protectedObjectUrl).toHaveBeenCalledWith('/api/question-assets/17/',expect.any(AbortSignal))
    expect(w.get('img').attributes('src')).toBe('blob:diagram');expect(w.find('script').exists()).toBe(false)
    w.unmount();expect(revoke).toHaveBeenCalledWith('blob:diagram')
  })
  it('edits a committed whole paper using bank revisions and keeps unsaved edits on conflict',async()=>{
    const live={...structuredClone(source),status:'committed',bank_versions:{'12':4},group_versions:{'9':2},mapping:[{group_id:9,question_id:12,source_units:[1]}]}
    vi.mocked(api).mockImplementation(async(path,method)=>{
      if(path.includes('exam-sources/?'))return {items:[live],next_page:null}
      if(method==='PUT')throw new Error('题库内容已更新，请重新读取整卷后再保存')
      return structuredClone(live)
    })
    const w=await open()
    expect(w.text()).toContain('整卷编辑')
    await w.findAll('textarea').find(el=>(el.element as HTMLTextAreaElement).value==='Question?')!.setValue('Changed after import')
    await w.findAll('button').find(b=>b.text()==='保存并同步题库')!.trigger('click');await flushPromises()
    const call=vi.mocked(api).mock.calls.find(([,method])=>method==='PUT')!
    expect(call[2]).toMatchObject({bank_versions:{'12':4},group_versions:{'9':2},expected_revision:2})
    expect(w.get('[role=alert]').text()).toContain('题库内容已更新')
    expect(w.findAll('textarea').some(el=>(el.element as HTMLTextAreaElement).value==='Changed after import')).toBe(true)
    w.unmount()
  })
  it('inserts manually cropped figures into the selected question without requiring a bank score',async()=>{
    const withPage={...structuredClone(source),units:[{id:1,label:'page',text:'',asset_ids:[17]}]}
    const original=vi.mocked(api).getMockImplementation()!
    vi.mocked(api).mockImplementation((path,method,data)=>path==='exam-sources/5/'&&!method?Promise.resolve(withPage):original(path,method,data))
    vi.mocked(protectedObjectUrl).mockResolvedValue('blob:page')
    const w=await open()
    const crop=w.findComponent({name:'PaperImageCropper'})
    crop.vm.$emit('insert','{{asset:91}}');await flushPromises()
    expect(w.findAll('textarea').some(el=>(el.element as HTMLTextAreaElement).value.includes('{{asset:91}}'))).toBe(true)
    expect(w.text()).toContain('有未保存修改');w.unmount()
  })

  it('replaces the selected shared-material image without changing the question',async()=>{
    const withPage={...structuredClone(source),units:[{id:1,label:'page',text:'',asset_ids:[17]}]}
    withPage.draft.groups[0]!.material='Shared {{asset:7}}'
    const original=vi.mocked(api).getMockImplementation()!
    vi.mocked(api).mockImplementation((path,method,data)=>path==='exam-sources/5/'&&!method?Promise.resolve(withPage):original(path,method,data))
    vi.mocked(protectedObjectUrl).mockResolvedValue('blob:page')
    const w=await open()
    await w.get('select[aria-label="裁图插入位置"]').setValue('material')
    await w.get('select[aria-label="插入方式"]').setValue('{{asset:7}}')
    w.findComponent({name:'PaperImageCropper'}).vm.$emit('insert','{{asset:92}}');await flushPromises()
    expect((w.get('textarea').element as HTMLTextAreaElement).value).toBe('Shared {{asset:92}}')
    expect(w.findAll('textarea').some(e=>(e.element as HTMLTextAreaElement).value==='Question?')).toBe(true)
    expect(w.text()).toContain('有未保存修改');w.unmount()
  })
})
