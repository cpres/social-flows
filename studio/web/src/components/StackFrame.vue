<template>
  <div class="stack-stage" ref="stage" :style="{ height: `${size.h}px` }">
    <div class="stackbox" :style="{ width: `${size.w}px`, height: `${size.h}px` }">
      <div class="pane" :class="{ editing: editing === 'top' }" :style="{ height: `${px.top}px` }">
        <slot name="top" :max-h="px.top" :out="geom.topOut" :bind-top="bindTop" />
      </div>
      <div v-if="px.divider" class="divider" :style="{ height: `${px.divider}px`, background: dividerColor }"></div>
      <div class="pane" :class="{ editing: editing === 'under' }" :style="{ height: `${px.under}px` }">
        <slot name="under" :max-h="px.under" :out="geom.underOut" />
      </div>
      <div v-if="guides" class="guides">
        <div class="g-caption">caption</div>
        <div class="g-buttons">buttons</div>
      </div>
    </div>
    <slot />
  </div>
</template>

<script setup>
// A Stack reel's frame: the top clip in the top pane for the whole reel, a
// divider, and the parts one after another underneath. Each pane holds a
// ReelFrame shaped to it (slots); the top clip is kept at the reel's time.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { clamp } from '../time'

const props = defineProps({
  split: { type: Number, default: 0.5 },          // the top pane's share, as the engine
  dividerPx: { type: Number, default: 4 },        // at 1080×1920
  dividerColor: { type: String, default: '#f7f1e3' },
  editing: { type: String, default: 'under' },    // which pane holds the selected clip
  topT: { type: Number, default: 0 },             // where in the top clip the reel is
  topRate: { type: Number, default: 1 },
  topPlaying: Boolean,
  guides: Boolean,
})

// Same arithmetic as the engine's load_top, so panes match the render.
const geom = computed(() => {
  const d = Math.max(0, Math.round(props.dividerPx / 2) * 2)
  const top = Math.round(((1920 - d) * props.split) / 2) * 2
  const under = 1920 - d - top
  return { d, top, under, topOut: 1080 / top, underOut: 1080 / under }
})

const stage = ref(null)
const width = ref(0)
const cap = ref(0)
const measureCap = () => { cap.value = Math.max(360, Math.min(window.innerHeight - 150, 820)) }
let observer
onMounted(() => {
  measureCap()
  window.addEventListener('resize', measureCap)
  observer = new ResizeObserver(([entry]) => { width.value = entry.contentRect.width })
  observer.observe(stage.value)
})
onBeforeUnmount(() => {
  observer?.disconnect()
  window.removeEventListener('resize', measureCap)
})
const size = computed(() => {
  const w = Math.round(Math.min(width.value, cap.value * (9 / 16)))
  return { w, h: Math.round((w * 16) / 9) }
})
const px = computed(() => {
  const k = size.value.h / 1920
  const divider = geom.value.d ? Math.max(1, Math.round(geom.value.d * k)) : 0
  const top = Math.round(geom.value.top * k)
  return { top, divider, under: size.value.h - top - divider }
})

// The top clip, when it isn't the one being edited: follow the reel's clock.
let topVideo = null
function bindTop(el) {
  if (el === topVideo) return
  topVideo = el
  el?.addEventListener('loadedmetadata', syncTop)
}
function syncTop() {
  const v = topVideo
  if (!v || v.readyState < 1) return
  const rate = clamp(props.topRate, 0.0625, 16)
  if (!props.topPlaying || Math.abs(v.currentTime - props.topT) > 0.3 * Math.max(1, rate)) v.currentTime = props.topT
  if (props.topPlaying) {
    v.playbackRate = rate
    if (v.paused) v.play().catch(() => {})
  } else if (!v.paused) v.pause()
}
watch(() => [props.topT, props.topPlaying, props.topRate], syncTop)
</script>

<style scoped>
.stack-stage {
  position: relative; display: grid; place-items: center;
  background: var(--stage); border-radius: var(--radius); overflow: hidden;
}
.stackbox { position: relative; display: flex; flex-direction: column; overflow: hidden; background: #000; }
.pane { position: relative; flex: none; }
.pane::after {
  content: ''; position: absolute; inset: 0; pointer-events: none; z-index: 4;
  box-shadow: inset 0 0 0 2px transparent; transition: box-shadow 0.15s;
}
.pane.editing::after { box-shadow: inset 0 0 0 2px var(--sage); }
.divider { flex: none; }
.guides { position: absolute; inset: 0; pointer-events: none; z-index: 5; }
.g-caption, .g-buttons {
  position: absolute; display: grid; place-items: center; font-size: 10px; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--on-media); background: rgb(247 241 227 / 18%);
  border: 1px dashed rgb(247 241 227 / 60%);
}
.g-caption { left: 0; right: 16%; bottom: 0; height: 20%; }
.g-buttons { right: 0; width: 14%; bottom: 0; height: 45%; }
</style>
