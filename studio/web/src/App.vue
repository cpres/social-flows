<template>
  <header class="topbar">
    <RouterLink to="/" class="brand">
      <span class="logo">▶</span> Footage Studio
    </RouterLink>
    <span class="root" v-if="root">{{ root }}</span>
  </header>
  <RouterView :key="$route.path" @root="root = $event" />
</template>

<script setup>
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'

const root = ref('')
const route = useRoute()
watch(() => route.path, () => { root.value = '' })
</script>
