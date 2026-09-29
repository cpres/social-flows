<template>
  <main class="page">
    <div class="head">
      <h1>Renders</h1>
      <p class="muted">Every finished video in <code>{{ dir }}</code>, newest first.</p>
      <button class="refresh inline" @click="load" :disabled="loading">↻ {{ loading ? 'Checking…' : 'Refresh' }}</button>
    </div>

    <p v-if="error" class="notice">{{ error }}</p>
    <p v-else-if="!loading && !videos.length" class="notice">
      Nothing rendered yet. Open a reel and click <b>Render video</b>.
    </p>

    <div class="list">
      <div v-for="v in videos" :key="v.name" class="row">
        <button class="thumb" @click="playing = v" title="Play">
          <img :src="api.renderedThumb(v.name, v.modified)" alt="" loading="lazy" />
          <span class="dur">{{ fmtTime(v.duration) }}</span>
        </button>
        <div class="info">
          <div class="name">{{ v.reel?.name || v.name.replace(/\.mp4$/, '') }}</div>
          <div class="muted sub">
            {{ when(v.modified) }} · {{ (v.size / 1e6).toFixed(1) }} MB
            <template v-if="v.reel"> · <RouterLink :to="`/reel/${v.reel.id}`">open reel</RouterLink></template>
          </div>
        </div>
        <div class="actions">
          <button class="btn" @click="playing = v">▶ Play</button>
          <button class="btn primary" @click="sending = v.name">Send to phone</button>
          <button class="btn" @click="api.revealRendered(v.name)">Show in Finder</button>
        </div>
      </div>
    </div>

    <div class="modal" v-if="playing" @click.self="playing = null">
      <div class="dialog player">
        <video :src="api.renderedFile(playing.name)" controls autoplay playsinline></video>
        <div class="controls">
          <span class="mono">{{ playing.name }}</span>
          <span class="spacer"></span>
          <button class="btn primary" @click="sending = playing.name; playing = null">Send to phone</button>
          <button class="btn" @click="playing = null">Close</button>
        </div>
      </div>
    </div>
    <SendToPhone v-if="sending" :name="sending" @close="sending = null" />
  </main>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { useRefreshOnFocus } from '../refresh'
import { fmtTime } from '../time'
import SendToPhone from '../components/SendToPhone.vue'

const videos = ref([])
const dir = ref('')
const loading = ref(true)
const error = ref('')
const playing = ref(null)
const sending = ref(null)

async function load() {
  loading.value = true
  try {
    const data = await api.rendered()
    videos.value = data.videos
    dir.value = data.dir
    error.value = ''
  } catch (e) {
    error.value = `Couldn't reach the server: ${e.message}`
  } finally {
    loading.value = false
  }
}
onMounted(load)
useRefreshOnFocus(load)

function when(epoch) {
  const d = new Date(epoch * 1000)
  return d.toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}
</script>

<style scoped>
.page { max-width: 1100px; margin: 0 auto; padding: 32px 24px 64px; }
.head { display: flex; align-items: baseline; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }
.head h1 { margin: 0; font-size: 26px; color: var(--forest); }
.head p { margin: 0; }
.refresh.inline { width: auto; margin-left: auto; }
.notice { background: var(--paper); border: 1px solid var(--line); border-radius: var(--radius); padding: 16px; }
.list { display: flex; flex-direction: column; gap: 10px; }
.row {
  display: grid; grid-template-columns: 72px 1fr auto; gap: 16px; align-items: center;
  background: var(--paper); border-radius: var(--radius); box-shadow: var(--shadow); padding: 10px 14px;
}
.thumb {
  position: relative; width: 72px; aspect-ratio: 9 / 16; border: 0; padding: 0; border-radius: 8px;
  overflow: hidden; background: var(--stage); cursor: pointer;
}
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.dur {
  position: absolute; right: 3px; bottom: 3px; font-size: 10px; padding: 0 4px; border-radius: 3px;
  background: rgb(31 42 31 / 75%); color: var(--on-media); font-family: ui-monospace, monospace;
}
.info { min-width: 0; }
.name { font-weight: 700; font-size: 16px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sub { font-size: 13px; margin-top: 2px; }
.sub a { text-decoration: underline; }
.actions { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.player { width: min(480px, 100%); }
.player video { width: 100%; max-height: 72vh; background: var(--stage); border-radius: 8px; display: block; }
@media (max-width: 720px) {
  .row { grid-template-columns: 60px 1fr; }
  .actions { grid-column: 1 / -1; justify-content: flex-start; }
}
</style>
