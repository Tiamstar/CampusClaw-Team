// @vitest-environment jsdom
import {it,expect,vi} from 'vitest'
import {mount} from '@vue/test-utils'
import {defineComponent} from 'vue'
import {useToasts} from '../src/useToasts'
it('queues concurrent messages, retains errors and clears timers on unmount',()=>{
 vi.useFakeTimers()
 let state:ReturnType<typeof useToasts>
 const w=mount(defineComponent({setup(){state=useToasts();return ()=>null}}))
 state!.notify('保存成功','success');state!.notify('权限不足','error')
 expect(state!.toasts.value).toHaveLength(2)
 vi.advanceTimersByTime(8000)
 expect(state!.toasts.value.map(t=>t.text)).toEqual(['权限不足'])
 state!.notify('正在处理');state!.notify('正在处理')
 expect(state!.toasts.value).toHaveLength(2)
 state!.dismiss(state!.toasts.value[0].id)
 expect(state!.toasts.value).toHaveLength(1)
 w.unmount();expect(vi.getTimerCount()).toBe(0);vi.useRealTimers()
})
