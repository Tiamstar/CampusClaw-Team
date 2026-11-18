<script setup lang="ts">
import { ref } from 'vue'
import { Download, Eye, FileText } from 'lucide-vue-next'
import { download, type FileInfo } from './api'
defineProps<{file:FileInfo}>()
const emit = defineEmits<{preview:[file:FileInfo]}>()
const busy = ref(false), error = ref('')
const size = (bytes:number) => bytes < 1048576 ? `${Math.ceil(bytes / 1024)} KB` : `${(bytes / 1048576).toFixed(1)} MB`
async function save(file:FileInfo) {
  busy.value = true; error.value = ''
  try { await download(file) }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '下载失败，请重试' }
  finally { busy.value = false }
}
</script>

<template>
  <div class="business-file">
    <FileText :size="22" class="business-file-icon"/>
    <div class="business-file-copy"><strong>{{file.name}}</strong><small>{{size(file.size)}}<template v-if="file.preview_note"> · {{file.preview_note}}</template></small><small v-if="error" class="file-error" role="alert">{{error}}</small></div>
    <div class="business-file-actions">
      <button v-if="file.preview_supported !== false" class="secondary" :aria-label="`预览 ${file.name}`" @click="emit('preview',file)"><Eye :size="16"/>预览</button>
      <span v-else class="preview-unavailable">不支持预览</span>
      <button class="secondary" :disabled="busy" :aria-label="`下载 ${file.name}`" @click="save(file)"><Download :size="16"/>{{busy?'下载中…':'下载'}}</button>
    </div>
  </div>
</template>
