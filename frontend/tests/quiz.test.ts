// @vitest-environment jsdom
import {beforeEach,afterEach,describe,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import QuizWorkspace from '../src/QuizWorkspace.vue'
import {api,protectedObjectUrl} from '../src/api'
vi.mock('../src/api',()=>({api:vi.fn(),openProtected:vi.fn(),protectedObjectUrl:vi.fn()}))
const quiz={id:1,title:'验收测验',status:'published',opens_at:'2026-11-15T00:00:00Z',closes_at:'2026-12-15T00:00:00Z',answers_at:'2026-12-15T00:00:00Z',time_limit_minutes:30,max_attempts:2,grades_published:false,revision:1}
const a={id:4,student_id:9,quiz_id:1,number:1,status:'in_progress',paper:[{id:7,kind:'blank',body:'填写 $x^2$ 的导数',options:[],score:'10',points:[],revision:1}],answers:{},answer_revision:0,saved_at:null,deadline:'2026-12-15T00:00:00Z',server_now:'2026-11-15T00:00:00Z',grading_status:'pending',submission_basis:''}
beforeEach(()=>{vi.clearAllMocks();vi.mocked(api).mockImplementation(async(path,method,data)=>{
  if(path==='courses/1/quizzes/')return [quiz]
  if(path.includes('forum/points/'))return []
  if(path.includes('/questions/?')||path.includes('/question-groups/?'))return {items:[],next_page:null}
  if(path==='quizzes/1/attempts/')return {...a}
  if(path.includes('attempts/?'))return {items:[],next_page:null}
  if(path==='quiz-attempts/4/answers/')return {answer_revision:1,saved_at:'2026-11-15T00:01:00Z'}
  if(path==='quiz-attempts/4/submit/')return {...a,status:'submitted',answers:{7:'2x'},grading_status:'finalized'}
  return {}
})})
afterEach(()=>vi.useRealTimers())
async function start(){const w=mount(QuizWorkspace,{props:{courseId:1,isTeacher:false}});await flushPromises();await w.findAll('button').find(b=>b.text().includes('验收测验'))!.trigger('click');await flushPromises();await w.findAll('button').find(b=>b.text()==='开始 / 恢复作答')!.trigger('click');await flushPromises();return w}
describe('quiz saves and grading privacy',()=>{
  it('restores the parent quiz of a linked attempt and returns to its answer list',async()=>{
    const original=vi.mocked(api).getMockImplementation()!
    vi.mocked(api).mockImplementation(async(path,...args)=>path==='quiz-attempts/4/'?{...a,status:'submitted'}:original(path,...args))
    const w=mount(QuizWorkspace,{props:{courseId:1,isTeacher:false,initialAttemptId:4}});await flushPromises()
    expect(w.text()).toContain('答卷回顾')
    await w.findAll('button').find(b=>b.text()==='← 返回答卷列表')!.trigger('click');await flushPromises()
    expect(w.text()).toContain('验收测验')
    expect(w.text()).not.toContain("Cannot read properties")
    expect(api).toHaveBeenCalledWith('quizzes/1/attempts/?page=1')
    expect(w.emitted('attemptChange')?.at(-1)).toEqual([undefined]);w.unmount()
  })
  it('discards a linked attempt response received after navigating back to the list',async()=>{
    const original=vi.mocked(api).getMockImplementation()!
    let finish!:(value:unknown)=>void
    vi.mocked(api).mockImplementation(async(path,...args)=>path==='quiz-attempts/4/'?new Promise(resolve=>finish=resolve):original(path,...args))
    const w=mount(QuizWorkspace,{props:{courseId:1,isTeacher:false,initialAttemptId:4}});await flushPromises()
    await w.setProps({initialAttemptId:undefined});finish({...a,status:'submitted'});await flushPromises()
    expect(w.text()).not.toContain('答卷回顾')
    expect(w.emitted('attemptChange')).toBeUndefined();w.unmount()
  })
  it('renders math and saves the server answer revision before submission',async()=>{
    const w=await start();expect(w.find('.katex').exists()).toBe(true)
    await w.get('input[placeholder="填写答案"]').setValue('2x')
    await w.findAll('button').find(b=>b.text()==='保存并交卷')!.trigger('click');await flushPromises();await w.findAll('button').find(b=>b.text()==='确认保存并交卷')!.trigger('click');await flushPromises()
    expect(api).toHaveBeenCalledWith('quiz-attempts/4/answers/','PUT',expect.objectContaining({answers:{7:'2x'},expected_revision:0,key:expect.any(String)}))
    expect(api).toHaveBeenCalledWith('quiz-attempts/4/submit/','POST',{})
    expect(w.text()).toContain('分数尚未公开');w.unmount()
  })
  it('keeps dirty answers and refuses submission when save conflicts',async()=>{
    const w=await start()
    const original=vi.mocked(api).getMockImplementation()!
    vi.mocked(api).mockImplementation(async(path,...args)=>{if(path.includes('/answers/'))throw new Error('答案版本冲突');return original(path,...args)})
    await w.get('input[placeholder="填写答案"]').setValue('local')
    await w.findAll('button').find(b=>b.text()==='保存并交卷')!.trigger('click');await flushPromises();await w.findAll('button').find(b=>b.text()==='确认保存并交卷')!.trigger('click');await flushPromises()
    expect(w.text()).toContain('仍有未保存答案')
    expect(w.get('input[placeholder="填写答案"]').element.value).toBe('local')
    expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/submit/'))).toBe(false);w.unmount()
  })
  it('reports empty and failed loading states',async()=>{
    vi.mocked(api).mockRejectedValue(new Error('服务不可用'))
    const w=mount(QuizWorkspace,{props:{courseId:1,isTeacher:false}});expect(w.text()).toContain('正在加载');await flushPromises();expect(w.get('[role=alert]').text()).toContain('服务不可用');w.unmount()
  })
})

describe('teacher question bank import',()=>{
  async function teacher(){
    const w=mount(QuizWorkspace,{props:{courseId:1,isTeacher:true}});await flushPromises()
    await w.findAll('button').find(b=>b.text()==='管理题库')!.trigger('click');await flushPromises()
    return w
  }
  it('downloads a protected template, blocks invalid rows, then imports and reloads the bank',async()=>{
    vi.mocked(protectedObjectUrl).mockResolvedValue('blob:template')
    const w=await teacher()
    const templateButton=w.findAll('button').find(b=>b.text()==='下载 Excel 模板')!
    await templateButton.trigger('click');await flushPromises()
    expect(protectedObjectUrl).toHaveBeenCalledWith('/api/question-import-template/xlsx/')
    const file=new File(['question-bank'], 'questions.xlsx')
    const input=w.get('#question-import-file')
    Object.defineProperty(input.element,'files',{value:[file],configurable:true})
    vi.mocked(api).mockImplementation(async(path,method,data)=>{
      if(path==='courses/1/questions/import/preview/')return {filename:file.name,total:2,valid_count:1,can_import:false,errors:[{row:3,message:'分值无效'}],questions:[]}
      return {}
    })
    await input.trigger('change');await flushPromises()
    expect(w.text()).toContain('分值无效')
    expect(w.findAll('button').find(b=>b.text().includes('原子导入'))?.attributes('disabled')).toBeDefined()
    expect(vi.mocked(api).mock.calls.some(([path])=>path==='courses/1/questions/import/commit/')).toBe(false)

    vi.mocked(api).mockImplementation(async(path,method,data)=>{
      if(path==='courses/1/questions/import/preview/')return {filename:file.name,total:1,valid_count:1,can_import:true,errors:[],questions:[{row:2,kind:'single',body:'1+1?',options:['1','2'],answer:{values:['1']},score:'5',points:['代数']}]}
      if(path==='courses/1/questions/import/commit/')return {imported_count:1,replayed:false}
      if(path.startsWith('courses/1/questions/?page=1'))return {items:[],next_page:null}
      return {}
    })
    Object.defineProperty(input.element,'files',{value:[file],configurable:true})
    await input.trigger('change');await flushPromises()
    const commit=w.findAll('button').find(b=>b.text().includes('原子导入'))!
    expect(commit.attributes('disabled')).toBeUndefined()
    await commit.trigger('click');await flushPromises()
    const call=vi.mocked(api).mock.calls.find(([path])=>path==='courses/1/questions/import/commit/')!
    expect(call[1]).toBe('POST');expect(call[2]).toBeInstanceOf(FormData)
    expect(w.text()).toContain('已导入 1 道题')
    expect(vi.mocked(api).mock.calls.some(([path])=>path.startsWith('courses/1/questions/?page=1'))).toBe(true)
    w.unmount()
  })
})

it('uses one cart path and applies assembly scores without changing bank records',async()=>{
 const original=vi.mocked(api).getMockImplementation()!
 vi.mocked(api).mockImplementation(async(path,...args)=>path.includes('/questions/?')?{items:[{id:7,kind:'short',body:'解释导数',options:[],answer:{values:[]},points:[],revision:1,score:null}],next_page:null}:original(path,...args))
 const w=mount(QuizWorkspace,{props:{courseId:1,isTeacher:true,initialView:'bank'}});await flushPromises()
 expect(w.text()).not.toContain('选此题组卷')
 await w.findAll('button').find(b=>b.text()==='加入选题篮')!.trigger('click')
 await w.findAll('button').find(b=>b.text()==='用选题篮创建测验')!.trigger('click');await flushPromises()
 expect(w.text()).toContain('1 题缺少参考答案')
 await w.get('input[type=number]').setValue('7.25')
 await w.findAll('button').find(b=>b.text()==='应用到全卷')!.trigger('click')
 expect(w.text()).toContain('全卷 7.25 分')
 expect(vi.mocked(api).mock.calls.some(c=>c[1]==='PUT')).toBe(false)
 w.unmount()
})

it('recovers a per-account assembly draft and reloads current question content',async()=>{
 sessionStorage.clear()
 const original=vi.mocked(api).getMockImplementation()!
 vi.mocked(api).mockImplementation(async(path,...args)=>path.includes('/questions/?')?{items:[{id:7,kind:'short',body:'当前题干',options:[],answer:{values:[]},points:[],revision:2,score:null}],next_page:null}:original(path,...args))
 sessionStorage.setItem('campusclaw.assembly.22.1',JSON.stringify({version:1,cart:[{key:'q7',ids:[7]}],fixedIds:[7],fixedScores:{7:8.5},title:'恢复测验',minutes:20,maxAttempts:2}))
 const w=mount(QuizWorkspace,{props:{courseId:1,isTeacher:true,ownerId:22,initialView:'bank'}});await flushPromises()
 await w.findAll('button').find(b=>b.text()==='恢复组卷草稿')!.trigger('click');await flushPromises()
 expect(w.text()).toContain('当前题干');expect(w.text()).toContain('全卷 8.50 分')
 expect(w.get('input[maxlength="200"]').element.value).toBe('恢复测验')
 expect(sessionStorage.getItem('campusclaw.assembly.22.1')).not.toContain('当前题干')
 w.unmount()
 const peer=mount(QuizWorkspace,{props:{courseId:1,isTeacher:true,ownerId:23,initialView:'bank'}});await flushPromises()
 expect(peer.text()).not.toContain('恢复组卷草稿');peer.unmount();sessionStorage.clear()
})

it('rejects unavailable questions during draft recovery without dropping the saved draft',async()=>{
 sessionStorage.setItem('campusclaw.assembly.22.1',JSON.stringify({version:1,cart:[{key:'q999',ids:[999]}],fixedIds:[]}))
 const w=mount(QuizWorkspace,{props:{courseId:1,isTeacher:true,ownerId:22,initialView:'bank'}});await flushPromises()
 await w.findAll('button').find(b=>b.text()==='恢复组卷草稿')!.trigger('click');await flushPromises()
 expect(w.text()).toContain('已停用或不可访问');expect(sessionStorage.getItem('campusclaw.assembly.22.1')).not.toBeNull()
 w.unmount();sessionStorage.clear()
})

it('applies bank filters together and preserves applied filters when paging',async()=>{
  const original=vi.mocked(api).getMockImplementation()!
  vi.mocked(api).mockImplementation(async(path,...args)=>path.includes('/questions/?')?{items:[],next_page:path.includes('page=1')?2:null}:original(path,...args))
  const w=mount(QuizWorkspace,{props:{courseId:1,isTeacher:true,initialView:'bank'}});await flushPromises()
  const filterForm=w.findAll('form').find(f=>f.text().includes('搜索题库'))!
  const selects=filterForm.findAll('select')
  await selects[0].setValue('short');await selects[2].setValue('missing');await selects[3].setValue('true')
  await filterForm.trigger('submit');await flushPromises()
  expect(api).toHaveBeenLastCalledWith('courses/1/questions/?page=1&q=&kind=short&point_id=&answer_state=missing&active=true')
  await selects[0].setValue('single')
  await w.findAll('button').find(b=>b.text()==='更多题目')!.trigger('click');await flushPromises()
  expect(api).toHaveBeenLastCalledWith('courses/1/questions/?page=2&q=&kind=short&point_id=&answer_state=missing&active=true')
  await w.findAll('button').find(b=>b.text()==='重置筛选')!.trigger('click');await flushPromises()
  expect(api).toHaveBeenLastCalledWith('courses/1/questions/?page=1&q=&kind=&point_id=&answer_state=&active=')
  expect(w.text()).toContain('没有符合条件的题目');w.unmount()
})

it('keeps successful paging filters after a failed search',async()=>{
  const original=vi.mocked(api).getMockImplementation()!
  vi.mocked(api).mockImplementation(async(path,...args)=>{
    if(path.includes('/questions/?')){if(path.includes('answer_state=missing'))throw new Error('暂时失败');return {items:[],next_page:2}}
    return original(path,...args)
  })
  const w=mount(QuizWorkspace,{props:{courseId:1,isTeacher:true,initialView:'bank'}});await flushPromises()
  const form=w.findAll('form').find(f=>f.text().includes('搜索题库'))!
  await form.findAll('select')[2].setValue('missing');await form.trigger('submit');await flushPromises()
  expect(w.text()).toContain('暂时失败')
  await w.findAll('button').find(b=>b.text()==='更多题目')!.trigger('click');await flushPromises()
  expect(api).toHaveBeenLastCalledWith('courses/1/questions/?page=2&q=&kind=&point_id=&answer_state=&active=')
  w.unmount()
})

it('sends per-type scores and the selected knowledge point when creating a random quiz',async()=>{
  const original=vi.mocked(api).getMockImplementation()!
  vi.mocked(api).mockImplementation(async(path,...args)=>
    path.includes('forum/points/')?[{id:5,name:'积分'}]:original(path,...args))
  const w=mount(QuizWorkspace,{props:{courseId:1,isTeacher:true}})
  await flushPromises()
  await w.findAll('button').find(button=>button.text()==='创建测验')!.trigger('click')
  const form=w.get('form')
  const input=(label:string)=>form.findAll('label').find(item=>item.text().startsWith(label))!.get('input')
  await input('测验标题').setValue('知识点随机测验')
  await input('开放时间').setValue('2026-11-28T10:00')
  await input('关闭时间').setValue('2026-11-28T11:00')
  await input('答案解析统一公布时间').setValue('2026-11-28T11:00')
  await form.get('select').setValue('5')
  await input('判断题数量').setValue('2')
  await input('判断每题分值').setValue('7.5')
  await form.trigger('submit')
  await flushPromises()
  const request=vi.mocked(api).mock.calls.find(([path,method])=>path==='courses/1/quizzes/'&&method==='POST')
  expect(request?.[2]).toEqual(expect.objectContaining({
    rules:expect.arrayContaining([{kind:'boolean',count:2,score:'7.5',point_id:5}])
  }))
  w.unmount()
})
