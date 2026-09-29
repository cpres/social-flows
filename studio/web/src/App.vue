<template>
  <header class="topbar">
    <RouterLink to="/" class="brand">
      <span class="logo">▶</span> Footage Studio
    </RouterLink>
    <span class="root" v-if="root">{{ root }}</span>
  </header>
  <RouterView @root="root = $event" />
</template>

<script setup>
import { ref } from 'vue'
const root = ref('')
</script>
