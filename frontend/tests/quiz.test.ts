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
  if(path==='quizzes/1/attempts/')return {...a}
  if(path.includes('attempts/?'))return {items:[],next_page:null}
  if(path==='quiz-attempts/4/answers/')return {answer_revision:1,saved_at:'2026-11-15T00:01:00Z'}
  if(path==='quiz-attempts/4/submit/')return {...a,status:'submitted',answers:{7:'2x'},grading_status:'finalized'}
  return {}
})})
afterEach(()=>vi.useRealTimers())
async function start(){const w=mount(QuizWorkspace,{props:{courseId:1,isTeacher:false}});await flushPromises();await w.findAll('button').find(b=>b.text().includes('验收测验'))!.trigger('click');await flushPromises();await w.findAll('button').find(b=>b.text()==='开始 / 恢复作答')!.trigger('click');await flushPromises();return w}
describe('quiz saves and grading privacy',()=>{
  it('renders math and saves the server answer revision before submission',async()=>{
    const w=await start();expect(w.find('.katex').exists()).toBe(true)
    await w.get('input[placeholder="填写答案"]').setValue('2x')
    await w.findAll('button').find(b=>b.text()==='保存并交卷')!.trigger('click');await flushPromises()
    expect(api).toHaveBeenCalledWith('quiz-attempts/4/answers/','PUT',expect.objectContaining({answers:{7:'2x'},expected_revision:0,key:expect.any(String)}))
    expect(api).toHaveBeenCalledWith('quiz-attempts/4/submit/','POST',{})
    expect(w.text()).toContain('分数尚未公开');w.unmount()
  })
  it('keeps dirty answers and refuses submission when save conflicts',async()=>{
    const w=await start()
    const original=vi.mocked(api).getMockImplementation()!
    vi.mocked(api).mockImplementation(async(path,...args)=>{if(path.includes('/answers/'))throw new Error('答案版本冲突');return original(path,...args)})
    await w.get('input[placeholder="填写答案"]').setValue('local')
    await w.findAll('button').find(b=>b.text()==='保存并交卷')!.trigger('click');await flushPromises()
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
      if(path==='courses/1/questions/?page=1')return {items:[],next_page:null}
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
    expect(vi.mocked(api).mock.calls.some(([path])=>path==='courses/1/questions/?page=1')).toBe(true)
    w.unmount()
  })
})
