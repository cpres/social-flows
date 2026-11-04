<template>
  <div class="stack-stage" ref="stage" :style="{ height: `${size.h}px` }">
    <div class="stackbox" :style="{ width: `${size.w}px`, height: `${size.h}px` }">
      <img v-if="alone && backdrop" class="blurbg" :src="backdrop" alt="" />
      <div class="pane" :class="{ editing: editing === 'top' }" :style="paneStyle(pos.a, g.top)">
        <slot name="top" :max-h="box(g.top).h" :out="out(g.top)" :bind-top="bindTop" />
      </div>
      <div v-if="g.divider" class="divider" :style="{ ...paneStyle(pos.d, g.divider), background: dividerColor }"></div>
      <div class="pane" :class="{ editing: editing === 'under' }" :style="paneStyle(pos.b, g.under)">
        <slot name="under" :max-h="box(g.under).h" :out="out(g.under)" />
      </div>
      <div v-if="guides" class="guides">
        <div class="g-caption">caption</div>
        <div class="g-buttons">buttons</div>
      </div>
      <slot name="overlay" />
    </div>
    <slot />
  </div>
</template>

<script setup>
// A Stack reel's frame: the top clip in one pane (the left one, in a wide
// reel), a divider, and the parts one after another in the other. Each pane
// holds a ReelFrame shaped to it (slots); the top clip is kept at the reel's
// time. x moves the panes as the render does (see stack.js): -1 the top clip
// alone in the middle, 0 split, 1 the part alone; a pane on its own sits
// over a blurred backdrop.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { clamp } from '../time'
import { panePositions, stackGeometry } from '../stack'

const props = defineProps({
  split: { type: Number, default: 0.5 },          // the top pane's share, as the engine
  dividerPx: { type: Number, default: 4 },        // at the render's size
  dividerColor: { type: String, default: '#f7f1e3' },
  frameW: { type: Number, default: 1080 },        // the render's size
  frameH: { type: Number, default: 1920 },
  x: { type: Number, default: 0 },
  backdrop: { type: String, default: '' },        // an image of the pane that's alone, blurred behind it
  editing: { type: String, default: 'under' },    // which pane holds the selected clip
  topT: { type: Number, default: 0 },             // where in the top clip the reel is
  topRate: { type: Number, default: 1 },
  topPlaying: Boolean,
  guides: Boolean,
})

// Same arithmetic as the engine's load_top, so panes match the render.
const g = computed(() => stackGeometry(props.frameW, props.frameH, props.split, props.dividerPx))
const pos = computed(() => panePositions(Math.max(-1, Math.min(1, props.x)), g.value))
const alone = computed(() => Math.abs(props.x) > 0.001)

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
  const r = props.frameW / props.frameH
  const w = Math.round(Math.min(width.value, cap.value * r))
  return { w, h: Math.round(w / r) }
})
const k = computed(() => size.value.h / props.frameH)
// A pane `along` render pixels long, in screen pixels.
function box(along) {
  const n = Math.round(along * k.value)
  return g.value.axis === 'x' ? { w: n, h: size.value.h } : { w: size.value.w, h: n }
}
const out = (along) => (g.value.axis === 'x' ? along / props.frameH : props.frameW / along)
function paneStyle(at, along) {
  const b = box(along)
  const p = `${Math.round(at * k.value)}px`
  return { width: `${b.w}px`, height: `${b.h}px`, ...(g.value.axis === 'x' ? { left: p, top: 0 } : { top: p, left: 0 }) }
}

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
.stackbox { position: relative; overflow: hidden; background: #000; }
.pane { position: absolute; }
.blurbg { position: absolute; inset: -8%; width: 116%; height: 116%; object-fit: cover; filter: blur(18px) brightness(0.85); }
.pane::after {
  content: ''; position: absolute; inset: 0; pointer-events: none; z-index: 4;
  box-shadow: inset 0 0 0 2px transparent; transition: box-shadow 0.15s;
}
.pane.editing::after { box-shadow: inset 0 0 0 2px var(--sage); }
.divider { position: absolute; }
.guides { position: absolute; inset: 0; pointer-events: none; z-index: 5; }
.g-caption, .g-buttons {
  position: absolute; display: grid; place-items: center; font-size: 10px; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--on-media); background: rgb(247 241 227 / 18%);
  border: 1px dashed rgb(247 241 227 / 60%);
}
.g-caption { left: 0; right: 16%; bottom: 0; height: 20%; }
.g-buttons { right: 0; width: 14%; bottom: 0; height: 45%; }
</style>
