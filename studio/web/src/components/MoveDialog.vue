<template>
  <div class="modal" @click.self="$emit('close')">
    <div class="dialog">
      <h2>Move {{ countLabel }}</h2>
      <p class="muted">
        Out of <b>{{ folderTitle(from) }}</b>. Their parts in reels come along.
        <template v-if="all"> Nothing will be left here, so this folder goes away.</template>
      </p>

      <p v-if="loading" class="muted">Loading folders…</p>
      <div v-else class="dest">
        <div class="choice" :class="{ on: mode === 'existing' }" v-if="others.length" @click="mode = 'existing'">
          <label class="pick"><input type="radio" value="existing" v-model="mode" />
            <span class="ctitle">To an existing folder</span></label>
          <div class="existing" v-if="mode === 'existing'">
            <button
              v-for="f in others" :key="f.name" class="exf" :class="{ on: target === f.name }"
              @click="target = f.name" @dblclick="go"
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

        <div class="choice" :class="{ on: mode === 'new' }" @click="mode = 'new'">
          <label class="pick"><input type="radio" value="new" v-model="mode" />
            <span class="ctitle">To a new folder</span></label>
          <div class="row" v-if="mode === 'new'">
            <label class="field date">
              Date
              <input type="date" v-model="newDate" />
            </label>
            <label class="field grow">
              What was it? <span class="opt">(optional)</span>
              <input ref="labelInput" v-model="newLabel" placeholder="e.g. garden build" @keydown.enter="go" />
            </label>
          </div>
          <p class="preview" v-if="mode === 'new'">
            <span class="folder-ico">▣</span>
            <b>{{ folderTitle(newName) || '—' }}</b>
          </p>
          <p class="warn" v-if="mode === 'new' && clash">
            <template v-if="newName === from">That's this folder.</template>
            <template v-else>
              You already have this folder.
              <button class="link" @click.stop="useExisting(newName)">Move into it instead</button>
            </template>
          </p>
        </div>
      </div>

      <p v-if="failure" class="err">{{ failure }}</p>
      <div class="controls">
        <span class="spacer"></span>
        <button class="btn" @click="$emit('close')">Cancel</button>
        <button class="btn primary" :disabled="!canMove" @click="go">
          {{ busy ? 'Moving…' : `Move to ${folderTitle(destName) || '…'}` }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { folderTitle } from '../time'

const props = defineProps({
  from: { type: String, required: true },          // the shoot folder they're in
  files: { type: Array, required: true },          // media rows to move
  all: Boolean,                                    // every file in the folder
})
const emit = defineEmits(['close', 'moved'])

const loading = ref(true)
const folders = ref([])
const mode = ref('existing')
const target = ref('')
const newDate = ref('')
const newLabel = ref('')
const busy = ref(false)
const failure = ref('')
const labelInput = ref(null)

const others = computed(() => folders.value.filter((f) => f.name !== props.from))
const newName = computed(() => [newDate.value, newLabel.value.trim()].filter(Boolean).join(' '))
const clash = computed(() => newName.value === props.from || folders.value.some((f) => f.name === newName.value))
const destName = computed(() => (mode.value === 'new' ? newName.value : target.value))
const canMove = computed(() => !busy.value && !loading.value && !!destName.value && !(mode.value === 'new' && clash.value))
const countLabel = computed(() => {
  const v = props.files.filter((m) => m.kind === 'video').length
  const p = props.files.length - v
  return [v && `${v} video${v === 1 ? '' : 's'}`, p && `${p} photo${p === 1 ? '' : 's'}`].filter(Boolean).join(' and ')
})

onMounted(async () => {
  try {
    folders.value = (await api.home()).folders
    // A new folder starts on the day this one is named for (it's usually the
    // label that was wrong), else on the day the first file was shot.
    const t = new Date((props.files[0]?.capturedAt || Date.now() / 1000) * 1000)
    newDate.value = /^\d{4}-\d{2}-\d{2}/.exec(props.from)?.[0]
      || `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`
    // The likeliest home: another folder for the same day, else the newest.
    const day = newDate.value
    target.value = (others.value.find((f) => f.name.startsWith(day)) || others.value[0])?.name || ''
    if (!others.value.length) mode.value = 'new'
  } catch (e) {
    failure.value = e.message
  } finally {
    loading.value = false
  }
})

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

async function go() {
  if (!canMove.value) return
  busy.value = true
  failure.value = ''
  try {
    const r = await api.moveFiles(props.from, {
      files: props.files.map((m) => m.file), to: destName.value, create: mode.value === 'new',
    })
    if (r.failed.length) failure.value = r.failed.map((f) => `${f.name}: ${f.error}`).join('\n')
    if (r.moved.length) emit('moved', r)
  } catch (e) {
    failure.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.dialog { display: flex; flex-direction: column; gap: 14px; width: min(560px, 100%); }
.dialog > p { margin: 0; }
.dest { display: flex; flex-direction: column; gap: 12px; }
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
.preview { display: flex; align-items: baseline; gap: 8px; width: 100%; margin: 2px 0 0; font-size: 14px; }
.folder-ico { color: var(--sage); }
.warn { width: 100%; margin: 0; font-size: 13px; color: var(--warn); }
.existing {
  width: 100%; display: flex; flex-direction: column; gap: 4px; max-height: 260px; overflow-y: auto;
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
.controls { margin-top: 0; }
.err { color: var(--danger); white-space: pre-line; margin: 0; }
.link {
  border: 0; background: none; padding: 0; color: var(--forest); font-weight: 600;
  cursor: pointer; font-size: 13px; text-decoration: underline; text-underline-offset: 2px;
}
@media (max-width: 500px) {
  .row { flex-wrap: wrap; }
  .field.date { width: 100%; }
}
</style>
