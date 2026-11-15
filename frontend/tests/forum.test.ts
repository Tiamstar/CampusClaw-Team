// @vitest-environment jsdom
import { describe,it,expect,vi,beforeEach } from 'vitest'
import { mount,flushPromises } from '@vue/test-utils'
import ForumWorkspace from '../src/ForumWorkspace.vue'
import { api } from '../src/api'
vi.mock('../src/api',()=>({api:vi.fn(),openProtected:vi.fn()}))
const question={id:1,title:'积分问题',body:String.raw`如何计算 $\frac{1}{2}$？ <img src=x onerror=alert(1)>`,author:{name:'匿名同学'},anonymous:true,points:[],mentions:[],pinned:false,featured:false,reply_count:0,created_at:'2026-11-15T12:00:00Z'}
beforeEach(()=>{
  vi.clearAllMocks()
  vi.mocked(api).mockImplementation(async(path,method)=>{
    if(path.includes('settings/'))return {draft_enabled:true,wait_hours:24,timezone:'Asia/Shanghai',revision:0}
    if(path.includes('/members/'))return [{id:2,name:'老师',role:'teacher'}]
    if(path.includes('/points/'))return [{id:1,name:'积分'}]
    if(path.includes('/posts/?'))return {items:[question],next_page:null}
    if(path==='forum/posts/1/')return question
    if(path.includes('drafts/'))return {items:[{id:3,status:'awaiting_review',body:'草稿',citations:[],model:'mock',skill_version:'v1'}],next_page:null}
    if(path.includes('similar/'))return {status:'unavailable',items:[]}
    return {items:[],next_page:null}
  })
})
describe('course forum',()=>{
  it('student view renders safe formulas and never requests private drafts',async()=>{
    const w=mount(ForumWorkspace,{props:{courseId:1,isTeacher:false}});await flushPromises()
    await w.get('.forum-post').trigger('click');await flushPromises()
    expect(w.find('.katex').exists()).toBe(true)
    expect(w.find('img').exists()).toBe(false)
    expect(w.text()).toContain('匿名同学')
    expect(w.find('.forum-drafts').exists()).toBe(false)
    expect(vi.mocked(api).mock.calls.some(([p])=>p.includes('drafts/'))).toBe(false)
  })
  it('requires explicit teacher confirmation before publishing an edited draft',async()=>{
    const w=mount(ForumWorkspace,{props:{courseId:1,isTeacher:true}});await flushPromises()
    await w.get('.forum-post').trigger('click');await flushPromises()
    const button=w.findAll('button').find(b=>b.text()==='确认并公开回复')!
    expect(button.attributes('disabled')).toBeDefined()
    await w.get('.forum-drafts textarea').setValue('已核对的回答')
    await w.get('.forum-drafts input[type=checkbox]').setValue(true)
    await button.trigger('click');await flushPromises()
    expect(api).toHaveBeenCalledWith('forum/drafts/3/publish/','POST',{body:'已核对的回答',confirm:true})
  })
  it('similarity failure leaves the post form usable',async()=>{
    const w=mount(ForumWorkspace,{props:{courseId:1,isTeacher:false}});await flushPromises()
    await w.findAll('button').find(b=>b.text()==='发布问题')!.trigger('click')
    await w.get('.forum-form input:not([type])').setValue('积分问题')
    await w.findAll('button').find(b=>b.text()==='查找相似问题')!.trigger('click');await flushPromises()
    expect(w.text()).toContain('相似帖检索暂不可用，仍可发布')
    expect(w.get('.forum-form textarea').exists()).toBe(true)
  })
  it('shows loading and recoverable errors',async()=>{
    vi.mocked(api).mockRejectedValue(new Error('暂不可用'))
    const w=mount(ForumWorkspace,{props:{courseId:1,isTeacher:false}})
    expect(w.text()).toContain('正在加载')
    await flushPromises();expect(w.get('[role=alert]').text()).toContain('暂不可用')
    expect(w.findAll('button').some(b=>b.text()==='搜索')).toBe(true)
  })
})
