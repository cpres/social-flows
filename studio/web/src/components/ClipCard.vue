<template>
  <div
    class="clip" :class="{ selected, used, dim: dim || media.missing }" @click="$emit('select')"
  >
    <div class="thumb">
      <img v-if="!media.missing" :src="thumbSrc" loading="lazy" alt="" draggable="false" />
      <span v-else class="gone">missing</span>
      <span class="dur" v-if="media.kind === 'video'">{{ fmtTime(media.duration) }}</span>
      <span class="dur photo" v-else>photo</span>
    </div>
    <div class="info">
      <div class="name" :title="`${media.folder}/${media.file}`">{{ media.file }}</div>
      <div class="muted sub">{{ sub }}</div>
      <div class="chip" v-if="chip">{{ chip }}</div>
      <div class="dots" v-if="dots.length">
        <span v-for="(d, i) in dots" :key="i" class="dot" :style="{ background: d.color }" :title="d.label"></span>
      </div>
    </div>
    <slot />
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { api } from '../api'
import { fmtTime } from '../time'

const props = defineProps({
  media: { type: Object, required: true },
  thumbTime: { type: Number, default: 0 },
  sub: { type: String, default: '' },
  chip: { type: String, default: '' },
  dots: { type: Array, default: () => [] },
  selected: Boolean,
  dim: Boolean,
  used: Boolean,   // already in a reel: a light border, so unused (newer) clips stand out

})
defineEmits(['select'])

// Poster follows the part's start, but only once dragging settles.
const thumbSrc = ref('')
let timer
const load = (t) => { thumbSrc.value = api.thumb(props.media.folder, props.media.file, Math.round(t), 240) }
load(props.thumbTime)
watch(() => props.thumbTime, (t) => {
  clearTimeout(timer)
  timer = setTimeout(() => load(t), 500)
})
</script>

<style scoped>
.clip {
  display: grid; grid-template-columns: 58px 1fr auto; gap: 10px; align-items: center;
  padding: 8px; border-radius: 10px; cursor: pointer; border: 1px solid transparent;
}
.clip:hover { background: var(--paper); }
.clip.used { border-color: var(--used); }
.clip.selected { background: var(--paper); border-color: var(--sage); box-shadow: var(--shadow); }
.clip.dim .thumb, .clip.dim .info { opacity: 0.4; }
.thumb { position: relative; aspect-ratio: 3 / 4; border-radius: 6px; overflow: hidden; background: var(--forest); }
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.gone { display: grid; place-items: center; height: 100%; color: var(--on-media); font-size: 11px; }
.dur {
  position: absolute; right: 3px; bottom: 3px; font-size: 10px; padding: 0 4px; border-radius: 3px;
  background: rgb(31 42 31 / 75%); color: var(--on-media); font-family: ui-monospace, monospace;
}
.dur.photo { background: var(--sage); color: var(--on-sage); font-family: inherit; }
.info { min-width: 0; }
.name { font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sub { font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chip { font-size: 11px; font-family: ui-monospace, monospace; color: var(--forest); margin-top: 2px; }
.dots { display: flex; gap: 3px; margin-top: 4px; flex-wrap: wrap; }
.dot { width: 9px; height: 9px; border-radius: 50%; }
</style>
