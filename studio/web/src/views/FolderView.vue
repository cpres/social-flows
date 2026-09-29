<template>
  <main v-if="error" class="page-msg">{{ error }} · <RouterLink to="/">back</RouterLink></main>
  <main v-else-if="!clips.length && loading" class="page-msg muted">Loading clips…</main>
  <main v-else class="folder">
    <!-- header: title, montage summary, actions -->
    <section class="bar">
      <RouterLink to="/" class="back" title="All folders">←</RouterLink>
      <div class="title">
        <h1>{{ folderTitle(name) }}</h1>
        <p class="muted">
          {{ kept.length }} of {{ clips.length }} kept ·
          montage <b class="total">{{ fmtTime(montageLength) }}</b>
          <span class="save">{{ saveState }}</span>
        </p>
      </div>
      <div class="bulk">
        <label class="field">
          Length for all
          <input type="number" min="0.2" step="0.1" v-model.number="settings.defaultLength" />
        </label>
        <button class="btn small" @click="applyLengthToAll">Apply to kept clips</button>
      </div>
      <button class="btn" @click="showSettings = !showSettings" :class="{ active: showSettings }">Settings</button>
      <button class="btn primary" @click="doExport" :disabled="exporting || !kept.length">
        {{ exporting ? 'Exporting…' : 'Export & preview cut list' }}
      </button>
    </section>

    <section v-if="showSettings" class="settings">
      <label class="field wide">
        Music file (optional — path relative to this folder, or absolute)
        <input v-model.trim="settings.music" placeholder="~/Music/montage-bed.mp3" />
      </label>
      <label class="field check">
        <span><input type="checkbox" v-model="settings.beatSync" :disabled="!settings.music" /> Beat sync</span>
        <small v-if="settings.beatSync">Cuts snap to beats; your lengths become approximate ({{ settings.beatsPerCut }} beats per cut).</small>
        <small v-else>Your lengths are used exactly.</small>
      </label>
      <label class="field" v-if="settings.beatSync">
        Beats per cut
        <input type="number" min="1" max="8" v-model.number="settings.beatsPerCut" />
      </label>
      <label class="field">
        Framing
        <select v-model="settings.fit">
          <option value="fill">Fill (crop to 9:16)</option>
          <option value="blur">Blurred background</option>
          <option value="pad">Brand colour bars</option>
        </select>
      </label>
      <label class="field">
        Glasses audio volume
        <input type="number" min="0" max="1" step="0.05" v-model.number="settings.originalVolume" />
      </label>
      <label class="field">
        Photo hold (s)
        <input type="number" min="0.2" step="0.1" v-model.number="settings.defaultHold" />
      </label>
    </section>

    <!-- montage strip: every kept cut, width proportional to its length -->
    <section class="montage" v-if="kept.length">
      <button
        v-for="c in kept" :key="c.file" class="seg"
        :class="{ current: c === current, photo: c.kind === 'photo' }"
        :style="{ flexGrow: c.length }"
        :title="`${c.file} · ${c.length.toFixed(1)}s`"
        @click="select(clips.indexOf(c))"
      >{{ c.length.toFixed(1) }}</button>
    </section>

    <div class="body">
      <aside class="list">
        <ClipCard
          v-for="(c, i) in clips" :key="c.file" :clip="c" :folder="name"
          :selected="i === selected" :ref="(el) => (cardEls[i] = el)"
          @select="select(i)" @toggle="c.keep = !c.keep"
        />
      </aside>

      <section class="editor" v-if="current">
        <div class="stage">
          <video
            v-if="current.kind === 'video'" ref="video" :src="api.media(name, current.file)"
            preload="auto" playsinline @loadedmetadata="onLoaded" @play="playing = true" @pause="playing = false"
            @click="togglePlay" @error="videoError = true"
          ></video>
          <img v-else :src="api.thumb(name, current.file, 0, 1280)" alt="" />
          <p v-if="videoError" class="unplayable">
            This browser can't play this file's codec (HEVC <code>.mov</code> often won't play in Chrome — try Safari).
            Thumbnails and trimming still work.
          </p>
        </div>

        <template v-if="current.kind === 'video'">
          <TrimBar
            :duration="duration" :start="current.start" :length="current.length" :playhead="playhead"
            :thumb-at="(t) => api.thumb(name, current.file, t, 160)"
            @update="setRange" @seek="seek"
          />
          <div class="controls">
            <button class="btn" @click="togglePlay" title="Space">{{ playing ? 'Pause' : 'Play' }}</button>
            <button class="btn" :class="{ active: loopSel }" @click="playSelection" title="Enter">
              ▶ Play selection
            </button>
            <span class="muted mono">{{ fmtTime(playhead) }}</span>
            <span class="spacer"></span>
            <button class="btn small" @click="setIn" title="I">Start here <kbd>I</kbd></button>
            <button class="btn small" @click="setOut" title="O">End here <kbd>O</kbd></button>
          </div>
        </template>

        <div class="timing">
          <label class="field" v-if="current.kind === 'video'">
            Start
            <input :value="fmtTime(current.start)" @change="onStartInput" />
          </label>
          <label class="field">
            {{ current.kind === 'video' ? 'Length (seconds)' : 'Hold (seconds)' }}
            <input type="number" min="0.2" step="0.1" :value="current.length.toFixed(1)" @change="onLengthInput" />
          </label>
          <div class="presets">
            <span class="muted">Quick lengths</span>
            <div>
              <button
                v-for="p in presets" :key="p" class="btn small"
                :class="{ active: Math.abs(current.length - p) < 0.05 }" @click="setLength(p)"
              >{{ p }}s</button>
            </div>
          </div>
          <label class="field check">
            <span><input type="checkbox" v-model="current.keep" /> Keep in montage <kbd>X</kbd></span>
          </label>
        </div>
        <p class="muted keys">
          <kbd>Space</kbd> play · <kbd>Enter</kbd> play selection · <kbd>I</kbd>/<kbd>O</kbd> set start/end at playhead ·
          <kbd>←</kbd>/<kbd>→</kbd> nudge start 0.1s · <kbd>↑</kbd>/<kbd>↓</kbd> previous/next clip · <kbd>X</kbd> keep/skip
        </p>
      </section>
    </div>

    <div class="modal" v-if="exportResult" @click.self="exportResult = null">
      <div class="dialog">
        <h2>{{ exportResult.ok ? 'Cut list' : 'Engine reported a problem' }}</h2>
        <p class="muted">Wrote <code>{{ exportResult.path }}</code></p>
        <pre>{{ exportResult.dryRun }}</pre>
        <p class="muted">Render it with:</p>
        <pre class="cmd">{{ exportResult.command }}</pre>
        <button class="btn primary" @click="exportResult = null">Close</button>
      </div>
    </div>
  </main>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../api'
import { clamp, fmtTime, folderTitle, parseTime } from '../time'
import ClipCard from '../components/ClipCard.vue'
import TrimBar from '../components/TrimBar.vue'

const props = defineProps({ name: { type: String, required: true } })
const emit = defineEmits(['root'])

const presets = [0.5, 1, 1.5, 2, 3, 5]
const clips = ref([])
const settings = reactive({})
const selected = ref(0)
const loading = ref(true)
const error = ref('')
const saveState = ref('')
const showSettings = ref(false)
const exporting = ref(false)
const exportResult = ref(null)
const cardEls = []

const video = ref(null)
const playhead = ref(0)
const playing = ref(false)
const loopSel = ref(false)
const videoError = ref(false)
const loadedDuration = ref(0)

const current = computed(() => clips.value[selected.value])
const kept = computed(() => clips.value.filter((c) => c.keep))
const montageLength = computed(() => kept.value.reduce((a, c) => a + c.length, 0))
const duration = computed(() => current.value?.duration || loadedDuration.value || 0)

// ---------------------------------------------------------------- load & autosave

let ready = false
let saveTimer
onMounted(async () => {
  try {
    const data = await api.folder(props.name)
    clips.value = data.clips
    Object.assign(settings, data.settings)
    emit('root', data.path)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
    await nextTick()
    ready = true
  }
})

watch([clips, settings], () => {
  if (!ready) return
  saveState.value = '· saving…'
  clearTimeout(saveTimer)
  saveTimer = setTimeout(save, 600)
}, { deep: true })

async function save() {
  try {
    await api.save(props.name, { clips: clips.value, settings })
    saveState.value = '· saved'
  } catch (e) {
    saveState.value = `· not saved: ${e.message}`
  }
}

// ---------------------------------------------------------------- selection

function select(i) {
  if (i < 0 || i >= clips.value.length) return
  selected.value = i
  loopSel.value = false
  videoError.value = false
  loadedDuration.value = 0
  playhead.value = current.value.start
  // Keep the selected card visible without scrolling the whole page.
  const el = cardEls[i]?.$el
  const list = el?.parentElement
  if (el && list) {
    if (el.offsetTop < list.scrollTop) list.scrollTop = el.offsetTop
    else if (el.offsetTop + el.offsetHeight > list.scrollTop + list.clientHeight)
      list.scrollTop = el.offsetTop + el.offsetHeight - list.clientHeight
  }
}

function onLoaded() {
  loadedDuration.value = video.value.duration
  seek(current.value.start)
}

// ---------------------------------------------------------------- playback

let raf
function tick() {
  const v = video.value
  if (v) {
    playhead.value = v.currentTime
    const c = current.value
    if (loopSel.value && c && v.currentTime >= c.start + c.length) v.currentTime = c.start
  }
  raf = requestAnimationFrame(tick)
}
onMounted(() => { raf = requestAnimationFrame(tick) })
onBeforeUnmount(() => {
  cancelAnimationFrame(raf)
  clearTimeout(saveTimer)
  if (ready) save()
})

function seek(t) {
  playhead.value = t
  if (video.value) video.value.currentTime = t
}

function togglePlay() {
  const v = video.value
  if (!v) return
  if (v.paused) v.play()
  else { v.pause(); loopSel.value = false }
}

function playSelection() {
  const v = video.value
  if (!v) return
  if (loopSel.value && !v.paused) { v.pause(); loopSel.value = false; return }
  loopSel.value = true
  v.currentTime = current.value.start
  v.play()
}

// ---------------------------------------------------------------- timing edits

function setRange({ start, length }) {
  const c = current.value
  c.start = Math.round(start * 100) / 100
  c.length = Math.round(length * 100) / 100
}

function setLength(len) {
  const c = current.value
  if (c.kind === 'photo') { c.length = Math.max(0.2, len); return }
  len = clamp(len, 0.2, duration.value)
  // Keep the start where it is if possible; otherwise slide earlier to fit.
  setRange({ start: Math.min(c.start, duration.value - len), length: len })
}

function setStart(s) {
  const c = current.value
  setRange({ start: clamp(s, 0, duration.value - c.length), length: c.length })
  seek(c.start)
}

function setIn() {
  const c = current.value
  const end = c.start + c.length
  const s = playhead.value
  // Start at playhead; keep the end if it's still after, else keep the length.
  if (end - s >= 0.2) setRange({ start: s, length: end - s })
  else setStart(s)
}

function setOut() {
  const c = current.value
  if (playhead.value - c.start >= 0.2) setRange({ start: c.start, length: playhead.value - c.start })
}

function onStartInput(e) {
  const t = parseTime(e.target.value)
  if (!isNaN(t)) setStart(t)
  e.target.value = fmtTime(current.value.start)
}

function onLengthInput(e) {
  const len = Number(e.target.value)
  if (len > 0) setLength(len)
  e.target.value = current.value.length.toFixed(1)
}

function applyLengthToAll() {
  const len = Number(settings.defaultLength)
  if (!(len > 0)) return
  for (const c of clips.value) {
    if (!c.keep || c.kind !== 'video') continue
    const l = Math.min(len, c.duration)
    c.length = l
    c.start = Math.min(c.start, Math.max(0, c.duration - l))
  }
}

// ---------------------------------------------------------------- export

async function doExport() {
  exporting.value = true
  try {
    clearTimeout(saveTimer)
    await save()
    exportResult.value = await api.exportFolder(props.name)
  } catch (e) {
    exportResult.value = { ok: false, path: '', dryRun: e.message, command: '' }
  } finally {
    exporting.value = false
  }
}

// ---------------------------------------------------------------- keyboard

function onKey(e) {
  if (e.target.closest('input, select, textarea') || e.metaKey || e.ctrlKey || !current.value) return
  const k = e.key
  if (k === ' ') togglePlay()
  else if (k === 'Enter') playSelection()
  else if (k === 'i' || k === 'I') setIn()
  else if (k === 'o' || k === 'O') setOut()
  else if (k === 'x' || k === 'X') current.value.keep = !current.value.keep
  else if (k === 'ArrowDown') select(selected.value + 1)
  else if (k === 'ArrowUp') select(selected.value - 1)
  else if (k === 'ArrowLeft' && current.value.kind === 'video') setStart(current.value.start - (e.shiftKey ? 1 : 0.1))
  else if (k === 'ArrowRight' && current.value.kind === 'video') setStart(current.value.start + (e.shiftKey ? 1 : 0.1))
  else if (k === 'Escape') exportResult.value = null
  else return
  e.preventDefault()
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<style scoped>
.page-msg { padding: 32px 24px; }
.folder { max-width: 1440px; margin: 0 auto; padding: 16px 24px 48px; }

.bar { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.back {
  display: grid; place-items: center; width: 36px; height: 36px; border-radius: 50%;
  background: var(--paper); box-shadow: var(--shadow); font-size: 18px;
}
.title { flex: 1; min-width: 220px; }
h1 { margin: 0; font-size: 24px; color: var(--forest); }
.title p { margin: 2px 0 0; font-size: 14px; }
.total { color: var(--forest); font-family: ui-monospace, monospace; }
.save { font-size: 12px; }
.bulk { display: flex; align-items: flex-end; gap: 8px; }
.bulk .field { width: 110px; }
.bulk .field input { padding: 3px 8px; }

.settings {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 14px;
  margin-top: 14px; padding: 16px; background: var(--paper); border-radius: var(--radius); box-shadow: var(--shadow);
}
.settings .wide { grid-column: span 2; }
.field.check span { display: flex; gap: 6px; align-items: center; color: var(--ink); font-size: 14px; }
.field.check small { font-size: 12px; }

.montage { display: flex; gap: 2px; margin: 16px 0 4px; height: 26px; }
.seg {
  flex-basis: 0; min-width: 6px; border: 0; border-radius: 4px; cursor: pointer;
  background: var(--sage); color: var(--forest); font-size: 10px; font-weight: 700; overflow: hidden;
  padding: 0;
}
.seg.photo { background: var(--sage-soft); }
.seg.current { background: var(--forest); color: var(--cream); }

.body { display: grid; grid-template-columns: 340px 1fr; gap: 24px; margin-top: 12px; align-items: start; }
.list {
  display: flex; flex-direction: column; gap: 2px;
  max-height: calc(100vh - 190px); overflow-y: auto; position: sticky; top: 12px; padding-right: 4px;
}
.editor { min-width: 0; }
.stage {
  position: relative; background: #121812; border-radius: var(--radius); overflow: hidden;
  display: grid; place-items: center; height: min(46vh, 560px); margin-bottom: 32px;
}
.stage video, .stage img { max-width: 100%; max-height: 100%; display: block; }
.stage video { cursor: pointer; }
.unplayable {
  position: absolute; left: 16px; right: 16px; bottom: 16px; margin: 0; padding: 10px 12px;
  background: var(--paper); border-radius: 8px; font-size: 13px;
}
.controls { display: flex; align-items: center; gap: 8px; margin-top: 14px; flex-wrap: wrap; }
.mono { font-family: ui-monospace, monospace; font-size: 13px; }
.spacer { flex: 1; }
.timing {
  display: flex; gap: 20px; align-items: flex-end; flex-wrap: wrap; margin-top: 18px;
  padding: 16px; background: var(--paper); border-radius: var(--radius); box-shadow: var(--shadow);
}
.timing .field { width: 150px; }
.timing .field input { font-family: ui-monospace, monospace; font-size: 18px; }
.presets { display: flex; flex-direction: column; gap: 4px; font-size: 12px; }
.presets div { display: flex; gap: 4px; flex-wrap: wrap; }
.timing .check { width: auto; }
.keys { font-size: 12px; line-height: 2; }

.modal { position: fixed; inset: 0; background: rgb(20 28 20 / 50%); display: grid; place-items: center; z-index: 10; padding: 16px; }
.dialog { background: var(--paper); border-radius: var(--radius); padding: 20px 24px; width: min(760px, 100%); max-height: 90vh; overflow: auto; }
.dialog h2 { margin: 0 0 4px; color: var(--forest); }
.dialog pre {
  background: var(--cream); padding: 12px; border-radius: 8px; font-size: 12px;
  overflow-x: auto; max-height: 50vh;
}
.dialog .cmd { max-height: none; }

@media (max-width: 860px) {
  .body { grid-template-columns: 1fr; }
  .list { position: static; max-height: 40vh; }
}
</style>
