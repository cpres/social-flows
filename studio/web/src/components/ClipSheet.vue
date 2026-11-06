<template>
  <div class="sheet" ref="sheet" @wheel.passive="manual" @touchmove.passive="manual" @keydown="manual">
    <div class="sheethead">
      <div><b>Clip sheet</b> <small class="muted">one row per scene · A and B side by side</small></div>
      <label class="follow" :class="{ on: follow }"><input type="checkbox" v-model="follow" /> Follow playhead</label>
    </div>
    <div class="cols">
      <div class="colhead a"><i></i><b>A lane</b> <small>{{ wide ? 'left' : 'top' }} slot · main</small></div>
      <div class="colhead b"><i></i><b>B lane</b> <small>{{ wide ? 'right' : 'bottom' }} slot · cut list</small></div>
    </div>

    <section
      v-for="row in rows" :key="row.sc.id" class="scene" :class="{ playing: row.k === playingScene }"
      :data-scene="row.k"
    >
      <button class="scenehead" @click="$emit('seek', row.start)" :title="`Move the playhead to ${fmtTime(row.start)}`">
        <span class="glyph" :class="`g-${row.sc.layout}`"><i></i><i></i></span>
        <b>Scene {{ row.k + 1 }} · {{ layoutLabel(row.sc.layout, wide) }}</b>
        <small class="mono">{{ fmtTime(row.start) }} → {{ fmtTime(row.end) }}</small>
        <span v-if="row.k === playingScene" class="chip playing">playing</span>
      </button>
      <div class="cells">
        <!-- lane A: its stretch in this scene, the shot a relay carries on, or off screen -->
        <div class="cell a">
          <button
            v-if="row.a" class="card a" :class="{ now: isNow(row.a), picked: pickedA === row.k }"
            @click="$emit('pick-a', row.k)" :title="row.a.carry ? `${row.a.part.media.file} carries on from the scene before` : row.a.part.media.file"
          >
            <img :src="api.thumb(row.a.part.media.folder, row.a.part.media.file, thumbAt(row.a), 160)" alt="" loading="lazy" />
            <span class="txt">
              <b>{{ row.a.carry ? '↪ ' : '' }}{{ short(row.a.part.media.file) }}</b>
              <small class="mono">{{ fmtTime(row.a.start) }} · {{ row.a.len.toFixed(1) }}s{{ row.a.rate && Math.abs(row.a.rate - 1) > 0.005 ? ` · ${row.a.rate.toFixed(2)}×` : '' }}</small>
              <span class="bar"><span :style="{ width: `${progress(row.a) * 100}%` }"></span></span>
            </span>
          </button>
          <div v-else class="off">{{ row.aOff }}</div>
        </div>
        <!-- lane B: its parts, in reel order -->
        <div class="cell b" @dragover.prevent @drop="$emit('drop-b-end', row)">
          <template v-if="row.b.length">
            <div v-for="c in row.b" :key="c.part.id" class="bwrap">
              <button
                class="card b" :class="{ now: isNow(c), picked: pickedB === c.part.id, over: dragOverId === c.part.id, photo: c.part.media.kind === 'photo' }"
                draggable="true" @dragstart="$emit('drag-b', c.part)" @dragend="dragOverId = null"
                @dragover.prevent="dragOverId = c.part.id" @dragleave="dragOverId = null" @drop.stop="dragOverId = null; $emit('drop-on', c.part)"
                @click="$emit('pick-b', c.part)"
              >
                <img :src="api.thumb(c.part.media.folder, c.part.media.file, c.part.start, 160)" alt="" loading="lazy" />
                <span class="txt">
                  <b>{{ short(c.part.media.file) }}</b>
                  <small class="mono">{{ fmtTime(c.start) }} · {{ c.len.toFixed(1) }}s{{ c.part.media.kind === 'photo' ? ' · photo' : '' }}{{ c.part.lighten ? ' · ☀' : '' }}</small>
                  <span class="bar"><span :style="{ width: `${progress(c) * 100}%` }"></span></span>
                </span>
                <span
                  class="keep" role="button" :title="'In the cut — click to skip (X)'" @click.stop="$emit('keep', c.part, false)"
                >✓</span>
              </button>
              <button
                v-if="c.next" class="tpill" :class="{ ruled: c.edge }" @click.stop="$emit('cycle', c.part)"
                :title="c.edge ? 'A new scene starts here: its transition is used' : `Into the next part: ${c.next.label}. Click to change (T).`"
              >{{ c.next.icon }} {{ c.next.label }}</button>
            </div>
          </template>
          <div v-else class="off">{{ row.bOff }}</div>
        </div>
      </div>
    </section>

    <!-- what isn't in any scene: lane A clips no scene shows, and skipped parts -->
    <section v-if="spareA.length || skipped.length" class="spare">
      <small class="muted">Not in the reel right now</small>
      <div class="cells">
        <div class="cell a" @dragover.prevent @drop="$emit('drop-a')">
          <button v-for="p in spareA" :key="p.id" class="card a quiet" :class="{ picked: pickedClip === p.id }" @click="$emit('pick-clip', p)" :title="`${p.media.file}: in lane A, no scene shows it yet`">
            <img :src="api.thumb(p.media.folder, p.media.file, p.start, 160)" alt="" loading="lazy" />
            <span class="txt"><b>{{ short(p.media.file) }}</b><small class="muted">lane A · no scene yet</small></span>
          </button>
        </div>
        <div class="cell b">
          <button v-for="p in skipped" :key="p.id" class="card b quiet" :class="{ picked: pickedB === p.id }" @click="$emit('pick-b', p)" :title="`${p.media.file}: skipped`">
            <img :src="api.thumb(p.media.folder, p.media.file, p.start, 160)" alt="" loading="lazy" />
            <span class="txt"><b>{{ short(p.media.file) }}</b><small class="muted">skipped</small></span>
            <span class="keep off" role="button" title="Skipped — click to keep (X)" @click.stop="$emit('keep', p, true)">–</span>
          </button>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
// The clip sheet: one row per scene, lane A's card beside lane B's parts,
// each with where it sits on the reel and a bar that fills as it plays. The
// scene under the playhead is outlined, the cards under it glow, and with
// Follow playhead the sheet keeps that row in view (pausing for a few
// seconds after you scroll it yourself).
import { computed, nextTick, ref, watch } from 'vue'
import { api } from '../api'
import { fmtTime } from '../time'
import { layoutLabel } from '../scenes'

const props = defineProps({
  rows: { type: Array, required: true },       // [{k, sc, start, end, a, aOff, b: [{part, start, len, next, edge}], bOff}]
  wide: Boolean,
  reelTime: { type: Number, default: null },
  reelOn: Boolean,
  pickedA: { type: Number, default: null },    // scene whose A stretch is selected
  pickedB: { type: Number, default: null },    // selected part id
  pickedClip: { type: Number, default: null }, // a lane A clip selected on its own
  spareA: { type: Array, default: () => [] },
  skipped: { type: Array, default: () => [] },
})
defineEmits(['seek', 'pick-a', 'pick-b', 'pick-clip', 'keep', 'cycle', 'drag-b', 'drop-on', 'drop-a', 'drop-b-end'])

const sheet = ref(null)
const follow = ref(true)
const dragOverId = ref(null)
const short = (name) => (name.length > 24 ? `${name.slice(0, 22)}…` : name)
const t = computed(() => props.reelTime)
const isNow = (c) => t.value !== null && t.value >= c.start - 1e-6 && t.value < c.start + c.len
const progress = (c) => (t.value === null ? 0 : Math.min(1, Math.max(0, (t.value - c.start) / (c.len || 1))))
const thumbAt = (a) => (a.part.media.kind === 'video' ? a.inClip : 0)
const playingScene = computed(() => {
  if (t.value === null) return -1
  const r = props.rows.find((x) => t.value >= x.start - 1e-6 && t.value < x.end)
  return r ? r.k : (props.rows.length ? props.rows[props.rows.length - 1].k : -1)
})

// Follow the playhead, unless the sheet was scrolled by hand in the last 3s.
let manualAt = 0
const manual = () => { manualAt = Date.now() }
watch(playingScene, async (k) => {
  if (!follow.value || k < 0 || Date.now() - manualAt < 3000) return
  await nextTick()
  const el = sheet.value?.querySelector(`[data-scene="${k}"]`)
  el?.scrollIntoView({ block: 'nearest', behavior: props.reelOn ? 'smooth' : 'auto' })
})
</script>

<style scoped>
.sheet { display: flex; flex-direction: column; gap: 10px; }
.sheethead { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.follow { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; padding: 4px 10px; border-radius: 8px; border: 1px solid var(--line); cursor: pointer; }
.follow.on { border-color: var(--playing); }
.cols, .cells { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.cols { position: sticky; top: 0; z-index: 2; background: var(--cream); padding: 4px 0; }
.colhead { display: flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 8px; font-size: 13px; color: var(--ink); }
.colhead small { color: var(--muted); font-size: 11px; }
.colhead i { width: 10px; height: 14px; border-radius: 2px; }
.colhead.a { background: var(--lane-a-soft); border: 1px solid var(--lane-a); }
.colhead.a i { background: var(--lane-a); }
.colhead.b { background: var(--lane-b-soft); border: 1px solid var(--lane-b); }
.colhead.b i { background: var(--lane-b); }
.scene { border: 1px solid var(--line); border-radius: var(--radius); padding: 8px; background: var(--paper); }
.scene.playing { border-color: var(--playing); box-shadow: 0 0 0 1px var(--playing); }
.scenehead {
  display: flex; align-items: center; gap: 8px; width: 100%; margin-bottom: 8px; padding: 0; border: 0; background: none;
  color: inherit; font: inherit; font-size: 13px; text-align: left; cursor: pointer;
}
.scenehead small { color: var(--muted); }
.chip.playing { font-size: 10px; font-weight: 700; padding: 1px 7px; border-radius: 8px; background: var(--playing); color: #fff; }
.glyph { display: inline-flex; flex-direction: column; gap: 2px; width: 10px; height: 16px; }
.glyph i { flex: 1; border-radius: 2px; }
.g-soloA i:first-child { background: var(--lane-a); } .g-soloA i:last-child { display: none; }
.g-soloB i:first-child { background: var(--lane-b); } .g-soloB i:last-child { display: none; }
.g-stack i:first-child { background: var(--lane-a); } .g-stack i:last-child { background: var(--lane-b); }
.g-swap i:first-child { background: var(--lane-b); } .g-swap i:last-child { background: var(--lane-a); }
.cell { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.bwrap { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; }
.card {
  position: relative; display: flex; align-items: center; gap: 8px; width: 100%; padding: 6px; border-radius: 10px; text-align: left;
  border: 1px solid var(--line); background: var(--cream); color: inherit; font: inherit; cursor: pointer; min-width: 0;
}
.card img { width: 40px; height: 52px; object-fit: cover; border-radius: 6px; flex: none; background: var(--stage); }
.card .txt { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
.card b { font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.card small { font-size: 11px; color: var(--muted); }
.bar { display: block; height: 3px; border-radius: 2px; background: var(--line); overflow: hidden; margin-top: 3px; }
.bar span { display: block; height: 100%; }
.card.a .bar span { background: var(--lane-a); }
.card.b .bar span { background: var(--lane-b); }
.card.a.now { background: var(--lane-a-soft); border-color: var(--lane-a); box-shadow: 0 0 0 1px var(--lane-a), 0 0 12px color-mix(in srgb, var(--lane-a) 45%, transparent); }
.card.b.now { background: var(--lane-b-soft); border-color: var(--lane-b); box-shadow: 0 0 0 1px var(--lane-b), 0 0 12px color-mix(in srgb, var(--lane-b) 45%, transparent); }
.card.picked { outline: 2px solid var(--picked); outline-offset: 1px; }
.card.over { box-shadow: inset 0 3px 0 var(--lane-b); }
.card.quiet { opacity: 0.6; }
.keep {
  position: absolute; right: 6px; top: 6px; width: 18px; height: 18px; border-radius: 50%; display: grid; place-items: center;
  font-size: 11px; border: 1px solid var(--line); color: var(--muted); background: var(--paper);
}
.keep.off { color: var(--ink); }
.off {
  display: grid; place-items: center; min-height: 64px; padding: 8px; border-radius: 10px; font-size: 12px; color: var(--muted); text-align: center;
  background: repeating-linear-gradient(45deg, rgb(128 128 128 / 14%) 0 6px, transparent 6px 12px);
}
.tpill {
  margin-left: 10px; font-size: 11px; padding: 1px 8px; border-radius: 10px; border: 1px dashed var(--line); background: transparent;
  color: var(--muted); cursor: pointer;
}
.tpill.ruled { opacity: 0.5; }
.spare { display: flex; flex-direction: column; gap: 6px; padding: 8px; border: 1px dashed var(--line); border-radius: var(--radius); }
</style>
