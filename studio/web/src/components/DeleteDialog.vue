<template>
  <div class="modal" @click.self="$emit('close')">
    <div class="dialog">
      <h2>Delete {{ countLabel }}?</h2>
      <p class="muted">
        From <b>{{ folderTitle(from) }}</b>. They go to the Trash, so you can still put them back from there.
        <template v-if="parts"> The {{ parts }} part{{ parts === 1 ? '' : 's' }} of them in reels will be taken out.</template>
        <template v-if="all"> Nothing will be left here, so this folder goes away.</template>
      </p>
      <p v-if="failure" class="err">{{ failure }}</p>
      <div class="controls">
        <span class="spacer"></span>
        <button class="btn" @click="$emit('close')">Cancel</button>
        <button class="btn danger" :disabled="busy" @click="go">{{ busy ? 'Deleting…' : 'Delete' }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { api } from '../api'
import { folderTitle } from '../time'

const props = defineProps({
  from: { type: String, required: true },   // the shoot folder they're in
  files: { type: Array, required: true },   // media rows to delete
  parts: { type: Number, default: 0 },      // their parts in reels
  all: Boolean,                             // every file in the folder
})
const emit = defineEmits(['close', 'deleted'])

const busy = ref(false)
const failure = ref('')
const countLabel = computed(() => {
  const v = props.files.filter((m) => m.kind === 'video').length
  const p = props.files.length - v
  return [v && `${v} video${v === 1 ? '' : 's'}`, p && `${p} photo${p === 1 ? '' : 's'}`].filter(Boolean).join(' and ')
})

async function go() {
  busy.value = true
  failure.value = ''
  try {
    const r = await api.deleteFiles(props.from, props.files.map((m) => m.file))
    if (r.failed.length) failure.value = r.failed.map((f) => `${f.name}: ${f.error}`).join('\n')
    if (r.deleted.length) emit('deleted', r)
  } catch (e) {
    failure.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.dialog { display: flex; flex-direction: column; gap: 14px; width: min(460px, 100%); }
.dialog > p { margin: 0; }
.controls { margin-top: 0; }
.err { color: var(--danger); white-space: pre-line; margin: 0; }
.btn.danger { background: var(--danger); border-color: var(--danger); color: #fff; }
</style>
