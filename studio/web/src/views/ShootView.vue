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
      <button
        v-if="draftAt" class="btn" @click="weave"
        :title="`Pick up the weave you started (saved ${savedAt(draftAt)})`"
      >⧉ Continue weave draft</button>
      <button class="btn" @click="makingReel = true" title="Make a reel from everything in this folder, in a style you pick">
        {{ hasSidecar ? 'Turn earlier trims into a reel' : 'Make a reel from this folder' }}
      </button>
      <NewReelDialog v-if="makingReel" :folder="name" :default-name="folderTitle(name)" @close="makingReel = false" />
      <button
        class="btn" :class="{ active: picking }" @click="picking ? stopPicking() : startPicking()" :disabled="!media.length"
        title="Move clips or photos into another shoot folder, or delete them"
      >↪ Move or delete files</button>
    </section>
    <p v-if="imported?.length && !picking" class="justin muted">
      Just imported {{ imported.length }} file{{ imported.length === 1 ? '' : 's' }} here.
      Wrong folder? <button class="link" @click="startPicking(imported)">Move {{ imported.length === 1 ? 'it' : 'them' }}</button>
    </p>
    <p v-if="movedTo" class="justin">
      Moved {{ movedTo.count }} file{{ movedTo.count === 1 ? '' : 's' }} to
      <RouterLink :to="`/shoot/${encodeURIComponent(movedTo.folder)}`">{{ folderTitle(movedTo.folder) }}</RouterLink>.
    </p>
    <p v-if="deletedCount" class="justin">
      Deleted {{ deletedCount }} file{{ deletedCount === 1 ? '' : 's' }}. They're in the Trash if you want them back.
    </p>
    <WeavePrompt
      v-if="offer" :videos="offer.videos" :long="offer.long" :photos="offer.photos" :draft="!!draftAt"
      @weave="weave" @dismiss="dismissOffer"
    />

    <div class="workspace" v-if="media.length">
      <aside class="cliplist" ref="listEl">
        <div v-if="picking" class="pickbar">
          <span><b>{{ picked.size }}</b> picked ·
            <button class="link" @click="pickAll(true)">All</button> ·
            <button class="link" @click="pickAll(false)">None</button></span>
          <span class="spacer"></span>
          <button class="btn small" @click="stopPicking">Cancel</button>
          <button class="btn small primary" :disabled="!picked.size" @click="moving = true">Move {{ picked.size || '' }}…</button>
          <button class="btn small danger" :disabled="!picked.size" @click="deleting = true">Delete…</button>
        </div>
        <button class="refresh" @click="reload" :disabled="refreshing" title="Look for new clips in this folder">
          ↻ {{ refreshing ? 'Checking…' : 'Check for new clips' }}
          <span v-if="newCount" class="new">+{{ newCount }} new</span>
        </button>
        <ClipCard
          v-for="(m, i) in media" :key="m.id" :media="m"
          :thumb-time="m.kind === 'video' ? draftOf(m).start : 0"
          :sub="clockTime(m.capturedAt) + (kept.has(m.id) ? ' · picked' : '')"
          :dots="partsOf(m.id).map((p) => ({ color: reelColor(p.reelId), label: reelName(p.reelId) }))"
          :selected="!picking && i === selected" :used="partsOf(m.id).length > 0"
          @select="picking ? togglePick(m.id) : select(i)"
        >
          <input v-if="picking" type="checkbox" class="pickbox" :checked="picked.has(m.id)" tabindex="-1" />
        </ClipCard>
        <button class="refresh" @click="reload" :disabled="refreshing" title="Look for new clips in this folder">
          ↻ {{ refreshing ? 'Checking…' : 'Check for new clips' }}
        </button>
      </aside>

      <section class="editor" v-if="current">
        <div class="preview-col">
          <ReelFrame
            :key="current.id" :media="current" :fit="current.kind === 'video' && range.layout ? range.layout : 'fill'"
            :guides="guides" muted
            :focus-x="range.focusX ?? 0.5" :focus-y="range.focusY ?? 0.5" :zoom="range.zoom || 1" :poster-time="range.start"
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
            :pins="pins" :pin-on="pinOn"
            @update="setRange" @seek="player.seek" @pick="activeId = $event"
            @pin-click="centreOn" @pin-move="movePin" @pin-drop="savePins" @pin-remove="removePin"
          />
          <div class="controls">
            <button class="btn" @click="player.toggle">{{ player.playing.value ? 'Pause' : 'Play' }} <kbd>Enter</kbd></button>
            <button class="btn" :class="{ active: player.playingPart.value }" @click="player.playPart">▶ Play selection <kbd>Space</kbd></button>
            <span class="muted mono">{{ fmtTime(player.playhead.value) }}</span>
            <span class="spacer"></span>
            <button class="btn small" @click="setIn">Start here <kbd>I</kbd></button>
            <button class="btn small" @click="setOut">End here <kbd>O</kbd></button>
          </div>
          <div class="controls highlights">
            <button class="btn small" @click="addPin" title="Pin the moment at the playhead and centre the selection on it">★ Highlight <kbd>H</kbd></button>
            <button
              v-for="(t, i) in pins" :key="i" class="btn small" :class="{ active: i === pinOn }"
              :title="`Centre the selection on ${fmtTime(t)}`" @click="centreOn(i)"
            >★ {{ fmtTime(t) }}</button>
            <span v-if="pinOn >= 0 && offCentre" class="muted small">off-centre: the clip {{ range.start < 0.01 ? 'starts' : 'ends' }} too close</span>
            <span v-else-if="!pins.length" class="muted small">Pin the moments that matter in a long clip; the selection sits with each one in its middle.</span>
          </div>
        </template>

        <TimingFields
          :kind="current.kind" :start="range.start" :length="range.length"
          :duration="current.duration" @update="setTiming"
        >
          <p v-if="!active && kept.has(current.id)" class="muted kept">
            Kept for this file: reels and Weave start from this pick.
            <button class="link" @click="resetPick">Reset</button>
          </p>
        </TimingFields>

        <div class="panel" v-if="current.kind === 'video'">
          <h3>Layout</h3>
          <div class="chips">
            <button
              v-for="l in LAYOUTS" :key="l.v" class="btn small" :class="{ active: (range.layout || 'fill') === l.v }"
              @click="setLayout(l.v)" :title="l.hint"
            >{{ l.label }}</button>
          </div>
          <p class="muted hint">{{ LAYOUTS.find((l) => l.v === (range.layout || 'fill')).hint }}</p>
        </div>

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
          <kbd>←</kbd>/<kbd>→</kbd> nudge 0.1s · <kbd>↑</kbd>/<kbd>↓</kbd> previous/next · <kbd>H</kbd> highlight ·
          <kbd>1</kbd>–<kbd>9</kbd> add to reel · <kbd>G</kbd> Instagram overlays
        </p>
        </div>
      </section>
    </div>
    <p v-else class="muted">No clips or photos in this folder.</p>
    <MoveDialog
      v-if="moving" :from="name" :files="media.filter((m) => picked.has(m.id))"
      :all="picked.size === media.length" @close="moving = false" @moved="moved"
    />
    <DeleteDialog
      v-if="deleting" :from="name" :files="media.filter((m) => picked.has(m.id))"
      :parts="items.filter((p) => picked.has(p.mediaId)).length"
      :all="picked.size === media.length" @close="deleting = false" @deleted="deleted"
    />
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, debouncedSaver } from '../api'
import { usePlayer } from '../player'
import { useRefreshOnFocus } from '../refresh'
import { clockTime, defaultStart, fitRange, fmtTime, folderTitle, reelColor, savedAt } from '../time'
import ClipCard from '../components/ClipCard.vue'
import MoveDialog from '../components/MoveDialog.vue'
import DeleteDialog from '../components/DeleteDialog.vue'
import ReelFrame from '../components/ReelFrame.vue'
import TimingFields from '../components/TimingFields.vue'
import TrimBar from '../components/TrimBar.vue'
import WeavePrompt from '../components/WeavePrompt.vue'
import NewReelDialog from '../components/NewReelDialog.vue'

const props = defineProps({ name: { type: String, required: true } })
const emit = defineEmits(['root'])
const router = useRouter()

const media = ref([])
const items = ref([])
const reels = ref([])
const hasSidecar = ref(false)
const draftAt = ref(null)      // a Weave draft for this shoot, saved then
const selected = ref(0)
const activeId = ref(null)     // a saved part being edited, or null for a new selection
const drafts = reactive({})    // mediaId -> { start, length, ... } picked here, kept on the server
const kept = reactive(new Set())  // mediaIds whose pick is saved
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
const allReels = ref([])   // archived too, for names of parts already in them
const reelName = (id) => (reels.value.find((r) => r.id === id) || allReels.value.find((r) => r.id === id))?.name ?? 'reel'
const segments = computed(() =>
  partsOf(current.value.id)
    .filter((p) => p.id !== activeId.value)
    .map((p) => ({ id: p.id, start: p.start, length: p.length, color: reelColor(p.reelId),
                   label: `${reelName(p.reelId)} · ${fmtTime(p.start)} (${p.length.toFixed(1)}s)` })))

const DEFAULT_LENGTH = 2   // seconds, for a new selection on a video

// A clip's selection: the one picked here before, else a fresh one where
// the engine would cut by default.
function initDraft(m) {
  if (m.pick) {
    drafts[m.id] = { ...m.pick }
    kept.add(m.id)
    return
  }
  kept.delete(m.id)
  const length = m.kind === 'video' ? Math.min(DEFAULT_LENGTH, m.duration || DEFAULT_LENGTH) : 1.6
  drafts[m.id] = { start: m.kind === 'video' ? defaultStart(m.duration, length) : 0, length, focusX: 0.5, focusY: 0.5, zoom: 1, layout: '' }
}
const draftOf = (m) => (m && drafts[m.id]) || { start: 0, length: DEFAULT_LENGTH, focusX: 0.5, focusY: 0.5, zoom: 1, layout: '' }
const guides = ref(false)

const saver = debouncedSaver((id, patch) => api.updateItem(id, patch))
// A pick is saved whole, so it's there next time and when the file goes into a reel.
const pickSaver = debouncedSaver((id) => api.savePick(id, drafts[id]).catch((e) => showFlash(e.message)))

const refreshing = ref(false)
const newCount = ref(0)

function apply(data) {
  data.media.forEach((m) => { if (!drafts[m.id]) initDraft(m) })
  media.value = data.media
  items.value = data.items
  // Archived reels aren't offered; stable order, so 1–9 keys don't move.
  allReels.value = data.reels
  reels.value = data.reels.filter((r) => !r.archivedAt).sort((a, b) => a.id - b.id)
  hasSidecar.value = data.hasSidecar
  draftAt.value = data.draftAt || null
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
    await Promise.all([saver.flushAll(), pickSaver.flushAll()])
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
onBeforeUnmount(() => { saver.flushAll(); pickSaver.flushAll() })

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
  patchRange(r)
}

// Where the 9:16 window sits in a frame that isn't 9:16.
function setFocus({ x, y, zoom }) {
  const patch = { focusX: x, focusY: y }
  if (zoom !== undefined) patch.zoom = zoom
  patchRange(patch)
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

// ---------------------------------------------------------------- highlights
// Moments pinned on a clip (saved on it, so Weave starts from them too). The
// selection can sit centred on one: half its length before, half after. While
// it is, changing the length keeps it centred.

const pins = computed(() => (current.value?.kind === 'video' ? current.value.highlights || [] : []))
const centreOf = (r) => r.start + r.length / 2
// The highlight the selection is centred on, or the one it would be if the
// clip's edge weren't in the way (it's inside the selection, nearest the middle).
const pinOn = computed(() => {
  const r = range.value
  let best = -1
  pins.value.forEach((t, i) => {
    if (t < r.start - 0.01 || t > r.start + r.length + 0.01) return
    const want = fitRange(t - r.length / 2, r.length, current.value.duration).start
    if (Math.abs(want - r.start) < 0.06 && (best < 0 || Math.abs(t - centreOf(r)) < Math.abs(pins.value[best] - centreOf(r)))) best = i
  })
  return best
})
const offCentre = computed(() => pinOn.value >= 0 && Math.abs(pins.value[pinOn.value] - centreOf(range.value)) > 0.05)

const pinSaver = debouncedSaver((id, { pins: ts }) => api.saveHighlights(id, ts).catch((e) => showFlash(e.message)), 300)
onBeforeUnmount(() => pinSaver.flushAll())
function savePins() {
  const m = current.value
  m.highlights = [...(m.highlights || [])].sort((a, b) => a - b)
  pinSaver.queue(m.id, { pins: [...m.highlights] })
}
function centreOn(i) {
  const t = pins.value[i]
  if (t === undefined) return
  setRange({ start: t - range.value.length / 2, length: range.value.length })
  player.seek(range.value.start)
}
function addPin() {
  const m = current.value
  if (m?.kind !== 'video') return
  const t = Math.round(player.playhead.value * 100) / 100
  const near = pins.value.findIndex((x) => Math.abs(x - t) < 0.25)
  if (near >= 0) return centreOn(near)
  m.highlights = [...pins.value, t]
  savePins()
  centreOn(m.highlights.indexOf(t))
  showFlash(`Highlight at ${fmtTime(t)}`)
}
// Dragging a ★ the selection is centred on brings the selection with it.
function movePin(i, t) {
  const m = current.value
  const was = pinOn.value === i
  m.highlights[i] = Math.min(Math.max(t, 0), m.duration)
  if (was) setRange({ start: m.highlights[i] - range.value.length / 2, length: range.value.length })
}
function removePin(i) {
  current.value.highlights.splice(i, 1)
  savePins()
}
// Start/length typed or a quick length: centred on a highlight, it stays centred.
function setTiming({ start, length }) {
  const i = pinOn.value
  if (i >= 0 && Math.abs(start - range.value.start) < 0.01 && Math.abs(length - range.value.length) >= 0.01) {
    start = pins.value[i] - length / 2
  }
  setRange({ start, length })
}

// ---------------------------------------------------------------- layout

// For landscape footage (a timelapse): crop it, or show it whole over a blurred copy.
const LAYOUTS = [
  { v: 'fill', label: 'Fill', hint: 'Crops to fit. Drag the window to reframe, corners to zoom.' },
  { v: 'blur', label: 'Blur', hint: 'The whole frame, with a blurred copy filling the top and bottom.' },
]
function setLayout(v) {
  patchRange({ layout: v === 'fill' ? '' : v })
}
// A change to a saved part saves to it; else it's the file's pick, kept for next time.
function patchRange(patch) {
  if (active.value) {
    Object.assign(active.value, patch)
    saver.queue(active.value.id, patch)
  } else {
    const m = current.value
    if (!drafts[m.id]) initDraft(m)
    Object.assign(drafts[m.id], patch)
    kept.add(m.id)
    pickSaver.queue(m.id, {})
  }
}

// Back to the default selection, forgetting the pick.
async function resetPick() {
  const m = current.value
  await pickSaver.flushAll()
  try {
    await api.deletePick(m.id)
    initDraft({ ...m, pick: null })
    m.pick = null
    player.seek(range.value.start)
  } catch (e) {
    showFlash(e.message)
  }
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
      mediaId: m.id, start: r.start, length: r.length, focusX: r.focusX, focusY: r.focusY, zoom: r.zoom || 1,
      ...(m.kind === 'video' ? { layout: r.layout || '' } : {}),
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

// ---------------------------------------------------------------- weave

// Files that just came in from Downloads (Home passes them along), and the
// offer to weave them: worth it for two or more videos, or one of 15s or more
// (its first and second 15 seconds are already different moments).
const imported = ref(window.history.state?.imported || null)
const offer = computed(() => {
  if (!imported.value?.length) return null
  const mine = media.value.filter((m) => imported.value.includes(m.file))
  const vids = mine.filter((m) => m.kind === 'video')
  const long = vids.filter((m) => m.duration >= 15).length
  if (vids.length < 2 && !long) return null
  return { videos: vids.length, long, photos: mine.length - vids.length }
})
function dismissOffer() {
  imported.value = null
  window.history.replaceState({ ...window.history.state, imported: null }, '')
}
function weave() {
  // history state has to be plain data, not Vue's reactive copy
  router.push({ path: `/weave/${encodeURIComponent(props.name)}`,
                state: { imported: imported.value ? [...imported.value] : null } })
}

// Making a reel from this folder: NewReelDialog asks its name and style.
const makingReel = ref(false)

// ---------------------------------------------------------------- moving

// Pick files in the list, then move them to another shoot folder (say, after
// importing a day into the wrong one), or delete accidental ones (to the Trash).
const picking = ref(false)
const picked = ref(new Set())   // media ids
const moving = ref(false)
const deleting = ref(false)
const deletedCount = ref(0)     // after a delete
const movedTo = ref(null)       // { folder, count } after a move

function startPicking(files) {
  // Straight after an import, those files; else the clip you're on.
  const ids = files ? media.value.filter((m) => files.includes(m.file)).map((m) => m.id) : [current.value?.id]
  picked.value = new Set(ids.filter(Boolean))
  picking.value = true
  movedTo.value = null
  deletedCount.value = 0
}
function stopPicking() {
  picking.value = false
  picked.value = new Set()
}
function togglePick(id) {
  const s = new Set(picked.value)
  s.has(id) ? s.delete(id) : s.add(id)
  picked.value = s
}
const pickAll = (on) => { picked.value = new Set(on ? media.value.map((m) => m.id) : []) }

async function moved(r) {
  moving.value = false
  stopPicking()
  if (imported.value) dismissOffer()
  if (r.emptied) {
    // Nothing left here: go to where everything went.
    router.replace(`/shoot/${encodeURIComponent(r.folder)}`)
    return
  }
  movedTo.value = { folder: r.folder, count: r.moved.length }
  await reload()
}

async function deleted(r) {
  deleting.value = false
  stopPicking()
  if (imported.value) dismissOffer()
  if (r.emptied) {
    router.replace('/')   // nothing left in this folder
    return
  }
  movedTo.value = null
  deletedCount.value = r.deleted.length
  await reload()
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
  else if ((k === 'h' || k === 'H') && video) addPin()
  else if (k === 'ArrowDown') select(selected.value + 1)
  else if (k === 'ArrowUp') select(selected.value - 1)
  else if (k === 'ArrowLeft' && video) { setRange({ ...range.value, start: range.value.start - (e.shiftKey ? 1 : 0.1) }); player.seek(range.value.start) }
  else if (k === 'ArrowRight' && video) { setRange({ ...range.value, start: range.value.start + (e.shiftKey ? 1 : 0.1) }); player.seek(range.value.start) }
  else if (k === 'Escape') picking.value ? stopPicking() : (activeId.value = null)
  else if (k === 'g' || k === 'G') guides.value = !guides.value
  else if (/^[1-9]$/.test(k) && !active.value && reels.value[Number(k) - 1]) tag(reels.value[Number(k) - 1])
  else return
  e.preventDefault()
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<style scoped>
.pickbar .btn.danger { color: var(--danger); border-color: var(--danger); }
.chips { display: flex; gap: 8px; flex-wrap: wrap; }
.hint { font-size: 12px; margin: 8px 0 0; }
.count {
  font-size: 11px; font-weight: 700; padding: 1px 7px; border-radius: 999px;
  background: var(--forest); color: var(--cream);
}
.key { opacity: 0.55; }
.justin { margin: 6px 0 0; font-size: 14px; }
.justin a { font-weight: 600; text-decoration: underline; }
.pickbar {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap; padding: 8px; margin-bottom: 4px;
  border-radius: 8px; background: var(--sage-soft); font-size: 13px; position: sticky; top: 0; z-index: 1;
}
.pickbox { accent-color: var(--forest); width: 18px; height: 18px; margin: 0; pointer-events: none; }
.link {
  border: 0; background: none; padding: 0; color: var(--forest); font-weight: 600;
  cursor: pointer; font-size: inherit; text-decoration: underline; text-underline-offset: 2px;
}
.kept { margin: 0; font-size: 12px; flex-basis: 100%; }
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
