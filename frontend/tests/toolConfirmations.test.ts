// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ToolConfirmations from '../src/ToolConfirmations.vue'
import AgentResponse from '../src/AgentResponse.vue'
import { api } from '../src/api'
vi.mock('../src/api',()=>({api:vi.fn()}))
afterEach(()=>vi.resetAllMocks())
const row={id:'fixture',tool_name:'mcp_hint',arguments:{text:'<img src=x onerror=alert(1)>'},status:'pending',expires_at:'2099-01-01T00:00:00Z',result:{},error:'',uncertain:false}
it('shows escaped complete arguments and never approves on load; explicit click sends only action',async()=>{
  vi.mocked(api).mockResolvedValueOnce([row] as any).mockResolvedValueOnce({...row,status:'succeeded'} as any).mockResolvedValueOnce([{...row,status:'succeeded',result:{answer:42}}] as any)
  const view=mount(ToolConfirmations,{props:{threadId:1}});await flushPromises()
  expect(api).toHaveBeenCalledTimes(1);expect(view.find('img').exists()).toBe(false)
  expect(view.get('pre').text()).toContain(row.arguments.text)
  await view.get('.primary').trigger('click');await flushPromises()
  expect(api).toHaveBeenNthCalledWith(2,'agent/threads/1/confirmations/fixture/','POST',{action:'confirm'})
  expect(view.text()).toContain('调用完成');expect(view.text()).toContain('42');expect(view.emitted('done')).toHaveLength(1)
  view.unmount()
})
it('cancels explicitly and reports replay refusal after refreshing server state',async()=>{
  vi.mocked(api).mockResolvedValueOnce([row] as any).mockRejectedValueOnce(new Error('确认已使用')).mockResolvedValueOnce([{...row,status:'rejected'}] as any)
  const view=mount(ToolConfirmations,{props:{threadId:1}});await flushPromises()
  await view.get('.confirmation-actions .secondary').trigger('click');await flushPromises()
  expect(api).toHaveBeenNthCalledWith(2,'agent/threads/1/confirmations/fixture/','POST',{action:'reject'})
  expect(view.text()).toContain('已取消');expect(view.text()).toContain('确认已使用');expect(view.find('.primary').exists()).toBe(false)
  view.unmount()
})
it('disables confirmation during streaming and ignores late results from previous thread',async()=>{
  let resolve!:(value:any)=>void
  vi.mocked(api).mockReturnValueOnce(new Promise(r=>{resolve=r})).mockResolvedValueOnce([{...row,id:'new'}] as any)
  const view=mount(ToolConfirmations,{props:{threadId:1,disabled:true}})
  await view.setProps({threadId:2});await flushPromises();resolve([{...row,id:'old',tool_name:'old private tool'}]);await flushPromises()
  expect(view.text()).not.toContain('old private tool');expect(view.get('.primary').attributes('disabled')).toBeDefined()
  await view.get('.primary').trigger('click');expect(api).toHaveBeenCalledTimes(2)
  view.unmount()
})
it('shows expired and uncertain executions without offering retry',async()=>{
  vi.mocked(api).mockResolvedValue([{...row,status:'expired'},{...row,id:'executing',status:'executing',uncertain:true}] as any)
  const view=mount(ToolConfirmations,{props:{threadId:1}});await flushPromises()
  expect(view.text()).toContain('已过期');expect(view.text()).toContain('系统不会自动重试');expect(view.find('.primary').exists()).toBe(false)
  view.unmount()
})

it('historical pending requests are not labeled as failed execution',()=>{
  const view=mount(AgentResponse,{props:{message:{id:1,role:'assistant',content:'',citations:[],attachments:[],created_at:'',metadata:{tools:[{name:'mcp_hint',status:'pending'}]}}}})
  expect(view.text()).toContain('已请求确认，结果见确认记录');expect(view.text()).not.toContain('未成功');view.unmount()
})
