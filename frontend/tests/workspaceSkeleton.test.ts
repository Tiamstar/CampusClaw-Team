// @vitest-environment jsdom
import {it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import LearningWorkspace from '../src/LearningWorkspace.vue'
import {api} from '../src/api'
vi.mock('../src/api',()=>({api:vi.fn()}))
it('shows loading placeholder until response and removes it on failure',async()=>{
 let reject:(e:Error)=>void=()=>{}
 vi.mocked(api).mockImplementation(()=>new Promise((_resolve,r)=>reject=r))
 const w=mount(LearningWorkspace,{props:{courseId:6,isTeacher:false}})
 await w.vm.$nextTick()
 expect(w.find('.workspace-skeleton').exists()).toBe(true)
 expect(w.text()).not.toContain('当前课程无可见学生记录')
 reject(new Error('服务暂不可用'));await flushPromises()
 expect(w.find('.workspace-skeleton').exists()).toBe(false)
 expect(w.get('[role=alert]').text()).toContain('服务暂不可用');w.unmount()
})
