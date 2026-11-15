// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AssistantStudio from '../src/AssistantStudio.vue'
import { api } from '../src/api'

vi.mock('../src/api', () => ({ api: vi.fn() }))
afterEach(() => vi.resetAllMocks())

function setup(failSave = false, canEdit = true) {
  const saved: any[] = []
  vi.mocked(api).mockImplementation(async (path, method, data) => {
    if (path === 'agent/catalog/') return {
      apps: [{ id: 'lesson', name: '教师备课', icon: '', description: '', prompt: '', starter: '准备一节课', default_skill_ids: ['lesson-plan-builder'] }],
      skills: [
        { id: 'lesson-plan-builder', name: '教案', description: '', source: '教学来源', category: '备课设计', builtin: true },
        { id: 'upload-1', name: '个人教学技能', description: '', source: '个人上传', category: '我的上传', builtin: false },
      ], can_manage_mcp: false, provider: 'mock', model: '',
    } as any
    if (path.includes('/assistant/')) {
      if (method === 'PUT') {
        saved.push(JSON.parse(JSON.stringify(data)))
        if (failSave) throw new Error('保存失败')
        return data as any
      }
      return { app_id: 'general', template: '', skill_ids: ['lesson-plan-builder'], mcp_refs: [], use_knowledge: true, can_edit: canEdit, revision: 3 } as any
    }
    return [] as any
  })
  return saved
}

it('binds recommended teaching skills without publishing private uploads', async () => {
  const saved = setup()
  const wrapper = mount(AssistantStudio, { props: { courseId: 1, threadId: null } })
  await flushPromises()
  expect(wrapper.findAll('option').map(option => option.text())).toContain('教学来源')
  await wrapper.get('.studio-nav button').trigger('click')
  await wrapper.get('.studio-app').trigger('click')
  await flushPromises()
  expect(saved[0]).toMatchObject({ app_id: 'lesson', skill_ids: ['lesson-plan-builder'], use_knowledge: true, revision: 3 })
  expect(wrapper.emitted('chat')).toEqual([['准备一节课']])
  wrapper.unmount()
})

it('restores the previous selection when saving an application fails', async () => {
  setup(true)
  const wrapper = mount(AssistantStudio, { props: { courseId: 1, threadId: null } })
  await flushPromises()
  await wrapper.get('.studio-nav button').trigger('click')
  await wrapper.get('.studio-app').trigger('click')
  await flushPromises()
  expect(wrapper.get('.studio-count strong').text()).toBe('01')
  expect(wrapper.emitted('chat')).toBeUndefined()
  expect(wrapper.get('.studio-notice').text()).toContain('保存失败')
  wrapper.unmount()
})

it('shows shared student configuration read-only and keeps personal upload unbindable', async () => {
  const saved = setup(false, false)
  const wrapper = mount(AssistantStudio, { props: { courseId: 1, threadId: null } })
  await flushPromises()
  expect(wrapper.text()).toContain('只读，由任课教师维护')
  expect(wrapper.findAll('.skill-add').every(button => button.attributes('disabled') !== undefined)).toBe(true)
  const nav = wrapper.findAll('.studio-nav button')
  await nav[2]!.trigger('click')
  expect(wrapper.get('textarea').attributes('disabled')).toBeDefined()
  expect(wrapper.get('select').attributes('disabled')).toBeDefined()
  await wrapper.get('.primary').trigger('click')
  expect(saved).toHaveLength(0)
  wrapper.unmount()
})
