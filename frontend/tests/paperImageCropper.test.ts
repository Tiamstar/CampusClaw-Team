// @vitest-environment jsdom
import {it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import PaperImageCropper from '../src/PaperImageCropper.vue'
import {api,protectedObjectUrl} from '../src/api'
vi.mock('../src/api',()=>({api:vi.fn(),protectedObjectUrl:vi.fn()}))
it('previews and keyboard-adjusts exact crop bounds without expanding into private answers',async()=>{
 vi.mocked(protectedObjectUrl).mockResolvedValue('blob:page');vi.mocked(api).mockResolvedValue({marker:'{{asset:20}}'})
 URL.revokeObjectURL=vi.fn()
 const w=mount(PaperImageCropper,{props:{assetId:1,sourceId:8,revision:3}});await flushPromises()
 const image=w.get('.crop-surface img')
 Object.defineProperty(image.element,'naturalWidth',{value:1000});Object.defineProperty(image.element,'naturalHeight',{value:2000});await image.trigger('load')
 for(const [label,value] of [['左边界','100'],['上边界','200'],['右边界','800'],['下边界','600']])await w.get(`[aria-label="${label}"]`).setValue(value)
 expect(w.get('.crop-preview-window').attributes('style')).toContain('aspect-ratio: 0.875')
 expect(w.text()).toContain('边缘标注完整')
 await w.findAll('button').find(b=>b.text()==='裁剪并插入所选位置')!.trigger('click');await flushPromises()
 expect(api).toHaveBeenCalledWith('exam-sources/8/','POST',{action:'crop',asset_id:1,box:[100,200,800,600],expected_revision:3})
 expect(w.emitted('insert')).toEqual([['{{asset:20}}']])
 await w.setProps({assetId:2});await flushPromises()
 expect((w.get('[aria-label=左边界]').element as HTMLInputElement).value).toBe('0')
 expect(w.find('.crop-preview-window').exists()).toBe(false);w.unmount()
})
