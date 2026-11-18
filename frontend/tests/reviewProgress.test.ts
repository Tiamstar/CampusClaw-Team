// @vitest-environment jsdom
import {it,expect} from 'vitest'
import {mount} from '@vue/test-utils'
import ReviewProgress from '../src/ReviewProgress.vue'
it('counts only current noncancelled reminders and recommends eligible prerequisites',async()=>{
 const plan={status:'active',stale:false,steps:[{point_id:1,name:'函数',prerequisite_ids:[]},{point_id:2,name:'积分',prerequisite_ids:[1]}],reminders:[{point_id:1,state:'completed',schedule_revision:1,due_at:''},{point_id:1,state:'cancelled',schedule_revision:2,due_at:''},...Array.from({length:5},(_,i)=>({point_id:1,state:i<4?'completed':'scheduled',schedule_revision:2,due_at:'',due:true})),{point_id:2,state:'scheduled',schedule_revision:2,due_at:''}]}
 const w=mount(ReviewProgress,{props:{plan}})
 expect(w.text()).toContain('已完成 4 / 6 次');expect(w.text()).toContain('建议下一步：积分')
 expect(w.text()).toContain('剩余约 20 分钟')
 await w.get('input').setValue('5');expect(w.text()).toContain('剩余约 10 分钟')
 await w.setProps({plan:{...plan,stale:true}});expect(w.find('progress').exists()).toBe(false)
})
