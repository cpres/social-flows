<template>
  <div class="compose">
    <button class="btn small" :class="{ active: open }" @click="toggle">✨ Make a track for this reel</button>
    <div v-if="open" class="composebox">
      <p class="muted small">
        AI music (Lyria, through OpenRouter) as long as this reel, building up and breaking down across it.
        Pick songs to take the feel from; they aren't sent anywhere, only measured here.
      </p>
      <div class="field">
        Like these songs
        <div class="chips">
          <button
            v-for="t in songs" :key="t.name" class="btn small" :class="{ active: refs.includes(t.name) }"
            @click="flip(t.name)"
          >{{ refs.includes(t.name) ? '✓ ' : '' }}{{ t.title || t.name }}</button>
          <span v-if="!songs.length" class="muted small">No songs on the shelf yet.</span>
        </div>
      </div>
      <div class="row">
        <label class="field">
          Tempo (bpm)
          <input type="number" min="50" max="200" step="1" v-model.number="bpm" :placeholder="plan ? String(Math.round(plan.bpm)) : 'from the songs'" />
        </label>
        <label class="field">
          Key
          <input v-model="key" :placeholder="plan?.key || 'from the songs'" />
        </label>
        <label class="field grow">
          Style
          <input v-model="style" :placeholder="plan?.style || 'e.g. lo-fi hip hop, warm keys'" />
        </label>
        <label class="field">
          Model
          <select v-model="model">
            <option value="pro">Pro: the reel's length</option>
            <option value="clip">Clip: 30s, cheaper test</option>
          </select>
        </label>
      </div>
      <label class="field">
        Anything else
        <input v-model="notes" placeholder="e.g. hopeful, a bit of a summer feel, marimba on top" />
      </label>
      <div class="actions">
        <button class="btn" :disabled="planning || making" @click="makePlan">{{ planning ? 'Working it out…' : 'Show the plan' }}</button>
        <button class="btn primary" :disabled="making || planning" @click="make">{{ making ? 'Making it (a minute or so)…' : 'Make it' }}</button>
        <span v-if="error" class="warn small">{{ error }}</span>
      </div>

      <div v-if="plan" class="plan">
        <p class="small">
          The reel runs <b>{{ fmtTime(plan.seconds) }}</b> at {{ Math.round(plan.bpm) }} bpm
          {{ plan.synced ? '(cutting on the beat)' : '(your lengths, not on the beat)' }}<template v-if="plan.asked < plan.seconds">;
          the Clip model makes {{ fmtTime(plan.asked) }}</template>.
          <template v-for="r in plan.refs" :key="r.name"><br />{{ r.title }}: {{ Math.round(r.bpm) }} bpm, {{ r.key }}, {{ r.words.join(', ') }}</template>
        </p>
        <div class="arc">
          <div
            v-for="(s, i) in plan.sections" :key="i" class="sec" :class="s.name.split(' ').pop().toLowerCase()"
            :style="{ flexGrow: s.end - s.start }" :title="s.what"
          >{{ s.name }}<small>{{ fmtTime(s.start) }}</small></div>
        </div>
        <label class="field">
          Prompt (edit it if you like; it's what gets sent)
          <textarea v-model="prompt" rows="9"></textarea>
        </label>
      </div>
      <p v-if="made" class="small">
        ✓ Made <b>{{ made.file }}</b>, {{ fmtTime(made.generated) }} long as it came back, and set as this reel's song.
        <span v-if="made.note" class="warn">{{ made.note }}</span>
      </p>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { api } from '../api'
import { fmtTime } from '../time'

const props = defineProps({ reelId: { type: Number, required: true }, shelf: { type: Object, required: true },
                            beforeAsk: { type: Function, default: null } })
const emit = defineEmits(['made'])

const open = ref(false)
const refs = ref([])
const bpm = ref(null)
const key = ref('')
const style = ref('')
const notes = ref('')
const model = ref('pro')
const plan = ref(null)
const prompt = ref('')
const planning = ref(false)
const making = ref(false)
const error = ref('')
const made = ref(null)

// AI tracks aren't much of a reference for the next one.
const songs = computed(() => props.shelf.tracks.filter((t) => !(t.categories || []).includes('AI')))

function toggle() { open.value = !open.value }
function flip(name) {
  refs.value = refs.value.includes(name) ? refs.value.filter((n) => n !== name) : [...refs.value, name]
}
const body = () => ({ refs: refs.value, bpm: bpm.value || null, key: key.value, style: style.value,
                      notes: notes.value, model: model.value })

async function makePlan() {
  planning.value = true
  error.value = ''
  try {
    if (props.beforeAsk) await props.beforeAsk()
    plan.value = await api.composePlan(props.reelId, body())
    prompt.value = plan.value.prompt
  } catch (e) {
    error.value = e.message
  } finally {
    planning.value = false
  }
}

async function make() {
  making.value = true
  error.value = ''
  made.value = null
  try {
    if (props.beforeAsk) await props.beforeAsk()
    // An edited prompt is sent as it is; otherwise the plan is worked out afresh.
    const edited = plan.value && prompt.value !== plan.value.prompt ? prompt.value : ''
    made.value = await api.compose(props.reelId, { ...body(), prompt: edited })
    emit('made', made.value)
  } catch (e) {
    error.value = e.message
  } finally {
    making.value = false
  }
}
</script>

<style scoped>
.compose { margin-top: 10px; }
.composebox { margin-top: 8px; padding: 12px; border: 1px solid var(--line, #ddd); border-radius: 8px; display: flex; flex-direction: column; gap: 10px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.row { display: flex; flex-wrap: wrap; gap: 10px; }
.row .field input { width: 110px; }
.row .grow { flex: 1; min-width: 180px; }
.row .grow input { width: 100%; }
.actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
textarea { font: 12px/1.4 ui-monospace, monospace; width: 100%; box-sizing: border-box; padding: 6px; }
.arc { display: flex; gap: 2px; height: 34px; margin: 6px 0 10px; }
.sec { flex-basis: 0; min-width: 0; overflow: hidden; white-space: nowrap; font-size: 11px; padding: 3px 5px;
       border-radius: 4px; background: var(--sage-soft, #e4ecdf); display: flex; flex-direction: column; }
.sec small { opacity: 0.7; }
.sec.build { background: #f3e3b8; }
.sec.drop { background: var(--sage, #8aa37c); color: #fff; }
.sec.breakdown, .sec.outro { background: #dfe6ee; }
</style>
