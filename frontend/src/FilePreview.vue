<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { Download, X, RefreshCw } from 'lucide-vue-next'
import { protectedObjectUrl, protectedText, download, type FileInfo } from './api'
const props = defineProps<{file:FileInfo}>()
const emit = defineEmits<{close:[]}>()
const loading = ref(true), error = ref(''), content = ref(''), objectUrl = ref(''), downloadError = ref('')
const closeButton = ref<HTMLButtonElement|null>(null)
let sequence = 0, controller:AbortController|null = null
const previousFocus = document.activeElement as HTMLElement|null
const previousOverflow = document.body.style.overflow

async function load() {
  const current = ++sequence
  controller?.abort(); controller = new AbortController()
  if (objectUrl.value) URL.revokeObjectURL(objectUrl.value)
  objectUrl.value = ''; content.value = ''; error.value = ''; loading.value = true
  try {
    if (props.file.preview_supported === false) throw new Error(props.file.preview_note || '此格式暂不支持在线预览，请下载后查看')
    const url = props.file.preview_url || `/api/files/${props.file.id}/preview/`
    if (props.file.preview_kind === 'pdf' || props.file.preview_kind === 'image') {
      const result = await protectedObjectUrl(url, controller.signal)
      if (current === sequence) objectUrl.value = result
      else URL.revokeObjectURL(result)
    } else {
      const result = await protectedText(url, controller.signal)
      if (current === sequence) content.value = result
    }
  } catch (cause) {
    if (current === sequence) error.value = cause instanceof Error ? cause.message : '预览失败，请下载原文件查看'
  } finally { if (current === sequence) loading.value = false }
}
async function save() {
  downloadError.value = ''
  try { await download(props.file) }
  catch (cause) { downloadError.value = cause instanceof Error ? cause.message : '下载失败，请重试' }
}
watch(() => props.file.id, load, {immediate:true})
onMounted(() => { document.body.style.overflow = 'hidden'; closeButton.value?.focus() })
onBeforeUnmount(() => {
  sequence++; controller?.abort()
  if (objectUrl.value) URL.revokeObjectURL(objectUrl.value)
  document.body.style.overflow = previousOverflow
  if (previousFocus?.isConnected) previousFocus.focus()
})
</script>

<template>
  <Teleport to="body">
    <div class="file-reader-backdrop" @click.self="emit('close')" @keydown.esc.stop.prevent="emit('close')">
      <section class="file-reader" role="dialog" aria-modal="true" :aria-label="`文件预览：${file.name}`">
        <header class="file-reader-header"><div><strong>{{file.name}}</strong><small>{{file.preview_note || '文件预览'}}</small></div><button class="secondary" @click="save"><Download :size="17"/>下载原文件</button><button ref="closeButton" class="icon-button" aria-label="关闭文件预览" @click="emit('close')"><X :size="23"/></button></header>
        <p v-if="downloadError" class="file-error" role="alert">{{downloadError}}</p>
        <div v-if="loading" class="file-reader-state" role="status">正在加载预览…</div>
        <div v-else-if="error" class="file-reader-state" role="alert"><h3>无法在线预览</h3><p>{{error}}</p><div><button class="secondary" @click="load"><RefreshCw :size="16"/>重试</button><button class="primary" @click="save"><Download :size="16"/>下载原文件</button></div></div>
        <div v-else-if="file.preview_kind==='image'" class="file-reader-image"><img :src="objectUrl" :alt="file.name"></div>
        <iframe v-else-if="file.preview_kind==='pdf'" class="file-reader-frame" :src="objectUrl+'#view=FitH'" :title="file.name"></iframe>
        <iframe v-else class="file-reader-frame" :srcdoc="content" sandbox="" :title="file.name"></iframe>
      </section>
    </div>
  </Teleport>
</template>
