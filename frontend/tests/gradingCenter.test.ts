// @vitest-environment jsdom
import {it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import GradingCenter from '../src/GradingCenter.vue'
import {api} from '../src/api'
vi.mock('../src/api',()=>({api:vi.fn()}))
it('opens the exact student assignment and offers retry after failure',async()=>{
 const item={version_id:9,version_number:2,student_id:4,student_name:'同学甲',assignment_id:8,assignment_title:'函数作业',course_id:6,course_name:'课程甲',submitted_at:'2026-11-18T00:00:00Z',status:'submitted'}
 vi.mocked(api).mockResolvedValueOnce({items:[item],next_page:null})
 const w=mount(GradingCenter);await flushPromises()
 await w.findAll('button').find(b=>b.text()==='批改此作业')!.trigger('click')
 expect(w.emitted('open')).toEqual([[item]])
 vi.mocked(api).mockRejectedValueOnce(new Error('网络失败'))
 await w.findAll('button').find(b=>b.text()==='刷新待批改')!.trigger('click');await flushPromises()
 expect(w.get('[role=alert]').text()).toBe('网络失败')
 expect(w.text()).not.toContain('暂无待批改作业');w.unmount()
})

it('loads quiz submissions independently and emits the attempt target',async()=>{
 const item={kind:'quiz',attempt_id:17,version_id:17,version_number:2,student_id:4,student_name:'甲',assignment_title:'测验甲',course_id:6,course_name:'课程甲',submitted_at:'2026-11-18T00:00:00Z',status:'submitted'}
 vi.mocked(api).mockResolvedValueOnce({items:[],next_page:null}).mockResolvedValueOnce({items:[item],next_page:null})
 const w=mount(GradingCenter);await flushPromises()
 await w.findAll('button').find(b=>b.text()==='测验待批改')!.trigger('click');await flushPromises()
 expect(api).toHaveBeenLastCalledWith('grading-queue/?page=1&kind=quiz')
 await w.findAll('button').find(b=>b.text()==='批改此答卷')!.trigger('click')
 expect(w.emitted('open')).toEqual([[item]]);w.unmount()
})
