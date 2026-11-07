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
        <div class="dial">
          <span class="mixbar" :title="plan ? `${plan.stats.splitPct}% split` : ''">
            <i v-for="(seg, j) in planBar" :key="j" :class="seg[1] ? 'ab' : 'b'" :style="{ flexGrow: seg[0] }"></i>
          </span>
          <label class="slider">
            <span class="muted">Split screen</span>
            <small class="muted">less</small>
            <input type="range" min="1" max="10" step="1" v-model.number="dial" />
            <small class="muted">more</small>
            <b class="dialv">{{ dial }}</b>
          </label>
          <small class="muted">{{ DIAL_HINT }}</small>
        </div>
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
          <span class="muted">Photos stay on screen for</span>
          <button v-for="x in [2, 3, 4, 6]" :key="x" class="btn small" :class="{ active: photo === x }" @click="photo = x">{{ x }}s</button>
          <small class="muted">(short clips play their own length)</small>
        </div>
        <p v-if="summary" class="estimate">
          {{ summary }}<i v-if="plan.stats.limitedBy === 'photos'" class="limited">Mostly photos, so splits stay short.</i>
          <small v-if="approx" class="muted"> (a little less once quiet moments are measured)</small>
        </p>
        <small class="muted">In the order they were shot. A photo shot while a long clip was recording comes in under it at that moment. A long clip plays from its start, or from the long stretch you picked on the shoot page; you can trim any of it in the reel afterwards.</small>
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
//   relay     clips hand the frame on (the next comes in underneath and takes
//             over), and photos come in under long clips as cameos; planned
//             by studio/relay.py, the dial says how much is split
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
  { v: 'relay', label: 'Relay', hint: 'Long-form: each clip plays at its own length and hands the frame on to the next; photos come in under long clips for a moment.', frames: ['b', 'ab', 'b', 'ab'], footage: true },
]
const name = ref(props.defaultName)
const from = ref('')
const source = computed(() => props.folder || from.value)
const style = ref('standard')
const busy = ref(false)
const error = ref('')
const LONG = 10   // as relay.py LONG_THRESHOLD
const CAPS = [{ v: 0, label: 'Their full length' }, { v: 20, label: 'Up to 20s' }, { v: 30, label: 'Up to 30s' }, { v: 60, label: 'Up to 60s' }]
const cap = ref(0)
const quiet = ref(false)
const photo = ref(4)
// How much is split, 1 (never) to 10 (whenever two things are there to share
// the frame). A preference: photos can't sit on running video for long.
const dial = ref(5)
const DIAL_HINT = 'Long clips hand the frame on to the next; photos come in under them for a moment, then the clip takes the frame back.'
// The plan at every dial setting (relay.py), fetched when the footage or the
// other settings change, so the bar follows the slider as it moves.
const plans = ref([])
const approx = ref(false)
let asked = 0
let timer = null
watch([source, style, photo, cap, quiet], () => {
  clearTimeout(timer)
  if (style.value !== 'relay' || !source.value) { plans.value = []; return }
  timer = setTimeout(async () => {
    const n = ++asked
    try {
      const r = await api.relayPlan(source.value, { photo: photo.value, cap: cap.value || null, quiet: quiet.value })
      if (n === asked) { plans.value = r.plans; approx.value = r.approx }
    } catch { if (n === asked) plans.value = [] }
  }, 150)
}, { immediate: true })
const plan = computed(() => plans.value.find((p) => p.dial === dial.value) || null)
const planBar = computed(() => plan.value?.bar?.length ? plan.value.bar : [[1, false]])
const count = (n, one, many) => `${n} ${n === 1 ? one : many}`
// 9 long clips, 5 photos (3 as cameos) · about 4:43.6 · 61% split
const summary = computed(() => {
  const s = plan.value?.stats
  if (!s) return ''
  const bits = []
  if (s.longCount) bits.push(count(s.longCount, 'long clip', 'long clips'))
  if (s.shortCount) bits.push(count(s.shortCount, 'short clip', 'short clips'))
  if (s.photoCount) bits.push(count(s.photoCount, 'photo', 'photos'))
  const list = bits.length > 1 ? `${bits.slice(0, -1).join(', ')} and ${bits[bits.length - 1]}` : bits.join('')
  const what = list + (s.cameoCount ? ` (${s.cameoCount} as cameo${s.cameoCount === 1 ? '' : 's'})` : '')
  return `${what} · about ${fmtTime(s.totalSeconds)} · ${s.splitPct}% split`
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
      ? await api.folderToReel(source.value, name.value.trim(), { style: style.value, dial: dial.value, photo: photo.value,
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
.limited { margin-left: 0.4em; }
.dial { display: flex; flex-direction: column; gap: 6px; }
.slider { display: flex; align-items: center; gap: 8px; }
.slider input { flex: 1; accent-color: var(--sage); }
.dialv { min-width: 1.5em; text-align: right; font-variant-numeric: tabular-nums; }
.mixbar { display: flex; gap: 2px; width: 100%; height: 18px; }
.mixbar i { display: flex; flex-direction: column; border-radius: 2px; min-width: 3px; }
.mixbar i.b { background: var(--lane-b, #e9b27a); }
.mixbar i.ab { background: linear-gradient(var(--lane-a, #b8cfa8) 0 48%, transparent 48% 52%, var(--lane-b, #e9b27a) 52%); }
</style>
