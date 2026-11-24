// @vitest-environment jsdom
import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import LatencyChart from '../src/LatencyChart.vue'
import LatencyMetrics from '../src/LatencyMetrics.vue'

it('keeps unknown and empty samples out of curves and shows exact sample counts',()=>{
  const v=mount(LatencyChart,{props:{title:'Fixture',interval:'five_minutes',points:[
    {time:'2026-11-16T00:00:00Z',samples:2,avg_ms:10,p95_ms:19},
    {time:'2026-11-16T00:05:00Z',samples:0,avg_ms:null,p95_ms:null}]}})
  expect(v.findAll('circle')).toHaveLength(2)
  expect(v.text()).toContain('1 个时间桶');expect(v.get('tbody').text()).toContain('19')
  expect(v.get('svg').attributes('aria-label')).toContain('单位毫秒');v.unmount()
})
it('breaks lines across missing buckets instead of drawing invented zero samples',()=>{
  const v=mount(LatencyChart,{props:{title:'Gaps',interval:'five_minutes',points:[
    {time:'2026-11-16T00:00:00Z',samples:1,avg_ms:10,p95_ms:10},
    {time:'2026-11-16T00:15:00Z',samples:1,avg_ms:30,p95_ms:30}]}})
  const path=v.findAll('path')[0]!.attributes('d')!
  expect(path.match(/M/g)).toHaveLength(2);expect(path).not.toContain('L');v.unmount()
})
it('shows no curve for legacy tasks with unknown processing times',()=>{
  const v=mount(LatencyMetrics,{props:{skills:[{kind:'guidance',skill_id:'guide'}],durations:{interval:'hour',note:'Actual samples only',model:[],task:[{skill_id:'guide',time:'2026-11-16T00:00:00Z',samples:1,avg_ms:100,p95_ms:100,processing_samples:0,processing_avg_ms:null,processing_p95_ms:null,queue_avg_ms:null,queue_p95_ms:null}]}}})
  expect(v.text()).toContain('尚无接口耗时统计')
  expect(v.findAll('svg')).toHaveLength(1);expect(v.text()).toContain('未知值不补零');v.unmount()
})
it('selects route-specific raw percentiles and separates premature close from HTTP errors',async()=>{
  const common={requests:4,completed:2,closed:1,transport_errors:1,client_errors:1,server_errors:0,avg_ms:10,p95_ms:15}
  const v=mount(LatencyMetrics,{props:{skills:[],http:{interval:'five_minutes',note:'HTTP 200不保证业务成功',routes_truncated:true,routes:[{...common,route:'api/courses/<int:course_id>/materials/',method:'GET',streaming:false},{...common,route:'api/agent/threads/<int:thread_id>/messages/stream/',method:'POST',streaming:true,p95_ms:999}],curve:[]}}})
  expect(v.text()).toContain('提前关闭 1 / 传输异常 1');expect(v.text()).toContain('P95 15 ms');expect(v.text()).toContain('50组接口')
  await v.get('select').setValue(JSON.stringify(['POST','api/agent/threads/<int:thread_id>/messages/stream/',true]))
  expect(v.text()).toContain('流式响应完整耗时');expect(v.text()).toContain('P95 999 ms')
  expect(v.text()).toContain('<int:course_id>');expect(v.find('int').exists()).toBe(false);v.unmount()
})
