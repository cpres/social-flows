<template>
  <div class="stack-stage" ref="stage" :style="{ height: `${size.h}px` }">
    <div class="stackbox" :class="{ side: landscape }" :style="{ width: `${size.w}px`, height: `${size.h}px` }">
      <div class="pane" :class="{ editing: editing === 'top' }" :style="along(px.top)">
        <slot name="top" :max-h="landscape ? size.h : px.top" :out="geom.topOut" :bind-top="bindTop" />
      </div>
      <div v-if="px.divider" class="divider" :style="{ ...along(px.divider), background: dividerColor }"></div>
      <div class="pane" :class="{ editing: editing === 'under' }" :style="along(px.under)">
        <slot name="under" :max-h="landscape ? size.h : px.under" :out="geom.underOut" />
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
// divider, and the parts one after another underneath (in a landscape reel,
// side by side: the top clip on the left, the parts on the right). Each pane
// holds a ReelFrame shaped to it (slots); the top clip is kept at the reel's time.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { clamp } from '../time'

const props = defineProps({
  split: { type: Number, default: 0.5 },          // the top pane's share, as the engine
  dividerPx: { type: Number, default: 4 },        // at the reel's full size
  dividerColor: { type: String, default: '#f7f1e3' },
  editing: { type: String, default: 'under' },    // which pane holds the selected clip
  topT: { type: Number, default: 0 },             // where in the top clip the reel is
  topRate: { type: Number, default: 1 },
  topPlaying: Boolean,
  guides: Boolean,
  landscape: Boolean,                             // 1920×1080, panes side by side
})

// Same arithmetic as the engine's load_top, so panes match the render. The
// panes share the height, or in a landscape reel the width.
const geom = computed(() => {
  const W = props.landscape ? 1920 : 1080
  const H = props.landscape ? 1080 : 1920
  const full = props.landscape ? W : H
  const d = Math.max(0, Math.round(props.dividerPx / 2) * 2)
  const top = Math.round(((full - d) * props.split) / 2) * 2
  const under = full - d - top
  const out = (n) => (props.landscape ? n / H : W / n)   // a pane's shape
  return { W, H, full, d, top, under, topOut: out(top), underOut: out(under) }
})
const along = (n) => (props.landscape ? { width: `${n}px` } : { height: `${n}px` })

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
  const { W, H } = geom.value
  const w = Math.round(Math.min(width.value, cap.value * (W / H)))
  return { w, h: Math.round((w * H) / W) }
})
const px = computed(() => {
  const g = geom.value
  const total = props.landscape ? size.value.w : size.value.h
  const k = total / g.full
  const divider = g.d ? Math.max(1, Math.round(g.d * k)) : 0
  const top = Math.round(g.top * k)
  return { top, divider, under: total - top - divider }
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
.stackbox.side { flex-direction: row; }
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
