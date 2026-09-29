<template>
  <div class="frame-stage" ref="stage">
    <div class="box" :style="{ width: `${box.w}px`, height: `${box.h}px`, background: backdrop }">
      <img
        v-if="mode === 'fit' && fit === 'blur'" class="blurbg" alt=""
        :src="api.thumb(media.folder, media.file, posterTime, 320)"
      />
      <div class="media" :style="mediaStyle">
        <video
          v-if="media.kind === 'video'" :ref="bindVideo" :src="api.media(media.folder, media.file)"
          preload="auto" playsinline :muted="muted" @loadedmetadata="onMeta" @play="$emit('play')" @pause="$emit('pause')"
          @error="$emit('error')" @click="$emit('toggle')"
        ></video>
        <img v-else :src="api.thumb(media.folder, media.file, 0, 1080)" alt="" @load="onImg" />
      </div>

      <!-- the part of the frame the reel keeps -->
      <div
        v-if="mode === 'crop'" class="window" :class="{ movable, dragging }" :style="windowStyle"
        @pointerdown="down" @pointermove="move" @pointerup="up" @pointercancel="up"
      >
        <span class="hint" v-if="movable">drag to reframe</span>
        <Guides v-if="guides" />
      </div>
      <Guides v-else-if="guides" />
    </div>
    <slot />
  </div>
</template>

<script setup>
import { computed, h, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { clamp } from '../time'

const OUT = 9 / 16   // the reel's shape
const BRAND = { forest: '#344a34', sage: '#8aa37c', cream: '#f7f1e3' }

const props = defineProps({
  media: { type: Object, required: true },
  fit: { type: String, default: 'fill' },          // fill | blur | pad, as the engine
  focusX: { type: Number, default: 0.5 },
  focusY: { type: Number, default: 0.5 },
  guides: Boolean,                                  // show where Instagram's UI covers
  muted: Boolean,                                   // matches whether the reel keeps clip audio
  posterTime: { type: Number, default: 0 },
  bindVideo: { type: Function, default: () => {} },
})
const emit = defineEmits(['focus', 'play', 'pause', 'error', 'toggle', 'loaded'])

// Instagram covers roughly the bottom fifth (caption) and a right-hand column (buttons).
const Guides = () => h('div', { class: 'guides' }, [
  h('div', { class: 'g-caption' }, 'caption'),
  h('div', { class: 'g-buttons' }, 'buttons'),
])

// Size as seen (the server applies rotation); fall back to the file itself.
const natural = reactive({ w: 0, h: 0 })
const aspect = computed(() => {
  const w = props.media.width || natural.w
  const hgt = props.media.height || natural.h
  return w && hgt ? w / hgt : OUT
})
function onMeta(e) {
  natural.w = e.target.videoWidth
  natural.h = e.target.videoHeight
  emit('loaded', e)
}
function onImg(e) {
  natural.w = e.target.naturalWidth
  natural.h = e.target.naturalHeight
}

// fill crops the source to 9:16 (show the whole source with the kept window);
// blur and pad fit the whole source inside a 9:16 frame.
const mode = computed(() => (props.fit === 'fill' ? 'crop' : 'fit'))
const boxAspect = computed(() => (mode.value === 'crop' ? aspect.value : OUT))

const stage = ref(null)
const space = reactive({ w: 0, h: 0 })
let observer
onMounted(() => {
  observer = new ResizeObserver(([entry]) => {
    space.w = entry.contentRect.width
    space.h = entry.contentRect.height
  })
  observer.observe(stage.value)
})
onBeforeUnmount(() => observer?.disconnect())

const box = computed(() => {
  let hgt = space.h
  let w = hgt * boxAspect.value
  if (w > space.w) { w = space.w; hgt = w / boxAspect.value }
  return { w: Math.round(w), h: Math.round(hgt) }
})

const mediaStyle = computed(() => {
  if (mode.value === 'crop') return { inset: 0 }
  // contained inside the 9:16 box
  const a = aspect.value
  if (a > OUT) {
    const hPct = (OUT / a) * 100
    return { left: 0, right: 0, top: `${(100 - hPct) / 2}%`, height: `${hPct}%` }
  }
  const wPct = (a / OUT) * 100
  return { top: 0, bottom: 0, left: `${(100 - wPct) / 2}%`, width: `${wPct}%` }
})

const backdrop = computed(() =>
  props.fit === 'pad' ? BRAND.forest : mode.value === 'fit' ? '#121812' : 'transparent')

// The 9:16 window, as percentages of the source.
const win = computed(() => {
  const a = aspect.value
  if (a > OUT * 1.005) {
    const w = (OUT / a) * 100
    return { w, h: 100, left: (100 - w) * props.focusX, top: 0, axis: 'x' }
  }
  if (a < OUT * 0.995) {
    const hgt = (a / OUT) * 100
    return { w: 100, h: hgt, left: 0, top: (100 - hgt) * props.focusY, axis: 'y' }
  }
  return { w: 100, h: 100, left: 0, top: 0, axis: null }
})
const movable = computed(() => win.value.axis !== null)
const windowStyle = computed(() => ({
  left: `${win.value.left}%`, top: `${win.value.top}%`,
  width: `${win.value.w}%`, height: `${win.value.h}%`,
}))

const dragging = ref(false)
let origin = null
function down(e) {
  if (!movable.value) return
  e.currentTarget.setPointerCapture(e.pointerId)
  dragging.value = true
  origin = { x: e.clientX, y: e.clientY, fx: props.focusX, fy: props.focusY }
}
function move(e) {
  if (!dragging.value) return
  const w = win.value
  if (w.axis === 'x') {
    const travel = box.value.w * (1 - w.w / 100)
    emit('focus', { x: round(clamp(origin.fx + (e.clientX - origin.x) / travel, 0, 1)), y: props.focusY })
  } else {
    const travel = box.value.h * (1 - w.h / 100)
    emit('focus', { x: props.focusX, y: round(clamp(origin.fy + (e.clientY - origin.y) / travel, 0, 1)) })
  }
}
function up() {
  dragging.value = false
}
const round = (v) => Math.round(v * 1000) / 1000
</script>

<style scoped>
.frame-stage {
  position: relative; display: grid; place-items: center; height: 100%;
  background: #121812; border-radius: var(--radius); overflow: hidden;
}
.box { position: relative; overflow: hidden; }
.media { position: absolute; }
.media video, .media img { width: 100%; height: 100%; display: block; object-fit: fill; }
.media video { cursor: pointer; }
.blurbg { position: absolute; inset: -10%; width: 120%; height: 120%; object-fit: cover; filter: blur(18px) brightness(0.8); }
.window {
  position: absolute; box-shadow: 0 0 0 9999px rgb(10 14 10 / 62%);
  outline: 2px solid var(--sage); pointer-events: none;
}
.window.movable { pointer-events: auto; cursor: grab; touch-action: none; }
.window.dragging { cursor: grabbing; }
.hint {
  position: absolute; top: 8px; left: 50%; transform: translateX(-50%); white-space: nowrap;
  font-size: 11px; padding: 2px 8px; border-radius: 999px; background: rgb(31 42 31 / 70%); color: var(--cream);
  pointer-events: none;
}
:deep(.guides) { position: absolute; inset: 0; pointer-events: none; }
:deep(.g-caption), :deep(.g-buttons) {
  position: absolute; display: grid; place-items: center; font-size: 10px; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--cream); background: rgb(247 241 227 / 18%);
  border: 1px dashed rgb(247 241 227 / 60%);
}
:deep(.g-caption) { left: 0; right: 16%; bottom: 0; height: 20%; }
:deep(.g-buttons) { right: 0; width: 14%; bottom: 0; height: 45%; }
</style>
