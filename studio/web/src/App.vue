<template>
  <header class="topbar">
    <RouterLink to="/" class="brand">
      <span class="logo">▶</span> Footage Studio
    </RouterLink>
    <span class="root" v-if="root">{{ root }}</span>
    <div class="themes" :class="{ alone: !root }" role="group" aria-label="Theme">
      <button
        v-for="t in THEMES" :key="t.v" :class="{ on: theme === t.v }"
        :aria-pressed="theme === t.v" @click="theme = t.v"
      >{{ t.label }}</button>
    </div>
  </header>
  <RouterView :key="$route.path" @root="root = $event" />
</template>

<script setup>
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { THEMES, theme } from './theme'

const root = ref('')
const route = useRoute()
watch(() => route.path, () => { root.value = '' })
</script>
