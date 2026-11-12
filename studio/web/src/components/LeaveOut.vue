<template>
  <div class="leaveout" role="dialog" aria-modal="true" aria-label="Leave things out of the flow">
    <header>
      <div class="title">
        <h2>Leave things out of the flow</h2>
        <p class="muted">
          Nothing in a Relay is on screen for less than {{ MIN }}s: any quicker is frantic.
          <template v-if="target">To fit about {{ fmtTime(target) }}, </template>
          <template v-else>To keep it that way, </template>
          click a section of a clip, or a photo, to take it out. Click it again to put it back.
          A long clip's sections sit under its bar; click the bar to take the whole clip out.
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
      <span>
        <b>{{ inCount.video }}</b> clip{{ inCount.video === 1 ? '' : 's' }}<template v-if="inCount.sections"> ({{ inCount.sections }} sections)</template>
        · <b>{{ inCount.photo }}</b> photo{{ inCount.photo === 1 ? '' : 's' }} in<template v-if="outCount"> · {{ outCount }} left out</template>
      </span>
      <span class="spacer"></span>
      <button class="btn small" v-if="short.length" @click="leaveShort">Leave out the {{ short.length }} under {{ MIN }}s</button>
      <button class="btn small" v-if="outCount" @click="putAllBack">Put everything back</button>
    </div>

    <div class="tiles">
      <div v-for="g in groups" :key="g.m.id" class="group" :class="{ many: g.sections.length > 1, off: g.off }">
        <!-- the bar over a long clip's sections: they're one clip -->
        <button
          v-if="g.sections.length > 1" class="bar" :title="`${g.m.file}: click to ${g.off ? 'put the clip back' : 'leave the whole clip out'}`"
          @click="toggleFile(g.m.id)"
        >
          <span class="name">{{ g.m.file }}</span>
          <span>{{ fmtTime(g.m.duration) }} · {{ g.sections.filter((s) => !s.out).length }} of {{ g.sections.length }} sections in</span>
        </button>
        <span v-else class="bar none"></span>
        <div class="row">
          <template v-if="g.sections.length > 1">
            <div
              v-for="s in g.sections" :key="s.start" class="tile" :class="{ on: !s.out && !g.off }" role="button" tabindex="0"
              :aria-pressed="!s.out && !g.off" :title="`${g.m.file} ${fmtTime(s.start)} to ${fmtTime(s.start + s.length)}: click to ${s.out || g.off ? 'put it back' : 'leave it out'}`"
              @click="toggleSection(g, s)" @keydown.enter.space.prevent="toggleSection(g, s)"
            >
              <img :src="api.thumb(g.m.folder, g.m.file, s.start + s.length / 2, 320)" loading="lazy" alt="" draggable="false" />
              <span class="x">{{ s.out || g.off ? '✕' : '✓' }}</span>
              <span class="tag">{{ clock(s.start) }}–{{ clock(s.start + s.length) }}</span>
              <span class="time">{{ s.length.toFixed(s.length % 1 ? 1 : 0) }}s</span>
            </div>
          </template>
          <div
            v-else class="tile" :class="{ on: !g.off, short: shortSet.has(g.m.id) }" role="button" tabindex="0"
            :aria-pressed="!g.off" :title="`${g.m.file}: click to ${g.off ? 'put it back' : 'leave it out'}`"
            @click="toggleFile(g.m.id)" @keydown.enter.space.prevent="toggleFile(g.m.id)"
          >
            <img :src="api.thumb(g.m.folder, g.m.file, thumbAt(g), 320)" loading="lazy" alt="" draggable="false" />
            <span class="x">{{ g.off ? '✕' : '✓' }}</span>
            <span class="tag" v-if="g.m.kind !== 'video'">photo</span>
            <span class="tag" v-else-if="g.sections.length === 1 && g.sections[0].length < g.m.duration - 0.5">{{ clock(g.sections[0].start) }}–{{ clock(g.sections[0].start + g.sections[0].length) }}</span>
            <span class="tag" v-else>▶ {{ fmtTime(g.m.duration) }}</span>
            <span class="warnb" v-if="shortSet.has(g.m.id) && !g.off">under {{ MIN }}s</span>
            <span class="time" v-if="g.m.kind === 'video' && g.sections.length === 1 && g.sections[0].length < g.m.duration - 0.5">{{ g.sections[0].length.toFixed(g.sections[0].length % 1 ? 1 : 0) }}s of {{ fmtTime(g.m.duration) }}</span>
            <span class="time" v-else>{{ clockTime(g.m.capturedAt) }}</span>
          </div>
        </div>
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
// shorter than that, or there's too much to fit the length picked. It shows
// what would play: each photo and short clip, and each long clip as the
// sections of it the plan plays (plan.pieces), under a bar that says they're
// one clip. Click a section, photo or clip to leave it out of the flow (the
// bar: the whole clip); the estimate follows (the New reel dialog plans it
// again). A whole file left out goes in the reel out of the cut, to put back.
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { api } from '../api'
import { clockTime, fmtTime } from '../time'

const props = defineProps({
  files: { type: Array, required: true },         // the folder's media, in shot order
  exclude: { type: Array, default: () => [] },    // media ids left out whole
  excludeAt: { type: Array, default: () => [] },  // sections left out: [{ file: media id, at: a moment in it }]
  plan: { type: Object, default: null },          // the plan at the dial set, with them left out
  target: { type: Number, default: 0 },            // seconds, or 0
  busy: Boolean,
})
const emit = defineEmits(['update:exclude', 'update:excludeAt', 'close', 'make'])
const MIN = 3   // relay.py MIN_SCENE

const out = computed(() => new Set(props.exclude))
const short = computed(() => props.plan?.stats.tooShort || [])
const shortSet = computed(() => new Set(short.value))
const over = computed(() => (props.target && props.plan ? overBy(props.plan.stats.totalSeconds, props.target) : 0))
const fits = computed(() => !!props.plan && over.value <= 0 && !short.value.length)

// Each file with the sections of it that play (a long clip's; [] for photos
// and short clips, and for a file left out whole, whose sections aren't planned).
const lastSections = new Map()   // a clip left out whole keeps showing the sections it had
const groups = computed(() => {
  const by = new Map()
  for (const p of props.plan?.pieces || []) {
    if (!by.has(p.file)) by.set(p.file, [])
    by.get(p.file).push(p)
  }
  return props.files.map((m) => {
    const off = out.value.has(m.id)
    let sections = by.get(m.id) || []
    if (!off && props.plan) lastSections.set(m.id, sections)
    if (off) sections = lastSections.get(m.id) || []
    return { m, off, sections }
  })
})
const inCount = computed(() => {
  const c = { video: 0, photo: 0, sections: 0 }
  for (const g of groups.value) {
    if (g.off) continue
    const live = g.sections.filter((s) => !s.out).length
    if (g.sections.length > 1 && !live) continue
    c[g.m.kind === 'video' ? 'video' : 'photo']++
    if (g.sections.length > 1) c.sections += live
  }
  return c
})
const outCount = computed(() => props.exclude.length
  + groups.value.reduce((n, g) => n + (g.off ? 0 : g.sections.filter((s) => s.out).length), 0))

const clock = (s) => { const t = Math.round(s); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}` }
const thumbAt = (g) => (g.m.kind !== 'video' ? 0 : g.sections.length === 1 ? g.sections[0].start + g.sections[0].length / 2 : (g.m.duration || 0) * 0.3)

function toggleFile(id) {
  const next = new Set(out.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  emit('update:exclude', [...next])
}
// A section: left out by a moment inside it (its middle), so it holds however
// long the sections come out; put back by taking those moments away again.
function toggleSection(g, s) {
  if (g.off) {   // the whole clip was out: back in, with just this section
    emit('update:exclude', props.exclude.filter((id) => id !== g.m.id))
    const others = g.sections.filter((x) => x !== s).map((x) => ({ file: g.m.id, at: x.start + x.length / 2 }))
    emit('update:excludeAt', [...props.excludeAt.filter((e) => e.file !== g.m.id), ...others])
    return
  }
  if (s.out) {
    const ats = new Set(s.ats || [])
    emit('update:excludeAt', props.excludeAt.filter((e) => !(e.file === g.m.id && ats.has(e.at))))
  } else {
    emit('update:excludeAt', [...props.excludeAt, { file: g.m.id, at: Math.round((s.start + s.length / 2) * 100) / 100 }])
  }
}
function leaveShort() {
  emit('update:exclude', [...new Set([...props.exclude, ...short.value])])
}
function putAllBack() {
  emit('update:exclude', [])
  emit('update:excludeAt', [])
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
.title p { margin: 0; max-width: 70ch; }
.status {
  display: flex; flex-direction: column; gap: 4px; padding: 12px 16px; border-radius: 12px; min-width: 260px;
  border: 1px solid #d8a24a; background: rgb(233 178 122 / 18%);
}
.status.ok { border-color: var(--sage); background: var(--sage-soft, rgb(184 207 168 / 25%)); }
.status b { font-size: 18px; font-variant-numeric: tabular-nums; }
.selbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.spacer { flex: 1; }
.tiles { display: flex; flex-wrap: wrap; gap: 14px 10px; flex: 1; align-content: flex-start; }
.group { display: flex; flex-direction: column; gap: 5px; max-width: 100%; }
.row { display: flex; flex-wrap: wrap; gap: 6px; }
/* the bar that says a clip's sections are one clip */
.bar {
  display: flex; justify-content: space-between; gap: 10px; align-items: center; height: 22px; padding: 0 8px;
  border: 0; border-radius: 6px; background: var(--sage); color: var(--on-sage, #fff); font: inherit; font-size: 11px;
  font-weight: 600; cursor: pointer; white-space: nowrap; overflow: hidden;
}
.bar .name { overflow: hidden; text-overflow: ellipsis; }
.bar.none { background: transparent; cursor: default; }
.group.off .bar:not(.none) { background: var(--line, #bbb); color: var(--muted); text-decoration: line-through; }
.tile {
  position: relative; width: 132px; aspect-ratio: 3 / 4; border-radius: 10px; overflow: hidden; cursor: pointer;
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
