// @vitest-environment jsdom
import {describe,it,expect} from 'vitest'
import {mount} from '@vue/test-utils'
import CourseNavigation from '../src/CourseNavigation.vue'
describe('course navigation',()=>{
 it('opens active secondary group and emits selection',async()=>{
  const w=mount(CourseNavigation,{props:{active:'exams',isTeacher:true}})
  expect(w.get('[aria-current="page"]').text()).toBe('试卷识别')
  await w.get('[aria-current="page"]').trigger('click')
  expect(w.emitted('select')).toEqual([['exams']])
  expect(w.findAll('.primary-navigation button')).toHaveLength(8)
  await w.setProps({active:'review'})
  expect(w.get('[aria-current="page"]').text()).toBe('复习路径')
 })
 it('hides teacher destinations from students',async()=>{
  const w=mount(CourseNavigation,{props:{active:'materials',isTeacher:false}})
  await w.get('[aria-controls="navigation-management"]').trigger('click')
  expect(w.text()).not.toContain('试卷识别');expect(w.text()).not.toContain('题库')
  await w.get('[aria-controls="navigation-learning"]').trigger('click')
  expect(w.text()).toContain('我的作业错题')
 })
})
