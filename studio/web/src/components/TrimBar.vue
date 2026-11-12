<template>
  <div class="trim">
    <div
      ref="bar" class="bar"
      @pointerdown="down($event, 'seek')" @pointermove="move" @pointerup="up" @pointercancel="up"
    >
      <div class="strip">
        <img v-for="t in stripTimes" :key="t" :src="thumbAt(t)" alt="" draggable="false" />
      </div>
      <div class="shade" :style="{ left: 0, width: pct(start) }"></div>
      <div class="shade" :style="{ left: pct(start + length), right: 0 }"></div>
      <div
        class="sel" :style="{ left: pct(start), width: pct(length) }"
        @pointerdown.stop="down($event, 'move')"
      >
        <span class="len">{{ length.toFixed(1) }}s</span>
      </div>
      <div class="handle in" :style="{ left: pct(start) }" @pointerdown.stop="down($event, 'start')">
        <span class="tip">{{ fmtTime(start) }}</span>
      </div>
      <div class="handle out" :style="{ left: pct(start + length) }" @pointerdown.stop="down($event, 'end')">
        <span class="tip">{{ fmtTime(start + length) }}</span>
      </div>
      <button
        v-for="(t, i) in pins" :key="`p${i}`" class="pin" :class="{ on: i === pinOn }" :style="{ left: pct(t) }"
        :title="`Highlight at ${fmtTime(t)}: click to centre the selection on it, drag to move it, double-click to take it off`"
        @pointerdown.stop="downPin($event, i)"
      >★</button>
      <div class="playhead" :style="{ left: pct(playhead) }"></div>
    </div>
    <div class="lane">
      <button
        v-for="seg in segments" :key="seg.id" class="part"
        :style="{ left: pct(seg.start), width: pct(seg.length), background: seg.color }"
        :title="seg.label" @click="$emit('pick', seg.id)"
      ></button>
    </div>
    <div class="ruler muted">
      <span>0:00</span><span>{{ fmtTime(duration / 2) }}</span><span>{{ fmtTime(duration) }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { clamp, fmtTime, stripTimes as filmstrip } from '../time'

const MIN_LEN = 0.2

const props = defineProps({
  duration: { type: Number, required: true },
  start: { type: Number, required: true },
  length: { type: Number, required: true },
  playhead: { type: Number, default: 0 },
  thumbAt: { type: Function, required: true },
  // Other parts of this clip (in any reel), drawn in a lane under the bar.
  segments: { type: Array, default: () => [] },
  // Highlights: moments pinned on the clip (seconds), drawn as ★ on the bar.
  pins: { type: Array, default: () => [] },
  pinOn: { type: Number, default: -1 },   // the one the selection is centred on
})
const emit = defineEmits(['update', 'seek', 'dragend', 'pick', 'pin-click', 'pin-move', 'pin-drop', 'pin-remove'])

const bar = ref(null)
let mode = null
let grabOffset = 0

const stripTimes = computed(() => filmstrip(props.duration))

const pct = (t) => `${(clamp(t, 0, props.duration) / (props.duration || 1)) * 100}%`

function timeAt(e) {
  const r = bar.value.getBoundingClientRect()
  return clamp(((e.clientX - r.left) / r.width) * props.duration, 0, props.duration)
}

function down(e, m) {
  mode = m
  bar.value.setPointerCapture(e.pointerId)
  grabOffset = timeAt(e) - props.start
  move(e)
}

// A ★: click centres the selection on it, drag moves it, a second press
// straight after takes it off. (The bar holds the pointer while a ★ is
// pressed, so the browser's own double-click would land on the bar.)
let pinDrag = null   // { i, moved }
let lastPin = { i: -1, at: 0 }
function downPin(e, i) {
  const now = performance.now()
  if (lastPin.i === i && now - lastPin.at < 400) {
    lastPin = { i: -1, at: now }
    return emit('pin-remove', i)
  }
  lastPin = { i, at: now }
  pinDrag = { i, moved: false, x: e.clientX }
  mode = 'pin'
  bar.value.setPointerCapture(e.pointerId)
}

function move(e) {
  if (!mode) return
  const t = timeAt(e)
  if (mode === 'pin') {
    if (!pinDrag.moved && Math.abs(e.clientX - pinDrag.x) < 4) return
    pinDrag.moved = true
    const at = Math.round(t * 100) / 100
    emit('pin-move', pinDrag.i, at)
    return emit('seek', at)
  }
  const d = props.duration
  const end = props.start + props.length
  if (mode === 'seek') {
    emit('seek', t)
  } else if (mode === 'start') {
    const s = clamp(t, 0, end - MIN_LEN)
    emit('update', { start: s, length: end - s })
    emit('seek', s)
  } else if (mode === 'end') {
    const e2 = clamp(t, props.start + MIN_LEN, d)
    emit('update', { start: props.start, length: e2 - props.start })
    emit('seek', e2)
  } else if (mode === 'move') {
    const s = clamp(t - grabOffset, 0, d - props.length)
    emit('update', { start: s, length: props.length })
    emit('seek', s)
  }
}

function up() {
  if (mode === 'pin') {
    emit(pinDrag.moved ? 'pin-drop' : 'pin-click', pinDrag.i)
    pinDrag = null
  } else if (mode && mode !== 'seek') emit('dragend')
  mode = null
}
</script>

<style scoped>
.trim { user-select: none; }
.bar {
  position: relative; height: 64px; border-radius: 8px; overflow: visible;
  background: var(--forest); cursor: pointer; touch-action: none;
}
.strip { position: absolute; inset: 0; display: flex; border-radius: 8px; overflow: hidden; }
.strip img { flex: 1; min-width: 0; height: 100%; object-fit: cover; pointer-events: none; }
.shade { position: absolute; top: 0; bottom: 0; background: rgb(20 28 20 / 62%); pointer-events: none; }
.shade:first-of-type { border-radius: 8px 0 0 8px; }
.sel {
  position: absolute; top: 0; bottom: 0; cursor: grab;
  border-top: 3px solid var(--sage); border-bottom: 3px solid var(--sage);
}
.sel:active { cursor: grabbing; }
.len {
  position: absolute; left: 50%; bottom: -26px; transform: translateX(-50%);
  font-size: 12px; font-weight: 700; color: var(--forest); white-space: nowrap;
}
.handle {
  position: absolute; top: -4px; bottom: -4px; width: 12px; margin-left: -6px;
  background: var(--sage); border-radius: 4px; cursor: ew-resize; z-index: 2;
  box-shadow: 0 0 0 2px var(--paper);
}
.handle::after {
  content: ''; position: absolute; left: 5px; top: 35%; bottom: 35%; width: 2px;
  background: var(--forest); border-radius: 1px;
}
.tip {
  position: absolute; top: -22px; left: 50%; transform: translateX(-50%);
  font-size: 11px; font-family: ui-monospace, monospace; color: var(--forest); white-space: nowrap;
}
.handle.in .tip { transform: translateX(-90%); }
.handle.out .tip { transform: translateX(-10%); }
.pin {
  position: absolute; top: -13px; width: 22px; height: 22px; margin-left: -11px; padding: 0;
  border: 0; border-radius: 999px; background: var(--forest); color: #f2c94c;
  font-size: 14px; line-height: 22px; cursor: grab; z-index: 4; box-shadow: 0 0 0 2px var(--paper);
}
.pin.on { box-shadow: 0 0 0 2px var(--paper), 0 0 0 4px #f2c94c; }
.pin:active { cursor: grabbing; }
.playhead {
  position: absolute; top: -6px; bottom: -6px; width: 2px; margin-left: -1px;
  background: var(--on-media); box-shadow: 0 0 0 1px #1f2a1f; pointer-events: none; z-index: 3;
}
.lane { position: relative; height: 10px; margin-top: 28px; }
.part {
  position: absolute; top: 0; bottom: 0; min-width: 4px; border: 0; padding: 0;
  border-radius: 3px; cursor: pointer; opacity: 0.85;
}
.part:hover { opacity: 1; outline: 2px solid var(--paper); }
.ruler { display: flex; justify-content: space-between; font-size: 11px; margin-top: 4px; font-family: ui-monospace, monospace; }
</style>
