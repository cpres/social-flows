<template>
  <main class="page">
    <p v-if="error" class="notice">{{ error }}</p>
    <p v-else-if="loading" class="muted">Reading your footage…</p>

    <template v-else>
      <div class="head">
        <h1>Reels</h1>
        <p class="muted">Concepts you're building. Tag parts of any clip or photo into them.</p>
      </div>
      <div class="grid">
        <RouterLink v-for="r in reels" :key="r.id" :to="`/reel/${r.id}`" class="card">
          <div class="cover">
            <img v-if="r.cover" :src="api.thumb(r.cover.folder, r.cover.name, r.cover.start, 640)" loading="lazy" alt="" />
            <div v-else class="empty">empty</div>
            <span class="badge">{{ fmtTime(r.totalLength) }}</span>
            <span class="swatch" :style="{ background: reelColor(r.id) }"></span>
          </div>
          <div class="meta">
            <h2>{{ r.name }}</h2>
            <p class="muted">{{ r.itemCount }} part{{ r.itemCount === 1 ? '' : 's' }}</p>
          </div>
        </RouterLink>
        <button class="card new" @click="newReel">
          <span class="plus">+</span>
          <span>New reel</span>
        </button>
      </div>

      <div class="head shoots">
        <h1>Shoots</h1>
        <p class="muted" v-if="folders.length">
          {{ folders.length }} folders · {{ fmtDuration(totalFootage) }} of video
        </p>
        <button class="refresh inline" @click="load" :disabled="refreshing">
          ↻ {{ refreshing ? 'Checking…' : 'Refresh' }}
        </button>
        <button class="btn primary import" @click="importing = true">
          ⇣ Import from Downloads
          <span class="count" v-if="waiting" :title="`${waiting} new from today`">{{ waiting }}</span>
        </button>
      </div>
      <p v-if="!folders.length" class="notice">
        No folders in <code>{{ root }}</code> yet. AirDrop clips from your phone and
        <button class="link" @click="importing = true">import them</button>, or make a folder per
        shoot (e.g. <code>2026-09-24</code>) and drop the clips in.
      </p>
      <div class="grid">
        <RouterLink
          v-for="f in folders" :key="f.name"
          :to="`/shoot/${encodeURIComponent(f.name)}`" class="card"
        >
          <div class="cover">
            <img v-if="f.cover" :src="api.thumb(f.name, f.cover, f.coverTime, 640)" loading="lazy" alt="" />
            <div v-else class="empty">empty</div>
            <span class="badge" v-if="f.totalDuration">{{ fmtDuration(f.totalDuration) }}</span>
            <span class="badge used" v-if="f.usedCount">{{ f.usedCount }} in reels</span>
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
      <button class="refresh bottom" @click="load" :disabled="refreshing">
        ↻ {{ refreshing ? 'Checking for new footage…' : 'Check for new footage' }}
      </button>
    </template>
    <ImportDialog
      v-if="importing" :folders="folders" :root="root"
      @close="importing = false" @imported="imported"
    />
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import ImportDialog from '../components/ImportDialog.vue'
import { useRefreshOnFocus } from '../refresh'
import { fmtDuration, fmtTime, folderTitle, reelColor } from '../time'

const emit = defineEmits(['root'])
const router = useRouter()
const folders = ref([])
const reels = ref([])
const root = ref('')
const error = ref('')
const loading = ref(true)
const totalFootage = computed(() => folders.value.reduce((a, f) => a + f.totalDuration, 0))

const refreshing = ref(false)
const importing = ref(false)
const waiting = ref(0)   // photos and videos from today in Downloads, not yet imported

async function load() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    const data = await api.home()
    folders.value = data.folders
    reels.value = data.reels
    root.value = data.root
    error.value = data.error || ''
    emit('root', data.root)
    checkDownloads()
  } catch (e) {
    error.value = `Couldn't reach the server: ${e.message}`
  } finally {
    loading.value = false
    refreshing.value = false
  }
}
onMounted(load)
useRefreshOnFocus(load)

async function checkDownloads() {
  try {
    const r = await api.importList()
    const songs = (r.songs || []).filter((f) => f.day === r.today && !f.inShelf).length
    waiting.value = (r.days.find((d) => d.day === r.today)?.new || 0) + songs
  } catch {
    waiting.value = 0
  }
}

function imported(r) {
  importing.value = false
  router.push(`/shoot/${encodeURIComponent(r.folder)}`)
}

async function newReel() {
  const name = window.prompt('Name the new reel')
  if (!name?.trim()) return
  try {
    const r = await api.createReel(name.trim())
    router.push(`/reel/${r.id}`)
  } catch (e) {
    window.alert(e.message)
  }
}
</script>

<style scoped>
.page { max-width: 1280px; margin: 0 auto; padding: 32px 24px 64px; }
.head { display: flex; align-items: baseline; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }
.head.shoots { margin-top: 44px; }
.refresh.inline { width: auto; margin-left: auto; }
.import { display: inline-flex; align-items: center; gap: 8px; }
.import .count {
  background: var(--sage); color: var(--on-sage); border-radius: 999px; font-size: 12px;
  font-weight: 700; padding: 0 7px; min-width: 20px; text-align: center;
}
.link {
  border: 0; background: none; padding: 0; color: var(--forest); font-weight: 600; cursor: pointer;
  text-decoration: underline; text-underline-offset: 2px;
}
.refresh.bottom { margin-top: 20px; }
h1 { margin: 0; font-size: 26px; color: var(--forest); }
.head p { margin: 0; }
.notice { background: var(--paper); border: 1px solid var(--line); border-radius: var(--radius); padding: 16px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 20px; }
.card {
  background: var(--paper); border-radius: var(--radius); overflow: hidden;
  box-shadow: var(--shadow); transition: transform 0.15s, box-shadow 0.15s; text-align: left;
}
.card:hover { transform: translateY(-2px); box-shadow: 0 6px 24px rgb(31 42 31 / 14%); }
.card.new {
  border: 2px dashed var(--sage); background: transparent; box-shadow: none; cursor: pointer;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px;
  min-height: 190px; color: var(--forest); font-weight: 600;
}
.plus { font-size: 34px; line-height: 1; }
.cover { position: relative; aspect-ratio: 4 / 5; background: var(--forest); }
.cover img { width: 100%; height: 100%; object-fit: cover; display: block; }
.empty { display: grid; place-items: center; height: 100%; color: var(--sage); }
.badge {
  position: absolute; right: 8px; bottom: 8px; font-size: 12px; font-weight: 600;
  background: rgb(31 42 31 / 75%); color: var(--on-media); padding: 2px 8px; border-radius: 999px;
}
.badge.used { right: auto; left: 8px; background: var(--sage); color: var(--on-sage); }
.swatch { position: absolute; left: 0; right: 0; bottom: 0; height: 4px; }
.meta { padding: 12px 14px 14px; }
h2 { margin: 0 0 4px; font-size: 17px; }
.meta p { margin: 0; font-size: 13px; }
.raw { font-family: ui-monospace, monospace; font-size: 12px; }
</style>
