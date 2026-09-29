<template>
  <div class="frame-stage" ref="stage" :style="{ height: `${box.h}px` }">
    <div class="box" :class="fxClass" :style="{ width: `${box.w}px`, height: `${box.h}px`, background: backdrop }">
      <img
        v-if="mode === 'fit' && fit === 'blur'" class="blurbg" alt=""
        :src="api.thumb(media.folder, media.file, posterTime, 320)"
      />
      <!-- same gamma curve the render uses, so the preview matches -->
      <svg v-if="lighten" class="defs" aria-hidden="true">
        <filter :id="filterId" color-interpolation-filters="sRGB">
          <feComponentTransfer>
            <feFuncR type="gamma" :exponent="liftExponent" />
            <feFuncG type="gamma" :exponent="liftExponent" />
            <feFuncB type="gamma" :exponent="liftExponent" />
          </feComponentTransfer>
        </filter>
      </svg>
      <div class="media" :style="[mediaStyle, liftStyle]">
        <video
          v-if="media.kind === 'video'" :ref="bindVideo" :src="api.media(media.folder, media.file)"
          preload="auto" playsinline :muted="muted" @loadedmetadata="onMeta" @play="$emit('play')" @pause="$emit('pause')"
          @playing="firePending"
          @error="$emit('error')" @click="$emit('toggle')"
        ></video>
        <img v-else :src="api.thumb(media.folder, media.file, 0, 1080)" alt="" @load="onImg" />
      </div>

      <!-- the part of the frame the reel keeps -->
      <div
        v-if="mode === 'crop' && !cropped" class="window" :class="{ movable, dragging }" :style="windowStyle"
        @pointerdown="down($event, 'move')" @pointermove="move" @pointerup="up" @pointercancel="up"
        @dblclick="resetZoom" :title="zoom > 1 ? 'Double-click to zoom back out' : ''"
      >
        <span class="hint">{{ movable ? 'drag to reframe · corners to zoom' : 'drag a corner to zoom' }}</span>
        <span class="zoomtag" v-if="zoom > 1.005">{{ zoom.toFixed(1) }}×</span>
        <span
          v-for="c in CORNERS" :key="c" class="corner" :class="c"
          @pointerdown.stop="down($event, c)" @pointermove.stop="move" @pointerup.stop="up" @pointercancel.stop="up"
        ></span>
        <Guides v-if="guides" />
      </div>
      <Guides v-else-if="guides" />
    </div>
    <slot />
  </div>
</template>

<script setup>
import { computed, h, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
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
  muted: Boolean,
  cropped: Boolean,
  effect: { type: Object, default: null },
  lighten: { type: Number, default: 0 },
  zoom: { type: Number, default: 1 },              // >1 = crop tighter than the full 9:16 window           // 0..1, as the engine's `lighten`          // { type, at }: a transition to play into this shot                                 // show only what the reel shows (while playing it)                                   // matches whether the reel keeps clip audio
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
const boxAspect = computed(() => (mode.value === 'crop' && !props.cropped ? aspect.value : OUT))

const stage = ref(null)

// Lighten: engine uses eq gamma = 1 + 0.6 × lighten, i.e. out = in^(1/gamma).
const filterId = `lift-${Math.random().toString(36).slice(2, 8)}`
const liftExponent = computed(() => 1 / (1 + 0.6 * props.lighten))
const liftStyle = computed(() => (props.lighten
  ? { filter: `url(#${filterId}) saturate(${1 + 0.08 * props.lighten})` } : {}))

// A rough, in-browser version of the transition into this shot, so playing
// the reel shows the flow. The render does the real thing.
const fxClass = ref('')
let pending = null
let fxTimer
function fire(type) {
  fxClass.value = ''
  clearTimeout(fxTimer)
  nextTick(() => {
    fxClass.value = `fx-${type}`
    fxTimer = setTimeout(() => { fxClass.value = '' }, 500)
  })
}
function firePending() {
  if (pending) fire(pending)
  pending = null
}
watch(() => props.effect, (fx) => {
  if (!fx || performance.now() - fx.at > 1500) return
  const v = stage.value?.querySelector('video')
  // A clip that's still loading gets its transition when it starts playing.
  if (props.media.kind === 'video' && (!v || v.paused)) pending = fx.type
  else fire(fx.type)
}, { immediate: true })

// The frame fills the column's width, up to a height that fits the window;
// the stage wraps it, so there are no empty bands above or below.
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
  clearTimeout(fxTimer)
  observer?.disconnect()
  window.removeEventListener('resize', measureCap)
})

const box = computed(() => {
  const w = Math.min(width.value, cap.value * boxAspect.value)
  return { w: Math.round(w), h: Math.round(w / boxAspect.value) }
})

const mediaStyle = computed(() => {
  if (mode.value === 'crop' && props.cropped) {
    // scale the source so the 9:16 window fills the box
    const w = win.value
    return {
      width: `${(100 / w.w) * 100}%`, height: `${(100 / w.h) * 100}%`,
      left: `${(-w.left / w.w) * 100}%`, top: `${(-w.top / w.h) * 100}%`,
      transformOrigin: `${w.left + w.w / 2}% ${w.top + w.h / 2}%`,
    }
  }
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
// The 9:16 window as percentages of the source: the largest one that fits,
// shrunk by the zoom, placed by focus (0 = left/top edge, 1 = right/bottom).
const MAX_ZOOM = 3
const CORNERS = ['nw', 'ne', 'sw', 'se']
const zoom = computed(() => clamp(props.zoom || 1, 1, MAX_ZOOM))
const win = computed(() => {
  const a = aspect.value
  let w = 100
  let h = 100
  if (a > OUT) w = (OUT / a) * 100
  else h = (a / OUT) * 100
  w /= zoom.value
  h /= zoom.value
  return { w, h, left: (100 - w) * props.focusX, top: (100 - h) * props.focusY }
})
const movable = computed(() => win.value.w < 99.5 || win.value.h < 99.5)
const windowStyle = computed(() => ({
  left: `${win.value.left}%`, top: `${win.value.top}%`,
  width: `${win.value.w}%`, height: `${win.value.h}%`,
}))

const dragging = ref(false)
let origin = null
function down(e, what) {
  e.currentTarget.setPointerCapture(e.pointerId)
  dragging.value = true
  const w = win.value
  const bw = box.value.w
  const bh = box.value.h
  const px = { l: (w.left / 100) * bw, t: (w.top / 100) * bh, w: (w.w / 100) * bw, h: (w.h / 100) * bh }
  // The corner opposite the one grabbed stays put while resizing.
  const anchor = {
    x: what.includes('w') ? px.l + px.w : px.l,
    y: what.includes('n') ? px.t + px.h : px.t,
  }
  origin = { what, x: e.clientX, y: e.clientY, fx: props.focusX, fy: props.focusY, anchor,
             fullW: px.w * zoom.value, rect: stage.value.querySelector('.box').getBoundingClientRect() }
}
function move(e) {
  if (!dragging.value) return
  if (Math.abs(e.clientX - origin.x) + Math.abs(e.clientY - origin.y) > 3) origin.moved = true
  if (!origin.moved) return
  const bw = box.value.w
  const bh = box.value.h
  const w = win.value
  if (origin.what === 'move') {
    const tx = bw * (1 - w.w / 100)
    const ty = bh * (1 - w.h / 100)
    emit('focus', {
      x: tx > 0.5 ? round(clamp(origin.fx + (e.clientX - origin.x) / tx, 0, 1)) : props.focusX,
      y: ty > 0.5 ? round(clamp(origin.fy + (e.clientY - origin.y) / ty, 0, 1)) : props.focusY,
      zoom: zoom.value,
    })
    return
  }
  // Corner: the new width follows the pointer's distance from the anchor; the
  // window stays 9:16 on screen.
  const px = e.clientX - origin.rect.left
  const py = e.clientY - origin.rect.top
  let nw = Math.max(Math.abs(px - origin.anchor.x), Math.abs(py - origin.anchor.y) * OUT)
  nw = clamp(nw, origin.fullW / MAX_ZOOM, origin.fullW)
  const nh = nw / OUT
  const left = clamp(origin.what.includes('w') ? origin.anchor.x - nw : origin.anchor.x, 0, bw - nw)
  const top = clamp(origin.what.includes('n') ? origin.anchor.y - nh : origin.anchor.y, 0, bh - nh)
  emit('focus', {
    x: bw - nw > 0.5 ? round(left / (bw - nw)) : 0.5,
    y: bh - nh > 0.5 ? round(top / (bh - nh)) : 0.5,
    zoom: Math.round((origin.fullW / nw) * 100) / 100,
  })
}
function up() {
  // A click on the window (no drag) plays/pauses, like clicking the video.
  if (dragging.value && origin && !origin.moved && origin.what === 'move') emit('toggle')
  dragging.value = false
}
function resetZoom() {
  if (zoom.value > 1) emit('focus', { x: props.focusX, y: props.focusY, zoom: 1 })
}
const round = (v) => Math.round(v * 1000) / 1000
</script>

<style scoped>
.frame-stage {
  position: relative; display: grid; place-items: center;
  background: #121812; border-radius: var(--radius); overflow: hidden;
}
.box { position: relative; overflow: hidden; }
.media { position: absolute; }
.media video, .media img { width: 100%; height: 100%; display: block; object-fit: fill; }
.media video { cursor: pointer; }
.blurbg { position: absolute; inset: -10%; width: 120%; height: 120%; object-fit: cover; filter: blur(18px) brightness(0.8); }
.window {
  position: absolute; box-shadow: 0 0 0 9999px rgb(10 14 10 / 62%);
  outline: 2px solid var(--sage); touch-action: none;
}
.corner {
  position: absolute; width: 18px; height: 18px; background: var(--sage);
  border: 2px solid var(--paper); border-radius: 3px; z-index: 2; touch-action: none;
}
/* inside the window, so they stay grabbable when it touches the frame's edge */
.corner.nw { left: 2px; top: 2px; cursor: nwse-resize; }
.corner.se { right: 2px; bottom: 2px; cursor: nwse-resize; }
.corner.ne { right: 2px; top: 2px; cursor: nesw-resize; }
.corner.sw { left: 2px; bottom: 2px; cursor: nesw-resize; }
.zoomtag {
  position: absolute; left: 50%; bottom: 8px; transform: translateX(-50%); font-size: 11px; font-weight: 700; pointer-events: none;
  padding: 1px 7px; border-radius: 999px; background: var(--sage); color: var(--forest);
}
.window.movable { pointer-events: auto; cursor: grab; touch-action: none; }
.window.dragging { cursor: grabbing; }
.hint {
  position: absolute; top: 8px; left: 50%; transform: translateX(-50%); white-space: nowrap;
  font-size: 11px; padding: 2px 8px; border-radius: 999px; background: rgb(31 42 31 / 70%); color: var(--cream);
  pointer-events: none;
}
.defs { position: absolute; width: 0; height: 0; }
/* transition previews */
.box.fx-flash::after, .box.fx-dip::after {
  content: ''; position: absolute; inset: 0; z-index: 3; pointer-events: none;
  animation: fx-fade 0.22s ease-out forwards;
}
.box.fx-flash::after { background: #fff; }
.box.fx-dip::after { background: #000; animation-duration: 0.35s; }
@keyframes fx-fade { from { opacity: 0.95; } to { opacity: 0; } }
.box.fx-whip .media { animation: fx-whip 0.22s ease-out; }
@keyframes fx-whip {
  from { transform: translateX(45%); filter: blur(10px); }
  to { transform: none; filter: none; }
}
.box.fx-zoom .media { animation: fx-zoom 0.3s cubic-bezier(0.2, 0.7, 0.3, 1); }
@keyframes fx-zoom { from { transform: scale(1.18); } to { transform: scale(1); } }
.box.fx-dissolve .media { animation: fx-in 0.3s ease-out; }
@keyframes fx-in { from { opacity: 0.2; } to { opacity: 1; } }
:deep(.guides) { position: absolute; inset: 0; pointer-events: none; }
:deep(.g-caption), :deep(.g-buttons) {
  position: absolute; display: grid; place-items: center; font-size: 10px; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--cream); background: rgb(247 241 227 / 18%);
  border: 1px dashed rgb(247 241 227 / 60%);
}
:deep(.g-caption) { left: 0; right: 16%; bottom: 0; height: 20%; }
:deep(.g-buttons) { right: 0; width: 14%; bottom: 0; height: 45%; }
</style>
