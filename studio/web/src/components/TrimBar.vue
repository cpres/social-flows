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
      <div class="playhead" :style="{ left: pct(playhead) }"></div>
    </div>
    <div class="ruler muted">
      <span>0:00</span><span>{{ fmtTime(duration / 2) }}</span><span>{{ fmtTime(duration) }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { clamp, fmtTime } from '../time'

const MIN_LEN = 0.2

const props = defineProps({
  duration: { type: Number, required: true },
  start: { type: Number, required: true },
  length: { type: Number, required: true },
  playhead: { type: Number, default: 0 },
  thumbAt: { type: Function, required: true },
})
const emit = defineEmits(['update', 'seek', 'dragend'])

const bar = ref(null)
let mode = null
let grabOffset = 0

// A thumbnail every ~20s of footage, between 6 and 14 frames.
const stripTimes = computed(() => {
  const d = props.duration
  if (!d) return []
  const n = clamp(Math.round(d / 20), 6, 14)
  return Array.from({ length: n }, (_, i) => Math.round(((i + 0.5) * d) / n))
})

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

function move(e) {
  if (!mode) return
  const t = timeAt(e)
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
  if (mode && mode !== 'seek') emit('dragend')
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
.playhead {
  position: absolute; top: -6px; bottom: -6px; width: 2px; margin-left: -1px;
  background: var(--cream); box-shadow: 0 0 0 1px var(--forest); pointer-events: none; z-index: 3;
}
.ruler { display: flex; justify-content: space-between; font-size: 11px; margin-top: 30px; font-family: ui-monospace, monospace; }
</style>
