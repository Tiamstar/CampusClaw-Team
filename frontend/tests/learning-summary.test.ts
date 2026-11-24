// @vitest-environment jsdom
import {mount} from '@vue/test-utils'
import {describe,it,expect} from 'vitest'
import LearningSummary from '../src/LearningSummary.vue'
describe('learning summary',()=>{
  it('deduplicates multi-tag evidence and prioritizes weaker points without counting unknown as zero',async()=>{
    const shared={attempt_id:1,question_id:9,score:'5',maximum:'10'}
    const w=mount(LearningSummary,{props:{points:[
      {id:1,name:'较弱',mastery:'.5',band:'consolidate',evidence:[shared]},
      {id:2,name:'发展',mastery:'.7',band:'developing',evidence:[shared,{attempt_id:2,question_id:10,score:'9',maximum:'10'}]},
      {id:3,name:'尚未学习',mastery:null,band:'unknown',evidence:[]}
    ]}})
    expect(w.findAll('.summary-metrics strong').map(x=>x.text())).toEqual(['2 / 3','2','70.0%'])
    expect(w.findAll('ol button').map(x=>x.text())).toEqual(['较弱 · 50.0%','发展 · 70.0%'])
    await w.get('ol button').trigger('click')
    expect(w.emitted('showEvidence')).toEqual([[1]])
    expect(w.find('a').exists()).toBe(false)
    expect(w.text()).toContain('未知 · 1 个')
  })
  it('shows an honest unknown empty state',()=>{
    const w=mount(LearningSummary,{props:{points:[]}})
    expect(w.text()).toContain('未知不代表零分')
    expect(w.findAll('.summary-metrics strong').map(x=>x.text())).toEqual(['0 / 0','0','未知'])
    expect(w.find('ol').exists()).toBe(false)
  })
})
