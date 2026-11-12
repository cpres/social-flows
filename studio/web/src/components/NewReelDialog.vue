<template>
  <div class="modal" @click.self="$emit('close')">
    <div class="dialog newreel">
      <h2>New reel</h2>
      <label class="field">
        Name
        <input ref="nameEl" v-model="name" @keydown.enter="make()" />
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
          <span class="muted">How long?</span>
          <button
            v-for="x in TARGETS" :key="x.v" class="btn small" :class="{ active: target === x.v }" @click="target = x.v"
            :title="x.v ? `Long clips' stretches are made as long as fits a reel of about ${x.label}` : 'Long clips play as long as you set below'"
          >{{ x.label }}</button>
        </div>
        <div class="tbtns" v-if="target">
          <span class="muted">Around each ★ highlight, play</span>
          <span v-if="plan">
            <template v-if="plan.stats.cap"><b>{{ plan.stats.cap }}s</b> (half before, half after), to fill {{ fmtTime(target) }}</template>
            <template v-else>all of the clip, to fill {{ fmtTime(target) }}</template>
          </span>
        </div>
        <div class="tbtns" v-else>
          <span class="muted">Around each ★ highlight, play</span>
          <button
            v-for="x in AROUNDS" :key="x" class="btn small" :class="{ active: around === x }" @click="around = x"
            :title="`${x / 2}s before each highlight and ${x / 2}s after`"
          >{{ x }}s</button>
          <small class="muted">(half before, half after; a long clip with highlights plays just those moments)</small>
        </div>
        <p v-if="plan && (plan.stats.highlightClips || plan.stats.suggestedClips)" class="muted small onpins">
          <template v-if="plan.stats.highlightClips">{{ count(plan.stats.highlightClips, 'long clip plays', 'long clips play') }} just the moments around your highlights</template><template
            v-if="plan.stats.highlightClips && plan.stats.suggestedClips">; </template><template
            v-if="plan.stats.suggestedClips">{{ count(plan.stats.suggestedClips, 'with', 'with') }} none marked {{ plan.stats.suggestedClips === 1 ? 'plays' : 'play' }} around its suggested ☆ moments</template>.
        </p>
        <!-- With a length, it decides how much of each long clip plays: nothing to set. -->
        <div class="tbtns" v-if="target && !allOnPins">
          <span class="muted">Other long clips ({{ LONG }}s or more) play</span>
          <span v-if="plan">
            <template v-if="plan.stats.cap">in stretches of <b>{{ plan.stats.cap }}s</b>, to fit</template>
            <template v-else>all of themselves (it's under {{ fmtTime(target) }} even so)</template>
          </span>
        </div>
        <div class="tbtns" v-if="!target">
          <span class="muted">Long clips ({{ LONG }}s or more) play</span>
          <button
            v-for="c in CAPS" :key="c.v" class="btn small" :class="{ active: cap === c.v }" @click="cap = c.v"
            :title="c.v ? `Each long clip plays as a few stretches of up to ${c.v}s, spread evenly through it` : 'Each long clip plays all of itself, less a moment at each end (or the long stretch you picked in the shoot)'"
          >{{ c.label }}</button>
        </div>
        <div class="tbtns" v-if="!target && cap">
          <span class="muted">At most</span>
          <button v-for="x in [2, 3, 4, 5, 6]" :key="x" class="btn small" :class="{ active: most === x }" @click="most = x">{{ x }}</button>
          <span class="muted">stretches per long clip</span>
          <small class="muted">(spread evenly through it; clips of 2 minutes or more get them all, shorter ones fewer)</small>
        </div>
        <label class="check" v-if="!target">
          <input type="checkbox" v-model="quiet" /> Skip quiet moments in long clips
          <small class="muted">(real speed; where nothing much happens is cut out)</small>
        </label>
        <div class="tbtns">
          <span class="muted">Photos stay on screen for</span>
          <button v-for="x in [3, 4, 6]" :key="x" class="btn small" :class="{ active: photo === x }" @click="photo = x">{{ x }}s</button>
          <small class="muted">(short clips play their own length)</small>
        </div>
        <div v-if="issue" class="issue">
          <span>
            <b>To keep everything on screen 3s or more, some videos or photos should come out.</b>
            <small>
              <template v-if="overSecs > 0">Even with the shortest stretches it's about {{ fmtTime(plan.stats.totalSeconds) }}, over {{ fmtTime(target) }}. </template>
              <template v-if="tooShort.length">{{ count(tooShort.length, 'clip is', 'clips are') }} under 3s however it's cut. </template>
            </small>
          </span>
          <button class="btn primary small" @click="leaving = true">Choose what to leave out…</button>
        </div>
        <div v-else class="tbtns">
          <button class="btn small" :disabled="!files.length" @click="leaving = true">Choose what's in…</button>
          <small class="muted">{{ exclude.length + excludeAt.length ? `${count(exclude.length + excludeAt.length, 'thing', 'things')} left out of the flow` : 'every clip and photo from the shoot is in' }}</small>
        </div>
        <p v-if="summary" class="estimate">
          {{ summary }}<i v-if="plan.stats.limitedBy === 'photos'" class="limited">Mostly photos, so splits stay short.</i>
          <small v-if="approx" class="muted"> (a little less once quiet moments are measured)</small>
        </p>
        <small class="muted">In the order they were shot. A photo shot while a long clip was recording comes in under it at that moment. A long clip with ★ highlights (marked on the shoot page, or ☆ suggested from where things move) plays just the moments around them; one without plays all of itself less a moment at each end, or the long stretch you picked. You can trim any of it in the reel afterwards.</small>
      </div>
      <LeaveOut
        v-if="leaving" :files="files" v-model:exclude="exclude" v-model:exclude-at="excludeAt" :plan="plan" :target="target" :busy="busy"
        @close="leaving = false" @make="make(true)"
      />
      <p v-if="error" class="warn small">{{ error }}</p>
      <div class="controls">
        <button class="btn" @click="$emit('close')">Cancel</button>
        <button class="btn primary" :disabled="busy || !name.trim()" @click="make()">{{ style === 'weave' ? 'Weave it…' : busy ? 'Making…' : 'Make the reel' }}</button>
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
import LeaveOut, { overBy } from './LeaveOut.vue'

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
// How long the reel should be, about: long clips' stretches are made to fit (0: as long as it takes).
const TARGETS = [{ v: 30, label: '0:30' }, { v: 45, label: '0:45' }, { v: 60, label: '1:00' }, { v: 90, label: '1:30' },
                 { v: 120, label: '2:00' }, { v: 180, label: '3:00' }, { v: 0, label: 'As long as it takes' }]
const target = ref(90)
const most = ref(4)   // stretches per long clip, at most (relay.py MOST_DEFAULT)
// Seconds of a long clip played around each of its highlights (relay.py AROUND_DEFAULT).
const AROUNDS = [4, 6, 10, 16, 20]
const around = ref(10)
const quiet = ref(false)
const photo = ref(4)
// Left out of the flow (folder media ids): see LeaveOut. The folder's files, for it.
const exclude = ref([])
const excludeAt = ref([])   // sections of long clips left out: [{ file, at }]
const leaving = ref(false)
const files = ref([])
watch(source, async (f) => {
  exclude.value = []
  excludeAt.value = []
  files.value = []
  if (!f) return
  try {
    const d = await api.folder(f)
    files.value = d.media.filter((m) => !m.missing).sort((a, b) => (a.capturedAt || 0) - (b.capturedAt || 0))
  } catch { /* the list just stays empty */ }
}, { immediate: true })
// How much is split, 1 (never) to 10 (whenever two things are there to share
// the frame). A preference: photos can't sit on running video for long.
const dial = ref(5)
const DIAL_HINT = 'A long clip hands the frame on to its own next stretch (a skip ahead) or the next clip (a new scene), which comes in underneath and takes over; photos come in under it for a moment, then it takes the frame back.'
// The plan at every dial setting (relay.py), fetched when the footage or the
// other settings change, so the bar follows the slider as it moves.
const plans = ref([])
const approx = ref(false)
let asked = 0
let timer = null
watch([source, style, photo, cap, most, quiet, target, around, exclude, excludeAt], () => {
  clearTimeout(timer)
  if (style.value !== 'relay' || !source.value) { plans.value = []; return }
  timer = setTimeout(async () => {
    const n = ++asked
    try {
      const r = await api.relayPlan(source.value, { photo: photo.value, cap: cap.value || null, most: most.value, quiet: !target.value && quiet.value,
                                                         target: target.value || null, around: around.value, exclude: exclude.value,
                                                         excludeAt: excludeAt.value })
      if (n === asked) { plans.value = r.plans; approx.value = r.approx }
    } catch { if (n === asked) plans.value = [] }
  }, 150)
}, { immediate: true })
const plan = computed(() => plans.value.find((p) => p.dial === dial.value) || null)
// Every long clip plays just the moments around its highlights (marked or suggested).
const allOnPins = computed(() => {
  const st = plan.value?.stats
  return !!st?.longCount && (st.highlightClips || 0) + (st.suggestedClips || 0) >= st.longCount
})
const planBar = computed(() => plan.value?.bar?.length ? plan.value.bar : [[1, false]])
const count = (n, one, many) => `${n} ${n === 1 ? one : many}`
// 9 long clips, 5 photos (3 as cameos) · about 4:43.6 · 61% split
const summary = computed(() => {
  const s = plan.value?.stats
  if (!s) return ''
  const bits = []
  if (s.longCount) {
    bits.push(count(s.longCount, 'long clip', 'long clips')
      + (s.longPieces > s.longCount ? ` (${s.longPieces} stretches)` : ''))
  }
  if (s.shortCount) bits.push(count(s.shortCount, 'short clip', 'short clips'))
  if (s.photoCount) bits.push(count(s.photoCount, 'photo', 'photos'))
  const list = bits.length > 1 ? `${bits.slice(0, -1).join(', ')} and ${bits[bits.length - 1]}` : bits.join('')
  const what = list + (s.cameoCount ? ` (${s.cameoCount} as cameo${s.cameoCount === 1 ? '' : 's'})` : '')
  const off = target.value && Math.abs(s.totalSeconds - target.value) > Math.max(5, target.value * 0.1)
  const short = s.splitPct ? 'all of the footage; splitting overlaps clips, so turn the split down for longer' : 'all of the footage there is'
  return `${what} · about ${fmtTime(s.totalSeconds)}${off ? (s.totalSeconds > target.value ? ' (the shortest it can be with this footage)' : ` (${short})`) : ''} · ${s.splitPct}% split`
})
// What keeps every moment from being 3s or more (relay.py MIN_SCENE): files
// under 3s themselves, or more than fits the length picked.
const tooShort = computed(() => plan.value?.stats.tooShort || [])
const overSecs = computed(() => (target.value && plan.value ? overBy(plan.value.stats.totalSeconds, target.value) : 0))
const issue = computed(() => style.value === 'relay' && !!plan.value && (tooShort.value.length > 0 || overSecs.value > 0))
const nameEl = ref(null)
onMounted(() => nextTick(() => nameEl.value?.focus()))
// A name some reel already has becomes its next take ("… take 3"), so making
// another reel from the same folder just works (the server does the same).
onMounted(async () => {
  const asked = name.value.trim()
  if (!asked) return
  try {
    const r = await api.freeReelName(asked)
    if (name.value.trim() === asked) name.value = r.name   // unless it's been typed over meanwhile
  } catch {}
})

// anyway: made from the leave-out screen as it stands. Otherwise, while
// something would be on screen under 3s, that screen comes up first.
async function make(anyway = false) {
  if (!name.value.trim() || busy.value) return
  error.value = ''
  if (!anyway && issue.value) { leaving.value = true; return }
  if (style.value === 'weave') {
    router.push({ path: `/weave/${encodeURIComponent(source.value)}`, query: { name: name.value.trim() } })
    return
  }
  busy.value = true
  try {
    const r = source.value
      ? await api.folderToReel(source.value, name.value.trim(), { style: style.value, dial: dial.value, photo: photo.value,
                                                                  cap: cap.value || null, most: most.value, quiet: !target.value && quiet.value,
                                                                  around: around.value, exclude: style.value === 'relay' ? exclude.value : [],
                                                                  excludeAt: style.value === 'relay' ? excludeAt.value : [],
                                                                  target: style.value === 'relay' ? target.value || null : null })
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
.onpins { margin: 0 0 6px; }
.issue { display: flex; align-items: center; gap: 12px; padding: 10px 12px; border-radius: 10px;
  border: 1px solid #d8a24a; background: rgb(233 178 122 / 18%); }
.issue > span { display: flex; flex-direction: column; gap: 2px; flex: 1; }
.issue small { color: var(--muted); }
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
