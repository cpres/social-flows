<template>
  <div class="split">
    <div
      ref="bar" class="bar"
      @pointerdown="down($event, -1)" @pointermove="move" @pointerup="up" @pointercancel="up"
    >
      <div class="strip">
        <img v-for="t in stripTimes" :key="t" :src="thumbAt(t)" alt="" draggable="false" />
      </div>
      <div v-for="(g, i) in gaps" :key="`g${i}`" class="shade" :style="{ left: pct(g[0]), width: pct(g[1] - g[0]) }"></div>
      <div
        v-for="(s, j) in starts" :key="j" class="win" :class="{ on: j === selected }"
        :style="{ left: pct(s), width: pct(lenOf(j)) }" :title="`${letter(j)}: ${fmtTime(s)} → ${fmtTime(s + lenOf(j))}`"
        @pointerdown.stop="down($event, j)"
      >
        <span class="tag">{{ letter(j) }}</span>
      </div>
      <div class="playhead" :style="{ left: pct(playhead) }"></div>
    </div>
    <!-- how much happens along the clip: the server's movement measure -->
    <svg v-if="activity?.length" class="lane" :viewBox="`0 0 ${duration || 1} 1`" preserveAspectRatio="none" aria-hidden="true">
      <path :d="area" />
    </svg>
    <div v-else class="lane empty muted">{{ activity === null ? 'Measuring movement…' : '' }}</div>
    <div class="ruler muted">
      <span>0:00</span><span>{{ fmtTime(duration / 2) }}</span><span>{{ fmtTime(duration) }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { clamp, fmtTime, stripTimes as filmstrip } from '../time'
import { letter } from '../weave'

// A clip's parts for Weave: several windows, each as long as its part, that
// slide along the filmstrip but never cross, so a always comes before b.
const props = defineProps({
  duration: { type: Number, required: true },
  starts: { type: Array, required: true },
  length: { type: [Number, Array], required: true },   // one for every window, or one each
  selected: { type: Number, default: 0 },
  playhead: { type: Number, default: 0 },
  thumbAt: { type: Function, required: true },
  activity: { type: Array, default: undefined },   // [[t, 0..1]]; null while it's being measured
})
const emit = defineEmits(['update', 'select', 'seek', 'dragend'])

const bar = ref(null)
let dragging = null   // the window being dragged, or -1 to scrub
let grabOffset = 0

const stripTimes = computed(() => filmstrip(props.duration))
const pct = (t) => `${(clamp(t, 0, props.duration) / (props.duration || 1)) * 100}%`
const lenOf = (j) => (Array.isArray(props.length) ? props.length[j] : props.length)

// The footage between the windows, dimmed.
const gaps = computed(() => {
  const out = []
  let at = 0
  const wins = props.starts.map((s, j) => [s, s + lenOf(j)]).sort((a, b) => a[0] - b[0])
  for (const [s, e] of wins) {
    if (s > at) out.push([at, s])
    at = Math.max(at, e)
  }
  if (at < props.duration) out.push([at, props.duration])
  return out
})

const area = computed(() => {
  const pts = props.activity
  const d = props.duration || 1
  return `M0,1 ${pts.map(([t, v]) => `L${t},${1 - v * 0.9}`).join(' ')} L${d},1 Z`
})

function timeAt(e) {
  const r = bar.value.getBoundingClientRect()
  return clamp(((e.clientX - r.left) / r.width) * props.duration, 0, props.duration)
}

function down(e, j) {
  dragging = j
  bar.value.setPointerCapture(e.pointerId)
  if (j >= 0) {
    emit('select', j)
    grabOffset = timeAt(e) - props.starts[j]
  }
  move(e)
}

function move(e) {
  if (dragging === null) return
  const t = timeAt(e)
  if (dragging < 0) return emit('seek', t)
  const j = dragging
  const s = props.starts
  const len = lenOf(j)
  // Between its neighbours; where they already overlap, just keep the order.
  let lo = j > 0 ? s[j - 1] + lenOf(j - 1) : 0
  let hi = j < s.length - 1 ? s[j + 1] - len : props.duration - len
  if (lo > hi) {
    lo = j > 0 ? s[j - 1] : 0
    hi = j < s.length - 1 ? s[j + 1] : props.duration - len
  }
  const next = Math.round(clamp(t - grabOffset, lo, Math.max(lo, hi)) * 100) / 100
  const starts = [...s]
  starts[j] = next
  emit('update', starts)
  emit('seek', next)
}

function up() {
  if (dragging !== null && dragging >= 0) emit('dragend')
  dragging = null
}
</script>

<style scoped>
.split { user-select: none; }
.bar {
  position: relative; height: 64px; border-radius: 8px; background: var(--forest);
  cursor: pointer; touch-action: none; margin-top: 22px;
}
.strip { position: absolute; inset: 0; display: flex; border-radius: 8px; overflow: hidden; }
.strip img { flex: 1; min-width: 0; height: 100%; object-fit: cover; pointer-events: none; }
.shade { position: absolute; top: 0; bottom: 0; background: rgb(20 28 20 / 62%); pointer-events: none; }
.win {
  position: absolute; top: -3px; bottom: -3px; min-width: 8px; cursor: grab; border-radius: 4px;
  border: 2px solid var(--sage); box-shadow: 0 0 0 1px rgb(20 28 20 / 50%);
}
.win:active { cursor: grabbing; }
.win.on { border: 3px solid var(--cream); box-shadow: 0 0 0 2px var(--forest); z-index: 2; }
.tag {
  position: absolute; top: -21px; left: 50%; transform: translateX(-50%);
  font-size: 12px; font-weight: 700; color: var(--forest); font-family: ui-monospace, monospace;
}
.win.on .tag { background: var(--forest); color: var(--cream); padding: 0 6px; border-radius: 999px; }
.playhead {
  position: absolute; top: -6px; bottom: -6px; width: 2px; margin-left: -1px;
  background: var(--on-media); box-shadow: 0 0 0 1px #1f2a1f; pointer-events: none; z-index: 3;
}
.lane { display: block; width: 100%; height: 22px; margin-top: 6px; }
.lane path { fill: var(--sage); opacity: 0.75; }
.lane.empty { font-size: 11px; line-height: 22px; }
.ruler { display: flex; justify-content: space-between; font-size: 11px; margin-top: 2px; font-family: ui-monospace, monospace; }
</style>
