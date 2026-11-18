// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AssignmentWorkspace from '../src/AssignmentWorkspace.vue'
import FilePreview from '../src/FilePreview.vue'
import { api, protectedText } from '../src/api'
import { confirmReviewNotesLeave, hasUnsavedReviewNotes } from '../src/unsavedReviewNotes'
vi.mock('../src/api',()=>({api:vi.fn(),download:vi.fn(),protectedText:vi.fn(),protectedObjectUrl:vi.fn()}))
afterEach(()=>vi.resetAllMocks())
const assignment={id:1,title:'Homework',description:'Task',max_score:'100',due_at:'2099-01-01T00:00:00Z',allow_late:false,allowed_extensions:[],max_file_size_mb:50,submission_limits:{max_files:10,max_total_bytes:52428800,max_text_length:50000},my_versions:[],submission_status:'unsubmitted'}
it('submits text and multiple files in one request with a retry key',async()=>{
  let submitted:FormData|undefined
  vi.mocked(api).mockImplementation(async(path,method,data)=>{
    if(method==='POST') { submitted=data as FormData; return {} as any }
    return assignment as any
  })
  const view=mount(AssignmentWorkspace,{props:{assignmentId:1,isTeacher:false}}); await flushPromises()
  await view.get('textarea').setValue('My answer')
  const input=view.get('input[type=file]')
  Object.defineProperty(input.element,'files',{value:[new File(['a'],'a.txt'),new File(['b'],'b.txt')]})
  await input.trigger('change'); await view.get('form').trigger('submit'); await flushPromises()
  expect(submitted!.get('text_content')).toBe('My answer')
  expect(submitted!.getAll('files')).toHaveLength(2)
  expect(submitted!.get('submission_key')).toBeTruthy(); view.unmount()
})
it('shows graded but unpublished state without a score',async()=>{
  vi.mocked(api).mockResolvedValue({...assignment,submission_status:'graded',my_versions:[{id:1,number:1,text_content:'answer',submitted_at:'2026-11-05T00:00:00Z',files:[],status:'graded',grade:null}]} as any)
  const view=mount(AssignmentWorkspace,{props:{assignmentId:1,isTeacher:false}}); await flushPromises()
  expect(view.text()).toContain('成绩与评语暂未公开'); expect(view.find('.homework-result').exists()).toBe(false); view.unmount()
})
it('sends explicit grade publication preference and current revision',async()=>{
  const calls:any[]=[]
  vi.mocked(api).mockImplementation(async(path,method,data)=>{
    if(method==='POST'){calls.push({path,data});return {} as any}
    if(path.endsWith('submissions/'))return [{student:{id:2,name:'Student',email:'student@example.test'},status:'submitted',versions:[{id:3,number:1,files:[],status:'submitted',grading_revision:0,grade:null}]}] as any
    return assignment as any
  })
  const view=mount(AssignmentWorkspace,{props:{assignmentId:1,isTeacher:true}}); await flushPromises()
  await view.get('.homework-grade-form input[type=number]').setValue('88');await view.get('.homework-grade-form input[type=checkbox]').setValue(true)
  await view.get('form').trigger('submit');await flushPromises()
  expect(calls[0]).toMatchObject({path:'submission-versions/3/grade/',data:{score:'88',published:true,expected_revision:0}}); view.unmount()
})
it('offers original download when preview parsing fails',async()=>{
  vi.mocked(protectedText).mockRejectedValue(new Error('无法解析文件内容'))
  const view=mount(FilePreview,{props:{file:{id:1,name:'broken.docx',size:10,created_at:'',download_url:'/download',preview_kind:'document',preview_supported:true}}})
  await flushPromises(); expect(document.body.textContent).toContain('无法在线预览');expect(document.body.textContent).toContain('下载原文件');view.unmount()
})

it('opens the requested student and refuses silently falling back to a different answer',async()=>{
 vi.mocked(api).mockImplementation(async(path)=>{
  if(path.endsWith('submissions/'))return [2,4].map(id=>({student:{id,name:'学生'+id,email:''},status:'submitted',versions:[{id:id+10,number:1,text_content:'答案'+id,files:[],status:'submitted',grading_revision:0,grade:null}]})) as any
  if(path.includes('settings'))return {grading_enabled:true,explanation_enabled:true}
  if(path.includes('ai-tasks'))return []
  return assignment as any
 })
 const w=mount(AssignmentWorkspace,{props:{assignmentId:1,isTeacher:true,initialStudentId:4}});await flushPromises()
 expect(w.text()).toContain('答案4')
 await w.setProps({initialStudentId:99});await flushPromises()
 expect(w.text()).toContain('不会自动打开其他学生的答卷')
 expect(w.find('.homework-grade-form').exists()).toBe(false)
 await w.setProps({initialStudentId:2});await flushPromises()
 expect(w.text()).toContain('答案2');w.unmount()
})

it('protects grading drafts on switching, refresh and leaving, retaining failed saves',async()=>{
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(false)
 vi.mocked(api).mockImplementation(async(path,method)=>{
  if(method==='POST')throw new Error('保存失败')
  if(path.endsWith('submissions/'))return [2,4].map(id=>({student:{id,name:'学生'+id,email:''},status:'submitted',versions:[{id:id+10,number:1,text_content:'答案'+id,files:[],status:'submitted',grading_revision:0,grade:null}]})) as any
  if(path.includes('settings'))return {grading_enabled:true,explanation_enabled:true}
  if(path.includes('ai-tasks'))return []
  return assignment as any
 })
 const w=mount(AssignmentWorkspace,{props:{assignmentId:1,isTeacher:true}});await flushPromises()
 expect(hasUnsavedReviewNotes()).toBe(false)
 await w.get('[aria-label="作业分数"]').setValue('82')
 await w.get('.homework-grade-form textarea').setValue('保留步骤分')
 expect(confirmReviewNotesLeave()).toBe(false)
 expect(confirm).toHaveBeenLastCalledWith(expect.stringContaining('批改尚未保存'))
 await w.findAll('.homework-student')[1]!.trigger('click');await flushPromises()
 expect(w.text()).toContain('学生2的作业')
 vi.mocked(api).mockClear()
 await w.findAll('button').find(b=>b.text().includes('刷新状态'))!.trigger('click');await flushPromises()
 expect(api).not.toHaveBeenCalled()
 await w.get('.homework-grade-form').trigger('submit');await flushPromises()
 expect(w.text()).toContain('保存失败')
 expect((w.get('[aria-label="作业分数"]').element as HTMLInputElement).value).toBe('82')
 expect((w.get('.homework-grade-form textarea').element as HTMLTextAreaElement).value).toBe('保留步骤分')
 const event=new Event('beforeunload',{cancelable:true});window.dispatchEvent(event);expect(event.defaultPrevented).toBe(true)
 await w.get('[aria-label="作业分数"]').setValue('');await w.get('.homework-grade-form textarea').setValue('')
 expect(hasUnsavedReviewNotes()).toBe(false)
 await w.get('[aria-label="作业分数"]').setValue('75')
 confirm.mockReturnValue(true)
 await w.findAll('.homework-student')[1]!.trigger('click');await flushPromises()
 expect(w.text()).toContain('学生4的作业');expect(hasUnsavedReviewNotes()).toBe(false)
 w.unmount();expect(hasUnsavedReviewNotes()).toBe(false);confirm.mockRestore()
})
