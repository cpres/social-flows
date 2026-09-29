<template>
  <div class="clip" :class="{ selected, skipped: !clip.keep }" @click="$emit('select')">
    <div class="thumb">
      <img :src="thumbSrc" loading="lazy" alt="" />
      <span class="dur" v-if="clip.kind === 'video'">{{ fmtTime(clip.duration) }}</span>
      <span class="dur photo" v-else>photo</span>
    </div>
    <div class="info">
      <div class="name" :title="clip.file">{{ clip.file }}</div>
      <div class="muted when">{{ clockTime(clip.capturedAt) }}</div>
      <div class="chip" v-if="clip.kind === 'video'">
        {{ fmtTime(clip.start) }} → {{ fmtTime(clip.start + clip.length) }}
        <b>{{ clip.length.toFixed(1) }}s</b>
      </div>
      <div class="chip" v-else>hold <b>{{ clip.length.toFixed(1) }}s</b></div>
    </div>
    <button
      class="keep" :class="{ on: clip.keep }" :title="clip.keep ? 'Kept — click to skip (X)' : 'Skipped — click to keep (X)'"
      @click.stop="$emit('toggle')"
    >{{ clip.keep ? '✓' : '–' }}</button>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { api } from '../api'
import { clockTime, fmtTime } from '../time'

const props = defineProps({
  clip: { type: Object, required: true },
  folder: { type: String, required: true },
  selected: Boolean,
})
defineEmits(['select', 'toggle'])

// Poster follows the chosen start, but only once dragging settles.
const thumbT = ref(Math.round(props.clip.start))
let timer
watch(() => props.clip.start, (s) => {
  clearTimeout(timer)
  timer = setTimeout(() => { thumbT.value = Math.round(s) }, 500)
})
const thumbSrc = ref('')
watch(thumbT, (t) => { thumbSrc.value = api.thumb(props.folder, props.clip.file, t, 240) }, { immediate: true })
</script>

<style scoped>
.clip {
  display: grid; grid-template-columns: 96px 1fr auto; gap: 10px; align-items: center;
  padding: 8px; border-radius: 10px; cursor: pointer; border: 1px solid transparent;
}
.clip:hover { background: var(--paper); }
.clip.selected { background: var(--paper); border-color: var(--sage); box-shadow: var(--shadow); }
.clip.skipped .thumb, .clip.skipped .info { opacity: 0.4; }
.thumb { position: relative; aspect-ratio: 16 / 10; border-radius: 6px; overflow: hidden; background: var(--forest); }
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.dur {
  position: absolute; right: 3px; bottom: 3px; font-size: 10px; padding: 0 4px; border-radius: 3px;
  background: rgb(31 42 31 / 75%); color: var(--cream); font-family: ui-monospace, monospace;
}
.dur.photo { background: var(--sage); color: var(--forest); font-family: inherit; }
.info { min-width: 0; }
.name { font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.when { font-size: 11px; }
.chip { font-size: 11px; font-family: ui-monospace, monospace; color: var(--forest); margin-top: 2px; }
.keep {
  width: 28px; height: 28px; border-radius: 50%; border: 2px solid var(--line);
  background: var(--paper); cursor: pointer; font-weight: 700; color: var(--muted);
}
.keep.on { background: var(--sage); border-color: var(--sage); color: var(--forest); }
</style>
