<template>
  <main class="studio">
    <header class="top">
      <button class="back" @click="leave" title="Back to the reel (Esc)">← {{ reel?.name || 'Reel' }}</button>
      <div class="ttl">
        <span class="kicker">Beat studio</span>
        <h1>Beat for {{ reel?.name || '…' }}</h1>
      </div>
      <div class="facts mono" v-if="preview">
        <span>{{ fmtTime(preview.seconds) }}</span><span>{{ tempo }} BPM</span><span>{{ keyNow }}</span>
      </div>
      <span class="spacer"></span>
      <div class="engine" role="radiogroup" aria-label="Made by">
        <button
          v-for="e in ENGINES" :key="e.v" role="radio" :aria-checked="engine === e.v" :class="{ on: engine === e.v }"
          :title="e.hint" @click="setEngine(e.v)"
        >{{ e.label }}</button>
      </div>
      <button class="btn primary go" :disabled="running || !ready || !!preview?.error" @click="generate()">
        {{ running ? (job?.takes?.length === 1 ? 'Making a take…' : 'Making takes…') : 'Generate a take' }}
      </button>
    </header>

    <section class="hero">
      <BeatVisual
        v-if="preview" :length="mode === 'playing' ? playingTake.length : preview.seconds"
        :sections="mode === 'playing' ? playingTake.sections || [] : (job?.plan?.sections && running ? job.plan.sections : preview.sections)"
        :curve="beat?.curve || []" :edges="heroEdges" :hits="beat?.hits !== false" :tempo="mode === 'playing' ? playingTake.tempo : tempo"
        :mode="mode" :takes="job?.takes || []" :envelope="playingEnv" :time="playT" :analyser="analyser" @seek="seekTo"
      />
      <div class="headline" aria-live="polite">
        <p class="big">{{ headline.big }}</p>
        <p class="sub">{{ headline.sub }}</p>
        <div v-if="running" class="pills">
          <span v-for="t in job.takes" :key="t.n" class="pill" :class="t.state">
            Take {{ t.n }}<template v-if="t.label"> · {{ t.label }}</template> · {{ takeState(t) }}
          </span>
        </div>
      </div>
    </section>

    <p v-if="loadError" class="warn pad">{{ loadError }}</p>
    <p v-if="opened" class="opened"><span>{{ opened }}</span><button class="x" @click="opened = ''" aria-label="Dismiss">✕</button></p>
    <div class="cols" v-if="ready">
      <div class="main">
        <BeatBuilder ref="builder" v-model="beat" :reel-id="id" :reel-name="reel.name" :shelf="shelf" :timeline="preview || { seconds: 0, scenes: [] }" />
      </div>
      <aside class="side">
        <section class="card activity">
          <h3>What's happening <small v-if="job" class="muted">{{ job.status === 'running' ? `${Math.round(elapsed)}s` : job.status === 'done' ? 'done' : 'stopped' }}</small></h3>
          <ol v-if="job?.log?.length" ref="logEl" class="log">
            <li v-for="(l, i) in job.log" :key="i" :class="l.kind"><span class="mono t">{{ fmtClock(l.t) }}</span><span>{{ l.text }}</span></li>
          </ol>
          <p v-else class="muted small">
            When you generate, this tells you what's going on: the sections laid out on your curve, the song the groove comes
            from, each take as it's composed and as its audio arrives, and how it was landed on the last frame.
          </p>
        </section>

        <section class="card takes">
          <h3>
            Takes <small class="muted">each exactly the reel's length; the take in the reel is its song</small>
            <button v-if="takes.some((t) => t.starred)" class="link starfilter" :aria-pressed="starOnly" @click="starOnly = !starOnly">{{ starOnly ? 'Show all' : '★ Starred only' }}</button>
          </h3>
          <p v-if="!takes.length && !running" class="muted small">
            No takes yet. <b>Generate a take</b> makes one from your settings. Listen to it, then try another direction,
            or <b>Adapt…</b> it to change just one thing.
          </p>
          <div v-if="takes.length && !running" class="directions">
            <span class="muted small">Try another direction</span>
            <button v-for="d in DIRECTIONS" :key="d.v" class="btn small" :title="d.hint" @click="generate({ lean: d.v })">{{ d.label }}</button>
          </div>
          <ul>
            <!-- takes being made right now -->
            <li v-for="p in pending" :key="`p${p.n}`" class="take pending" :class="p.state">
              <span class="spin" :class="p.state" aria-hidden="true"></span>
              <div class="tinfo">
                <b>Take {{ p.n }}<template v-if="p.label"> · {{ p.label }}</template></b>
                <small v-if="sourceTake" class="from">↳ from Take {{ sourceTake.n }}</small>
                <small class="muted">{{ takeState(p) }}</small>
                <div class="pbar"><i :style="{ width: `${p.expected ? Math.min(100, (p.received / p.expected) * 100) : 0}%` }"></i></div>
              </div>
            </li>
            <li v-for="t in shownTakes" :key="t.id" class="take" :class="{ inuse: inUse?.take === t.id, playing: playing === t.id, source: running && job?.source === t.id, 'adapting-open': adapting === t.id }">
              <button class="play" @click="toggle(t)" :aria-label="playing === t.id ? `Pause take ${t.n}` : `Play take ${t.n}`">{{ playing === t.id ? '❚❚' : '▶' }}</button>
              <div class="tinfo">
                <div class="tname">
                  <button class="star" :class="{ on: t.starred }" :aria-pressed="!!t.starred" :aria-label="t.starred ? `Unstar take ${t.n}` : `Star take ${t.n}`"
                          :title="t.starred ? 'Starred: click to unstar' : 'Star it if you like it'" @click="star(t)">{{ t.starred ? '★' : '☆' }}</button>
                  <b>Take {{ t.n }} · {{ takeName(t) }}</b>
                </div>
                <small v-if="t.fromN" class="from">↳ from Take {{ t.fromN }}</small>
                <small class="mono muted">{{ t.tempo }} BPM · {{ t.key }} · {{ fmtTime(t.length) }} · {{ t.engine === 'elevenlabs' ? 'ElevenLabs' : 'Lyria' }} · {{ madeAt(t.created) }}</small>
                <svg class="wave" viewBox="0 0 60 20" preserveAspectRatio="none" aria-hidden="true">
                  <rect v-for="(v, i) in miniWave(t.id)" :key="i" :x="i + 0.15" width="0.7" :y="10 - v * 9.5" :height="Math.max(v * 19, 0.6)"
                        :class="{ past: playing === t.id && i / 60 < playT / t.length }" />
                </svg>
                <!-- what it was asked for: where it started, the energy, the hits, the instruments -->
                <div v-if="t.beat" class="tsum">
                  <span v-for="(c, i) in summary(t)" :key="i" class="chip" :class="c.kind">{{ c.text }}</span>
                  <button class="link more" :aria-expanded="open === t.id" @click="open = open === t.id ? null : t.id">{{ open === t.id ? 'Less' : 'Details ▾' }}</button>
                </div>
                <dl v-if="open === t.id && t.beat" class="tdetails">
                  <dt>Levers</dt><dd>{{ leversText(t.beat) || 'all at 0' }}</dd>
                  <dt>Tempo · key</dt><dd>{{ t.tempo }} BPM · {{ t.key }}</dd>
                  <dt>Sections</dt><dd>{{ (t.sections || []).map((x) => `${x.name} ${fmtTime(x.start)}`).join(' → ') || '—' }}</dd>
                  <dt>Asked for</dt><dd class="prompt">{{ t.prompt }}</dd>
                </dl>
              </div>
              <div class="tact">
                <span v-if="running && job?.source === t.id" class="tag">{{ pending[0]?.label === 'rebuilt for the new cut' ? 'Rebuilding…' : 'Adapting…' }}</span>
                <button
                  v-else-if="!running" class="btn small" :class="{ primary: adapting === t.id }" :aria-expanded="adapting === t.id"
                  @click="openAdapt(t)" title="Make a new take from this one, changed the way you say: same seed and tempo"
                >Adapt…</button>
                <button v-if="inUse?.take !== t.id" class="btn small" @click="use(t)">Use in reel</button>
                <span v-else class="btn small primary done">✓ In the reel</span>
                <button
                  v-if="inUse?.take === t.id && stale && !running" class="btn small warnbtn" @click="generate({ rebuild: t.id })"
                  :title="`The cut changed: the reel now runs ${fmtTime(staleLen)}, this take ${fmtTime(t.length)}`"
                >Rebuild to {{ fmtTime(staleLen) }}</button>
                <button class="x" @click="remove(t)" :aria-label="`Delete take ${t.n}`" title="Delete this take">✕</button>
              </div>
              <div v-if="adapting === t.id && !running" class="adapt">
                <p class="small muted">A new take from Take {{ t.n }}, with its seed and tempo, changed this way:</p>
                <div class="chips">
                  <button
                    v-for="o in adaptOptions" :key="o.v" class="btn small" :class="{ primary: tweaks.includes(o.v) }" :aria-pressed="tweaks.includes(o.v)"
                    @click="tweaks = tweaks.includes(o.v) ? tweaks.filter((x) => x !== o.v) : [...tweaks, o.v]"
                  >{{ o.label }}</button>
                </div>
                <input v-model="adaptNote" maxlength="200" placeholder="or say how, e.g. add a kalimba melody" @keydown.enter="doAdapt(t)" aria-label="How to change it, in your words" />
                <div class="row">
                  <button class="btn small primary" @click="doAdapt(t)">{{ tweaks.length || adaptNote.trim() ? 'Make it' : 'Another like it' }}</button>
                  <button class="btn small" @click="adapting = null">Cancel</button>
                </div>
              </div>
            </li>
          </ul>
        </section>
      </aside>
    </div>
    <audio ref="audioEl" preload="auto" @ended="playing = null" @pause="onPause" crossorigin="anonymous"></audio>
  </main>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { fmtTime } from '../time'
import { CURVES, LEVERS, TOPS, derivedTempo, newBeat, sceneFractions } from '../beat'
import BeatBuilder from '../components/BeatBuilder.vue'
import BeatVisual from '../components/BeatVisual.vue'

const props = defineProps({ id: { type: [String, Number], required: true } })
const id = Number(props.id)
const router = useRouter()

const ENGINES = [
  { v: 'elevenlabs', label: 'ElevenLabs', hint: 'Follows the sections exactly, with hits on your scene changes; keeps a seed for More like this. Needs a paid ElevenLabs plan.' },
  { v: 'lyria', label: 'Lyria', hint: 'Google Lyria 3 through your OpenRouter account: about $0.08 a take, follows the timing loosely, no seed.' },
]

// One take at a time; then another, leaning a direction (a fresh take with the settings as they are).
const DIRECTIONS = [
  { v: 'drums', label: 'Tighter drums', hint: 'One more take from your settings, with tight, punchy drums' },
  { v: 'bass', label: 'More bass, warmer', hint: 'One more take from your settings, warmer with the bass up front' },
  { v: 'space', label: 'Sparser, more space', hint: 'One more take from your settings, sparer with more air' },
  { v: 'fresh', label: 'Just another', hint: 'One more take from your settings as they are, started fresh' },
]
const reel = ref(null)
const shelf = ref({ tracks: [] })
const beat = ref(null)
const preview = ref(null)
const ready = ref(false)
const loadError = ref('')
const builder = ref(null)

const tempo = computed(() => (beat.value ? beat.value.tempo ?? derivedTempo(beat.value.levers) : 100))
const keyNow = computed(() => builder.value?.key ?? beat.value?.key ?? '')
const engine = computed(() => beat.value?.engine || 'elevenlabs')
const inUse = computed(() => beat.value?.inUse || null)
const heroEdges = computed(() => (preview.value?.scenes || []).slice(1).map((s) => s.start))
function setEngine(v) { if (beat.value) beat.value.engine = v }

// ---------------------------------------------------------------- loading and saving
async function load() {
  try {
    const [r, sh] = await Promise.all([api.reel(id), api.music()])
    reel.value = r
    shelf.value = sh
    let b = r.settings?.beat
    if (!b) {
      const tl = await api.beatLength(id, 100)
      b = newBeat(sceneFractions(tl.scenes || [], tl.seconds))
      await api.updateReel(id, { settings: { beat: b } })
    }
    beat.value = { engine: 'elevenlabs', inUse: null, ...b }
    await refreshPreview()
    ready.value = true
    takes.value = await api.beatTakes(id)
    const last = await api.beatLastJob(id)
    if (last) { job.value = last; if (last.status === 'running') poll() }
    await startFromLink()
  } catch (e) {
    loadError.value = String(e.message || e)
  }
}
// Opened from the reel's song (Settings › Music): ?take=<id> loads that
// beat's settings and opens Adapt on it; ?from=<song> starts from that song.
const route = useRoute()
const opened = ref('')
async function startFromLink() {
  const q = route.query
  if (q.take) {
    const t = takes.value.find((x) => x.id === q.take)
    if (t?.beat) {
      // Its settings, with the tempo and key it was made at (so they don't wait on the song being measured again).
      beat.value = { ...beat.value, ...t.beat, tempo: t.tempo ?? t.beat.tempo, key: t.key || t.beat.key,
                     engine: t.engine || beat.value.engine, inUse: beat.value.inUse }
      opened.value = `Take ${t.n} · ${t.label}: its settings are loaded below. Adapt… it to change one thing (same seed), or change anything and generate a new take.`
      await nextTick()
      openAdapt(t)
      await nextTick()
      document.querySelector('.take.adapting-open')?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    } else opened.value = 'That beat isn\'t one of this reel\'s takes any more; the studio has the reel\'s beat settings.'
  } else if (q.from) {
    await nextTick()
    const name = String(q.from)
    const track = shelf.value.tracks.find((x) => x.name === name)
    builder.value?.pickSong(name, (track?.categories || []).find((c) => c.toLowerCase() !== 'ai') || '')
    opened.value = `Starting from ${track?.title || name}, the reel's song: its groove, tempo and key set the levers below.`
  }
  if (q.take || q.from) router.replace({ path: route.path })   // once: a reload keeps what's set now
}
async function refreshPreview() {
  try { preview.value = await api.beatPreview(id) } catch (e) { loadError.value = String(e.message || e) }
}
// Every change is saved (a moment after the last one), then the plan is worked out again.
let saveTimer
watch(beat, (b, was) => {
  if (!ready.value || !b || !was) return
  clearTimeout(saveTimer)
  saveTimer = setTimeout(async () => {
    await api.updateReel(id, { settings: { beat: b } })
    await refreshPreview()
  }, 400)
}, { deep: true })

// ---------------------------------------------------------------- generating
const job = ref(null)
const running = computed(() => job.value?.status === 'running')
const elapsed = ref(0)
let pollTimer
async function generate(extra = {}) {
  clearTimeout(saveTimer)
  await api.updateReel(id, { settings: { beat: beat.value } })   // what's on screen is what's asked for
  stop()
  try {
    job.value = await api.beatGenerate(id, { engine: engine.value, ...extra })
    poll()
  } catch (e) {
    job.value = { status: 'failed', log: [{ t: 0, text: String(e.message || e), kind: 'error' }], takes: [], error: String(e.message || e) }
  }
}
function poll() {
  clearTimeout(pollTimer)
  pollTimer = setTimeout(async () => {
    try { job.value = await api.beatJob(job.value.id) } catch { /* the next try */ }
    elapsed.value = job.value?.elapsed || 0
    if (job.value?.status === 'running') poll()
    else {
      takes.value = await api.beatTakes(id)
      const r = await api.reel(id)
      if (beat.value && r.settings?.beat) beat.value.inUse = r.settings.beat.inUse ?? null
    }
  }, 400)
}
const takeState = (t) => ({
  waiting: 'waiting', asking: 'composing…', receiving: `${fmtTime(t.received)} of ${fmtTime(t.expected)}`,
  finishing: 'landing it…', done: 'ready', failed: 'failed',
}[t.state] || t.state)
watch(() => job.value?.log?.length, async () => {
  await nextTick()
  if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
})
const logEl = ref(null)
// When a take was made: a time today, else the day too.
function madeAt(iso) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  return d.toDateString() === new Date().toDateString() ? time : `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${time}`
}
const fmtClock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

// ---------------------------------------------------------------- takes
const takes = ref([])
const envs = reactive({})
watch(takes, (list) => {
  for (const t of list) {
    if (envs[t.id] !== undefined) continue
    envs[t.id] = null
    api.beatTakeEnvelope(id, t.id).then((e) => { envs[t.id] = e }).catch(() => {})
  }
})
function miniWave(tid) {
  const e = envs[tid]
  if (!e?.db?.length) return Array(60).fill(0.04)
  const per = e.db.length / 60
  return Array.from({ length: 60 }, (_, i) => {
    let p = 0
    const a = Math.floor(i * per)
    const b = Math.max(a + 1, Math.floor((i + 1) * per))
    for (let j = a; j < b; j++) p += 10 ** (e.db[j] / 10)
    return Math.max(0.03, Math.min(1, (10 * Math.log10(p / (b - a) || 1e-9) + 54) / 54))
  })
}
// What each take was asked for, from the settings it keeps: its name (style,
// song or vibe, and the direction), and a summary of the plan.
const styleFamilies = ref([])
api.beatStyles().then((f) => { styleFamilies.value = f }).catch(() => {})
const instrumentNames = ref({})
api.beatInstruments().then((o) => { instrumentNames.value = Object.fromEntries(o.map((x) => [x.v, x.label])) }).catch(() => {})
const VIBE_NAMES = { garden: 'Garden morning', ecstatic: 'Ecstatic dance', street: 'Street grit', lofi: 'Lo-fi chill' }
const open = ref(null)
function styleOf(b) {
  const f = styleFamilies.value.find((x) => x.v === b?.from?.family)
  const st = f?.styles.find((x) => x.v === b.from.style)
  return st ? { family: f.label, style: st.label } : null
}
function sourceText(b) {
  if (!b?.from) return ''
  if (b.from.kind === 'style') { const st = styleOf(b); return st ? `${st.family} · ${st.style}` : 'a style' }
  if (b.from.kind === 'song') return `♪ ${shelf.value.tracks.find((x) => x.name === b.from.name)?.title || b.from.name}`
  return VIBE_NAMES[b.vibe] ? `From scratch · ${VIBE_NAMES[b.vibe]}` : 'From scratch'
}
// Older takes were called "as set": name them from what they were asked for.
function takeName(t) {
  if (!['as set', 'another take'].includes(t.label) || !t.beat) return t.label
  const b = t.beat
  return styleOf(b)?.style || (b.from?.kind === 'song' ? `from ${sourceText(b).slice(2)}` : VIBE_NAMES[b.vibe] || 'your levers')
}
function energyText(b) {
  const c = b.ceiling ?? 1
  const top = TOPS.find((o) => Math.abs(o.v - c) < 0.03)
  const shape = CURVES.find((x) => x.v === b.preset)?.label || 'your own curve'
  return `Energy: ${top ? top.label : `top ${Math.round(c * 100)}%`}${top && top.v < 1 ? ` (top ${Math.round(c * 100)}%)` : ''} · ${shape}`
}
function summary(t) {
  const b = t.beat
  const out = [{ text: sourceText(b), kind: 'src' }, { text: energyText(b), kind: 'energy' }]
  const hits = (t.sections || []).filter((x) => x.edge_in).length
  if (b.hits && hits) out.push({ text: `hits on ${hits} scene change${hits === 1 ? '' : 's'}`, kind: '' })
  out.push({ text: b.end ? 'ends on the last frame' : 'fades out', kind: '' })
  const ins = (b.instruments || []).map((k) => instrumentNames.value[k] || k)
  if (ins.length) out.push({ text: ins.join(' · '), kind: 'ins' })
  const VOICE_NAMES = { male: 'Male hums', chant: 'Male chant', female: 'Female voice', choir: 'Choir' }
  out.push({ text: VOICE_NAMES[b.voices] ? `Voices: ${VOICE_NAMES[b.voices]} (wordless)` : 'No voices', kind: b.voices && b.voices !== 'none' ? 'voice' : '' })
  if (b.prompt) out.push({ text: 'your own prompt', kind: 'warn' })
  return out
}
const leversText = (b) => LEVERS.filter((l) => (b.levers?.[l.v] || 0) > 0).map((l) => `${l.label} ${b.levers[l.v]}`).join(' · ')

// Takes being made, shown above the rest while a run is going.
const pending = computed(() => (running.value ? (job.value?.takes || []).filter((t) => t.state !== 'done') : []))
const sourceTake = computed(() => takes.value.find((t) => t.id === job.value?.source) || null)
const starOnly = ref(false)
const shownTakes = computed(() => (starOnly.value ? takes.value.filter((t) => t.starred) : takes.value))
async function star(t) {
  t.starred = !t.starred
  try { await api.beatStar(id, t.id, t.starred) } catch { t.starred = !t.starred }
  if (starOnly.value && !takes.value.some((x) => x.starred)) starOnly.value = false
}
// Adapt: a new take from this one, changed by the picked tweaks and/or a note.
const adaptOptions = ref([])
api.beatAdapts().then((o) => { adaptOptions.value = o }).catch(() => {})
const adapting = ref(null)
const tweaks = ref([])
const adaptNote = ref('')
function openAdapt(t) {
  adapting.value = adapting.value === t.id ? null : t.id
  tweaks.value = []
  adaptNote.value = ''
}
function doAdapt(t) {
  const body = { adapt: { take: t.id, tweaks: tweaks.value, note: adaptNote.value.trim() } }
  adapting.value = null
  generate(body)
}
async function use(t) {
  await api.beatUse(id, t.id)
  const r = await api.reel(id)
  beat.value.inUse = r.settings?.beat?.inUse ?? { take: t.id, length: t.length, tempo: t.tempo }
}
async function remove(t) {
  if (!confirm(`Delete take ${t.n} (${t.label})?${inUse.value?.take === t.id ? ' It stays in the reel until you pick another song.' : ''}`)) return
  if (playing.value === t.id) stop()
  await api.beatDelete(id, t.id)
  takes.value = takes.value.filter((x) => x.id !== t.id)
}
// The take in the reel, checked against the reel's length now at its tempo.
const staleLen = ref(0)
const stale = computed(() => inUse.value && staleLen.value && Math.abs(staleLen.value - inUse.value.length) > 0.05)
watch(() => [inUse.value?.take, preview.value?.seconds], async () => {
  if (!inUse.value) { staleLen.value = 0; return }
  try { staleLen.value = (await api.beatLength(id, inUse.value.tempo)).seconds } catch { staleLen.value = 0 }
}, { immediate: true })

// ---------------------------------------------------------------- playing
const audioEl = ref(null)
const playing = ref(null)
const playT = ref(0)
const analyser = ref(null)
let actx = null
let tick = 0
const playingTake = computed(() => takes.value.find((t) => t.id === playing.value) || {})
const playingEnv = computed(() => (playing.value ? envs[playing.value] : null))
const mode = computed(() => (running.value ? 'generating' : playing.value ? 'playing' : 'idle'))
function ensureAnalyser() {
  if (actx) return
  try {
    actx = new (window.AudioContext || window.webkitAudioContext)()
    const node = actx.createAnalyser()
    node.fftSize = 256
    actx.createMediaElementSource(audioEl.value).connect(node)
    node.connect(actx.destination)
    analyser.value = node
  } catch { analyser.value = null }   // the picture just goes without the live bars
}
async function toggle(t) {
  const a = audioEl.value
  if (playing.value === t.id) { a.pause(); return }
  window.dispatchEvent(new CustomEvent('footage-audio', { detail: 'take' }))   // stops a song preview
  ensureAnalyser()
  await actx?.resume?.()
  a.src = api.beatTakeAudio(id, t.id)
  playing.value = t.id
  playT.value = 0
  try { await a.play() } catch { playing.value = null }
  cancelAnimationFrame(tick)
  const step = () => { playT.value = a.currentTime; if (playing.value) tick = requestAnimationFrame(step) }
  tick = requestAnimationFrame(step)
}
function onPause() { if (audioEl.value && !audioEl.value.ended) playing.value = null }
function stop() { audioEl.value?.pause(); playing.value = null }
function seekTo(s) { if (audioEl.value) audioEl.value.currentTime = Math.max(0, s) }

// ---------------------------------------------------------------- the headline over the picture
const headline = computed(() => {
  const j = job.value
  if (running.value) {
    const last = j.log?.[j.log.length - 1]?.text || 'Starting…'
    const arriving = (j.takes || []).filter((t) => t.state === 'receiving')
    const most = arriving.length ? Math.max(...arriving.map((t) => t.received)) : 0
    return {
      big: last,
      sub: `${engine.value === 'elevenlabs' ? 'ElevenLabs' : 'Lyria'} · ${Math.round(elapsed.value)}s`
        + (arriving.length ? ` · audio arriving: ${fmtTime(most)} of ${fmtTime(arriving[0].expected)}` : ''),
    }
  }
  if (playing.value) {
    const t = playingTake.value
    return { big: `Take ${t.n} · ${t.label}`, sub: `${fmtTime(playT.value)} / ${fmtTime(t.length || 0)} · click the picture to jump` }
  }
  if (j?.status === 'failed') return { big: 'That run didn\'t work', sub: j.error || '' }
  if (j?.status === 'done' && takes.value.length) return { big: j.log?.[j.log.length - 1]?.text || 'Takes ready', sub: 'Play one below.' }
  const p = preview.value
  if (!p) return { big: 'Loading the reel…', sub: '' }
  if (p.error) return { big: p.error, sub: '' }
  const hits = beat.value?.hits && heroEdges.value.length ? ` · hits at ${heroEdges.value.map((e) => fmtTime(e)).join(', ')}` : ''
  return { big: p.sections.map((s) => s.name).join(' → '), sub: `${p.sections.length} sections over ${fmtTime(p.seconds)}${hits}` }
})

// ---------------------------------------------------------------- leaving
function leave(e) {
  if (e?.target?.closest?.('input, textarea, select')) return
  stop()
  router.push(`/reel/${id}`)
}
function onKey(e) { if (e.key === 'Escape') leave(e) }
const otherAudio = (e) => { if (e.detail !== 'take') stop() }   // a song preview started
onMounted(() => { load(); window.addEventListener('keydown', onKey); window.addEventListener('footage-audio', otherAudio) })
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('footage-audio', otherAudio)
  clearTimeout(pollTimer); clearTimeout(saveTimer); cancelAnimationFrame(tick)
  audioEl.value?.pause(); actx?.close?.()
})
</script>

<style scoped>
.studio {
  position: fixed; inset: 0; z-index: 60; overflow: auto; background: var(--cream); color: var(--ink);
  --v-blue: #8fb0dc; --v-soft: rgb(143 176 220 / 16%); --v-ink: #e4e7ea; --v-muted: #98a3ad; --v-hit: #e08038;
  --v-band: rgb(255 255 255 / 4%); --v-cream: #efe6cf; --v-dim: rgb(143 176 220 / 20%);
}
.top {
  position: sticky; top: 0; z-index: 2; display: flex; flex-wrap: wrap; align-items: center; gap: 10px 16px;
  padding: 12px 24px; background: var(--stage); color: #e4e7ea; border-bottom: 1px solid rgb(255 255 255 / 8%);
}
.back { flex: none; white-space: nowrap; max-width: 220px; overflow: hidden; text-overflow: ellipsis; border: 1px solid rgb(255 255 255 / 18%); background: transparent; color: inherit; border-radius: 8px; padding: 6px 12px; font: inherit; cursor: pointer; }
.back:hover { border-color: rgb(255 255 255 / 40%); }
.ttl { display: flex; flex-direction: column; }
.kicker { font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: #98a3ad; }
.ttl h1 { margin: 0; font-size: 20px; color: #bfd6b1; }
.facts { display: flex; gap: 6px; }
.facts span { padding: 3px 9px; border-radius: 999px; background: rgb(255 255 255 / 8%); font-size: 12px; }
.spacer { flex: 1; }
.engine { display: inline-flex; padding: 3px; border-radius: 10px; background: rgb(255 255 255 / 7%); }
.engine button { border: 0; background: transparent; color: #c5ccd3; padding: 6px 12px; border-radius: 8px; font: inherit; font-size: 13px; cursor: pointer; }
.engine button.on { background: #8fb0dc; color: #10151b; font-weight: 600; }
.go { padding: 10px 20px; font-size: 15px; background: #8fb0dc; color: #10151b; border-color: #8fb0dc; }
.go:disabled { opacity: 0.6; }
.hero { position: relative; height: clamp(240px, 34vh, 360px); background: var(--stage); }
.headline { position: absolute; left: 24px; right: 24px; bottom: 74px; pointer-events: none; color: #eef1f4; text-shadow: 0 1px 8px rgb(0 0 0 / 55%); }
.headline .big { margin: 0; font-size: clamp(16px, 2vw, 22px); font-weight: 600; max-width: 70ch; }
.headline .sub { margin: 4px 0 0; font-size: 13px; color: #b8c1ca; }
.pills { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.pill { font-size: 12px; padding: 3px 10px; border-radius: 999px; background: rgb(255 255 255 / 10%); }
.pill.receiving { background: rgb(143 176 220 / 30%); }
.pill.done { background: rgb(239 230 207 / 25%); }
.pill.failed { background: rgb(224 128 56 / 35%); }
.pad { padding: 12px 24px; }
.opened { display: flex; align-items: center; gap: 10px; margin: 14px 24px 0; padding: 10px 14px; border-radius: 10px; background: rgb(111 147 196 / 16%); font-size: 14px; }
.opened .x { margin-left: auto; }
.cols { display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, 420px); gap: 20px; padding: 18px 24px 40px; align-items: start; }
@media (max-width: 1000px) { .cols { grid-template-columns: 1fr; } }
.side { position: sticky; top: 76px; display: flex; flex-direction: column; gap: 14px; }
@media (max-width: 1000px) { .side { position: static; } }
.card { border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; background: var(--paper); }
.card h3 { margin: 0 0 8px; font-size: 14px; }
.card h3 small { font-weight: 400; margin-left: 6px; }
.log { list-style: none; margin: 0; padding: 0; max-height: 260px; overflow: auto; font-size: 13px; display: flex; flex-direction: column; gap: 6px; }
.log li { display: grid; grid-template-columns: 38px 1fr; gap: 8px; line-height: 1.35; }
.log .t { color: var(--muted); font-size: 11px; padding-top: 2px; }
.log li.error span:last-child { color: var(--danger); }
.log li.done span:last-child { font-weight: 600; }
.takes ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.take { display: grid; grid-template-columns: 40px minmax(0, 1fr); gap: 10px; padding: 10px; border: 1px solid var(--line); border-radius: 10px; }
.take.inuse { border-color: #6f93c4; box-shadow: inset 0 0 0 1px #6f93c4; }
.play { width: 40px; height: 40px; border-radius: 50%; border: 0; background: #6f93c4; color: #fff; font-size: 13px; cursor: pointer; }
.tinfo { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.tinfo b { font-size: 13px; }
.wave { width: 100%; height: 26px; margin-top: 4px; }
.wave rect { fill: #6f93c4; opacity: 0.45; }
.wave rect.past { opacity: 1; }
.tact { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.tact .done { cursor: default; }
.warnbtn { border-color: var(--warn); color: var(--warn); }
.tname { display: flex; flex-wrap: nowrap; align-items: baseline; gap: 4px; }
.tname b { flex: 1; min-width: 0; }
.tname .star { flex: none; }
.star { border: 0; background: none; padding: 0 2px; font-size: 17px; line-height: 1; color: var(--muted); cursor: pointer; }
.star.on { color: #e0a43a; }
.star:hover { color: #e0a43a; }
.from { color: #6f93c4; font-size: 12px; }
.starfilter { margin-left: 8px; font-size: 12px; font-weight: 400; }
.take.source { border-color: #e08038; box-shadow: inset 0 0 0 1px #e08038; }
.tag { font-size: 12px; padding: 3px 10px; border-radius: 999px; background: rgb(224 128 56 / 18%); color: #e08038; }
.take.pending { border-style: dashed; border-color: #6f93c4; }
.spin { width: 40px; height: 40px; border-radius: 50%; border: 3px solid rgb(111 147 196 / 25%); border-top-color: #6f93c4; animation: spin 1s linear infinite; box-sizing: border-box; }
.spin.failed { animation: none; border-color: var(--danger); }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
.pbar { height: 4px; border-radius: 2px; background: rgb(111 147 196 / 18%); margin-top: 6px; overflow: hidden; }
.pbar i { display: block; height: 100%; background: #6f93c4; transition: width 0.3s; }
.tsum { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; margin-top: 6px; }
.tsum .chip { font-size: 11px; padding: 2px 8px; border-radius: 999px; background: rgb(128 128 128 / 12%); color: var(--ink); }
.tsum .chip.src { background: rgb(111 147 196 / 18%); font-weight: 600; }
.tsum .chip.energy { background: rgb(224 128 56 / 14%); }
.tsum .chip.ins { background: rgb(138 163 124 / 18%); }
.tsum .chip.voice { background: rgb(150 120 190 / 18%); }
.tsum .chip.warn { background: rgb(224 128 56 / 22%); }
.tsum .more { font-size: 11px; margin-left: 2px; }
.tdetails { display: grid; grid-template-columns: auto 1fr; gap: 3px 10px; margin: 8px 0 0; font-size: 12px; }
.tdetails dt { color: var(--muted); }
.tdetails dd { margin: 0; }
.tdetails .prompt { white-space: pre-wrap; color: var(--muted); }
.adapt { grid-column: 1 / -1; display: flex; flex-direction: column; gap: 8px; padding: 10px; border-radius: 8px; background: rgb(111 147 196 / 10%); }
.adapt p { margin: 0; }
.adapt .chips { display: flex; flex-wrap: wrap; gap: 6px; }
.adapt input { font: inherit; font-size: 13px; padding: 6px 8px; }
.adapt .row { display: flex; gap: 6px; }
.directions { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-bottom: 10px; padding: 8px 10px; border-radius: 8px; background: rgb(111 147 196 / 10%); }
.x { margin-left: auto; border: 0; background: none; color: var(--muted); cursor: pointer; font-size: 14px; }
.x:hover { color: var(--danger); }
</style>
