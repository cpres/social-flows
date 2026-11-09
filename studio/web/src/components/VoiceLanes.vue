<template>
  <!-- The voice track and its captions under the reel's strip, on the same clock.
       Its own component, so the reel page playing doesn't redraw every line:
       it changes only when the line being said does. -->
  <div class="lane vlane" v-if="pieces.length" @click="seek" title="The voice: click to play from there">
    <div
      v-for="p in pieces" :key="p.id" class="vpiece" :style="at(p.at, p.length)"
      :title="`${p.file} · ${fmtTime(p.at)} → ${fmtTime(p.at + p.length)}`"
    >🎙 {{ p.file }}</div>
    <div
      v-for="(f, i) in fx" :key="`fx${i}`" class="vfx" :style="at(f.start, f.end - f.start)"
      :title="`${fxInfo(f.effect).label} at ${fmtTime(f.start)}`"
    >{{ fxInfo(f.effect).icon }}</div>
  </div>
  <div class="lane clane" v-if="lines.length" @click="seek">
    <div
      v-for="(l, i) in lines" :key="i" class="cline" :class="{ on: i === active }" :style="at(l.start, l.end - l.start)"
      :title="l.text"
    >{{ l.text }}</div>
  </div>
</template>

<script setup>
import { fxInfo } from '../captions'
import { fmtTime } from '../time'

const props = defineProps({
  pieces: { type: Array, default: () => [] },
  fx: { type: Array, default: () => [] },
  lines: { type: Array, default: () => [] },   // [] when captions are off
  length: { type: Number, default: 1 },        // the reel's length, which the lanes span
  active: { type: Number, default: -1 },       // the line being said
})
const emit = defineEmits(['seek'])
const at = (start, len) => ({ left: `${(start / (props.length || 1)) * 100}%`, width: `${(len / (props.length || 1)) * 100}%` })
function seek(e) {
  const r = e.currentTarget.getBoundingClientRect()
  emit('seek', ((e.clientX - r.left) / r.width) * props.length)
}
</script>

<style scoped>
.lane { position: relative; flex: none; height: 20px; cursor: pointer; border-radius: 4px; background: rgb(128 128 128 / 8%); }
.vpiece {
  position: absolute; top: 0; bottom: 0; border: 1.5px solid var(--warn); border-radius: 4px; font-size: 10px; font-weight: 600;
  padding: 0 6px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; color: var(--ink); line-height: 17px;
  background: rgb(181 100 45 / 10%);
}
.vfx {
  position: absolute; top: 2px; bottom: 2px; border-radius: 3px; background: rgb(181 100 45 / 45%); color: var(--paper);
  font-size: 10px; line-height: 14px; text-align: center; overflow: hidden; pointer-events: none;
}
.clane { height: 18px; }
.cline {
  position: absolute; top: 1px; bottom: 1px; border: 1px solid var(--line); border-radius: 4px; background: var(--paper);
  font-size: 10px; padding: 0 4px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; line-height: 14px; color: var(--muted);
}
.cline.on { border-color: var(--warn); color: var(--ink); }
</style>
