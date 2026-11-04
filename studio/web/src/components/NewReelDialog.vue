<template>
  <div class="modal" @click.self="$emit('close')">
    <div class="dialog newreel">
      <h2>New reel</h2>
      <label class="field">
        Name
        <input ref="nameEl" v-model="name" @keydown.enter="make" />
      </label>
      <label class="field" v-if="!folder">
        From
        <select v-model="from">
          <option value="">Nothing yet (an empty reel)</option>
          <option v-for="f in folders" :key="f.name" :value="f.name">{{ folderTitle(f.name) }}</option>
        </select>
      </label>

      <span class="muted">What style?</span>
      <div class="styles">
        <button
          v-for="st in STYLES" :key="st.v" class="style" :class="{ active: style === st.v }" :disabled="st.footage && !source"
          @click="style = st.v" :title="st.footage && !source ? 'Start this from a shoot' : ''"
        >
          <span class="strip">
            <span v-for="(f, i) in st.frames" :key="i" class="mini" :class="f"><i></i><i></i></span>
          </span>
          <b>{{ st.label }}</b>
          <small>{{ st.hint }}</small>
        </button>
      </div>

      <div v-if="style === 'relay'" class="opts">
        <div class="tbtns">
          <span class="muted">Long clips ({{ LONG }}s or more) play</span>
          <button
            v-for="c in CAPS" :key="c.v" class="btn small" :class="{ active: cap === c.v }" @click="cap = c.v"
            :title="c.v ? `Each long clip plays up to ${c.v}s` : 'Each long clip plays all of itself (or the long stretch you picked in the shoot)'"
          >{{ c.label }}</button>
        </div>
        <label class="check">
          <input type="checkbox" v-model="quiet" /> Skip quiet moments in long clips
          <small class="muted">(real speed; where nothing much happens is cut out)</small>
        </label>
        <div class="tbtns">
          <span class="muted">Photos and short clips: alone for</span>
          <button v-for="x in [2, 3, 4, 6]" :key="x" class="btn small" :class="{ active: solo === x }" @click="solo = x">{{ x }}s</button>
        </div>
        <div class="tbtns">
          <span class="muted">Each one carries on above the next for</span>
          <button v-for="x in [1, 2, 3, 5]" :key="x" class="btn small" :class="{ active: overlap === x }" @click="overlap = x">{{ x }}s</button>
        </div>
        <p v-if="estimate" class="estimate">
          <b>{{ estimate.long }}</b> long clip{{ estimate.long === 1 ? '' : 's' }} at their own length,
          <b>{{ estimate.short }}</b> photo{{ estimate.short === 1 ? '' : 's' }} and short clip{{ estimate.short === 1 ? '' : 's' }}:
          about <b>{{ fmtTime(estimate.total) }}</b>{{ quiet ? ' (less, with quiet moments skipped)' : '' }}.
        </p>
        <small class="muted">In the order they were shot. A long clip plays from its start, or from the long stretch you picked on the shoot page; you can trim any of it in the reel afterwards.</small>
      </div>
      <p v-if="error" class="warn small">{{ error }}</p>
      <div class="controls">
        <button class="btn" @click="$emit('close')">Cancel</button>
        <button class="btn primary" :disabled="busy || !name.trim()" @click="make">{{ style === 'weave' ? 'Weave it…' : busy ? 'Making…' : 'Make the reel' }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
// Making a reel: its name, where its footage comes from, and its style.
//   standard  one part after another, full frame
//   weave     the Weave wizard: clips cut into parts and interleaved
//   stack     the longest clip on top (lane A) the whole way, the rest under it
//   relay     each clip alone, then it carries on in the top slot while the
//             next comes in underneath and takes over: single, split, single…
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { fmtTime, folderTitle } from '../time'

const props = defineProps({
  folder: { type: String, default: '' },     // making it from this shoot
  folders: { type: Array, default: () => [] }, // or picking one (Home)
  defaultName: { type: String, default: '' },
})
defineEmits(['close'])
const router = useRouter()

const STYLES = [
  { v: 'standard', label: 'Standard', hint: 'One part after another, full frame.', frames: ['b', 'b', 'b'] },
  { v: 'weave', label: 'Weave', hint: 'Clips cut into parts and interleaved: a bit of each, then back for more.', frames: ['b', 'a1', 'b'], footage: true },
  { v: 'stack', label: 'Stack', hint: 'The longest clip on top the whole way, the others underneath, at real speed.', frames: ['ab', 'ab', 'ab'], footage: true },
  { v: 'relay', label: 'Relay', hint: 'Long-form: each clip plays alone at its own length, then moves up and carries on while the next comes in under it and takes over.', frames: ['b', 'ab', 'b', 'ab'], footage: true },
]
const name = ref(props.defaultName)
const from = ref('')
const source = computed(() => props.folder || from.value)
const style = ref('standard')
const solo = ref(3)
const overlap = ref(3)
const busy = ref(false)
const error = ref('')
const LONG = 10   // as scenes.py LONG_CLIP
const CAPS = [{ v: 0, label: 'Their full length' }, { v: 20, label: 'Up to 20s' }, { v: 30, label: 'Up to 30s' }, { v: 60, label: 'Up to 60s' }]
const cap = ref(0)
const quiet = ref(false)
// The shoot's files, for the length estimate.
const files = ref([])
watch(source, async (f) => {
  files.value = []
  if (!f) return
  try { files.value = (await api.folder(f)).media } catch { /* no estimate */ }
}, { immediate: true })
const estimate = computed(() => {
  const list = files.value
  if (!list.length) return null
  let total = 0
  let long = 0
  list.forEach((m, i) => {
    const under = i ? overlap.value : 0
    const after = i + 1 < list.length ? overlap.value : 0
    if (m.kind === 'video' && m.duration >= LONG) {
      long++
      const own = m.pick && m.pick.length >= LONG ? m.pick.length : m.duration
      const room = cap.value ? Math.min(own, cap.value) : own
      total += under + Math.max(solo.value, room - under - after)
    } else total += under + solo.value
  })
  return { long, short: list.length - long, total }
})
const nameEl = ref(null)
onMounted(() => nextTick(() => nameEl.value?.focus()))

async function make() {
  if (!name.value.trim() || busy.value) return
  error.value = ''
  if (style.value === 'weave') {
    router.push({ path: `/weave/${encodeURIComponent(source.value)}`, query: { name: name.value.trim() } })
    return
  }
  busy.value = true
  try {
    const r = source.value
      ? await api.folderToReel(source.value, name.value.trim(), { style: style.value, solo: solo.value, overlap: overlap.value,
                                                                  cap: cap.value || null, quiet: quiet.value })
      : await api.createReel(name.value.trim())
    router.push(`/reel/${r.id}`)
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.newreel { display: flex; flex-direction: column; gap: 12px; }
.newreel h2 { margin: 0; }
.styles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.style {
  display: flex; flex-direction: column; align-items: flex-start; gap: 6px; padding: 12px; text-align: left;
  border: 1px solid var(--line); border-radius: var(--radius); background: transparent; color: inherit; font: inherit; cursor: pointer;
}
.style small { color: var(--muted); font-size: 12px; line-height: 1.35; }
.style.active { border-color: var(--sage); background: var(--sage-soft); }
.style:disabled { opacity: 0.45; cursor: not-allowed; }
.strip { display: flex; gap: 4px; }
.mini { display: flex; flex-direction: column; gap: 2px; width: 14px; height: 24px; }
.mini i { flex: 1; border-radius: 2px; }
.mini.b i:first-child { background: #e9b27a; } .mini.b i:last-child { display: none; }
.mini.a1 i:first-child { background: #b8cfa8; } .mini.a1 i:last-child { display: none; }
.mini.ab i:first-child { background: #b8cfa8; } .mini.ab i:last-child { background: #e9b27a; }
.opts { display: flex; flex-direction: column; gap: 8px; padding: 12px; border-radius: var(--radius); background: var(--cream); }
.tbtns { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.controls { display: flex; justify-content: flex-end; gap: 8px; }
.check { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.estimate { margin: 0; }
</style>
