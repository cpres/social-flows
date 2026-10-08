<template>
  <div class="modal" @click.self="close">
    <div class="dialog import">
      <div class="top">
        <div>
          <h2>Import from Downloads</h2>
          <p class="muted mono">{{ dir }}</p>
        </div>
        <button class="x" aria-label="Close" @click="close">×</button>
      </div>

      <p v-if="loading" class="muted">Looking in Downloads…</p>
      <p v-else-if="error" class="err">{{ error }}</p>
      <p v-else-if="!days.length" class="empty">
        No photos, videos or songs have arrived in Downloads in the last month.
        AirDrop some from your phone, then come back here.
      </p>

      <template v-else>
        <div class="days" role="tablist" aria-label="Day they arrived">
          <button
            v-for="d in days" :key="d.day" class="day" :class="{ on: d.day === day }"
            role="tab" :aria-selected="d.day === day" @click="pickDay(d.day)"
          >
            <span class="dname">{{ dayLabel(d.day) }}</span>
            <span class="dcount">
              {{ d.photos + d.videos }}<template v-if="d.songs"> · ♪ {{ d.songs }}</template>
              <span v-if="d.new < d.photos + d.videos" class="muted">· {{ d.photos + d.videos - d.new }} duplicate{{ d.photos + d.videos - d.new === 1 ? '' : 's' }}</span>
            </span>
          </button>
        </div>

        <section class="songs" v-if="daySongs.length">
          <div class="selbar">
            <b>Songs</b>
            <span class="muted">for the music folder · <span class="mono">{{ musicDir }}</span></span>
          </div>
          <label v-for="f in daySongs" :key="f.name" class="song" :class="{ done: f.inShelf }">
            <input type="checkbox" :checked="chosenSongs.has(f.name)" @change="toggleSong(f.name)" />
            <span class="sname">♪ {{ f.name }}</span>
            <span class="muted small" v-if="f.inShelf">already there as {{ f.inShelf }}</span>
            <span class="muted mono small">{{ clockTime(f.arrived) }}</span>
          </label>
          <div class="songgo">
            <span class="muted small" v-if="songNotice">{{ songNotice }}</span>
            <span class="spacer"></span>
            <button class="btn" :disabled="!chosenSongs.size || songBusy" @click="moveSongs">
              {{ songBusy ? 'Moving…' : `Move ${chosenSongs.size} song${chosenSongs.size === 1 ? '' : 's'} to the music folder` }}
            </button>
          </div>
        </section>
        <p class="ok" v-else-if="songNotice">{{ songNotice }}</p>

        <template v-if="dayFiles.length">
        <div class="selbar">
          <span><b>{{ chosen.size }}</b> of {{ dayFiles.length }} selected
            <span class="muted" v-if="chosenCounts">· {{ chosenCounts }}</span>
          </span>
          <span class="spacer"></span>
          <button class="link" @click="selectAll(true)">All</button>
          <button class="link" @click="selectAll(false)">None</button>
        </div>

        <p class="dupnote" v-if="chosenDups">
          {{ chosenDups }} of these {{ chosenDups === 1 ? 'is a duplicate' : 'are duplicates' }}
          of something already in Footage. {{ chosenDups === 1 ? "It won't" : "They won't" }} be
          copied again, just deleted from Downloads.
        </p>

        <div class="thumbs">
          <button
            v-for="f in dayFiles" :key="f.name" class="thumb"
            :class="{ on: chosen.has(f.name), done: isDup(f) }"
            :aria-pressed="chosen.has(f.name)" :title="f.name" @click="toggle(f.name)"
          >
            <img :src="api.importThumb(f.name)" loading="lazy" alt="" />
            <span class="check">{{ chosen.has(f.name) ? '✓' : '' }}</span>
            <span class="tag" v-if="f.kind === 'video'">▶</span>
            <span class="tag heic" v-else-if="f.convert" title="Converted to JPEG on import">HEIC</span>
            <span class="already" v-if="f.importedTo">already in {{ folderTitle(f.importedTo) }}</span>
            <span class="already" v-else-if="f.copyOf">copy of {{ f.copyOf }}</span>
            <span class="time">{{ clockTime(f.arrived) }}</span>
          </button>
        </div>

        <div class="dest">
          <div class="choice" :class="{ on: mode === 'new' }" @click="mode = 'new'">
            <label class="pick"><input type="radio" value="new" v-model="mode" />
              <span class="ctitle">New shoot folder</span></label>
            <div class="row" v-if="mode === 'new'">
              <label class="field date">
                Date
                <input type="date" v-model="newDate" />
              </label>
              <label class="field grow">
                What was it? <span class="opt">(optional)</span>
                <input
                  ref="labelInput" v-model="newLabel" placeholder="e.g. garden build"
                  @keydown.enter="go"
                />
              </label>
            </div>
            <p class="preview" v-if="mode === 'new'">
              <span class="folder-ico">▣</span>
              <b>{{ folderTitle(newName) || '—' }}</b>
              <span class="mono muted" v-if="newName">{{ root }}/{{ newName }}</span>
            </p>
            <p class="warn" v-if="mode === 'new' && clash">
              You already have this folder.
              <button class="link" @click.stop="useExisting(newName)">Add to it instead</button>
            </p>
          </div>

          <div class="choice" :class="{ on: mode === 'existing' }" v-if="folders.length" @click="mode = 'existing'">
            <label class="pick"><input type="radio" value="existing" v-model="mode" />
              <span class="ctitle">Add to an existing folder</span></label>
            <div class="existing" v-if="mode === 'existing'">
              <button
                v-for="f in folders" :key="f.name" class="exf" :class="{ on: target === f.name }"
                @click="target = f.name"
              >
                <img v-if="f.cover" :src="api.thumb(f.name, f.cover, f.coverTime, 160)" loading="lazy" alt="" />
                <span v-else class="noimg"></span>
                <span class="exmeta">
                  <b>{{ folderTitle(f.name) }}</b>
                  <span class="muted">{{ f.clipCount }} clip{{ f.clipCount === 1 ? '' : 's' }}<template
                    v-if="f.photoCount"> · {{ f.photoCount }} photo{{ f.photoCount === 1 ? '' : 's' }}</template></span>
                </span>
              </button>
            </div>
          </div>
        </div>
        </template>
      </template>

      <p v-if="failure" class="err">{{ failure }}</p>
      <p v-if="notice" class="ok">{{ notice }}</p>
      <div class="controls">
        <span class="spacer"></span>
        <button class="btn" @click="close">Cancel</button>
        <button class="btn primary" v-if="dayFiles.length" :disabled="!canImport" @click="go">
          {{ busy ? 'Importing…' : importLabel }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { clockTime, folderTitle } from '../time'

const props = defineProps({
  folders: { type: Array, default: () => [] },   // the shoots, newest first
  root: { type: String, default: '' },
})
const emit = defineEmits(['close', 'imported'])

const loading = ref(true)
const error = ref('')
const dir = ref('~/Downloads')
const today = ref('')
const days = ref([])
const files = ref([])
const day = ref('')
const chosen = ref(new Set())
const songs = ref([])
const musicDir = ref('')
const chosenSongs = ref(new Set())
const songBusy = ref(false)
const songNotice = ref('')

const mode = ref('new')
const newDate = ref('')
const newLabel = ref('')
const target = ref('')
const notice = ref('')
const busy = ref(false)
const failure = ref('')
const labelInput = ref(null)

const isDup = (f) => !!(f.importedTo || f.copyOf)
const dayFiles = computed(() => files.value.filter((f) => f.day === day.value))
const daySongs = computed(() => songs.value.filter((f) => f.day === day.value))
const chosenCounts = computed(() => {
  const picked = dayFiles.value.filter((f) => chosen.value.has(f.name))
  const v = picked.filter((f) => f.kind === 'video').length
  const p = picked.length - v
  return [v && `${v} video${v === 1 ? '' : 's'}`, p && `${p} photo${p === 1 ? '' : 's'}`]
    .filter(Boolean).join(', ')
})
const chosenDups = computed(() => dayFiles.value.filter((f) => chosen.value.has(f.name) && isDup(f)).length)
const chosenNew = computed(() => chosen.value.size - chosenDups.value)
const newName = computed(() => [newDate.value, newLabel.value.trim()].filter(Boolean).join(' '))
const clash = computed(() => props.folders.some((f) => f.name === newName.value))
const destName = computed(() => (mode.value === 'new' ? newName.value : target.value))
const canImport = computed(() =>
  !busy.value && chosen.value.size > 0 && !!destName.value && !(mode.value === 'new' && clash.value))
const importLabel = computed(() => {
  const n = chosenNew.value
  const d = chosenDups.value
  const clear = `clear ${d} duplicate${d === 1 ? '' : 's'}`
  if (!n) return clear[0].toUpperCase() + clear.slice(1)
  return `Import ${n} file${n === 1 ? '' : 's'}${d ? ` · ${clear}` : ''}`
})

// A local date as YYYY-MM-DD (toISOString would give the UTC day).
const isoDay = (t) =>
  `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`

function dayLabel(d) {
  if (d === today.value) return 'Today'
  const t = new Date(`${today.value}T12:00`)
  t.setDate(t.getDate() - 1)
  if (d === isoDay(t)) return 'Yesterday'
  return new Date(`${d}T12:00`).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
}

function pickDay(d) {
  day.value = d
  // Everything from that day: new files get imported, duplicates cleared out.
  chosen.value = new Set(dayFiles.value.map((f) => f.name))
  chosenSongs.value = new Set(daySongs.value.map((f) => f.name))
  newDate.value = d
  // A folder for that day already? Offer it, else a new one.
  const match = props.folders.find((f) => f.name.startsWith(d))
  target.value = match?.name || props.folders[0]?.name || ''
  mode.value = match ? 'existing' : 'new'
}

function toggle(name) {
  const s = new Set(chosen.value)
  s.has(name) ? s.delete(name) : s.add(name)
  chosen.value = s
}
function toggleSong(name) {
  const s = new Set(chosenSongs.value)
  s.has(name) ? s.delete(name) : s.add(name)
  chosenSongs.value = s
}

async function moveSongs() {
  songBusy.value = true
  failure.value = ''
  try {
    const r = await api.importMusic([...chosenSongs.value])
    const m = r.moved.length
    const d = r.removed.length
    songNotice.value = [
      m && `Moved ${m} song${m === 1 ? '' : 's'} to the music folder.`,
      d && `Deleted ${d} the music folder already had.`,
    ].filter(Boolean).join(' ')
    if (r.failed.length) failure.value = r.failed.map((f) => `${f.name}: ${f.error}`).join('\n')
    await load()
  } catch (e) {
    failure.value = e.message
  } finally {
    songBusy.value = false
  }
}

const selectAll = (on) => { chosen.value = new Set(on ? dayFiles.value.map((f) => f.name) : []) }

function useExisting(name) {
  target.value = name
  mode.value = 'existing'
}

watch(mode, async (m) => {
  if (m === 'new') {
    await nextTick()
    labelInput.value?.focus()
  }
})

async function go() {
  if (!canImport.value) return
  busy.value = true
  failure.value = ''
  try {
    const r = await api.importFiles({
      files: [...chosen.value], folder: destName.value,
      create: mode.value === 'new',
    })
    if (r.failed.length && !r.imported.length && !r.skipped.length) {
      failure.value = r.failed.map((f) => `${f.name}: ${f.error}`).join('\n')
      return
    }
    if (r.imported.length) {
      emit('imported', r)
      return
    }
    const n = r.removed.length
    notice.value = `Deleted ${n} duplicate${n === 1 ? '' : 's'} from Downloads.`
    await load()
  } catch (e) {
    failure.value = e.message
  } finally {
    busy.value = false
  }
}

function close() {
  if (!busy.value) emit('close')
}
const onKey = (e) => { if (e.key === 'Escape') close() }

async function load() {
  try {
    const r = await api.importList()
    dir.value = r.dir
    today.value = r.today || isoDay(new Date())
    days.value = r.days
    files.value = r.files
    songs.value = r.songs || []
    musicDir.value = r.musicDir || ''
    error.value = r.error || ''
    // Start on today if anything came in, else the latest day with something new.
    const start = r.days.find((d) => d.day === day.value) || r.days.find((d) => d.day === today.value) || r.days.find((d) => d.new) || r.days[0]
    if (start) pickDay(start.day)
  } catch (e) {
    error.value = `Couldn't read Downloads: ${e.message}`
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKey)
  load()
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<style scoped>
.import { width: min(880px, 100%); display: flex; flex-direction: column; gap: 14px; }
.top { display: flex; align-items: flex-start; gap: 12px; }
.top > div { flex: 1; min-width: 0; }
.top p { margin: 0; font-size: 12px; }
.x {
  border: 0; background: transparent; font-size: 26px; line-height: 1; cursor: pointer;
  color: var(--muted); padding: 0 4px;
}
.x:hover { color: var(--ink); }
.err { color: var(--danger); white-space: pre-line; margin: 0; }
.empty {
  margin: 0; padding: 28px 20px; text-align: center; border: 2px dashed var(--line);
  border-radius: var(--radius); color: var(--muted);
}

.days { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 2px; }
.day {
  display: flex; flex-direction: column; align-items: flex-start; gap: 1px; flex: none;
  border: 1px solid var(--line); background: var(--paper); border-radius: 10px;
  padding: 6px 12px; cursor: pointer; text-align: left;
}
.day:hover { border-color: var(--sage); }
.day.on { background: var(--forest); border-color: var(--forest); color: var(--cream); }
.day.on .muted { color: inherit; opacity: 0.75; }
.dname { font-weight: 600; font-size: 14px; }
.dcount { font-size: 12px; }

.selbar { display: flex; align-items: center; gap: 10px; font-size: 13px; }
.link {
  border: 0; background: none; padding: 0; color: var(--forest); font-weight: 600;
  cursor: pointer; font-size: 13px; text-decoration: underline; text-underline-offset: 2px;
}
.thumbs {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); gap: 8px;
  max-height: 34vh; overflow-y: auto; padding: 2px;
}
.thumb {
  position: relative; aspect-ratio: 1; border: 0; padding: 0; border-radius: 8px; overflow: hidden;
  background: var(--stage); cursor: pointer; outline: 3px solid transparent; outline-offset: -3px;
  transition: outline-color 0.1s, opacity 0.1s;
}
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; opacity: 0.55; transition: opacity 0.1s; }
.thumb.on { outline-color: var(--sage); }
.thumb.on img { opacity: 1; }
.thumb.done:not(.on) img { opacity: 0.3; }
.check {
  position: absolute; top: 6px; right: 6px; width: 22px; height: 22px; border-radius: 50%;
  display: grid; place-items: center; font-size: 13px; font-weight: 700;
  border: 2px solid var(--on-media); background: rgb(0 0 0 / 25%); color: var(--on-sage);
}
.thumb.on .check { background: var(--sage); border-color: var(--sage); }
.tag, .time, .already {
  position: absolute; font-size: 11px; font-weight: 600; color: var(--on-media);
  background: rgb(20 28 20 / 70%); padding: 1px 6px; border-radius: 999px;
}
.tag { top: 6px; left: 6px; }
.time { bottom: 6px; right: 6px; }
.already {
  left: 6px; right: 6px; top: 50%; transform: translateY(-50%); border-radius: 6px; text-align: center;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

.dest { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; align-items: start; }
.choice {
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 12px 14px;
  border: 1px solid var(--line); border-radius: var(--radius); cursor: pointer; background: var(--paper);
}
.choice:hover { border-color: var(--sage); }
.choice.on { border-color: var(--sage); background: var(--sage-soft); cursor: default; }
.pick { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.choice input[type='radio'] { accent-color: var(--forest); margin: 0; }
.ctitle { font-weight: 600; color: var(--forest); }
.row { display: flex; gap: 10px; width: 100%; margin-top: 4px; }
.field.date { flex: none; width: 150px; }
.field.grow { flex: 1; min-width: 0; }
.opt { opacity: 0.7; }
.preview { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; width: 100%; margin: 2px 0 0; font-size: 14px; }
.preview .mono { font-size: 11px; word-break: break-all; }
.folder-ico { color: var(--sage); }
.warn { width: 100%; margin: 0; font-size: 13px; color: var(--warn); }
.existing {
  width: 100%; display: flex; flex-direction: column; gap: 4px; max-height: 200px; overflow-y: auto;
  margin-top: 4px;
}
.exf {
  display: flex; align-items: center; gap: 10px; text-align: left; padding: 4px;
  border: 1px solid transparent; border-radius: 8px; background: transparent; cursor: pointer;
}
.exf:hover { background: var(--paper); }
.exf.on { background: var(--paper); border-color: var(--forest); }
.exf img, .noimg { width: 40px; height: 40px; border-radius: 6px; object-fit: cover; flex: none; background: var(--forest); }
.exmeta { display: flex; flex-direction: column; font-size: 13px; min-width: 0; }
.exmeta b { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.exmeta .muted { font-size: 12px; }

.songs { display: flex; flex-direction: column; gap: 6px; }
.song {
  display: flex; align-items: center; gap: 10px; padding: 6px 10px; cursor: pointer;
  border: 1px solid var(--line); border-radius: 8px; background: var(--paper); font-size: 14px;
}
.song input { accent-color: var(--forest); margin: 0; }
.song.done .sname { opacity: 0.6; }
.sname { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.small { font-size: 12px; }
.songgo { display: flex; align-items: center; gap: 10px; }
.controls { margin-top: 0; }
.dupnote {
  margin: 0; padding: 8px 12px; font-size: 13px; border-radius: 8px;
  background: var(--sage-soft); color: var(--ink);
}
.ok { margin: 0; color: var(--forest); font-weight: 600; }
@media (max-width: 700px) {
  .dest { grid-template-columns: 1fr; }
}
</style>
