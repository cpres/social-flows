<template>
  <div ref="box" class="bvis" :class="mode">
    <canvas ref="cv" role="img" :aria-label="label" @pointerdown="seek"></canvas>
  </div>
</template>

<script setup>
// The beat studio's picture of the music, drawn on a canvas every frame:
// - idle: the planned beat (its sections, energy curve and hits), bars
//   pulsing on the beat at its tempo;
// - generating: each take's lane filling as its audio arrives;
// - playing: the take's own waveform, a playhead, and live frequency bars.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { curveAt } from '../beat'

const props = defineProps({
  length: { type: Number, default: 0 },
  sections: { type: Array, default: () => [] },   // [{ start, end, name, energy }]
  curve: { type: Array, default: () => [[0, 0.5], [1, 0.5]] },
  edges: { type: Array, default: () => [] },      // scene changes, seconds
  hits: { type: Boolean, default: true },
  tempo: { type: Number, default: 100 },
  mode: { type: String, default: 'idle' },         // idle | generating | playing
  takes: { type: Array, default: () => [] },       // generating: [{ n, label, state, received, expected }]
  envelope: { type: Object, default: null },       // playing: { step, db: [...] }
  time: { type: Number, default: 0 },              // playing: where the take is
  analyser: { type: Object, default: null },       // playing: a Web Audio AnalyserNode
})
const emit = defineEmits(['seek'])

const box = ref(null)
const cv = ref(null)
const label = computed(() => (props.mode === 'playing' ? 'The take playing, its waveform and frequencies'
  : props.mode === 'generating' ? 'The takes arriving as they are made'
    : `The planned beat: ${props.sections.map((s) => s.name).join(', ')}`))

let raf = 0
let ro = null
let w = 0
let h = 0
const t0 = performance.now()
const bins = new Uint8Array(64)

function colors() {
  const cs = getComputedStyle(box.value)
  const v = (k, d) => cs.getPropertyValue(k).trim() || d
  return {
    blue: v('--v-blue', '#8fb0dc'), soft: v('--v-soft', 'rgba(143,176,220,0.16)'), ink: v('--v-ink', '#e4e7ea'),
    muted: v('--v-muted', '#98a0a8'), hit: v('--v-hit', '#e08038'), band: v('--v-band', 'rgba(255,255,255,0.035)'),
    cream: v('--v-cream', '#efe6cf'), dim: v('--v-dim', 'rgba(143,176,220,0.22)'),
  }
}

function size() {
  const r = box.value.getBoundingClientRect()
  const dpr = window.devicePixelRatio || 1
  w = Math.max(200, r.width)
  h = Math.max(160, r.height)
  cv.value.width = Math.round(w * dpr)
  cv.value.height = Math.round(h * dpr)
  cv.value.style.width = `${w}px`
  cv.value.style.height = `${h}px`
  cv.value.getContext('2d').setTransform(dpr, 0, 0, dpr, 0, 0)
}

const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`
const hash = (i) => { const x = Math.sin(i * 12.9898) * 43758.5453; return x - Math.floor(x) }

function draw() {
  raf = requestAnimationFrame(draw)
  if (!cv.value || document.hidden) return
  const g = cv.value.getContext('2d')
  const c = colors()
  const L = props.length || 1
  const now = (performance.now() - t0) / 1000
  const top = 26
  const foot = 30
  const mid = top + (h - top - foot) / 2
  const amp = (h - top - foot) / 2 - 4
  const X = (s) => (s / L) * w
  g.clearRect(0, 0, w, h)

  // sections: soft bands, names on top, start times underneath
  props.sections.forEach((s, i) => {
    const x0 = X(s.start)
    const x1 = X(s.end)
    if (i % 2 === 0) { g.fillStyle = c.band; g.fillRect(x0, top - 6, x1 - x0, h - top - foot + 12) }
    g.fillStyle = c.muted
    g.font = '600 11px ui-sans-serif, system-ui, sans-serif'
    g.textBaseline = 'alphabetic'
    if (x1 - x0 > 46) g.fillText(s.name.toUpperCase(), x0 + 8, 16)
    g.font = '11px ui-monospace, Menlo, monospace'
    if (x1 - x0 > 34) g.fillText(fmt(s.start), x0 + 8, h - 10)
  })

  // the energy curve behind the bars
  g.beginPath()
  for (let i = 0; i <= 160; i++) {
    const f = i / 160
    const y = mid - curveAt(props.curve, f) * amp
    if (i) g.lineTo(f * w, y); else g.moveTo(0, y)
  }
  for (let i = 160; i >= 0; i--) g.lineTo((i / 160) * w, mid + curveAt(props.curve, i / 160) * amp)
  g.closePath()
  g.fillStyle = c.soft
  g.fill()

  // bars
  const n = Math.max(24, Math.floor(w / 7))
  const bw = Math.max(2, (w / n) * 0.62)
  const beat = 60 / (props.tempo || 100)
  const env = props.envelope
  let done = 1   // generating: how far the furthest take has come (0..1)
  if (props.mode === 'generating') {
    done = Math.max(0, ...props.takes.map((t) => (t.expected ? t.received / t.expected : 0)))
  }
  const played = props.mode === 'playing' ? props.time / L : 1
  for (let i = 0; i < n; i++) {
    const f = (i + 0.5) / n
    let a
    if (props.mode === 'playing' && env?.db?.length) {
      // the take itself: its loudness over this bar's stretch
      const a0 = Math.floor((f - 0.5 / n) * L / env.step)
      const a1 = Math.max(a0 + 1, Math.floor((f + 0.5 / n) * L / env.step))
      let p = 0
      for (let j = a0; j < a1; j++) p += 10 ** ((env.db[j] ?? -70) / 10)
      const db = 10 * Math.log10(p / (a1 - a0) || 1e-9)
      a = Math.max(0.03, Math.min(1, (db + 54) / 54))
    } else {
      // the plan: the curve, pulsing on the beat, rippling across the reel
      const phase = ((now + f * L * 0.04) / beat) % 1
      const pulse = Math.exp(-phase * 3.2)
      a = curveAt(props.curve, f) * (0.45 + 0.4 * pulse + 0.15 * hash(i + Math.floor(now / beat)))
      a = Math.max(0.04, a)
    }
    const x = f * w - bw / 2
    let fill = c.blue
    if (props.mode === 'generating' && f > done) {
      // not here yet: a faint scan sweeping across
      const scan = Math.max(0, 1 - Math.abs(((now * 0.35) % 1.2) - f) * 6)
      g.globalAlpha = 0.18 + 0.4 * scan
    } else if (props.mode === 'playing' && f > played) {
      g.globalAlpha = 0.32
    } else g.globalAlpha = 1
    g.fillStyle = fill
    g.fillRect(x, mid - a * amp, bw, a * amp * 2)
  }
  g.globalAlpha = 1

  // scene changes, and the hits that land on them
  g.save()
  g.setLineDash([4, 4])
  g.strokeStyle = c.hit
  g.lineWidth = 1.2
  for (const e of props.edges) {
    const x = X(e)
    g.beginPath(); g.moveTo(x, top - 4); g.lineTo(x, h - foot + 4); g.stroke()
    if (props.hits) {
      g.setLineDash([])
      g.fillStyle = c.hit
      g.beginPath(); g.moveTo(x, top - 8); g.lineTo(x + 5, top - 3); g.lineTo(x, top + 2); g.lineTo(x - 5, top - 3); g.closePath(); g.fill()
      g.setLineDash([4, 4])
    }
  }
  g.restore()

  // generating: a lane per take filling as its audio arrives
  if (props.mode === 'generating') {
    const lane = 4
    props.takes.forEach((t, k) => {
      const y = h - foot - 4 - (props.takes.length - k) * (lane + 4)
      g.fillStyle = c.dim
      g.fillRect(0, y, w, lane)
      const p = t.expected ? Math.min(1, t.received / t.expected) : 0
      g.fillStyle = t.state === 'failed' ? c.hit : t.state === 'done' ? c.cream : c.blue
      g.fillRect(0, y, p * w, lane)
      if (t.state === 'receiving' || t.state === 'asking') {   // a glowing head where it's arriving
        const hx = t.state === 'asking' ? ((now * 0.25 + k * 0.3) % 1) * w : p * w
        const grd = g.createRadialGradient(hx, y + 2, 0, hx, y + 2, 14)
        grd.addColorStop(0, c.cream); grd.addColorStop(1, 'rgba(0,0,0,0)')
        g.fillStyle = grd
        g.fillRect(hx - 14, y - 10, 28, 24)
      }
    })
  }

  // playing: the playhead and live frequencies
  if (props.mode === 'playing') {
    const x = played * w
    g.fillStyle = c.cream
    g.fillRect(x - 1, top - 8, 2, h - top - foot + 16)
    if (props.analyser) {
      props.analyser.getByteFrequencyData(bins)
      const m = 48
      const fw = Math.min(10, (w * 0.5) / m)
      for (let i = 0; i < m; i++) {
        const v = bins[Math.floor((i / m) ** 1.6 * bins.length)] / 255
        g.fillStyle = c.cream
        g.globalAlpha = 0.25 + 0.6 * v
        g.fillRect(w - (m - i) * fw - 8, h - foot - 2 - v * 46, fw - 2, v * 46)
      }
      g.globalAlpha = 1
    }
  }
}

function seek(e) {
  if (props.mode !== 'playing') return
  const r = cv.value.getBoundingClientRect()
  emit('seek', ((e.clientX - r.left) / r.width) * (props.length || 0))
}

onMounted(() => {
  size()
  ro = new ResizeObserver(size)
  ro.observe(box.value)
  raf = requestAnimationFrame(draw)
})
onBeforeUnmount(() => { cancelAnimationFrame(raf); ro?.disconnect() })
</script>

<style scoped>
.bvis { position: relative; width: 100%; height: 100%; }
canvas { display: block; }
.bvis.playing canvas { cursor: pointer; }
</style>
