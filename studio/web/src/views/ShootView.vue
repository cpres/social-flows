<template>
  <main v-if="error" class="screen-msg">{{ error }} · <RouterLink to="/">back</RouterLink></main>
  <main v-else-if="loading" class="screen-msg muted">Loading clips…</main>
  <main v-else class="screen">
    <section class="headbar">
      <RouterLink to="/" class="back" title="Home">←</RouterLink>
      <div class="title">
        <h1>{{ folderTitle(name) }}</h1>
        <p class="muted">
          {{ media.length }} files · {{ items.length }} part{{ items.length === 1 ? '' : 's' }} tagged into reels
        </p>
      </div>
      <button class="btn" @click="folderToReel" title="Make a reel from everything in this folder">
        {{ hasSidecar ? 'Turn earlier trims into a reel' : 'Make a reel from this folder' }}
      </button>
    </section>

    <div class="workspace" v-if="media.length">
      <aside class="cliplist" ref="listEl">
        <button class="refresh" @click="reload" :disabled="refreshing" title="Look for new clips in this folder">
          ↻ {{ refreshing ? 'Checking…' : 'Check for new clips' }}
          <span v-if="newCount" class="new">+{{ newCount }} new</span>
        </button>
        <ClipCard
          v-for="(m, i) in media" :key="m.id" :media="m"
          :thumb-time="m.kind === 'video' ? draftOf(m).start : 0"
          :sub="clockTime(m.capturedAt)"
          :dots="partsOf(m.id).map((p) => ({ color: reelColor(p.reelId), label: reelName(p.reelId) }))"
          :selected="i === selected" :used="partsOf(m.id).length > 0" @select="select(i)"
        />
        <button class="refresh" @click="reload" :disabled="refreshing" title="Look for new clips in this folder">
          ↻ {{ refreshing ? 'Checking…' : 'Check for new clips' }}
        </button>
      </aside>

      <section class="editor" v-if="current">
        <div class="preview-col">
          <ReelFrame
            :key="current.id" :media="current" fit="fill" :guides="guides" muted
            :focus-x="range.focusX ?? 0.5" :focus-y="range.focusY ?? 0.5" :poster-time="range.start"
            :bind-video="(el) => (player.video.value = el)"
            @loaded="onLoaded" @play="player.events.onPlay" @pause="player.events.onPause"
            @error="player.events.onError" @toggle="player.toggle" @focus="setFocus"
          >
            <p v-if="player.failed.value" class="unplayable">
              This browser can't play this file's codec (HEVC often won't play in Chrome — try Safari).
              Thumbnails and trimming still work.
            </p>
          </ReelFrame>
          <label class="guides-toggle muted"><input type="checkbox" v-model="guides" /> Show Instagram overlays <kbd>G</kbd></label>
        </div>

        <div class="edit-col">

        <p v-if="active" class="editing" :style="{ borderColor: reelColor(active.reelId) }">
          Editing its part in <b>{{ reelName(active.reelId) }}</b> — changes save as you go.
          <button class="btn small" @click="activeId = null">Done</button>
        </p>

        <template v-if="current.kind === 'video'">
          <TrimBar
            :duration="current.duration" :start="range.start" :length="range.length"
            :playhead="player.playhead.value" :segments="segments"
            :thumb-at="(t) => api.thumb(current.folder, current.file, t, 160)"
            @update="setRange" @seek="player.seek" @pick="activeId = $event"
          />
          <div class="controls">
            <button class="btn" @click="player.toggle">{{ player.playing.value ? 'Pause' : 'Play' }} <kbd>Enter</kbd></button>
            <button class="btn" :class="{ active: player.playingPart.value }" @click="player.playPart">▶ Play selection <kbd>Space</kbd></button>
            <span class="muted mono">{{ fmtTime(player.playhead.value) }}</span>
            <span class="spacer"></span>
            <button class="btn small" @click="setIn">Start here <kbd>I</kbd></button>
            <button class="btn small" @click="setOut">End here <kbd>O</kbd></button>
          </div>
        </template>

        <TimingFields
          :kind="current.kind" :start="range.start" :length="range.length"
          :duration="current.duration" @update="setRange"
        />

        <div class="panel" v-if="!active">
          <h3>{{ current.kind === 'video' ? 'Add this selection to a reel' : 'Use this photo in' }}</h3>
          <div class="chips">
            <button
              v-for="(r, i) in reels" :key="r.id" class="reelchip"
              :class="{ on: current.kind === 'photo' && partsOf(current.id).some((p) => p.reelId === r.id) }"
              @click="tag(r)"
            >
              <span class="sw" :style="{ background: reelColor(r.id) }"></span>
              {{ r.name }}
              <span class="count" v-if="countIn(r.id)" :title="`${countIn(r.id)} part(s) of this clip already in ${r.name}`">{{ countIn(r.id) }} here</span>
              <kbd v-if="i < 9" class="key" :title="`Press ${i + 1} to add`">{{ i + 1 }}</kbd>
            </button>
            <button class="reelchip" @click="newReelAndTag">+ New reel</button>
          </div>
          <p class="muted flash" v-if="flash">{{ flash }}</p>
        </div>

        <div class="panel" v-if="partsOf(current.id).length">
          <h3>In reels</h3>
          <div
            v-for="p in partsOf(current.id)" :key="p.id" class="partrow"
            :class="{ activepart: p.id === activeId }"
          >
            <span class="sw" :style="{ background: reelColor(p.reelId) }"></span>
            <RouterLink :to="`/reel/${p.reelId}?item=${p.id}`" class="reelname">{{ reelName(p.reelId) }}</RouterLink>
            <span class="mono" v-if="current.kind === 'video'">{{ fmtTime(p.start) }} → {{ fmtTime(p.start + p.length) }}</span>
            <b class="mono">{{ p.length.toFixed(1) }}s</b>
            <span class="spacer"></span>
            <button class="btn small" @click="activeId = p.id; player.seek(p.start)">Edit</button>
            <button class="btn small" @click="untag(p)" title="Remove from this reel">Remove</button>
          </div>
        </div>

        <p class="muted keys">
          <kbd>Space</kbd> play selection · <kbd>Enter</kbd> play/pause whole clip · <kbd>I</kbd>/<kbd>O</kbd> start/end at playhead ·
          <kbd>←</kbd>/<kbd>→</kbd> nudge 0.1s · <kbd>↑</kbd>/<kbd>↓</kbd> previous/next ·
          <kbd>1</kbd>–<kbd>9</kbd> add to reel · <kbd>G</kbd> Instagram overlays
        </p>
        </div>
      </section>
    </div>
    <p v-else class="muted">No clips or photos in this folder.</p>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, debouncedSaver } from '../api'
import { usePlayer } from '../player'
import { useRefreshOnFocus } from '../refresh'
import { clockTime, defaultStart, fitRange, fmtTime, folderTitle, reelColor } from '../time'
import ClipCard from '../components/ClipCard.vue'
import ReelFrame from '../components/ReelFrame.vue'
import TimingFields from '../components/TimingFields.vue'
import TrimBar from '../components/TrimBar.vue'

const props = defineProps({ name: { type: String, required: true } })
const emit = defineEmits(['root'])
const router = useRouter()

const media = ref([])
const items = ref([])
const reels = ref([])
const hasSidecar = ref(false)
const selected = ref(0)
const activeId = ref(null)     // a saved part being edited, or null for a new selection
const drafts = reactive({})    // mediaId -> { start, length } not yet in any reel
const loading = ref(true)
const error = ref('')
const flash = ref('')
const listEl = ref(null)

const current = computed(() => media.value[selected.value])
const active = computed(() => items.value.find((p) => p.id === activeId.value && p.mediaId === current.value?.id))
const range = computed(() => active.value || draftOf(current.value))
const player = usePlayer(() => range.value)

const partsOf = (mediaId) => items.value.filter((p) => p.mediaId === mediaId).sort((a, b) => a.start - b.start)
const countIn = (reelId) => partsOf(current.value.id).filter((p) => p.reelId === reelId).length
const reelName = (id) => reels.value.find((r) => r.id === id)?.name ?? 'reel'
const segments = computed(() =>
  partsOf(current.value.id)
    .filter((p) => p.id !== activeId.value)
    .map((p) => ({ id: p.id, start: p.start, length: p.length, color: reelColor(p.reelId),
                   label: `${reelName(p.reelId)} · ${fmtTime(p.start)} (${p.length.toFixed(1)}s)` })))

const DEFAULT_LENGTH = 2   // seconds, for a new selection on a video

// A fresh selection per clip, where the engine would cut by default.
function initDraft(m) {
  const length = m.kind === 'video' ? Math.min(DEFAULT_LENGTH, m.duration || DEFAULT_LENGTH) : 1.6
  drafts[m.id] = { start: m.kind === 'video' ? defaultStart(m.duration, length) : 0, length, focusX: 0.5, focusY: 0.5 }
}
const draftOf = (m) => (m && drafts[m.id]) || { start: 0, length: DEFAULT_LENGTH, focusX: 0.5, focusY: 0.5 }
const guides = ref(false)

const saver = debouncedSaver((id, patch) => api.updateItem(id, patch))

const refreshing = ref(false)
const newCount = ref(0)

function apply(data) {
  data.media.forEach((m) => { if (!drafts[m.id]) initDraft(m) })
  media.value = data.media
  items.value = data.items
  reels.value = [...data.reels].sort((a, b) => a.id - b.id)   // stable, so 1–9 keys don't move
  hasSidecar.value = data.hasSidecar
}

onMounted(async () => {
  try {
    const data = await api.folder(props.name)
    apply(data)
    emit('root', data.path)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
})

// Pick up clips added to the folder since the page opened, keeping your place.
async function reload() {
  if (refreshing.value || loading.value) return
  refreshing.value = true
  try {
    await saver.flushAll()
    const keep = current.value?.id
    const before = new Set(media.value.map((m) => m.id))
    const data = await api.folder(props.name)
    apply(data)
    newCount.value = data.media.filter((m) => !before.has(m.id)).length
    const i = media.value.findIndex((m) => m.id === keep)
    selected.value = i >= 0 ? i : 0
    if (newCount.value) setTimeout(() => { newCount.value = 0 }, 4000)
  } catch (e) {
    showFlash(e.message)
  } finally {
    refreshing.value = false
  }
}
useRefreshOnFocus(reload)
onBeforeUnmount(() => saver.flushAll())

// ---------------------------------------------------------------- selection

function select(i) {
  if (i < 0 || i >= media.value.length) return
  selected.value = i
  activeId.value = null
  player.reset()
  player.playhead.value = range.value.start
  const el = listEl.value?.querySelectorAll(':scope > .clip')[i]
  const list = listEl.value
  if (el && list) {
    if (el.offsetTop < list.scrollTop) list.scrollTop = el.offsetTop
    else if (el.offsetTop + el.offsetHeight > list.scrollTop + list.clientHeight)
      list.scrollTop = el.offsetTop + el.offsetHeight - list.clientHeight
  }
}

function onLoaded() {
  player.seek(range.value.start)
}

watch(activeId, (id) => { if (id) player.seek(range.value.start) })

// ---------------------------------------------------------------- editing

function setRange({ start, length }) {
  const r = current.value.kind === 'video'
    ? fitRange(start, length, current.value.duration)
    : { start: 0, length: Math.max(0.2, Math.round(length * 100) / 100) }
  if (active.value) {
    Object.assign(active.value, r)
    saver.queue(active.value.id, r)
  } else {
    Object.assign(draftOf(current.value), r)
  }
}

// Where the 9:16 window sits in a frame that isn't 9:16.
function setFocus({ x, y }) {
  const patch = { focusX: x, focusY: y }
  if (active.value) {
    Object.assign(active.value, patch)
    saver.queue(active.value.id, patch)
  } else {
    Object.assign(draftOf(current.value), patch)
  }
}

function setIn() {
  const r = range.value
  const end = r.start + r.length
  const t = player.playhead.value
  if (end - t >= 0.2) setRange({ start: t, length: end - t })
  else setRange({ start: t, length: r.length })
}

function setOut() {
  const r = range.value
  if (player.playhead.value - r.start >= 0.2) setRange({ start: r.start, length: player.playhead.value - r.start })
}

// ---------------------------------------------------------------- tagging

async function tag(reel) {
  const m = current.value
  if (m.kind === 'photo') {
    const existing = partsOf(m.id).find((p) => p.reelId === reel.id)
    if (existing) return untag(existing)
  }
  const r = draftOf(m)
  try {
    const item = await api.addItem(reel.id, {
      mediaId: m.id, start: r.start, length: r.length, focusX: r.focusX, focusY: r.focusY,
    })
    items.value.push(item)
    showFlash(`Added to ${reel.name}`)
  } catch (e) {
    showFlash(e.message)
  }
}

async function untag(part) {
  await api.deleteItem(part.id)
  items.value = items.value.filter((p) => p.id !== part.id)
  if (activeId.value === part.id) activeId.value = null
}

async function newReelAndTag() {
  const name = window.prompt('Name the new reel')
  if (!name?.trim()) return
  try {
    const r = await api.createReel(name.trim())
    reels.value.push({ id: r.id, name: r.name })
    await tag(r)
  } catch (e) {
    showFlash(e.message)
  }
}

async function folderToReel() {
  const name = window.prompt('Name for the new reel', props.name)
  if (!name?.trim()) return
  try {
    const r = await api.folderToReel(props.name, name.trim())
    router.push(`/reel/${r.id}`)
  } catch (e) {
    window.alert(e.message)
  }
}

let flashTimer
function showFlash(text) {
  flash.value = text
  clearTimeout(flashTimer)
  flashTimer = setTimeout(() => { flash.value = '' }, 2000)
}

// ---------------------------------------------------------------- keyboard

function onKey(e) {
  if (e.target.closest('input, select, textarea') || e.metaKey || e.ctrlKey || e.altKey || !current.value) return
  const k = e.key
  const video = current.value.kind === 'video'
  if (k === ' ') player.playPart()
  else if (k === 'Enter') player.toggle()
  else if ((k === 'i' || k === 'I') && video) setIn()
  else if ((k === 'o' || k === 'O') && video) setOut()
  else if (k === 'ArrowDown') select(selected.value + 1)
  else if (k === 'ArrowUp') select(selected.value - 1)
  else if (k === 'ArrowLeft' && video) { setRange({ ...range.value, start: range.value.start - (e.shiftKey ? 1 : 0.1) }); player.seek(range.value.start) }
  else if (k === 'ArrowRight' && video) { setRange({ ...range.value, start: range.value.start + (e.shiftKey ? 1 : 0.1) }); player.seek(range.value.start) }
  else if (k === 'Escape') activeId.value = null
  else if (k === 'g' || k === 'G') guides.value = !guides.value
  else if (/^[1-9]$/.test(k) && !active.value && reels.value[Number(k) - 1]) tag(reels.value[Number(k) - 1])
  else return
  e.preventDefault()
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<style scoped>
.chips { display: flex; gap: 8px; flex-wrap: wrap; }
.count {
  font-size: 11px; font-weight: 700; padding: 1px 7px; border-radius: 999px;
  background: var(--forest); color: var(--cream);
}
.key { opacity: 0.55; }
.flash { margin: 10px 0 0; font-size: 13px; color: var(--forest); }
.editing {
  margin: -16px 0 18px; padding: 8px 12px; border-left: 4px solid; background: var(--paper);
  border-radius: 6px; font-size: 14px; display: flex; align-items: center; gap: 10px;
}
.partrow { display: flex; align-items: center; gap: 10px; padding: 6px 4px; border-radius: 6px; }
.partrow.activepart { background: var(--sage-soft); }
.partrow .sw { width: 12px; height: 12px; border-radius: 50%; flex: none; }
.reelname { font-weight: 600; text-decoration: underline; text-decoration-color: var(--line); }
</style>
