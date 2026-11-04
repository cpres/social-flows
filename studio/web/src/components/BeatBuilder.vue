<template>
  <div class="beatb">
    <header class="bhead">
      <div>
        <h4>Beat for {{ reelName }}</h4>
        <p class="muted small">
          Made to the reel's exact length · <b class="mono">{{ fmtTime(length) }}</b>
          <template v-if="synced"> at {{ tempo }} BPM (its parts are whole beats)</template> · rebuilds if you change the cut
        </p>
      </div>
    </header>

    <!-- 1 · Start from -->
    <section class="bsec">
      <h5>1 · Start from <small class="muted">a song in your Reels folder sets the groove and sound palette; nothing is copied note for note</small></h5>
      <div class="cards">
        <button
          v-for="c in categories" :key="c.name" class="card" :class="{ on: beat.from.kind === 'song' && beat.from.category === c.name }"
          @click="pickCategory(c)"
        >
          <b>{{ c.name }}</b>
          <small>{{ c.songs.length }} song{{ c.songs.length === 1 ? '' : 's' }}<template v-if="styleOf(c.songs[0].name)?.words"> · {{ styleOf(c.songs[0].name).words[0] }}</template></small>
        </button>
        <label v-if="unsorted.length" class="card pick" :class="{ on: beat.from.kind === 'song' && !beat.from.category }">
          <b>No category ▾</b>
          <small>{{ beat.from.kind === 'song' && !beat.from.category ? songName(beat.from.name) : `pick one of ${unsorted.length}` }}</small>
          <select :value="beat.from.kind === 'song' && !beat.from.category ? beat.from.name : ''" @change="pickSong($event.target.value, '')" aria-label="A song with no category">
            <option value="" disabled>Pick a song…</option>
            <option v-for="t in unsorted" :key="t.name" :value="t.name">{{ t.title || t.name }}</option>
          </select>
        </label>
        <button class="card" :class="{ on: beat.from.kind === 'scratch' }" @click="beat.from = { kind: 'scratch' }">
          <b>From scratch</b><small>levers only</small>
        </button>
      </div>
      <p v-if="beat.from.kind === 'song'" class="small fromline">
        <template v-if="catSongs.length > 1">
          Song
          <select :value="beat.from.name" @change="pickSong($event.target.value, beat.from.category)">
            <option v-for="t in catSongs" :key="t.name" :value="t.name">{{ t.title || t.name }}</option>
          </select>
        </template>
        <template v-else><b>{{ songName(beat.from.name) }}</b></template>
        <span class="muted">
          <template v-if="refStyle?.measured"> · {{ refStyle.bpm >= 40 ? `${Math.round(refStyle.bpm)} BPM, ` : 'no clear beat, ' }}{{ refStyle.key }}, {{ refStyle.words.join(', ') }}</template>
          <template v-else-if="refStyle && !refStyle.measured"> · its tempo and key need beat detection (<code>./studio/run.sh --beat</code>); its categories still set the style</template>
          <template v-else> · listening to it…</template>
        </span>
      </p>
    </section>

    <!-- 2 · Energy over the reel -->
    <section class="bsec">
      <div class="bsechead">
        <h5>2 · Energy over the reel <small class="muted">drag a point · click the curve to add one · double-click to remove</small></h5>
        <div class="tbtns">
          <button v-for="c in CURVES" :key="c.v" class="btn small" :class="{ primary: beat.preset === c.v }" @click="setPreset(c.v)">{{ c.label }}</button>
        </div>
      </div>
      <div ref="pad" class="pad" @pointerdown.self="addPoint" @pointermove="dragMove" @pointerup="dragEnd" @pointercancel="dragEnd">
        <span class="padlabel top">peak</span><span class="padlabel bottom">calm</span>
        <svg class="curve" viewBox="0 0 1000 200" preserveAspectRatio="none" aria-hidden="true">
          <path :d="area" class="fill" />
          <path :d="line" class="line" vector-effect="non-scaling-stroke" />
          <line
            v-for="(e, i) in edges" :key="i" :x1="e * 1000" :x2="e * 1000" y1="0" y2="200" class="edgeline"
            vector-effect="non-scaling-stroke"
          />
        </svg>
        <button
          v-for="(p, i) in beat.curve" :key="i" class="pt" :class="{ hot: drag === i }"
          :style="{ left: `${p[0] * 100}%`, top: `${(1 - p[1]) * 100}%` }"
          :title="`${fmtTime(p[0] * length)} · energy ${Math.round(p[1] * 100)}%${i && i < beat.curve.length - 1 ? ' · double-click to remove' : ''}`"
          :aria-label="`Point at ${fmtTime(p[0] * length)}, energy ${Math.round(p[1] * 100)} percent`"
          @pointerdown.stop="dragStart($event, i)" @dblclick.stop="removePoint(i)" @keydown="keyPoint($event, i)"
        ></button>
      </div>
      <div class="sstrip">
        <div
          v-for="(s, k) in fractions" :key="k" class="sblock" :class="`l-${s.layout}`"
          :style="{ left: `${s.a * 100}%`, width: `calc(${(s.b - s.a) * 100}% - 3px)` }"
          :title="`${layoutLabel(s.layout)} · ${roles[k]} · ${fmtTime(s.a * length)} → ${fmtTime(s.b * length)}`"
        >{{ layoutLabel(s.layout) }} · {{ roles[k] }}</div>
      </div>
      <div class="tbtns">
        <button class="btn small" :class="{ primary: beat.hits }" @click="beat.hits = !beat.hits" :aria-pressed="beat.hits">{{ beat.hits ? '✓ ' : '' }}Hits on scene changes</button>
        <button class="btn small" :class="{ primary: beat.end }" @click="beat.end = !beat.end" :aria-pressed="beat.end">{{ beat.end ? '✓ ' : '' }}End on the last frame</button>
        <span class="muted small">
          Dashed lines = your scene changes.<template v-if="beat.hits && edges.length"> A fill, riser or drop lands on each.</template>
          {{ beat.end ? `The final bar resolves exactly at ${fmtTime(length)}.` : `It fades out by ${fmtTime(length)}.` }}
        </span>
      </div>
    </section>

    <!-- 3 · Vibe levers, and what gets asked for -->
    <div class="twocol">
      <section class="bsec">
        <div class="bsechead">
          <h5>3 · Vibe levers <small class="muted">click a notch · 0 = off</small></h5>
          <div class="tbtns">
            <button v-for="v in VIBES" :key="v.v" class="btn small" :class="{ primary: vibeNow === v.v }" @click="setVibe(v)">{{ v.label }}</button>
          </div>
        </div>
        <div class="levers">
          <div v-for="l in LEVERS" :key="l.v" class="lever">
            <span class="lnum mono">{{ beat.levers[l.v] }}</span>
            <div class="notches" role="radiogroup" :aria-label="l.label">
              <button
                v-for="n in [5, 4, 3, 2, 1]" :key="n" class="notch" :class="{ on: beat.levers[l.v] >= n }" role="radio"
                :aria-checked="beat.levers[l.v] === n" :aria-label="`${l.label} ${n}`" @click="setLever(l.v, n)"
              ></button>
            </div>
            <b>{{ l.label }}</b>
            <small class="muted">{{ l.hint }}</small>
          </div>
        </div>
      </section>

      <section class="bsec under">
        <h5>Under the levers</h5>
        <div class="derived">
          <label class="dcard">
            <span class="muted small">Tempo</span>
            <input class="mono big" type="number" min="60" max="180" :value="tempo" @change="setTempo($event.target.value)" aria-label="Tempo in BPM" />
            <small class="muted">BPM · {{ beat.tempo != null ? 'yours' : tempoFrom }}<button v-if="beat.tempo != null" class="link" @click="beat.tempo = null">use the levers'</button></small>
          </label>
          <label class="dcard">
            <span class="muted small">Key</span>
            <input class="mono big" :value="key" @change="setKey($event.target.value)" aria-label="Key" />
            <small class="muted">{{ beat.key ? 'yours' : keyFrom }}<button v-if="beat.key" class="link" @click="beat.key = null">use the levers'</button></small>
          </label>
        </div>
        <label class="field">
          <span class="small">What gets asked for <button v-if="beat.prompt != null" class="link" @click="beat.prompt = null">back to the built one</button></span>
          <textarea rows="6" :value="prompt" @input="beat.prompt = $event.target.value"></textarea>
          <small v-if="beat.prompt != null" class="muted">Edited: changes above won't change it until you go back to the built one.</small>
        </label>
        <button class="btn primary gen" disabled title="Generating comes in the next step: it needs ELEVENLABS_API_KEY">Generate 3 takes</button>
        <p class="muted small">Three takes per run. Changing one lever and pressing “More like this” on a take keeps its seed, so only that quality shifts.</p>
      </section>
    </div>

    <!-- 4 · Takes -->
    <section class="bsec">
      <h5>4 · Takes <small class="muted">each one is exactly the reel's length; the music row in the editor shows the one in use</small></h5>
      <p class="muted small empty">No takes yet. <b>Generate 3 takes</b> makes three, each {{ fmtTime(length) }} long.</p>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { api } from '../api'
import { fmtTime } from '../time'
import {
  CURVES, LEVERS, VIBES, beatPrompt, curveAt, derivedKey, derivedTempo, leverClick, presetCurve, sceneFractions, sceneRole,
} from '../beat'

const props = defineProps({
  reelId: { type: Number, required: true },
  reelName: { type: String, default: '' },
  shelf: { type: Object, required: true },
  scenes: { type: Array, default: () => [] },   // [{ layout, start, end }] on the reel's clock now
  reelLength: { type: Number, default: 0 },      // its length now (with the song it has)
})
const beat = defineModel({ type: Object, required: true })

const LAYOUT_LABEL = { soloA: 'Solo A', stack: 'Stack', soloB: 'Solo B', swap: 'B over A' }
const layoutLabel = (v) => LAYOUT_LABEL[v] || v

// ---------------------------------------------------------------- start from
const tracks = computed(() => (props.shelf.tracks || []).filter((t) => !(t.categories || []).some((c) => c.toLowerCase() === 'ai')))
const categories = computed(() => {
  const by = new Map()
  for (const t of tracks.value) for (const c of t.categories || []) {
    if (!by.has(c)) by.set(c, [])
    by.get(c).push(t)
  }
  return [...by.entries()].map(([name, songs]) => ({ name, songs })).sort((a, b) => a.name.localeCompare(b.name))
})
const unsorted = computed(() => tracks.value.filter((t) => !(t.categories || []).length))
const catSongs = computed(() => categories.value.find((c) => c.name === beat.value.from.category)?.songs || [])
const songName = (name) => { const t = tracks.value.find((x) => x.name === name); return t?.title || name }
function pickCategory(c) { pickSong(c.songs[0].name, c.name) }
function pickSong(name, category) {
  if (name) beat.value.from = { kind: 'song', name, category }
}

// What a song sounds like (measured on the server, once).
const styles = ref({})
const styleOf = (name) => styles.value[name]
async function fetchStyle(name) {
  if (!name || name in styles.value) return
  styles.value = { ...styles.value, [name]: null }
  try { styles.value = { ...styles.value, [name]: await api.musicStyle(name) } } catch { /* shown without it */ }
}
watch(categories, async (cs) => { for (const c of cs) await fetchStyle(c.songs[0].name) }, { immediate: true })
watch(() => beat.value.from.name, (n) => fetchStyle(n), { immediate: true })
const refStyle = computed(() => (beat.value.from.kind === 'song' ? styles.value[beat.value.from.name] : null))

// ---------------------------------------------------------------- tempo, key, length
const tempo = computed(() => beat.value.tempo ?? derivedTempo(beat.value.levers))
const tempoFrom = computed(() => {
  const from = ['upbeat', 'chill', 'ecstatic', 'funky'].filter((k) => beat.value.levers[k] > 0)
  return from.length ? `from ${from.map((k) => LEVERS.find((l) => l.v === k).label).join(', ')}` : 'a middle tempo'
})
const refKey = computed(() => (refStyle.value?.measured ? refStyle.value.key : ''))
const key = computed(() => beat.value.key || derivedKey(beat.value.levers, refKey.value))
const keyFrom = computed(() => `from Happy${refKey.value ? `, on your song's ${refKey.value.split(' ')[0]}` : ''}`)
function setTempo(v) {
  const n = Math.round(Number(v))
  beat.value.tempo = Number.isFinite(n) && n ? Math.min(180, Math.max(60, n)) : null
}
function setKey(v) { beat.value.key = String(v).trim() || null }

// The reel's length at this tempo: the server's plan (parts are whole beats when cutting on the beat).
const length = ref(props.reelLength)
const synced = ref(false)
let lenTimer
watch(() => [tempo.value, props.reelLength, props.scenes.length], () => {
  clearTimeout(lenTimer)
  lenTimer = setTimeout(async () => {
    try {
      const r = await api.beatLength(props.reelId, tempo.value)
      if (r?.seconds) { length.value = r.seconds; synced.value = r.synced }
    } catch { length.value = props.reelLength }
  }, 250)
}, { immediate: true })
onBeforeUnmount(() => clearTimeout(lenTimer))

// ---------------------------------------------------------------- the curve
const fractions = computed(() => sceneFractions(props.scenes, props.reelLength))
const edges = computed(() => fractions.value.slice(1).map((s) => s.a))
const roles = computed(() => fractions.value.map((s, k) => sceneRole(beat.value.curve, s, k, fractions.value.length)))
// "Follow my scenes" follows them as they change.
watch(() => JSON.stringify(fractions.value), () => {
  if (beat.value.preset === 'follow') beat.value.curve = presetCurve('follow', fractions.value)
})
function setPreset(v) {
  beat.value.preset = v
  beat.value.curve = presetCurve(v, fractions.value)
}
const samples = computed(() => Array.from({ length: 201 }, (_, i) => [i / 200, curveAt(beat.value.curve, i / 200)]))
const line = computed(() => samples.value.map(([x, y], i) => `${i ? 'L' : 'M'}${(x * 1000).toFixed(1)},${((1 - y) * 200).toFixed(1)}`).join(''))
const area = computed(() => `${line.value}L1000,200L0,200Z`)

const pad = ref(null)
const drag = ref(null)
function at(e) {
  const r = pad.value.getBoundingClientRect()
  return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, 1 - (e.clientY - r.top) / r.height))]
}
function edit(points) {
  beat.value.curve = points
  beat.value.preset = 'custom'
}
function dragStart(e, i) {
  e.currentTarget.setPointerCapture?.(e.pointerId)
  drag.value = i
}
function dragMove(e) {
  const i = drag.value
  if (i === null) return
  const [x, y] = at(e)
  const pts = beat.value.curve.map((p) => [...p])
  const last = pts.length - 1
  pts[i][1] = Math.round(y * 100) / 100
  // Ends stay at the ends; others move between their neighbours.
  if (i > 0 && i < last) pts[i][0] = Math.round(Math.min(pts[i + 1][0] - 0.01, Math.max(pts[i - 1][0] + 0.01, x)) * 1000) / 1000
  edit(pts)
}
function dragEnd() { drag.value = null }
function addPoint(e) {
  const [x, y] = at(e)
  const pts = beat.value.curve.map((p) => [...p])
  if (pts.some((p) => Math.abs(p[0] - x) < 0.015)) return
  pts.push([Math.round(x * 1000) / 1000, Math.round(y * 100) / 100])
  pts.sort((a, b) => a[0] - b[0])
  edit(pts)
  drag.value = pts.findIndex((p) => p[0] === Math.round(x * 1000) / 1000)
}
function removePoint(i) {
  if (i === 0 || i === beat.value.curve.length - 1) return
  edit(beat.value.curve.filter((_, j) => j !== i))
}
function keyPoint(e, i) {
  const step = { ArrowUp: [0, 0.05], ArrowDown: [0, -0.05], ArrowLeft: [-0.01, 0], ArrowRight: [0.01, 0] }[e.key]
  if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); return removePoint(i) }
  if (!step) return
  e.preventDefault()
  const pts = beat.value.curve.map((p) => [...p])
  const last = pts.length - 1
  pts[i][1] = Math.round(Math.min(1, Math.max(0, pts[i][1] + step[1])) * 100) / 100
  if (i > 0 && i < last) pts[i][0] = Math.round(Math.min(pts[i + 1][0] - 0.01, Math.max(pts[i - 1][0] + 0.01, pts[i][0] + step[0])) * 1000) / 1000
  edit(pts)
}

// ---------------------------------------------------------------- levers
const vibeNow = computed(() => VIBES.find((v) => LEVERS.every((l) => (beat.value.levers[l.v] || 0) === v.levers[l.v]))?.v || '')
function setLever(k, n) {
  beat.value.levers = { ...beat.value.levers, [k]: Math.max(0, leverClick(beat.value.levers[k] || 0, n)) }
  beat.value.vibe = vibeNow.value
}
function setVibe(v) {
  beat.value.levers = { ...v.levers }
  beat.value.vibe = v.v
}

// ---------------------------------------------------------------- the prompt
const built = computed(() => beatPrompt({
  tempo: tempo.value, key: key.value,
  from: beat.value.from.kind === 'song' ? { ...beat.value.from, title: songName(beat.value.from.name) } : beat.value.from,
  levers: beat.value.levers, curve: beat.value.curve, hits: beat.value.hits, end: beat.value.end,
  length: length.value, edges: edges.value.map((f) => f * length.value),
}))
const prompt = computed(() => beat.value.prompt ?? built.value)
defineExpose({ built, length, tempo, key })
</script>

<style scoped>
.beatb { --b-blue: #6f93c4; --b-blue-soft: rgb(111 147 196 / 18%); display: flex; flex-direction: column; gap: 14px; margin-top: 10px; }
:root[data-theme='dark'] .beatb { --b-blue: #8fb0dc; --b-blue-soft: rgb(143 176 220 / 16%); }
.bhead h4 { margin: 0; color: var(--forest); font-size: 20px; }
.bhead p { margin: 2px 0 0; }
.bsec { border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; background: var(--paper); }
.bsec h5 { margin: 0 0 10px; font-size: 14px; }
.bsec h5 small { font-weight: 400; margin-left: 6px; }
.bsechead { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 10px; }
.bsechead h5 { margin: 0; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 8px; }
.card {
  position: relative; display: flex; flex-direction: column; align-items: flex-start; gap: 2px; padding: 10px 12px; text-align: left;
  border: 1px solid var(--line); border-radius: 8px; background: transparent; color: inherit; font: inherit; cursor: pointer;
}
.card small { color: var(--muted); font-size: 12px; }
.card.on { border-color: var(--b-blue); box-shadow: inset 0 0 0 1px var(--b-blue); background: var(--b-blue-soft); }
.card.pick select { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
.fromline { margin: 8px 0 0; }
.fromline select { margin: 0 4px; }
.pad {
  position: relative; height: 180px; border-radius: 8px; background: rgb(128 128 128 / 8%); cursor: crosshair; touch-action: none;
  margin: 0 6px;
}
.curve { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.curve .fill { fill: var(--b-blue-soft); }
.curve .line { fill: none; stroke: var(--b-blue); stroke-width: 2.5; }
.curve .edgeline { stroke: #e08038; stroke-width: 1.2; stroke-dasharray: 4 4; }
.padlabel { position: absolute; left: 8px; font-size: 11px; color: var(--muted); pointer-events: none; }
.padlabel.top { top: 6px; } .padlabel.bottom { bottom: 6px; }
.pt {
  position: absolute; width: 16px; height: 16px; margin: -8px 0 0 -8px; padding: 0; border-radius: 50%; cursor: grab; touch-action: none;
  border: 2px solid var(--b-blue); background: var(--paper);
}
.pt:hover, .pt.hot, .pt:focus-visible { background: var(--b-blue); outline: none; }
.sstrip { position: relative; height: 26px; margin: 6px 6px 10px; }
.sblock {
  position: absolute; top: 0; bottom: 0; border-radius: 5px; font-size: 11px; font-weight: 600; padding: 0 8px; line-height: 26px;
  overflow: hidden; white-space: nowrap; text-overflow: ellipsis; color: #1d2a1d;
}
.sblock.l-soloA { background: #b8cfa8; } .sblock.l-soloB { background: #e9b27a; }
.sblock.l-stack { background: #a9bcd3; } .sblock.l-swap { background: #c9c2b0; }
.tbtns { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.twocol { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(260px, 1fr); gap: 14px; }
@media (max-width: 900px) { .twocol { grid-template-columns: 1fr; } }
.levers { display: grid; grid-template-columns: repeat(10, minmax(0, 1fr)); gap: 6px; }
@media (max-width: 700px) { .levers { grid-template-columns: repeat(5, minmax(0, 1fr)); } }
.lever { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 8px 4px; border: 1px solid var(--line); border-radius: 8px; text-align: center; }
.lever b { font-size: 12px; } .lever small { font-size: 10px; line-height: 1.2; }
.lnum { font-size: 13px; font-weight: 700; }
.notches { display: flex; flex-direction: column; gap: 4px; width: 100%; align-items: center; }
.notch { width: min(36px, 80%); height: 16px; border-radius: 4px; border: 1px solid var(--line); background: rgb(128 128 128 / 10%); cursor: pointer; padding: 0; }
.notch.on { background: var(--b-blue); border-color: var(--b-blue); }
.notch:focus-visible { outline: 2px solid var(--b-blue); outline-offset: 1px; }
.under { display: flex; flex-direction: column; gap: 10px; }
.under h5 { margin: 0; }
.derived { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.dcard { display: flex; flex-direction: column; gap: 2px; padding: 8px 10px; border: 1px solid var(--line); border-radius: 8px; }
.dcard input.big { font-size: 22px; font-weight: 700; border: 0; background: transparent; color: inherit; padding: 0; width: 100%; }
.dcard small .link { margin-left: 6px; }
.under textarea { width: 100%; box-sizing: border-box; font: inherit; font-size: 13px; line-height: 1.45; }
.gen { width: 100%; padding: 10px; font-size: 15px; }
.empty { margin: 0; }
</style>
