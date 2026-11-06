<template>
  <div class="scene-stage" ref="stage" :style="{ height: `${size.h}px` }">
    <div class="scenebox" :style="{ width: `${size.w}px`, height: `${size.h}px` }">
      <div class="content" :style="moveStyle">
        <div
          v-for="lane in lanes" :key="lane" class="slot" :class="[`lane-${lane}`, { picked: picked === lane }]"
          :style="rectStyle(rectOf(lane))" @click.capture="pickSlot($event, lane)"
          :title="picked === lane ? '' : `Select what's in the ${lane} slot`"
        >
          <slot :name="lane" :max-h="px(rectOf(lane)).h" :out="rectOf(lane).w / rectOf(lane).h" :bind-a="bindA" />
          <span class="chip" :class="`lane-${lane}`">{{ lane }} · {{ where(lane) }}</span>
          <span v-if="captions[lane]" class="caption mono">{{ captions[lane].name }} {{ captions[lane].t }}</span>
        </div>
        <div
          v-if="slots.divider" class="divider" :class="slots.axis" :style="{ ...rectStyle(rectOf('divider')), background: dividerColor }"
          @pointerdown="down" @pointermove="move" @pointerup="up" @pointercancel="up"
          title="Drag to change the split · [ and ] nudge it"
        ><span class="ratio mono">{{ ratio }}</span></div>
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
// The reel's frame for one scene: each lane on screen in its slot (see
// scenes.js sceneSlots), a lane chip on each, and the divider between, which
// can be dragged to change the split. The A lane's video is kept at the
// reel's time (aT, aRate). A scene coming in moves as the render does:
// slide and push from the bottom (the right in a wide frame), dissolve.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { clamp } from '../time'

const props = defineProps({
  frameW: { type: Number, default: 1080 },
  frameH: { type: Number, default: 1920 },
  slots: { type: Object, required: true },    // sceneSlots(): {A?, B?, divider?, axis, first, second, d, full}
  dividerColor: { type: String, default: '#f7f1e3' },
  editing: { type: String, default: '' },      // which lane holds the selected part
  into: { type: Object, default: null },       // {type, p}: the scene coming in, p 0..1
  aT: { type: Number, default: 0 },            // where in the A clip the reel is
  aRate: { type: Number, default: 1 },
  aPlaying: Boolean,
  guides: Boolean,
  picked: { type: String, default: '' },        // which slot holds the selected part: outlined
  captions: { type: Object, default: () => ({}) }, // {A: {name, t}, B: ...}: the clip and time in it
})
const emit = defineEmits(['split', 'pick'])
// Clicking a slot that doesn't hold the selected part selects what's in it.
function pickSlot(e, lane) {
  if (props.picked === lane) return
  e.stopPropagation()
  e.preventDefault()
  emit('pick', lane)
}

// The lanes on screen, and while a morph runs, a lane leaving (it slides out
// as the others take its room, rather than leaving black behind).
const lanes = computed(() => ['A', 'B'].filter((l) => props.slots[l] || (props.into?.type === 'morph' && props.into.p < 1 && props.into.from?.[l])))
const wide = computed(() => props.frameW > props.frameH)
const where = (lane) => {
  if (!props.slots[lane]) return 'going'
  if (['A', 'B'].filter((l) => props.slots[l]).length === 1) return 'full frame'
  const first = props.slots[lane].x === 0 && props.slots[lane].y === 0
  return wide.value ? (first ? 'left' : 'right') : (first ? 'top' : 'bottom')
}

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
const k = computed(() => size.value.w / props.frameW)
const px = (r) => ({ w: Math.round(r.w * k.value), h: Math.round(r.h * k.value) })
function rectStyle(r) {
  const p = px(r)
  return { left: `${Math.round(r.x * k.value)}px`, top: `${Math.round(r.y * k.value)}px`, width: `${p.w}px`, height: `${p.h}px` }
}

// A scene coming in: eased like the render's. A morph (into or out of Solo A)
// moves each lane's slot: A from where it was, B in from its side.
const ease = computed(() => 0.5 - 0.5 * Math.cos(Math.PI * clamp(props.into?.p ?? 1, 0, 1)))
function rectOf(lane) {
  const r = props.slots[lane]
  const t = props.into
  if (!t || t.type !== 'morph' || t.p >= 1) return r
  const e = ease.value
  const from = t.from?.[lane]
  if (!r) {   // leaving: out past its own edge
    const wideFrame = props.frameW > props.frameH
    if (wideFrame) return { ...from, x: from.x === 0 ? from.x - (from.x + from.w) * e : from.x + (props.frameW - from.x) * e }
    return { ...from, y: from.y === 0 ? from.y - (from.y + from.h) * e : from.y + (props.frameH - from.y) * e }
  }
  if (from) return { w: from.w + (r.w - from.w) * e, h: from.h + (r.h - from.h) * e, x: from.x + (r.x - from.x) * e, y: from.y + (r.y - from.y) * e }
  // arriving from its side: below (or right) if it sits after the other lane, else above (or left)
  const wideFrame = props.frameW > props.frameH
  const out = wideFrame ? (r.x > 0 ? props.frameW - r.x : -(r.x + r.w)) : (r.y > 0 ? props.frameH - r.y : -(r.y + r.h))
  return wideFrame ? { ...r, x: r.x + out * (1 - e) } : { ...r, y: r.y + out * (1 - e) }
}
const moveStyle = computed(() => {
  const t = props.into
  if (!t || t.type === 'cut' || t.type === 'morph' || t.p >= 1) return {}
  const e = 0.5 - 0.5 * Math.cos(Math.PI * clamp(t.p, 0, 1))
  if (t.type === 'dissolve') return { opacity: e }
  const off = `${(1 - e) * 100}%`
  return { transform: wide.value ? `translateX(${off})` : `translateY(${off})` }
})

// The divider: drag along the split to change the primary slot's share.
const ratio = computed(() => {
  const s = props.slots
  const a = Math.round((s.first / (s.first + s.second)) * 100)
  return `${a} / ${100 - a}`
})
let dragging = null
function down(e) {
  e.currentTarget.setPointerCapture(e.pointerId)
  const box = e.currentTarget.parentElement.getBoundingClientRect()
  dragging = { box }
}
function move(e) {
  if (!dragging) return
  const { box } = dragging
  const at = wide.value ? (e.clientX - box.left) / box.width : (e.clientY - box.top) / box.height
  emit('split', Math.round(clamp(at, 0.3, 0.7) * 50) / 50)
}
function up() { dragging = null }

// The A lane's video, when it isn't the one being edited: follow the reel's clock.
let aVideo = null
function bindA(el) {
  if (el === aVideo) return
  aVideo = el
  el?.addEventListener('loadedmetadata', syncA)
  syncA()
}
function syncA() {
  const v = aVideo
  if (!v || v.readyState < 1) return
  const rate = clamp(props.aRate, 0.0625, 16)
  if (!props.aPlaying || Math.abs(v.currentTime - props.aT) > 0.3 * Math.max(1, rate)) v.currentTime = props.aT
  if (props.aPlaying) {
    v.playbackRate = rate
    if (v.paused) v.play().catch(() => {})
  } else if (!v.paused) v.pause()
}
watch(() => [props.aT, props.aPlaying, props.aRate], syncA)
</script>

<style scoped>
.scene-stage {
  position: relative; display: grid; place-items: center;
  background: var(--stage); border-radius: var(--radius); overflow: hidden;
}
.scenebox { position: relative; overflow: hidden; background: #000; }
.content { position: absolute; inset: 0; }
.slot { position: absolute; overflow: hidden; }
.slot::after {
  content: ''; position: absolute; inset: 0; pointer-events: none; z-index: 4;
  box-shadow: inset 0 0 0 2px transparent; transition: box-shadow 0.15s;
}
.slot.lane-A::after { box-shadow: inset 0 0 0 2px var(--lane-a); }
.slot.lane-B::after { box-shadow: inset 0 0 0 2px var(--lane-b); }
.slot.picked::after { box-shadow: inset 0 0 0 2px var(--lane-a), inset 0 0 0 4px #fff; }
.slot.lane-B.picked::after { box-shadow: inset 0 0 0 2px var(--lane-b), inset 0 0 0 4px #fff; }
.slot:not(.picked) { cursor: pointer; }
.chip {
  position: absolute; left: 8px; top: 8px; z-index: 5; pointer-events: none;
  font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 6px; color: var(--on-lane);
}
.chip.lane-A { background: var(--lane-a); }
.chip.lane-B { background: var(--lane-b); }
.caption {
  position: absolute; left: 8px; bottom: 8px; z-index: 5; pointer-events: none; max-width: calc(100% - 16px);
  font-size: 11px; padding: 2px 7px; border-radius: 6px; background: rgb(0 0 0 / 60%); color: #fff;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.divider { position: absolute; z-index: 6; display: grid; place-items: center; touch-action: none; }
.divider.y { cursor: ns-resize; }
.divider.x { cursor: ew-resize; }
.divider::before { content: ''; position: absolute; inset: -6px; }
.ratio {
  position: relative; font-size: 11px; padding: 1px 8px; border-radius: 10px;
  background: var(--panel, #f7f1e3); color: var(--ink, #1d2a1d); box-shadow: 0 1px 3px rgb(0 0 0 / 30%); white-space: nowrap;
}
.guides { position: absolute; inset: 0; pointer-events: none; z-index: 7; }
.g-caption, .g-buttons {
  position: absolute; display: grid; place-items: center; font-size: 10px; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--on-media); background: rgb(247 241 227 / 18%);
  border: 1px dashed rgb(247 241 227 / 60%);
}
.g-caption { left: 0; right: 16%; bottom: 0; height: 20%; }
.g-buttons { right: 0; width: 14%; bottom: 0; height: 45%; }
</style>
