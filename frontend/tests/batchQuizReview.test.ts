// @vitest-environment jsdom
import {it,expect,vi} from 'vitest'
import {useBatchQuizReview} from '../src/useBatchQuizReview'
import {api,streamAgent} from '../src/api'
vi.mock('../src/api',()=>({api:vi.fn(),streamAgent:vi.fn()}))
it('restores matching drafts, retries failures and never writes grades',async()=>{
 vi.mocked(api).mockReset();vi.mocked(streamAgent).mockReset()
 const item={question_id:7,score:'5',feedback:'步骤',needs_reference:false}
 vi.mocked(api).mockImplementation(async(path)=>path.includes('/1/')?[{status:'awaiting_review',body:JSON.stringify({answer_encoding_version:2,grade_revision:2,items:[item]})}]:[] as any)
 vi.mocked(streamAgent).mockImplementationOnce(async()=>{throw new Error('服务不可用')}).mockImplementationOnce(async(_p,_d,h)=>{h.onEvent?.('complete',{grade_revision:1,items:[item]})})
 const batch=useBatchQuizReview()
 await batch.run([{attempt_id:1,grade_revision:2},{attempt_id:2,grade_revision:1}])
 expect(batch.reviews.value[1]!.items).toHaveLength(1)
 expect(batch.reviews.value[2]!.error).toBe('服务不可用')
 await batch.run([{attempt_id:2,grade_revision:1}])
 expect(batch.reviews.value[2]!.items).toHaveLength(1)
 expect(batch.busy.value).toBe(false)
 expect(vi.mocked(api).mock.calls.every(c=>c.length===1)).toBe(true)
 expect(vi.mocked(streamAgent).mock.calls.every(c=>c[0].endsWith('/suggestion/'))).toBe(true)
})
it('stops after current, discards incomplete and stale model results',async()=>{
 vi.mocked(api).mockReset();vi.mocked(streamAgent).mockReset();vi.mocked(api).mockResolvedValue([])
 const batch=useBatchQuizReview()
 vi.mocked(streamAgent).mockImplementation(async(_p,_d,h)=>{h.onEvent?.('item',{question_id:7,score:'4',feedback:'partial'});batch.stopAfterCurrent()})
 await batch.run([{attempt_id:1,grade_revision:1},{attempt_id:2,grade_revision:1}])
 expect(streamAgent).toHaveBeenCalledTimes(1)
 expect(batch.reviews.value[1]!.items).toEqual([])
 expect(batch.progress.value).toContain('已停止后续评阅')
 vi.mocked(streamAgent).mockImplementation(async(_p,_d,h)=>{h.onEvent?.('complete',{grade_revision:9,items:[]})})
 await batch.run([{attempt_id:1,grade_revision:1}])
 expect(batch.reviews.value[1]!.error).toContain('评分版本已变化')
})

it('does not launch a model when stopped while loading history',async()=>{
 vi.mocked(api).mockReset();vi.mocked(streamAgent).mockReset()
 let release!:(value:any)=>void
 vi.mocked(api).mockImplementation(()=>new Promise(resolve=>release=resolve))
 const batch=useBatchQuizReview()
 const run=batch.run([{attempt_id:1,grade_revision:1}])
 batch.stopAfterCurrent();release([]);await run
 expect(streamAgent).not.toHaveBeenCalled()
 expect(batch.reviews.value[1]!.ready).toBe(false)
 expect(batch.progress.value).toContain('0 / 1')
})

it('does not recover legacy answer encoding suggestions',async()=>{
 vi.mocked(api).mockReset();vi.mocked(streamAgent).mockReset()
 vi.mocked(api).mockResolvedValue([{status:'awaiting_review',body:JSON.stringify({grade_revision:1,items:[{question_id:7,score:'0',feedback:'old ambiguous'}]})}])
 vi.mocked(streamAgent).mockImplementation(async(_p,_d,h)=>{h.onEvent('complete',{grade_revision:1,items:[{question_id:7,score:'3',feedback:'C=5',needs_reference:true}]})})
 const batch=useBatchQuizReview();await batch.run([{attempt_id:1,grade_revision:1}])
 expect(streamAgent).toHaveBeenCalledTimes(1)
 expect(batch.reviews.value[1]!.items[0]!.feedback).toBe('C=5')
 expect(batch.reviews.value[1]!.ready).toBe(true)
})
