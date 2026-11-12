<template>
  <div class="leaveout" role="dialog" aria-modal="true" aria-label="Leave things out of the flow">
    <header>
      <div class="title">
        <h2>Leave things out of the flow</h2>
        <p class="muted">
          Nothing in a Relay is on screen for less than {{ MIN }}s: any quicker is frantic.
          <template v-if="target">To fit about {{ fmtTime(target) }}, </template>
          <template v-else>To keep it that way, </template>
          click a clip or photo to take it out. Click it again to put it back.
        </p>
      </div>
      <div class="status" :class="{ ok: fits }">
        <b v-if="!plan">Working it out…</b>
        <template v-else>
          <b>{{ fits ? '✓ ' : '' }}about {{ fmtTime(plan.stats.totalSeconds) }}<template v-if="target"> of {{ fmtTime(target) }}</template></b>
          <small v-if="over > 0">{{ fmtTime(plan.stats.totalSeconds - target) }} too long: take out a few more</small>
          <small v-if="short.length">{{ short.length }} {{ short.length === 1 ? 'clip is' : 'clips are' }} under {{ MIN }}s however it's cut (marked below)</small>
          <small v-if="fits">Every moment on screen {{ MIN }}s or more{{ target ? ', and near enough the length' : '' }}.</small>
        </template>
      </div>
    </header>

    <div class="selbar">
      <span><b>{{ inCount.video }}</b> clip{{ inCount.video === 1 ? '' : 's' }} · <b>{{ inCount.photo }}</b> photo{{ inCount.photo === 1 ? '' : 's' }} in<template v-if="out.size"> · {{ out.size }} left out</template></span>
      <span class="spacer"></span>
      <button class="btn small" v-if="short.length" @click="leaveShort">Leave out the {{ short.length }} under {{ MIN }}s</button>
      <button class="btn small" v-if="out.size" @click="emit('update:exclude', [])">Put everything back</button>
    </div>

    <div class="tiles">
      <div
        v-for="m in files" :key="m.id" class="tile" :class="{ on: !out.has(m.id), short: shortSet.has(m.id) }"
        role="button" tabindex="0" :aria-pressed="!out.has(m.id)" :title="`${m.file}: click to ${out.has(m.id) ? 'put it back' : 'leave it out'}`"
        @click="toggle(m.id)" @keydown.enter.space.prevent="toggle(m.id)"
      >
        <img :src="api.thumb(m.folder, m.file, m.kind === 'video' ? (m.duration || 0) * 0.3 : 0, 320)" loading="lazy" alt="" draggable="false" />
        <span class="x" :aria-label="out.has(m.id) ? 'left out' : 'in'">{{ out.has(m.id) ? '✕' : '✓' }}</span>
        <span class="tag" v-if="m.kind === 'video'">▶ {{ fmtTime(m.duration) }}</span>
        <span class="tag" v-else>photo</span>
        <span class="warnb" v-if="shortSet.has(m.id) && !out.has(m.id)">under {{ MIN }}s</span>
        <span class="time">{{ clockTime(m.capturedAt) }}</span>
      </div>
    </div>

    <footer>
      <button class="btn" @click="emit('close')">Back to the settings</button>
      <span class="spacer"></span>
      <button class="btn primary" :disabled="busy" @click="emit('make')">{{ busy ? 'Making…' : fits ? 'Make the reel' : 'Make it anyway' }}</button>
    </footer>
  </div>
</template>

<script setup>
// The full-screen check before a Relay reel is made, when it can't keep every
// moment on screen for MIN seconds (relay.py MIN_SCENE): some clips are
// shorter than that, or there's too much to fit the length picked. Click a
// clip or photo to leave it out of the flow; the estimate follows (the New
// reel dialog plans it again with them left out). Left out things go in the
// reel out of the cut, so they can be put back there.
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { api } from '../api'
import { clockTime, fmtTime } from '../time'

const props = defineProps({
  files: { type: Array, required: true },       // the folder's media, in shot order
  exclude: { type: Array, default: () => [] },  // media ids left out
  plan: { type: Object, default: null },        // the plan at the dial set, with them left out
  target: { type: Number, default: 0 },          // seconds, or 0
  busy: Boolean,
})
const emit = defineEmits(['update:exclude', 'close', 'make'])
const MIN = 3   // relay.py MIN_SCENE

const out = computed(() => new Set(props.exclude))
const short = computed(() => props.plan?.stats.tooShort || [])
const shortSet = computed(() => new Set(short.value))
const over = computed(() => (props.target && props.plan ? overBy(props.plan.stats.totalSeconds, props.target) : 0))
const fits = computed(() => !!props.plan && over.value <= 0 && !short.value.length)
const inCount = computed(() => {
  const c = { video: 0, photo: 0 }
  for (const m of props.files) if (!out.value.has(m.id)) c[m.kind === 'video' ? 'video' : 'photo']++
  return c
})

function toggle(id) {
  const next = new Set(out.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  emit('update:exclude', [...next])
}
function leaveShort() {
  emit('update:exclude', [...new Set([...props.exclude, ...short.value])])
}
const onKey = (e) => { if (e.key === 'Escape') emit('close') }
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<script>
// Seconds a reel runs over its target, past the leeway the dialog allows (0: it fits).
export function overBy(total, target) {
  return Math.max(0, total - target - Math.max(5, target * 0.1))
}
</script>

<style scoped>
.leaveout {
  position: fixed; inset: 0; z-index: 200; display: flex; flex-direction: column; gap: 14px;
  padding: 24px 28px; background: var(--paper); color: var(--ink); overflow: auto;
}
header { display: flex; gap: 24px; align-items: flex-start; flex-wrap: wrap; }
.title { flex: 1; min-width: 280px; }
.title h2 { margin: 0 0 6px; }
.title p { margin: 0; max-width: 62ch; }
.status {
  display: flex; flex-direction: column; gap: 4px; padding: 12px 16px; border-radius: 12px; min-width: 260px;
  border: 1px solid #d8a24a; background: rgb(233 178 122 / 18%);
}
.status.ok { border-color: var(--sage); background: var(--sage-soft, rgb(184 207 168 / 25%)); }
.status b { font-size: 18px; font-variant-numeric: tabular-nums; }
.selbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.spacer { flex: 1; }
.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(132px, 1fr)); gap: 10px; flex: 1; align-content: start; }
.tile {
  position: relative; aspect-ratio: 3 / 4; border-radius: 10px; overflow: hidden; cursor: pointer;
  background: var(--stage); outline: 3px solid transparent; outline-offset: -3px;
}
.tile img { width: 100%; height: 100%; object-fit: cover; display: block; opacity: 0.3; filter: grayscale(0.8); pointer-events: none; }
.tile.on { outline-color: var(--sage); }
.tile.on img { opacity: 1; filter: none; }
.tile.on.short { outline-color: #d8a24a; }
.tile:focus-visible { outline-color: var(--ink); }
.x {
  position: absolute; top: 6px; right: 6px; width: 24px; height: 24px; border-radius: 50%;
  display: grid; place-items: center; font-size: 13px; font-weight: 700;
  border: 2px solid var(--on-media, #fff); background: rgb(0 0 0 / 45%); color: #fff;
}
.tile.on .x { background: var(--sage); border-color: var(--sage); color: var(--on-sage, #fff); }
.tag, .time, .warnb {
  position: absolute; font-size: 11px; font-weight: 600; color: var(--on-media, #fff);
  background: rgb(20 28 20 / 70%); padding: 1px 6px; border-radius: 999px;
}
.tag { left: 6px; bottom: 6px; }
.time { right: 6px; bottom: 6px; }
.warnb { left: 6px; top: 6px; background: #b8741f; }
footer { display: flex; gap: 8px; align-items: center; position: sticky; bottom: -24px; padding: 12px 0; background: var(--paper); }
</style>
