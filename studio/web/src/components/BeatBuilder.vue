<template>
  <div class="beatb">
    <!-- 1 · Start from -->
    <section class="bsec">
      <h5>1 · Start from <small class="muted">a song in your Reels folder sets the groove and sound palette; nothing is copied note for note</small></h5>
      <div class="cards">
        <div v-for="c in categories" :key="c.name" class="cardwrap">
          <button class="card" :class="{ on: beat.from.kind === 'song' && beat.from.category === c.name }" @click="pickCategory(c)">
            <b>{{ c.name }}</b>
            <small>{{ c.songs.length }} song{{ c.songs.length === 1 ? '' : 's' }}<template v-if="styleOf(c.songs[0].name)?.words"> · {{ styleOf(c.songs[0].name).words[0] }}</template></small>
          </button>
          <button
            class="hear" :class="{ on: hearing === catSong(c) }" @click="hear(catSong(c))"
            :title="hearing === catSong(c) ? 'Stop' : `Hear 30s from the middle of ${songName(catSong(c))}`"
            :aria-label="hearing === catSong(c) ? `Stop ${songName(catSong(c))}` : `Hear ${songName(catSong(c))}`"
          >{{ hearing === catSong(c) ? '■' : '▶' }}</button>
          <span v-if="hearing === catSong(c)" class="heard" :style="{ width: `${heardShare * 100}%` }"></span>
        </div>
        <div v-if="unsorted.length" class="cardwrap">
          <label class="card pick" :class="{ on: beat.from.kind === 'song' && !beat.from.category }">
            <b>No category ▾</b>
            <small>{{ uncatPick ? songName(uncatPick) : `pick one of ${unsorted.length}` }}</small>
            <select :value="uncatPick || ''" @change="pickSong($event.target.value, '')" aria-label="A song with no category">
              <option value="" disabled>Pick a song…</option>
              <option v-for="t in unsorted" :key="t.name" :value="t.name">{{ t.title || t.name }}</option>
            </select>
          </label>
          <button
            v-if="uncatPick" class="hear" :class="{ on: hearing === uncatPick }" @click="hear(uncatPick)"
            :title="hearing === uncatPick ? 'Stop' : `Hear 30s from the middle of ${songName(uncatPick)}`"
            :aria-label="hearing === uncatPick ? `Stop ${songName(uncatPick)}` : `Hear ${songName(uncatPick)}`"
          >{{ hearing === uncatPick ? '■' : '▶' }}</button>
          <span v-if="uncatPick && hearing === uncatPick" class="heard" :style="{ width: `${heardShare * 100}%` }"></span>
        </div>
        <button class="card" :class="{ on: beat.from.kind === 'scratch' }" @click="beat.from = { kind: 'scratch' }">
          <b>From scratch</b><small>levers only</small>
        </button>
      </div>
      <p v-if="beat.from.kind === 'song'" class="small fromline">
        <button class="hear inline" :class="{ on: hearing === beat.from.name }" @click="hear(beat.from.name)" :aria-label="hearing === beat.from.name ? 'Stop' : `Hear ${songName(beat.from.name)}`"
                :title="hearing === beat.from.name ? 'Stop' : 'Hear 30s from the middle of it'">{{ hearing === beat.from.name ? '■' : '▶' }}</button>
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
      <p v-if="songNote" class="small songnote" :class="{ edited: songNote.edited }">
        {{ songNote.text }}
        <button v-if="songNote.edited" class="link" @click="applySong(beat.from.name, true)">set them from the song again</button>
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
      <div class="tops" role="radiogroup" aria-label="How high the energy goes">
        <span class="muted small">Highest it goes</span>
        <button
          v-for="o in TOPS" :key="o.v" class="btn small" role="radio" :aria-checked="topChoice === o.v" :class="{ primary: topChoice === o.v }"
          :title="o.hint" @click="setTop(o.v)"
        >{{ o.label }}</button>
        <span class="muted small">or drag the line along the top of the curve</span>
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
        <!-- the ceiling: drag it down to keep things calmer -->
        <div
          class="ceil" :class="{ hot: ceilDrag }" :style="{ top: `${(1 - topNow) * 100}%` }" role="slider" tabindex="0"
          aria-label="How high the energy goes" aria-valuemin="10" aria-valuemax="100" :aria-valuenow="Math.round(topNow * 100)"
          @pointerdown.stop="ceilStart" @dblclick.stop="setTop(1)" @keydown="ceilKey"
          title="Drag down to keep the energy lower the whole way; double-click for Full"
        ><span class="ceilgrip">Top {{ Math.round(topNow * 100) }}% ↕</span></div>
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
            <small class="muted">BPM · {{ beat.tempo != null ? (refStyle?.measured && beat.tempo === songTempo(refStyle.bpm) ? `from ${songName(beat.from.name)}` : 'yours') : tempoFrom }}<button v-if="beat.tempo != null" class="link" @click="beat.tempo = null">use the levers'</button></small>
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
      </section>
    </div>

  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { api } from '../api'
import { fmtTime } from '../time'
import {
  CURVES, LEVERS, TOPS, VIBES, beatPrompt, capCurve, leversFromSong, songTempo, curveAt, derivedKey, derivedTempo, leverClick, presetCurve, sceneFractions,
  sceneRole, topOf,
} from '../beat'

const props = defineProps({
  reelId: { type: Number, required: true },
  reelName: { type: String, default: '' },
  shelf: { type: Object, required: true },
  // The reel at the beat's tempo, from the server: { seconds, synced, scenes: [{ layout, start, end }] }.
  timeline: { type: Object, default: () => ({ seconds: 0, scenes: [] }) },
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
function pickCategory(c) { pickSong(catSong(c), c.name) }
// A category's song: the one picked in it, else its first.
const catSong = (c) => (beat.value.from.category === c.name && c.songs.some((t) => t.name === beat.value.from.name)
  ? beat.value.from.name : c.songs[0].name)
// No category's song: the one picked there, remembered while another card is chosen.
const lastUncat = ref('')
const uncatPick = computed(() => (beat.value.from.kind === 'song' && !beat.value.from.category ? beat.value.from.name : lastUncat.value))
watch(uncatPick, (n) => { if (n) lastUncat.value = n })

// ---------------------------------------------------------------- hearing a song
// 30 seconds from the middle of a song, faded in and out; one at a time, and
// it stops a take that's playing (and a take stops it): 'footage-audio' events.
const PREVIEW = 30
const FADE = 0.6
const hearing = ref('')
const heardShare = ref(0)
let player = null
let span = [0, 0]
let frame = 0
function stopHearing() {
  cancelAnimationFrame(frame)
  if (player) { player.pause(); player.removeAttribute('src'); player.load() }
  hearing.value = ''
  heardShare.value = 0
}
async function hear(name) {
  if (!name) return
  if (hearing.value === name) return stopHearing()
  stopHearing()
  window.dispatchEvent(new CustomEvent('footage-audio', { detail: 'preview' }))
  player = player || new Audio()
  player.preload = 'auto'
  player.src = api.musicFile(name)
  hearing.value = name
  const known = tracks.value.find((t) => t.name === name)?.duration
  await new Promise((ok) => {
    if (player.readyState >= 1) ok()
    else player.addEventListener('loadedmetadata', ok, { once: true })
  })
  if (hearing.value !== name) return
  const dur = known || player.duration || 0
  const len = Math.min(PREVIEW, dur || PREVIEW)
  const from = Math.max(0, dur / 2 - len / 2)
  span = [from, from + len]
  player.currentTime = from
  player.volume = 0
  try { await player.play() } catch { return stopHearing() }
  const step = () => {
    if (hearing.value !== name) return
    const t = player.currentTime
    const into = t - span[0]
    const left = span[1] - t
    player.volume = Math.max(0, Math.min(1, into / FADE, left / FADE))
    heardShare.value = Math.min(1, Math.max(0, into / (span[1] - span[0])))
    if (left <= 0 || player.ended) return stopHearing()
    frame = requestAnimationFrame(step)
  }
  frame = requestAnimationFrame(step)
}
const otherAudio = (e) => { if (e.detail !== 'preview') stopHearing() }
window.addEventListener('footage-audio', otherAudio)
onBeforeUnmount(() => { window.removeEventListener('footage-audio', otherAudio); stopHearing() })
function pickSong(name, category) {
  if (!name) return
  beat.value.from = { kind: 'song', name, category }
  applySong(name)
}
// Starting from a song sets the levers, tempo and key from it (once it's been
// measured), so what's shown is what's asked for. Change them after as you like.
const pendingSong = ref('')
function applySong(name, now = false) {
  const st = styles.value[name]
  if (st === undefined || st === null) {   // still measuring: as soon as it's in
    pendingSong.value = name
    fetchStyle(name)
    return
  }
  pendingSong.value = ''
  if (beat.value.from.name !== name && !now) return
  const cats = tracks.value.find((t) => t.name === name)?.categories || []
  beat.value.levers = leversFromSong(st.measured ? st : null, cats)
  beat.value.tempo = st.measured ? songTempo(st.bpm) : null
  beat.value.key = null
  beat.value.vibe = 'song'
}
const songNote = computed(() => {
  if (beat.value.from.kind !== 'song') return null
  const name = songName(beat.value.from.name)
  if (pendingSong.value) return { text: `Setting the levers, tempo and key from ${name} once it's measured…` }
  if (beat.value.vibe === 'song') return { text: `The levers, tempo and key below are set from ${name}; change any of them and the takes follow what you set.` }
  if (beat.value.vibe === 'song-edited') return { text: `Set from ${name}, then changed by you: the takes follow the levers as they are now.`, edited: true }
  return { text: `The levers are your own (${VIBES.find((v) => v.v === beat.value.vibe)?.label || 'changed'}), not from ${name}: the takes take ${name}'s groove and sound, with these levers.`, edited: true }
})

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
watch(styles, () => { if (pendingSong.value && styles.value[pendingSong.value]) applySong(pendingSong.value) }, { deep: true })

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

// The reel's length at this tempo (the studio asks the server: parts are whole beats when cutting on the beat).
const length = computed(() => props.timeline.seconds || 0)

// ---------------------------------------------------------------- the curve
const fractions = computed(() => sceneFractions(props.timeline.scenes || [], props.timeline.seconds))
const edges = computed(() => fractions.value.slice(1).map((s) => s.a))
const roles = computed(() => fractions.value.map((s, k) => sceneRole(beat.value.curve, s, k, fractions.value.length)))
// "Follow my scenes" follows them as they change.
watch(() => JSON.stringify(fractions.value), () => {
  if (beat.value.preset === 'follow') beat.value.curve = capCurve(presetCurve('follow', fractions.value), beat.value.ceiling ?? 1)
})
function setPreset(v) {
  beat.value.preset = v
  beat.value.curve = capCurve(presetCurve(v, fractions.value), beat.value.ceiling ?? 1)
}

// The ceiling: how high the energy goes. A preset is redrawn under it; a
// curve of your own is squashed (or stretched back up) from where it was.
const topNow = computed(() => topOf(beat.value.curve))
const topChoice = computed(() => {
  const c = beat.value.ceiling ?? 1
  return TOPS.find((o) => Math.abs(o.v - c) < 0.03)?.v ?? null
})
let ceilBase = null
function setTop(top, base = null) {
  const t = Math.round(Math.min(1, Math.max(0.1, top)) * 100) / 100
  beat.value.ceiling = t >= 0.995 ? null : t
  beat.value.curve = beat.value.preset !== 'custom'
    ? capCurve(presetCurve(beat.value.preset, fractions.value), t)
    : capCurve(base || beat.value.curve, t, true)
}
const ceilDrag = ref(false)
function ceilStart(e) {
  e.currentTarget.setPointerCapture?.(e.pointerId)
  ceilBase = beat.value.curve.map((p) => [...p])
  ceilDrag.value = true
}
function ceilKey(e) {
  const d = { ArrowUp: 0.05, ArrowDown: -0.05 }[e.key]
  if (!d) return
  e.preventDefault()
  setTop(topNow.value + d)
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
  if (ceilDrag.value) { setTop(at(e)[1], ceilBase); return }
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
function dragEnd() { drag.value = null; ceilDrag.value = false; ceilBase = null }
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
  beat.value.vibe = String(beat.value.vibe || '').startsWith('song') ? 'song-edited' : vibeNow.value
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
  length: length.value, edges: edges.value.map((f) => f * length.value), ceiling: beat.value.ceiling,
}))
const prompt = computed(() => beat.value.prompt ?? built.value)
defineExpose({ built, prompt, length, tempo, key, keyFrom, tempoFrom })
</script>

<style scoped>
.beatb { --b-blue: #6f93c4; --b-blue-soft: rgb(111 147 196 / 18%); display: flex; flex-direction: column; gap: 14px; margin-top: 10px; }
:root[data-theme='dark'] .beatb { --b-blue: #8fb0dc; --b-blue-soft: rgb(143 176 220 / 16%); }
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
.cardwrap { position: relative; display: flex; }
.cardwrap .card { flex: 1; padding-right: 44px; }
.hear {
  position: absolute; top: 8px; right: 8px; z-index: 1; width: 30px; height: 30px; border-radius: 50%; padding: 0;
  border: 1px solid var(--b-blue); background: var(--paper); color: var(--b-blue); font-size: 11px; line-height: 1; cursor: pointer;
}
.hear:hover, .hear:focus-visible, .hear.on { background: var(--b-blue); color: var(--paper); outline: none; }
.hear.inline { position: static; width: 24px; height: 24px; margin-right: 6px; vertical-align: middle; font-size: 9px; }
.heard { position: absolute; left: 1px; bottom: 1px; height: 3px; border-radius: 0 0 0 8px; background: var(--b-blue); pointer-events: none; transition: width 0.1s linear; }
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
.songnote { margin: 6px 0 0; padding: 6px 10px; border-radius: 8px; background: var(--b-blue-soft); }
.songnote.edited { background: rgb(224 128 56 / 12%); }
.songnote .link { margin-left: 6px; }
.tops { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: -2px 0 10px; }
.ceil {
  position: absolute; left: 0; right: 0; height: 14px; margin-top: -7px; cursor: ns-resize; z-index: 2; touch-action: none;
  background: linear-gradient(to bottom, transparent 6px, #e08038 6px, #e08038 8px, transparent 8px); opacity: 0.55;
}
.ceil:hover, .ceil.hot, .ceil:focus-visible { opacity: 1; outline: none; }
.ceilgrip {
  position: absolute; right: 6px; top: -9px; font-size: 11px; font-weight: 600; padding: 1px 7px; border-radius: 999px;
  background: #e08038; color: #1d1208; white-space: nowrap;
}
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
</style>
