// @vitest-environment jsdom
import { describe,it,expect,vi,beforeEach } from 'vitest'
import { mount,flushPromises } from '@vue/test-utils'
import ForumWorkspace from '../src/ForumWorkspace.vue'
import { api } from '../src/api'
import securityCases from '../../apitest/cases/security-negative.json'
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
  it('shows actionable safe draft failure without a publish control',async()=>{
    const original=vi.mocked(api).getMockImplementation()!
    vi.mocked(api).mockImplementation(async(path,method,...rest)=>{
      if(path.includes('drafts/'))return {items:[{id:3,status:'failed',body:'',citations:[],model:'',skill_version:'v1',
        error_code:'citation_labels',error:'回答的引用标记与所选资料不一致，已阻止该草稿；请人工核对来源。'}],next_page:null}
      return original(path,method,...rest)
    })
    const w=mount(ForumWorkspace,{props:{courseId:1,isTeacher:true}});await flushPromises()
    await w.get('.forum-post').trigger('click');await flushPromises()
    expect(w.get('.forum-drafts [role=alert]').text()).toContain('引用标记与所选资料不一致')
    expect(w.text()).toContain('请人工核对来源')
    expect(w.findAll('button').some(b=>b.text()==='确认并公开回复')).toBe(false)
    expect(w.text()).not.toContain('citation_labels')
    w.unmount()
  })
  it('renders the retained XSS corpus safely while preserving formulas and code',async()=>{
    const previous=question.body
    question.body=securityCases.xss.body
    const w=mount(ForumWorkspace,{props:{courseId:1,isTeacher:false}})
    try {
      await flushPromises();await w.get('.forum-post').trigger('click');await flushPromises()
      expect(w.find('script,iframe,svg[onload],[onerror],a[href^="javascript:"]').exists()).toBe(false)
      expect(w.find('.katex').exists()).toBe(true)
      expect(w.find('code').text()).toContain('<script>这段代码应当按原文显示</script>')
      expect(w.text()).toContain('SECURITY-NEGATIVE-XSS')
    } finally {question.body=previous;w.unmount()}
  })
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

it('allows the question author to resolve using a specific reply and reopen with revision',async()=>{
 const original=vi.mocked(api).getMockImplementation()!
 vi.mocked(api).mockImplementation(async(path,method,...rest)=>{
  if(path==='forum/posts/1/'&&method==='PATCH')return {...question,is_mine:true,resolved_reply_id:8,revision:1}
  if(path==='forum/posts/1/')return {...question,is_mine:true,revision:0}
  if(path.includes('/replies/'))return {items:[{id:8,author:{name:'同学'},body:'回答',citations:[]}],next_page:null}
  return original(path,method,...rest)
 })
 const w=mount(ForumWorkspace,{props:{courseId:1,isTeacher:false}});await flushPromises();await w.get('.forum-post').trigger('click');await flushPromises()
 await w.findAll('button').find(b=>b.text()==='此回复解决了问题')!.trigger('click');await flushPromises()
 expect(api).toHaveBeenCalledWith('forum/posts/1/','PATCH',{resolved_reply_id:8,expected_revision:0})
 expect(w.text()).toContain('已采纳为解决方案')
 await w.findAll('button').find(b=>b.text()==='重新打开讨论')!.trigger('click');await flushPromises()
 expect(api).toHaveBeenCalledWith('forum/posts/1/','PATCH',{resolved_reply_id:null,expected_revision:1})
 w.unmount()
})

it('automatically checks similar discussions, preserves the question while inspecting and requires acknowledgement',async()=>{
 const original=vi.mocked(api).getMockImplementation()!
 vi.mocked(api).mockImplementation(async(path,...args)=>path.includes('similar/')?{status:'ready',items:[{id:1,title:'已有积分讨论'}]}:original(path,...args))
 const w=mount(ForumWorkspace,{props:{courseId:1,isTeacher:false}});await flushPromises()
 await w.findAll('button').find(b=>b.text()==='发布问题')!.trigger('click')
 vi.useFakeTimers()
 await w.get('.forum-form input:not([type])').setValue('积分有什么含义')
 await w.get('.forum-form textarea').setValue('保留我写的详细问题')
 vi.advanceTimersByTime(500);await flushPromises()
 expect(w.text()).toContain('已有积分讨论')
 expect(w.findAll('button').find(b=>b.text()==='发布问题'&&b.element.closest('form'))!.attributes('disabled')).toBeDefined()
 await w.findAll('button').find(b=>b.text()==='已有积分讨论')!.trigger('click');await flushPromises()
 await w.findAll('button').find(b=>b.text()==='返回继续编辑我的问题')!.trigger('click')
 expect(w.get('.forum-form textarea').element.value).toBe('保留我写的详细问题')
 await w.findAll('label').find(l=>l.text().includes('我已看过上述讨论'))!.get('input').setValue(true)
 expect(w.findAll('button').find(b=>b.text()==='发布问题'&&b.element.closest('form'))!.attributes('disabled')).toBeUndefined()
 await w.get('.forum-form input:not([type])').setValue('新问题')
 expect(w.text()).not.toContain('已有积分讨论')
 w.unmount();expect(vi.getTimerCount()).toBe(0);vi.useRealTimers()
})

it('discards late similarity results after the title changes',async()=>{
 const original=vi.mocked(api).getMockImplementation()!
 let resolveOld:(v:any)=>void=()=>{}
 vi.mocked(api).mockImplementation(async(path,...args)=>path.includes('similar/')?new Promise(r=>{resolveOld=r}):original(path,...args))
 const w=mount(ForumWorkspace,{props:{courseId:1,isTeacher:false}});await flushPromises()
 await w.findAll('button').find(b=>b.text()==='发布问题')!.trigger('click')
 await w.get('.forum-form input:not([type])').setValue('旧标题')
 await w.findAll('button').find(b=>b.text()==='查找相似问题')!.trigger('click')
 await w.get('.forum-form input:not([type])').setValue('新的标题')
 resolveOld({status:'ready',items:[{id:1,title:'过期建议'}]});await flushPromises()
 expect(w.text()).not.toContain('过期建议');w.unmount()
})

it('restores unpublished questions only for the same owner and course',async()=>{
 sessionStorage.clear()
 const w=mount(ForumWorkspace,{props:{courseId:1,isTeacher:false,ownerId:22}});await flushPromises()
 await w.findAll('button').find(b=>b.text()==='发布问题')!.trigger('click')
 await w.get('.forum-form input:not([type])').setValue('保存的问题')
 await w.get('.forum-form textarea').setValue('尚未发布的正文')
 w.unmount()
 const restored=mount(ForumWorkspace,{props:{courseId:1,isTeacher:false,ownerId:22}});await flushPromises()
 await restored.findAll('button').find(b=>b.text()==='发布问题')!.trigger('click')
 expect(restored.get('.forum-form textarea').element.value).toBe('尚未发布的正文');restored.unmount()
 const peer=mount(ForumWorkspace,{props:{courseId:1,isTeacher:false,ownerId:23}});await flushPromises()
 await peer.findAll('button').find(b=>b.text()==='发布问题')!.trigger('click')
 expect(peer.get('.forum-form textarea').element.value).toBe('');peer.unmount();sessionStorage.clear()
})

it('restores edited teacher drafts but never restores publication confirmation',async()=>{
 sessionStorage.clear()
 const w=mount(ForumWorkspace,{props:{courseId:1,isTeacher:true,ownerId:22}});await flushPromises()
 await w.get('.forum-post').trigger('click');await flushPromises()
 await w.get('.forum-drafts textarea').setValue('教师尚未公开的修订')
 await w.get('.forum-drafts input[type=checkbox]').setValue(true);w.unmount()
 const restored=mount(ForumWorkspace,{props:{courseId:1,isTeacher:true,ownerId:22}});await flushPromises()
 await restored.get('.forum-post').trigger('click');await flushPromises()
 expect(restored.get('.forum-drafts textarea').element.value).toBe('教师尚未公开的修订')
 expect(restored.get('.forum-drafts input[type=checkbox]').element.checked).toBe(false)
 restored.unmount();sessionStorage.clear()
})

it('restores a linked post and emits list navigation without stale details',async()=>{
 const w=mount(ForumWorkspace,{props:{courseId:1,isTeacher:false,initialPostId:1}});await flushPromises()
 expect(api).toHaveBeenCalledWith('forum/posts/1/')
 expect(w.find('.forum-post').exists()).toBe(false)
 expect(w.text()).toContain('积分问题')
 await w.findAll('button').find(b=>b.text()==='← 返回讨论列表')!.trigger('click');await flushPromises()
 expect(w.emitted('postChange')?.at(-1)).toEqual([undefined])
 await w.setProps({initialPostId:undefined});await flushPromises()
 expect(w.find('.forum-post').exists()).toBe(true);w.unmount()
})
it('isolates a late linked post response after back navigation',async()=>{
 const original=vi.mocked(api).getMockImplementation()!
 let finish!:(value:unknown)=>void
 vi.mocked(api).mockImplementation(async(path,...args)=>path==='forum/posts/1/'?new Promise(resolve=>finish=resolve):original(path,...args))
 const w=mount(ForumWorkspace,{props:{courseId:1,isTeacher:false,initialPostId:1}});await flushPromises()
 await w.setProps({initialPostId:undefined});finish(question);await flushPromises()
 expect(w.find('.forum-post').exists()).toBe(true)
 expect(w.text()).not.toContain('← 返回讨论列表');w.unmount()
})
it('keeps unavailable linked posts out of the unrelated list and retries exact post',async()=>{
 const original=vi.mocked(api).getMockImplementation()!
 vi.mocked(api).mockImplementation(async(path,...args)=>{if(path==='forum/posts/1/')throw new Error('帖子不可访问');return original(path,...args)})
 const w=mount(ForumWorkspace,{props:{courseId:1,isTeacher:false,initialPostId:1}});await flushPromises()
 expect(w.text()).toContain('帖子不可访问');expect(w.find('.forum-post').exists()).toBe(false)
 vi.mocked(api).mockImplementation(original)
 await w.findAll('button').find(b=>b.text()==='重新读取讨论')!.trigger('click');await flushPromises()
 expect(w.text()).toContain('← 返回讨论列表');expect(w.text()).not.toContain('帖子不可访问');w.unmount()
})
