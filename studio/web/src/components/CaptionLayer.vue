<template>
  <!-- The captions over a 9:16 frame at reel time t, laid out like the render
       (sizes in % of the frame's width, as the engine's). -->
  <div class="caplayer" aria-hidden="true">
    <div v-if="group && bg === 'scrim'" class="scrim" :style="{ opacity: frame.shown }"></div>
    <div class="column" :style="columnStyle">
    <template v-if="group">
      <div class="block" :class="[`st-${variant}`, `bg-${bg}`]" :style="[blockStyle, frame.move]">
        <div v-if="bg !== 'scrim' && bg !== 'shadow'" class="fill" :style="{ opacity: frame.shown }"></div>
        <span v-if="variant === 'page' && title" class="ttl" :style="{ opacity: 0.75 * frame.shown }">{{ title }}</span>
        <span
          v-for="(l, i) in group.lines" :key="`${l.start}-${i}`" class="ln"
          :style="{ opacity: frame.lines[i] }"
        ><span v-for="(r, k) in lineRuns[i]" :key="k" :style="r.fx ? { textShadow: frame.shadows[`${i}.${k}`] } : null">{{ r.text }}</span></span>
      </div>
    </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, shallowRef, watch } from 'vue'
import {
  addCaptionFonts, CAPTION_BOX, captionGroups, emphasisShadow, envelope, fontFamily, fontOf, lineOpacity, styleOf,
} from '../captions'

const props = defineProps({
  lines: { type: Array, default: () => [] },   // on the reel's clock: { start, end, text, stanza }
  variant: { type: String, default: 'breath' },   // the caption style: stanza | unfold | breath | page
  font: { type: String, default: 'cormorant-italic' },
  bg: { type: String, default: 'shadow' },
  size: { type: Number, default: 1 },
  title: { type: String, default: '' },
  t: { type: Number, default: 0 },
  clock: { type: Function, default: null },      // while playing: reads the reel's time, instead of t
  fx: { type: Boolean, default: true },          // show voice effects on their words
  ratio: { type: Number, default: 9 / 16 },      // the frame's width / height
})
// The words sit in a centred column no wider than the frame is tall (as the render).
const columnStyle = computed(() => {
  const w = 100 / Math.max(1, props.ratio)
  return { left: `${(100 - w) / 2}%`, width: `${w}%` }
})
addCaptionFonts()

const groups = computed(() => captionGroups(props.lines, props.variant))

// What's on screen, worked out from the time but only handed to the page when
// it looks different (opacities to 2%, moves to 0.05% of the width): a line
// that's simply showing costs nothing. With a clock, the layer keeps its own
// time, at most 30 times a second, so playing the reel doesn't redraw it.
const now = shallowRef(props.t)
const groupIdx = computed(() => groups.value.findIndex((g) => now.value >= g.a && now.value <= g.b))
const group = computed(() => groups.value[groupIdx.value] || null)
const lineRuns = computed(() => (group.value ? group.value.lines.map(runs) : []))
const EMPTY = { shown: 0, lines: [], shadows: {}, move: null, key: '' }
const frame = shallowRef(EMPTY)
const q = (v, step) => Math.round(v / step) * step
function look(t) {
  const g = group.value
  if (!g) return EMPTY
  const shown = q(envelope(t, g.a, g.b, g.fi, g.fo), 0.02)
  const lines = g.segs.map((segs) => q(lineOpacity(segs, t), 0.02))
  const shadows = {}
  lineRuns.value.forEach((rs, i) => rs.forEach((r, k) => { if (r.fx) shadows[`${i}.${k}`] = shadowFor(r.fx, t) }))
  let move = null
  if (props.variant === 'breath') {
    // rises 2.2% of the width as it comes in, 1.2% as it goes (as the render)
    const y = 2.2 * Math.max(0, 1 - (t - g.a) / Math.max(g.fi, 0.01)) - 1.2 * Math.max(0, 1 - (g.b - t) / Math.max(g.fo, 0.01))
    move = { transform: `translateY(calc(-50% + ${q(y, 0.05).toFixed(2)}cqw))` }
  }
  return { shown, lines, shadows, move, key: `${groupIdx.value}|${shown}|${lines.join(',')}|${move?.transform}|${Object.values(shadows).join('|')}` }
}
function update(t) {
  now.value = t
  const next = look(t)
  if (next.key !== frame.value.key) frame.value = next
}
watch(() => [props.t, group.value, lineRuns.value, props.bg, props.variant], () => { if (!props.clock) update(props.t) },
  { immediate: true })
let raf
let last = 0
function tick(ts) {
  if (ts - last >= 33) {
    last = ts
    update(props.clock() ?? 0)
  }
  raf = requestAnimationFrame(tick)
}
watch(() => props.clock, (c) => {
  cancelAnimationFrame(raf)
  if (c) { update(c() ?? 0); raf = requestAnimationFrame(tick) }
}, { immediate: true })
onBeforeUnmount(() => cancelAnimationFrame(raf))

// A line in runs of words: plain, or lifted out by effects.
function runs(l) {
  if (!props.fx || !l.fx?.length) return [{ text: l.text }]
  const words = l.text.split(' ')
  const out = []
  words.forEach((w, i) => {
    const hits = l.fx.filter((f) => i >= f.words[0] && i <= f.words[1])
    const last = out[out.length - 1]
    const sp = i < words.length - 1 ? ' ' : ''
    if (last && sameFx(last.fx, hits)) last.text += w + sp
    else out.push({ text: w + sp, fx: hits.length ? hits : null })
  })
  return out
}
const sameFx = (a, b) => (a || []).length === b.length && b.every((f, i) => a[i] === f)
// The effect's copies under the words, plus the line's own shadow where it has one.
function shadowFor(fxs, t) {
  const fx = emphasisShadow(fxs, t, props.bg === 'paper')
  const own = props.bg === 'shadow' || props.bg === 'scrim' ? '0 0.3cqw 2.4cqw rgb(0 0 0 / 55%)' : ''
  return [fx, own].filter(Boolean).join(', ') || 'none'
}

const blockStyle = computed(() => {
  const f = fontOf(props.font)
  const [side, padX, padY] = CAPTION_BOX[props.bg] || CAPTION_BOX.shadow
  const s = {
    left: `${side}cqw`, right: `${side}cqw`, padding: `${padY}cqw ${padX}cqw`,
    fontFamily: fontFamily(props.font), fontWeight: f.weight,
    fontSize: `${styleOf(props.variant).size * f.scale * (props.size || 1)}cqw`,
  }
  return s
})
</script>

<style scoped>
.caplayer { position: absolute; inset: 0; pointer-events: none; z-index: 2; overflow: hidden; contain: strict; }
.column { position: absolute; top: 0; bottom: 0; container-type: inline-size; }
.scrim { position: absolute; inset: 0; background: rgb(45 62 38 / 48%); }
.block { position: absolute; bottom: 25%; color: #f7f1e3; text-align: center; line-height: 1.32; }
.block.st-breath { bottom: auto; top: 50%; }
.block.st-page { text-align: left; }
.fill { position: absolute; inset: 0; }
.bg-band .fill { background: rgb(45 62 38 / 64%); }
.bg-paper { color: #2d3e26; }
.bg-paper .fill { background: rgb(247 241 227 / 95%); border-radius: 0.8cqw; box-shadow: 0 1cqw 4cqw rgb(0 0 0 / 30%); }
.bg-blur .fill { background: rgb(18 24 18 / 26%); -webkit-backdrop-filter: blur(2.4cqw); backdrop-filter: blur(2.4cqw); }
.bg-shadow .ln, .bg-scrim .ln { text-shadow: 0 0.3cqw 2.4cqw rgb(0 0 0 / 55%); }
/* each line on its own layer: fading it doesn't redraw the text */
.ln { position: relative; display: block; text-wrap: balance; will-change: opacity; }
.block { will-change: transform; }
.st-page .ln { text-wrap: wrap; }
.ttl {
  position: relative; display: block; font-size: 0.62em; letter-spacing: 0.14em; text-transform: uppercase;
  margin-bottom: 0.9em;
}
</style>
