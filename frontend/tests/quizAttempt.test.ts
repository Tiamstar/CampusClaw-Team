// @vitest-environment jsdom
import {describe,it,expect,vi} from 'vitest'
import {mount} from '@vue/test-utils'
import QuizAttemptPanel from '../src/QuizAttemptPanel.vue'
vi.mock('../src/api',()=>({api:vi.fn(),openProtected:vi.fn(),protectedObjectUrl:vi.fn()}))
const paper=[{id:10,kind:'single',body:'Choose $x^2$',options:['one','two'],score:'3',answer:{values:['0']}},{id:20,kind:'short',body:'Explain',options:[],score:'7',answer:{values:[]}}]
function props(teacher=false){return {attempt:{id:2,number:1,status:teacher?'submitted':'in_progress',paper,answers:{10:'0',20:{text:'steps',image_ids:[]}},grading_status:'awaiting_review'},isTeacher:teacher,answers:{10:'0',20:{text:'steps',image_ids:[]}},scores:{10:'3',20:''},feedback:{},reason:'',remaining:120,saveState:'已保存到服务器',dirty:false,saving:false,busy:false,aiBusy:false,aiStatus:'',aiElapsed:0,aiItems:[] as any[],aiReady:false,error:'',notice:'',suggestions:[]}}
describe('dedicated quiz workspace',()=>{
 it('navigates questions and asks for submission confirmation with unanswered count',async()=>{
  const w=mount(QuizAttemptPanel,{props:props()});expect(w.find('.katex').exists()).toBe(true)
  await w.get('button[aria-label="第 2 题"]').trigger('click');expect(w.get('textarea').element.value).toBe('steps')
  await w.findAll('button').find(b=>b.text()==='保存并交卷')!.trigger('click');expect(w.find('[role=dialog]').text()).toContain('已填写 2 题')
  expect(w.emitted('submit')).toBeUndefined();await w.findAll('button').find(b=>b.text()==='确认保存并交卷')!.trigger('click');expect(w.emitted('submit')).toHaveLength(1);w.unmount()
 })
 it('shows incremental suggestions but allows adoption only on successful completion',async()=>{
  const p=props(true);p.aiBusy=true;p.aiItems=[{question_id:20,score:'5.5',feedback:'实际步骤需要补充',needs_reference:true}]
  const w=mount(QuizAttemptPanel,{props:p});await w.get('button[aria-label="第 2 题"]').trigger('click')
  let adopt=w.findAll('button').find(b=>b.text()==='采纳本题建议到评分草稿')!;expect(adopt.attributes('disabled')).toBeDefined();expect(w.text()).toContain('缺少参考答案')
  await w.setProps({aiBusy:false,aiReady:true});adopt=w.findAll('button').find(b=>b.text()==='采纳本题建议到评分草稿')!;await adopt.trigger('click');expect(w.emitted('adopt')).toEqual([[20]]);expect(w.emitted('review')).toBeUndefined();w.unmount()
 })
})

it('briefly confirms a successful save without showing success on failure',async()=>{
 vi.useFakeTimers()
 const w=mount(QuizAttemptPanel,{props:{...props(),saveState:'正在保存…'}})
 await w.setProps({saveState:'已保存到服务器'})
 expect(w.find('.toast-stack').text()).toContain('答案已保存')
 vi.advanceTimersByTime(2000);await w.vm.$nextTick()
 expect(w.find('.toast-stack').text()).not.toContain('答案已保存')
 await w.setProps({saveState:'保存失败：网络中断'})
 expect(w.find('.toast-stack').text()).not.toContain('答案已保存')
 w.unmount();vi.useRealTimers()
})
