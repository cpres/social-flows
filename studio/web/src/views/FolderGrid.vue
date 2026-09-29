<template>
  <main class="page">
    <div class="head">
      <h1>Footage</h1>
      <p class="muted" v-if="folders.length">
        {{ folders.length }} folders · {{ fmtDuration(totalFootage) }} of video
      </p>
    </div>

    <p v-if="error" class="notice">{{ error }}</p>
    <p v-else-if="loading" class="muted">Reading folders…</p>
    <p v-else-if="!folders.length" class="notice">
      No folders in <code>{{ root }}</code> yet. Make one per shoot (e.g. <code>2026-09-24</code>)
      and drop the clips in.
    </p>

    <div class="grid">
      <RouterLink
        v-for="f in folders" :key="f.name"
        :to="`/folder/${encodeURIComponent(f.name)}`" class="card"
      >
        <div class="cover">
          <img v-if="f.cover" :src="api.thumb(f.name, f.cover, f.coverTime, 640)" loading="lazy" alt="" />
          <div v-else class="empty">empty</div>
          <span class="badge" v-if="f.totalDuration">{{ fmtDuration(f.totalDuration) }}</span>
          <span class="badge edited" v-if="f.edited">{{ f.keptCount }} kept</span>
        </div>
        <div class="meta">
          <h2>{{ folderTitle(f.name) }}</h2>
          <p class="muted">
            <span v-if="folderTitle(f.name) !== f.name" class="raw">{{ f.name }} · </span>
            {{ f.clipCount }} clip{{ f.clipCount === 1 ? '' : 's' }}
            <template v-if="f.photoCount"> · {{ f.photoCount }} photo{{ f.photoCount === 1 ? '' : 's' }}</template>
          </p>
        </div>
      </RouterLink>
    </div>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { fmtDuration, folderTitle } from '../time'

const emit = defineEmits(['root'])
const folders = ref([])
const root = ref('')
const error = ref('')
const loading = ref(true)
const totalFootage = computed(() => folders.value.reduce((a, f) => a + f.totalDuration, 0))

onMounted(async () => {
  try {
    const data = await api.folders()
    folders.value = data.folders
    root.value = data.root
    error.value = data.error || ''
    emit('root', data.root)
  } catch (e) {
    error.value = `Couldn't reach the server: ${e.message}`
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.page { max-width: 1280px; margin: 0 auto; padding: 32px 24px 64px; }
.head { display: flex; align-items: baseline; gap: 16px; margin-bottom: 20px; }
h1 { margin: 0; font-size: 28px; color: var(--forest); }
.head p { margin: 0; }
.notice { background: var(--paper); border: 1px solid var(--line); border-radius: var(--radius); padding: 16px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 20px; }
.card {
  background: var(--paper); border-radius: var(--radius); overflow: hidden;
  box-shadow: var(--shadow); transition: transform 0.15s, box-shadow 0.15s;
}
.card:hover { transform: translateY(-2px); box-shadow: 0 6px 24px rgb(31 42 31 / 14%); }
.cover { position: relative; aspect-ratio: 16 / 10; background: var(--forest); }
.cover img { width: 100%; height: 100%; object-fit: cover; display: block; }
.empty { display: grid; place-items: center; height: 100%; color: var(--sage); }
.badge {
  position: absolute; right: 8px; bottom: 8px; font-size: 12px; font-weight: 600;
  background: rgb(31 42 31 / 75%); color: var(--cream); padding: 2px 8px; border-radius: 999px;
}
.badge.edited { right: auto; left: 8px; background: var(--sage); color: var(--forest); }
.meta { padding: 12px 14px 14px; }
h2 { margin: 0 0 4px; font-size: 17px; }
.meta p { margin: 0; font-size: 13px; }
.raw { font-family: ui-monospace, monospace; font-size: 12px; }
</style>
