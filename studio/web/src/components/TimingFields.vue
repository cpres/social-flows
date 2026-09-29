<template>
  <div class="timing">
    <label class="field" v-if="kind === 'video'">
      Start
      <input :value="fmtTime(start)" @change="onStart" />
    </label>
    <label class="field">
      {{ kind === 'video' ? 'Length (seconds)' : 'Hold (seconds)' }}
      <input type="number" min="0.2" step="0.1" :value="length.toFixed(1)" @change="onLength" />
    </label>
    <div class="presets">
      <span class="muted">Quick lengths</span>
      <div>
        <button
          v-for="p in presets" :key="p" class="btn small"
          :class="{ active: Math.abs(length - p) < 0.05 }" @click="setLength(p)"
        >{{ p }}s</button>
      </div>
    </div>
    <slot />
  </div>
</template>

<script setup>
import { fitRange, fmtTime, parseTime } from '../time'

const props = defineProps({
  kind: { type: String, required: true },
  start: { type: Number, required: true },
  length: { type: Number, required: true },
  duration: { type: Number, default: 0 },
})
const emit = defineEmits(['update'])
const presets = [0.5, 1, 1.5, 2, 3, 5]

function update(start, length) {
  if (props.kind === 'photo') emit('update', { start: 0, length: Math.max(0.2, length) })
  else emit('update', fitRange(start, length, props.duration))
}
// Changing the length keeps the start where it is when it can.
const setLength = (len) => update(Math.min(props.start, props.duration - len), len)

function onStart(e) {
  const t = parseTime(e.target.value)
  if (!isNaN(t)) update(t, props.length)
  e.target.value = fmtTime(props.start)
}
function onLength(e) {
  const len = Number(e.target.value)
  if (len > 0) setLength(len)
  e.target.value = props.length.toFixed(1)
}
</script>

<style scoped>
.timing {
  display: flex; gap: 20px; align-items: flex-end; flex-wrap: wrap; margin-top: 18px;
  padding: 16px; background: var(--paper); border-radius: var(--radius); box-shadow: var(--shadow);
}
.field { width: 150px; }
.field input { font-family: ui-monospace, monospace; font-size: 18px; }
.presets { display: flex; flex-direction: column; gap: 4px; font-size: 12px; }
.presets div { display: flex; gap: 4px; flex-wrap: wrap; }
</style>
