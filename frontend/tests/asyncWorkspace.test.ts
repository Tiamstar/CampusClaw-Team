// @vitest-environment jsdom
import {it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import {defineComponent,h} from 'vue'
import {asyncWorkspace} from '../src/asyncWorkspace'
it('shows a placeholder while loading then the requested module',async()=>{
 vi.useFakeTimers()
 let resolve:(value:any)=>void=()=>{}
 const component=asyncWorkspace(()=>new Promise(r=>resolve=r))
 const w=mount(defineComponent({setup:()=>()=>h(component)}))
 vi.advanceTimersByTime(150);await flushPromises()
 expect(w.find('.workspace-skeleton').exists()).toBe(true)
 resolve({default:defineComponent({setup:()=>()=>h('p','工作区已加载')})});await flushPromises()
 expect(w.text()).toContain('工作区已加载');expect(w.find('.workspace-skeleton').exists()).toBe(false)
 w.unmount();vi.useRealTimers()
})
it('offers an actionable failure instead of an empty page',async()=>{
 const warn=vi.spyOn(console,'warn').mockImplementation(()=>{})
 const w=mount(defineComponent({setup:()=>()=>h(asyncWorkspace(()=>Promise.reject(new Error('network'))))}))
 await flushPromises();expect(w.get('[role=alert]').text()).toContain('功能页面未能加载');expect(w.text()).toContain('刷新重试')
 w.unmount();warn.mockRestore()
})

it('forwards exposed leave guards through the async wrapper',async()=>{
 const guard=vi.fn(()=>false)
 const inner=defineComponent({setup(_props,{expose}){expose({canLeave:guard});return ()=>h('p','editor')}})
 const component=asyncWorkspace(async()=>({default:inner}))
 const w=mount(defineComponent({components:{component},template:'<component ref="editor"/>'}))
 await flushPromises()
 expect((w.vm.$refs.editor as any).canLeave()).toBe(false);expect(guard).toHaveBeenCalledOnce();w.unmount()
})
