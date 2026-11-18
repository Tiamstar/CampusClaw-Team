// @vitest-environment jsdom
import {describe,it,expect,vi,beforeEach} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import WrongAnswerWorkspace from '../src/WrongAnswerWorkspace.vue'
import {api} from '../src/api'
vi.mock('../src/api',()=>({api:vi.fn()}))
vi.mock('../src/CourseworkAI.vue',()=>({default:{props:['assignment','version','isTeacher'],template:'<div class="fake-ai">错题讲解 <button @click="$emit(\'adopt\')">复习</button></div>',emits:['adopt']}}))
const rows=[{assignment:{id:1,course_id:6,title:'积分作业',max_score:'10'} ,version:{id:3,number:2,submitted_at:'2026-10-01T00:00:00Z',grade:{revision:2,score:'5',feedback:'',published:true,published_at:'2026-11-11',graded_at:'2026-11-11',reviewed_items:[{id:'q1',title:'边界',maximum:'10',score:'5',feedback:'需要检查边界'}]},grade_published:true}}]
beforeEach(()=>{vi.clearAllMocks();vi.mocked(api).mockResolvedValue({results:rows,has_more:false})})
describe('wrong answer review workspace',()=>{
 it('summarizes published item evidence and filters recent records',async()=>{const w=mount(WrongAnswerWorkspace,{props:{courseId:6}});await flushPromises();expect(w.text()).toContain('1 个本页未满分评分项');expect(w.text()).toContain('优先查看：积分作业');expect(w.findAll('.fake-ai')).toHaveLength(1);await w.get('button').trigger('click');expect(w.text()).toContain('错题讲解');w.unmount()})
 it('explains an empty recent filter without changing server data',async()=>{const w=mount(WrongAnswerWorkspace,{props:{courseId:6}});await flushPromises();await w.findAll('button').find(b=>b.text()==='最近30天')!.trigger('click');expect(w.text()).toContain('本页最近30天没有错题记录。');expect(api).toHaveBeenCalledWith('courses/6/wrong-answers/?page=1');w.unmount()})
})
