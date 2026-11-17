<template>
  <div class="dest">
    <div class="choice" :class="{ on: mode === 'new' }" @click="mode = 'new'">
      <label class="pick"><input type="radio" value="new" v-model="mode" />
        <span class="ctitle">New shoot folder</span></label>
      <div class="row" v-if="mode === 'new'">
        <label class="field date">
          Date
          <input type="date" v-model="date" />
        </label>
        <label class="field grow">
          What was it? <span class="opt">(optional)</span>
          <input ref="labelInput" v-model="label" placeholder="e.g. garden build" @keydown.enter="$emit('enter')" />
        </label>
      </div>
      <p class="preview" v-if="mode === 'new'">
        <span class="folder-ico">▣</span>
        <b>{{ folderTitle(newName) || '—' }}</b>
        <span class="mono muted" v-if="newName">{{ root }}/{{ newName }}</span>
      </p>
      <p class="warn" v-if="mode === 'new' && clash">
        You already have this folder.
        <button class="link" @click.stop="useExisting(newName)">Add to it instead</button>
      </p>
    </div>

    <div class="choice" :class="{ on: mode === 'existing' }" v-if="folders.length" @click="mode = 'existing'">
      <label class="pick"><input type="radio" value="existing" v-model="mode" />
        <span class="ctitle">Add to an existing folder</span></label>
      <div class="existing" v-if="mode === 'existing'">
        <button
          v-for="f in folders" :key="f.name" class="exf" :class="{ on: target === f.name }"
          @click="target = f.name"
        >
          <img v-if="f.cover" :src="api.thumb(f.name, f.cover, f.coverTime, 160)" loading="lazy" alt="" />
          <span v-else class="noimg"></span>
          <span class="exmeta">
            <b>{{ folderTitle(f.name) }}</b>
            <span class="muted">{{ f.clipCount }} clip{{ f.clipCount === 1 ? '' : 's' }}<template
              v-if="f.photoCount"> · {{ f.photoCount }} photo{{ f.photoCount === 1 ? '' : 's' }}</template></span>
          </span>
        </button>
      </div>
    </div>
  </div>
</template>

<script>
// A new shoot folder's name: "2026-10-06 garden build".
export const folderNameOf = (date, label) => [date, (label || '').trim()].filter(Boolean).join(' ')
</script>

<script setup>
// Where an import goes: a new shoot folder (a date and "What was it?") or one
// already there. Import from Downloads and from Google Photos both use it.
import { computed, nextTick, ref, watch } from 'vue'
import { api } from '../api'
import { folderTitle } from '../time'

const props = defineProps({
  folders: { type: Array, default: () => [] },   // the shoots, newest first
  root: { type: String, default: '' },
})
defineEmits(['enter'])
const mode = defineModel('mode', { default: 'new' })      // new | existing
const date = defineModel('date', { default: '' })
const label = defineModel('label', { default: '' })
const target = defineModel('target', { default: '' })   // the existing folder

const labelInput = ref(null)
const newName = computed(() => folderNameOf(date.value, label.value))
const clash = computed(() => props.folders.some((f) => f.name === newName.value))

function useExisting(name) {
  target.value = name
  mode.value = 'existing'
}

watch(mode, async (m) => {
  if (m === 'new') {
    await nextTick()
    labelInput.value?.focus()
  }
})
</script>

<style scoped>
.dest { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; align-items: start; }
.choice {
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 12px 14px;
  border: 1px solid var(--line); border-radius: var(--radius); cursor: pointer; background: var(--paper);
}
.choice:hover { border-color: var(--sage); }
.choice.on { border-color: var(--sage); background: var(--sage-soft); cursor: default; }
.pick { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.choice input[type='radio'] { accent-color: var(--forest); margin: 0; }
.ctitle { font-weight: 600; color: var(--forest); }
.row { display: flex; gap: 10px; width: 100%; margin-top: 4px; }
.field.date { flex: none; width: 150px; }
.field.grow { flex: 1; min-width: 0; }
.opt { opacity: 0.7; }
.preview { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; width: 100%; margin: 2px 0 0; font-size: 14px; }
.preview .mono { font-size: 11px; word-break: break-all; }
.folder-ico { color: var(--sage); }
.warn { width: 100%; margin: 0; font-size: 13px; color: var(--warn); }
.link {
  border: 0; background: none; padding: 0; color: var(--forest); font-weight: 600;
  cursor: pointer; font-size: 13px; text-decoration: underline; text-underline-offset: 2px;
}
.existing {
  width: 100%; display: flex; flex-direction: column; gap: 4px; max-height: 200px; overflow-y: auto;
  margin-top: 4px;
}
.exf {
  display: flex; align-items: center; gap: 10px; text-align: left; padding: 4px;
  border: 1px solid transparent; border-radius: 8px; background: transparent; cursor: pointer;
}
.exf:hover { background: var(--paper); }
.exf.on { background: var(--paper); border-color: var(--forest); }
.exf img, .noimg { width: 40px; height: 40px; border-radius: 6px; object-fit: cover; flex: none; background: var(--forest); }
.exmeta { display: flex; flex-direction: column; font-size: 13px; min-width: 0; }
.exmeta b { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.exmeta .muted { font-size: 12px; }
@media (max-width: 700px) {
  .dest { grid-template-columns: 1fr; }
}
</style>
