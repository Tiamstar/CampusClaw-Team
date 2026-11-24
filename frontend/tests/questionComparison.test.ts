// @vitest-environment jsdom
import {it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import QuestionComparison from '../src/QuestionComparison.vue'
import {api,streamAgent} from '../src/api'
import {hasUnsavedReviewNotes} from '../src/unsavedReviewNotes'
vi.mock('../src/api',()=>({api:vi.fn(),streamAgent:vi.fn(),openProtected:vi.fn()}))
it('compares answers, retains a rejected grade and saves only the selected question',async()=>{
 const response={quiz_title:'测验',question:{id:7,kind:'short',body:'求导',score:'10',answer:{values:[]},options:[]},questions:[{id:7,kind:'short',score:'10'},{id:8,kind:'short',score:'10'}],items:[{attempt_id:3,student_name:'甲',number:1,answer:{text:'学生推导',image_ids:[12]},score:null,feedback:'',grade_revision:1,grading_status:'awaiting_review'}],next_page:null}
 vi.mocked(api).mockResolvedValueOnce(response)
 const w=mount(QuestionComparison,{props:{attemptId:3}});await flushPromises()
 expect(w.text()).toContain('学生推导');expect(w.text()).toContain('查看手写图片 1')
 expect(hasUnsavedReviewNotes()).toBe(false)
 await w.get('input[type=number]').setValue('8')
 await w.get('input[maxlength="500"]').setValue('核对步骤')
 await w.get('textarea').setValue('部分正确')
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(false)
 await w.findAll('button').find(b=>b.text()==='第 2 题')!.trigger('click')
 expect(api).toHaveBeenCalledTimes(1)
 vi.mocked(api).mockRejectedValueOnce(new Error('版本冲突，请刷新'))
 await w.get('form').trigger('submit');await flushPromises()
 expect(w.get('[role=alert]').text()).toContain('版本冲突')
 expect((w.get('input[type=number]').element as HTMLInputElement).value).toBe('8')
 vi.mocked(api).mockResolvedValueOnce({score:'8.00',feedback:'部分正确',grade_revision:2,grading_status:'awaiting_review'})
 await w.get('form').trigger('submit');await flushPromises()
 expect(api).toHaveBeenLastCalledWith('quiz-attempts/3/questions/7/review/','POST',{score:'8',feedback:'部分正确',reason:'核对步骤',expected_revision:1})
 expect(w.text()).toContain('本题评分已保存');expect(hasUnsavedReviewNotes()).toBe(false)
 expect(w.emitted('saved')).toHaveLength(1)
 w.unmount();confirm.mockRestore()
})

it('adopts only a completed batch suggestion and invalidates it after formal save',async()=>{
 vi.mocked(api).mockReset();vi.mocked(streamAgent).mockReset()
 let finish!:()=>void
 const response={quiz_title:'测验',question:{id:7,kind:'short',body:'求导',score:'10',answer:{values:['参考']},options:[]},questions:[{id:7,kind:'short',score:'10'}],items:[{attempt_id:3,student_name:'甲',number:1,answer:{text:'推导'},score:null,feedback:'',grade_revision:1,grading_status:'awaiting_review'}],next_page:null}
 vi.mocked(api).mockResolvedValueOnce(response).mockResolvedValueOnce([])
 const item={question_id:7,score:'6',feedback:'建议保留步骤分',needs_reference:false}
 vi.mocked(streamAgent).mockImplementation(async(_p,_d,h)=>{
  h.onEvent('item',item)
  await new Promise<void>(resolve=>finish=resolve)
  h.onEvent('complete',{grade_revision:1,items:[item]})
 })
 const w=mount(QuestionComparison,{props:{attemptId:3}});await flushPromises()
 await w.get('textarea').setValue('教师自己的评语')
 await w.findAll('button').find(b=>b.text()==='评阅本页答卷')!.trigger('click');await flushPromises()
 expect(w.text()).not.toContain('核对后采用本题建议')
 expect((w.get('textarea').element as HTMLTextAreaElement).value).toBe('教师自己的评语')
 expect(w.get('fieldset').attributes()).toHaveProperty('disabled')
 finish();await flushPromises()
 expect((w.get('textarea').element as HTMLTextAreaElement).value).toBe('教师自己的评语')
 await w.findAll('button').find(b=>b.text()==='核对后采用本题建议')!.trigger('click')
 expect((w.get('input[type=number]').element as HTMLInputElement).value).toBe('6')
 expect((w.get('textarea').element as HTMLTextAreaElement).value).toBe('建议保留步骤分')
 expect(vi.mocked(api).mock.calls.every(c=>c.length===1)).toBe(true)
 vi.mocked(api).mockResolvedValueOnce({score:'6.00',feedback:item.feedback,grade_revision:2,grading_status:'finalized'})
 await w.get('form').trigger('submit');await flushPromises()
 expect(w.text()).not.toContain('核对后采用本题建议')
 expect(w.text()).toContain('本题评分已保存')
 expect(hasUnsavedReviewNotes()).toBe(false);w.unmount()
})

it('retries the failed target question without silently reloading the previous one',async()=>{
 vi.mocked(api).mockReset()
 const response={quiz_title:'测验',question:{id:7,kind:'short',body:'第一题',score:'10',answer:{values:[]},options:[]},questions:[{id:7},{id:8}],items:[],next_page:null}
 vi.mocked(api).mockResolvedValueOnce(response).mockRejectedValueOnce(new Error('网络中断')).mockResolvedValueOnce({...response,question:{...response.question,id:8,body:'第二题'}})
 const w=mount(QuestionComparison,{props:{attemptId:3}});await flushPromises()
 await w.findAll('button').find(b=>b.text()==='第 2 题')!.trigger('click');await flushPromises()
 expect(w.get('[role=alert]').text()).toContain('网络中断')
 await w.findAll('button').find(b=>b.text()==='重新加载')!.trigger('click');await flushPromises()
 expect(api).toHaveBeenLastCalledWith('quiz-attempts/3/comparison/?page=1&question_id=8')
 expect(w.text()).toContain('第二题');w.unmount()
})
it('shows access loss as a blocking panel with a return action',async()=>{
 vi.mocked(api).mockReset();vi.mocked(api).mockRejectedValueOnce(Object.assign(new Error('任课关系已变更'),{status:403}))
 const w=mount(QuestionComparison,{props:{attemptId:3}});await flushPromises()
 expect(w.get('[role=alert]').text()).toContain('当前没有访问权限')
 expect(w.text()).not.toContain('重新加载')
 await w.findAll('button').find(b=>b.text()==='返回列表')!.trigger('click')
 expect(w.emitted('back')).toHaveLength(1);w.unmount()
})
