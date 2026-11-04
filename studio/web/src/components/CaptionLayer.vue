<template>
  <!-- The captions over a 9:16 frame at reel time t, laid out like the render
       (sizes in % of the frame's width, as the engine's). -->
  <div class="caplayer" aria-hidden="true">
    <div v-if="group && bg === 'scrim'" class="scrim" :style="{ opacity: shown }"></div>
    <div class="column" :style="columnStyle">
    <template v-if="group">
      <div class="block" :class="[`st-${variant}`, `bg-${bg}`]" :style="blockStyle">
        <div v-if="bg !== 'scrim' && bg !== 'shadow'" class="fill" :style="{ opacity: shown }"></div>
        <span v-if="variant === 'page' && title" class="ttl" :style="{ opacity: 0.75 * shown }">{{ title }}</span>
        <span
          v-for="(l, i) in group.lines" :key="`${l.start}-${i}`" class="ln"
          :style="{ opacity: lineOpacity(group.segs[i], t) }"
        ><span v-for="(r, k) in runs(l)" :key="k" :style="r.fx ? { textShadow: shadowFor(r.fx) } : null">{{ r.text }}</span></span>
      </div>
    </template>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
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
const group = computed(() => groups.value.find((g) => props.t >= g.a && props.t <= g.b) || null)
const shown = computed(() => (group.value ? envelope(props.t, group.value.a, group.value.b, group.value.fi, group.value.fo) : 0))

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
function shadowFor(fxs) {
  const fx = emphasisShadow(fxs, props.t, props.bg === 'paper')
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
  if (props.variant === 'breath' && group.value) {
    // rises 2.2% of the width as it comes in, 1.2% as it goes (as the render)
    const g = group.value
    const y = 2.2 * Math.max(0, 1 - (props.t - g.a) / Math.max(g.fi, 0.01))
      - 1.2 * Math.max(0, 1 - (g.b - props.t) / Math.max(g.fo, 0.01))
    s.transform = `translateY(calc(-50% + ${y.toFixed(3)}cqw))`
  }
  return s
})
</script>

<style scoped>
.caplayer { position: absolute; inset: 0; pointer-events: none; z-index: 2; overflow: hidden; }
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
.ln { position: relative; display: block; text-wrap: balance; }
.st-page .ln { text-wrap: wrap; }
.ttl {
  position: relative; display: block; font-size: 0.62em; letter-spacing: 0.14em; text-transform: uppercase;
  margin-bottom: 0.9em;
}
</style>
