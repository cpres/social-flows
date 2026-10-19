<template>
  <div class="songpicker">
    <div class="chips cats" v-if="categories.length" aria-label="Show songs in">
      <button class="btn small" :class="{ active: !cat }" @click="cat = ''">All <span class="n">{{ shelf.tracks.length }}</span></button>
      <button
        v-for="c in categories" :key="c.name" class="btn small" :class="{ active: cat === c.name }"
        @click="cat = cat === c.name ? '' : c.name"
      >{{ c.name }} <span class="n">{{ c.count }}</span></button>
      <button v-if="unsorted" class="btn small" :class="{ active: cat === NONE }" @click="cat = cat === NONE ? '' : NONE">
        No category <span class="n">{{ unsorted }}</span>
      </button>
    </div>
    <div class="songrow">
      <select :id="id" :value="modelValue" @change="$emit('update:modelValue', $event.target.value)">
        <option value="">No music</option>
        <option v-if="modelValue && !track" :value="modelValue">{{ modelValue }}</option>
        <option v-if="track && !shown.includes(track)" :value="track.name">{{ songLabel(track) }}</option>
        <option v-for="t in shown" :key="t.name" :value="t.name">{{ songLabel(t) }}</option>
      </select>
      <slot />
      <button class="btn" :class="{ active: editing }" :disabled="!track" title="Give this song a name and categories" @click="toggleEdit">✎</button>
    </div>
    <p class="songmeta" v-if="track && !editing">
      <span v-for="c in track.categories" :key="c" class="cat">{{ c }}</span>
      <button v-if="!track.categories.length" class="link" @click="toggleEdit">Add categories</button>
      <span class="muted">{{ track.artist ? `by ${track.artist}` : '' }}{{ track.duration ? ` · ${fmtDuration(track.duration)}` : '' }}</span>
    </p>

    <div class="songedit" v-if="editing && track">
      <div class="two">
        <label class="field">
          Name
          <input v-model="draft.title" :placeholder="track.fileTitle" @keydown.enter="save" />
        </label>
        <label class="field">
          Artist
          <input v-model="draft.artist" :placeholder="track.fileArtist || 'Unknown'" @keydown.enter="save" />
        </label>
      </div>
      <div class="field">
        Categories
        <div class="chips">
          <button
            v-for="c in choices" :key="c" class="btn small" :class="{ active: has(c) }"
            @click="flip(c)"
          >{{ has(c) ? '✓ ' : '' }}{{ c }}</button>
          <input class="addcat" v-model="newCat" placeholder="New category…" @keydown.enter.prevent="addCat" />
        </div>
      </div>
      <p class="muted small">
        The file says: <template v-if="fileSays">{{ fileSays }}</template><template v-else>nothing (no tags)</template> ·
        <code>{{ track.name }}</code>
        <template v-if="track.pixabayId"> · <a :href="pixabayUrl" target="_blank" rel="noopener">find it on Pixabay</a> for its genre and mood</template>
      </p>
      <div class="actions">
        <span v-if="failure" class="warn small">{{ failure }}</span>
        <button class="btn" @click="editing = false">Cancel</button>
        <button class="btn primary" :disabled="saving" @click="save">{{ saving ? 'Saving…' : 'Save' }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { api } from '../api'
import { songLabel } from '../songs'
import { fmtDuration } from '../time'

const props = defineProps({
  modelValue: { type: String, default: '' },
  shelf: { type: Object, required: true },   // { tracks: [...] } from api.music()
  id: { type: String, default: undefined },
})
const emit = defineEmits(['update:modelValue', 'update:shelf'])

// A few to start from, offered until there are a few of your own.
const STARTERS = ['Chill', 'Upbeat', 'Happy', 'Emotional', 'Epic', 'Acoustic', 'Lo-fi', 'Cinematic']
const NONE = '\u0000none'

const byTitle = (a, b) => songLabel(a).localeCompare(songLabel(b), undefined, { sensitivity: 'base' })
const track = computed(() => props.shelf.tracks.find((t) => t.name === props.modelValue) || null)

// Categories in use, with how many songs are in each.
const categories = computed(() => {
  const n = new Map()
  for (const t of props.shelf.tracks) for (const c of t.categories || []) n.set(c, (n.get(c) || 0) + 1)
  return [...n].map(([name, count]) => ({ name, count })).sort((a, b) => a.name.localeCompare(b.name))
})
const unsorted = computed(() => (categories.value.length ? props.shelf.tracks.filter((t) => !t.categories?.length).length : 0))

const cat = ref('')
const shown = computed(() => props.shelf.tracks
  .filter((t) => !cat.value || (cat.value === NONE ? !t.categories?.length : t.categories?.includes(cat.value)))
  .sort(byTitle))
// A category that empties out (renamed away) stops filtering.
watch(categories, (cs) => { if (cat.value && cat.value !== NONE && !cs.some((c) => c.name === cat.value)) cat.value = '' })

// ---------------------------------------------------------------- editing

const editing = ref(false)
const draft = reactive({ title: '', artist: '', categories: [] })
const newCat = ref('')
const saving = ref(false)
const failure = ref('')

function toggleEdit() {
  if (editing.value) return (editing.value = false)
  const t = track.value
  Object.assign(draft, {
    title: t.title === t.fileTitle ? '' : t.title,
    artist: t.artist === t.fileArtist ? '' : t.artist,
    categories: [...t.categories],
  })
  newCat.value = ''
  failure.value = ''
  editing.value = true
}
watch(() => props.modelValue, () => { editing.value = false })

const choices = computed(() => {
  const used = categories.value.map((c) => c.name)
  const all = [...used, ...draft.categories.filter((c) => !used.includes(c))]
  const lower = all.map((c) => c.toLowerCase())
  return used.length >= 4 ? all : [...all, ...STARTERS.filter((c) => !lower.includes(c.toLowerCase()))]
})
const has = (c) => draft.categories.some((d) => d.toLowerCase() === c.toLowerCase())
function flip(c) {
  draft.categories = has(c) ? draft.categories.filter((d) => d.toLowerCase() !== c.toLowerCase()) : [...draft.categories, c]
}
function addCat() {
  const c = newCat.value.trim().replace(/\s+/g, ' ')
  if (c && !has(c)) draft.categories = [...draft.categories, c]
  newCat.value = ''
}

const fileSays = computed(() => {
  const tags = track.value?.fileTags || {}
  return Object.entries(tags).map(([k, v]) => `${k} “${v}”`).join(', ')
})
const pixabayUrl = computed(() => {
  const words = track.value.fileTitle.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
  return `https://pixabay.com/music/search/${encodeURIComponent(words)}/`
})

async function save() {
  if (saving.value) return
  addCat()
  saving.value = true
  failure.value = ''
  try {
    emit('update:shelf', await api.saveSong(track.value.name, { ...draft }))
    editing.value = false
  } catch (e) {
    failure.value = e.message
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.songpicker { display: flex; flex-direction: column; gap: 6px; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.cats .n { opacity: 0.6; font-size: 11px; }
.songrow { display: flex; gap: 8px; align-items: center; }
.songrow select { flex: 1; min-width: 0; }
.songrow :deep(.btn) { align-self: stretch; font-size: 14px; }
.songmeta { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin: 0; font-size: 12px; }
.cat { padding: 1px 8px; border-radius: 999px; background: var(--sage-soft); color: var(--forest); font-weight: 600; }
.songedit {
  display: flex; flex-direction: column; gap: 10px; padding: 12px; border-radius: 10px;
  border: 1px solid var(--line); background: var(--cream);
}
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.field .addcat { width: 160px; padding: 3px 8px; font-size: 13px; }
.actions { display: flex; gap: 8px; justify-content: flex-end; align-items: center; }
.small { font-size: 12px; margin: 0; }
.warn { color: var(--danger); }
code { word-break: break-all; }
.link {
  border: 0; background: none; padding: 0; color: var(--forest); font-weight: 600; cursor: pointer;
  text-decoration: underline; text-underline-offset: 2px; font-size: inherit;
}
</style>
