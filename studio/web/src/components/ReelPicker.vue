<template>
  <div class="reelpicker" @focusout="onFocusOut">
    <input
      ref="input" v-model="query" class="find" :placeholder="placeholder"
      role="combobox" aria-autocomplete="list" :aria-expanded="open"
      @focus="open = true" @input="open = true; at = 0" @keydown="onKey"
    />
    <ul v-if="open" class="list" role="listbox" ref="listEl">
      <li v-if="options.length === 1 && query.trim()" class="muted empty">No reel has “{{ query.trim() }}” in its name</li>
      <li
        v-for="(o, i) in options" :key="o.key" role="option" :aria-selected="i === at"
        :class="{ at: i === at, create: o.create }" @mousedown.prevent="choose(o)" @mousemove="at = i"
      >
        <template v-if="o.create">+ New reel<template v-if="query.trim()"> “{{ query.trim() }}”</template></template>
        <template v-else>
          <span class="sw" :style="{ background: colorOf(o.reel.id) }"></span>
          <span class="name">{{ o.reel.name }}</span>
          <small v-if="note(o.reel)" class="muted">{{ note(o.reel) }}</small>
        </template>
      </li>
    </ul>
  </div>
</template>

<script setup>
// Add to a reel by typing part of its name: the reels (most recently edited
// first) narrowed to the ones with every word typed, ↑/↓ and Enter to pick,
// and a new reel, named what's typed, at the bottom.
import { computed, nextTick, ref } from 'vue'

const props = defineProps({
  reels: { type: Array, default: () => [] },          // [{ id, name }]
  colorOf: { type: Function, default: () => 'transparent' },
  note: { type: Function, default: () => '' },         // reel -> a word after its name ("2 here")
  placeholder: { type: String, default: 'Add to reel… (type to find)' },
})
const emit = defineEmits(['pick', 'create'])

const input = ref(null)
const listEl = ref(null)
const query = ref('')
const open = ref(false)
const at = ref(0)

const options = computed(() => {
  const words = query.value.toLowerCase().split(/\s+/).filter(Boolean)
  const found = props.reels
    .filter((r) => words.every((w) => r.name.toLowerCase().includes(w)))
    .map((r) => ({ key: r.id, reel: r }))
  return [...found, { key: 'new', create: true }]
})

function choose(o) {
  if (!o) return
  if (o.create) emit('create', query.value.trim())
  else emit('pick', o.reel)
  query.value = ''
  open.value = false
  input.value?.blur()
}
function onKey(e) {
  const n = options.value.length
  if (e.key === 'ArrowDown') at.value = (at.value + 1) % n
  else if (e.key === 'ArrowUp') at.value = (at.value - 1 + n) % n
  else if (e.key === 'Enter') choose(options.value[at.value])
  else if (e.key === 'Escape') { query.value = ''; open.value = false; input.value?.blur() }
  else return
  e.preventDefault()
  e.stopPropagation()
  nextTick(() => listEl.value?.querySelectorAll('[role=option]')[at.value]?.scrollIntoView({ block: 'nearest' }))
}
function onFocusOut(e) {
  if (!e.currentTarget.contains(e.relatedTarget)) open.value = false
}
defineExpose({ focus: () => input.value?.focus() })
</script>

<style scoped>
.reelpicker { position: relative; }
.find { width: 100%; box-sizing: border-box; }
.list {
  position: absolute; z-index: 30; left: 0; right: 0; top: calc(100% + 4px); margin: 0; padding: 4px;
  list-style: none; max-height: 280px; overflow: auto; border-radius: 10px;
  background: var(--paper); border: 1px solid var(--line); box-shadow: var(--shadow);
}
.list li {
  display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-radius: 7px; cursor: pointer;
}
.list li.at { background: var(--line); }
.list li.create { color: var(--sage); }
.list li.empty { cursor: default; font-size: 12px; }
.name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sw { width: 10px; height: 10px; border-radius: 50%; flex: none; }
</style>
