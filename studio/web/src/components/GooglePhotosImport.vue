<template>
  <div class="modal" @click.self="close">
    <div class="dialog gphotos">
      <div class="top">
        <div>
          <h2>Import from Google Photos</h2>
          <p class="muted">Pick what's in it in Google's own picker; it's downloaded into a shoot folder here.</p>
        </div>
        <button class="x" aria-label="Close" @click="close">×</button>
      </div>

      <p v-if="loading" class="muted">Checking Google Photos…</p>

      <!-- Not set up: say how, rather than fail. -->
      <section v-else-if="!status.configured" class="setup">
        <b>Google Photos needs a one-time setup first.</b>
        <ol>
          <li>In the <a href="https://console.cloud.google.com/" target="_blank" rel="noopener">Google Cloud console</a>,
            make a project and enable the <b>Photos Picker API</b>.</li>
          <li>Set up the <b>OAuth consent screen</b> (External, Testing) and add your Google account as a test user.</li>
          <li>Under Credentials, create an <b>OAuth client ID</b> of type <b>Desktop app</b>.</li>
          <li>Put its ID and secret in <span class="mono">.env</span> at the top of the repo:
            <pre class="mono">GOOGLE_CLIENT_ID=…apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=…</pre></li>
          <li>Restart the studio (<span class="mono">./studio/run.sh</span>) and come back here.</li>
        </ol>
        <p class="muted small">The README has the same steps under “Import from Google Photos”.</p>
      </section>

      <section v-else-if="!status.signedIn" class="signin">
        <p>Sign in once with the Google account your photos are in. It opens in a new tab and comes back here.</p>
        <button class="btn primary" @click="signIn">{{ signingIn ? 'Waiting for Google…' : 'Sign in with Google' }}</button>
        <small v-if="signingIn" class="muted">Finish in the other tab; this updates by itself.</small>
      </section>

      <template v-else>
        <!-- 1. what kind of reel this is -->
        <section>
          <div class="sh"><span class="step">1</span><b>What kind of reel is this?</b>
            <small class="muted">A starting point for New reel: everything there stays changeable.</small></div>
          <div class="styles">
            <button
              v-for="st in STYLES" :key="st.v" class="style" :class="{ active: style === st.v }" @click="style = st.v"
            >
              <span class="strip">
                <span v-for="(f, i) in st.frames" :key="i" class="mini" :class="f"><i></i><i></i></span>
              </span>
              <b>{{ st.label }}</b>
              <small>{{ st.hint }}</small>
            </button>
          </div>
        </section>

        <!-- 2. the album link, kept as a note -->
        <section>
          <div class="sh"><span class="step">2</span><b>Album link</b> <span class="muted small">(optional)</span></div>
          <div class="linkrow">
            <input v-model="albumLink" placeholder="https://photos.google.com/…/album/…" />
            <button class="btn small" :disabled="!linkOk" @click="openAlbum">Open ↗</button>
          </div>
          <small class="muted">Kept with the shoot for reference. Apps can't read an album from its link, so the
            picking happens in Google's picker, next.</small>
        </section>

        <!-- 3. pick in Google Photos -->
        <section>
          <div class="sh"><span class="step">3</span><b>Choose in Google Photos</b></div>
          <div v-if="!session" class="pickrow">
            <button class="btn primary" @click="pick">Choose in Google Photos…</button>
            <small class="muted">Opens Google's picker in a new tab. To take an album, open <b>Albums</b> there, then
              the album, and select its photos and videos (if the picker offers no "select all" for an
              album, click each one).</small>
          </div>
          <div v-else-if="!picked" class="pickrow">
            <span class="spinner" aria-hidden="true"></span>
            <span>Waiting for you to finish picking in the Google Photos tab…</span>
            <button class="link" @click="reopen">Open it again</button>
            <button class="link" @click="resetPick">Cancel</button>
          </div>
          <div v-else class="picked">
            <span><b>{{ picked.length }}</b> picked<template v-if="pickedCounts"> · {{ pickedCounts }}</template></span>
            <span v-if="already.length" class="dupnote">
              {{ already.length }} {{ already.length === 1 ? 'is' : 'are' }} already in Footage
              (in {{ alreadyIn }}) and won't be downloaded again.
            </span>
            <button class="link" @click="resetPick" :disabled="busy">Choose again</button>
          </div>
        </section>

        <!-- 4. where it goes -->
        <section v-if="picked && fresh.length">
          <div class="sh"><span class="step">4</span><b>Where should it go?</b></div>
          <ShootDestination
            :folders="folders" :root="root" v-model:mode="mode" v-model:date="newDate"
            v-model:label="newLabel" v-model:target="target" @enter="go"
          />
        </section>

        <!-- 5. downloading -->
        <section v-if="job" class="progress">
          <div class="bar"><i :style="{ width: `${pct}%` }"></i></div>
          <span class="muted small">
            {{ job.done }} of {{ job.total }} · {{ mb(job.bytes) }}<template v-if="job.failed.length">
              · {{ job.failed.length }} couldn't be downloaded</template>
          </span>
        </section>
      </template>

      <p v-if="failure" class="err">{{ failure }}</p>
      <p v-if="notice" class="ok">{{ notice }}</p>
      <div class="controls">
        <button v-if="status.signedIn && !busy" class="link small signout" @click="signOut">Sign out of Google</button>
        <span class="spacer"></span>
        <button class="btn" @click="close" :disabled="busy">{{ busy ? 'Downloading…' : 'Cancel' }}</button>
        <button class="btn primary" v-if="picked && fresh.length" :disabled="!canImport" @click="go">
          {{ busy ? 'Importing…' : `Import ${fresh.length} file${fresh.length === 1 ? '' : 's'}` }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
// Import from Google Photos: say what kind of reel it's for (Relay unless
// you pick another), pick in Google's picker (the Photos Picker API: an
// album's link can't be read by an app), then it's downloaded into a shoot
// folder. The shoot then opens New reel set up from that, still changeable.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { gphotos } from '../api'
import { STYLES } from '../reelStyles'
import { folderTitle } from '../time'
import ShootDestination, { folderNameOf } from './ShootDestination.vue'

const props = defineProps({
  folders: { type: Array, default: () => [] },
  root: { type: String, default: '' },
})
const emit = defineEmits(['close', 'imported'])

const loading = ref(true)
const status = ref({ configured: false, signedIn: false })
const failure = ref('')
const notice = ref('')

const style = ref('relay')
const albumLink = ref('')
const linkOk = computed(() => /^https:\/\/\S+$/.test(albumLink.value.trim()))
function openAlbum() { if (linkOk.value) window.open(albumLink.value.trim(), '_blank', 'noopener') }

// ---------------------------------------------------------------- signing in
const signingIn = ref(false)
let signTimer = null
function signIn() {
  window.open('/api/gphotos/auth', '_blank')
  signingIn.value = true
  clearInterval(signTimer)
  signTimer = setInterval(async () => {
    try {
      const s = await gphotos.status()
      if (s.signedIn) { status.value = s; signingIn.value = false; clearInterval(signTimer) }
    } catch { /* keep waiting */ }
  }, 2000)
}
async function signOut() {
  status.value = await gphotos.signOut()
  resetPick()
}

// ---------------------------------------------------------------- picking
const session = ref(null)   // { sessionId, pickerUri, pollSeconds, timeoutSeconds }
const picked = ref(null)    // [{ id, filename, kind, createTime, capturedAt, already }]
let pollTimer = null
let pickerTab = null

async function pick() {
  failure.value = ''
  // Opened now, while it's still a click: a tab opened after the wait is blocked.
  pickerTab = window.open('', '_blank')
  try {
    session.value = await gphotos.newSession()
    if (pickerTab) pickerTab.location = session.value.pickerUri
    else pickerTab = window.open(session.value.pickerUri, '_blank')
    poll(Date.now() + session.value.timeoutSeconds * 1000)
  } catch (e) {
    pickerTab?.close()
    failure.value = e.message
    if (/sign in/i.test(e.message)) status.value = await gphotos.status()
  }
}
function reopen() { if (session.value) pickerTab = window.open(session.value.pickerUri, '_blank') }
function poll(until) {
  clearTimeout(pollTimer)
  pollTimer = setTimeout(async () => {
    if (!session.value) return
    if (Date.now() > until) {
      failure.value = 'The Google Photos picker timed out. Choose again.'
      resetPick(false)
      return
    }
    try {
      const r = await gphotos.session(session.value.sessionId)
      if (r.ready) {
        picked.value = r.items
        setDate()
        return
      }
    } catch (e) {
      failure.value = e.message
    }
    poll(until)
  }, Math.max(2, session.value.pollSeconds || 5) * 1000)
}
function resetPick(clear = true) {
  clearTimeout(pollTimer)
  session.value = null
  picked.value = null
  if (clear) failure.value = ''
}

const already = computed(() => (picked.value || []).filter((i) => i.already))
const fresh = computed(() => (picked.value || []).filter((i) => !i.already))
const alreadyIn = computed(() => [...new Set(already.value.map((i) => folderTitle(i.already)))].join(', '))
const pickedCounts = computed(() => {
  const v = (picked.value || []).filter((i) => i.kind === 'video').length
  const p = (picked.value || []).length - v
  return [p && `${p} photo${p === 1 ? '' : 's'}`, v && `${v} video${v === 1 ? '' : 's'}`].filter(Boolean).join(', ')
})

// ---------------------------------------------------------------- where it goes
const mode = ref('new')
const newDate = ref('')
const newLabel = ref('')
const target = ref(props.folders[0]?.name || '')
const isoDay = (t) =>
  `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`
// The day the first of it was taken (not today: it may be weeks old).
function setDate() {
  const times = (fresh.value.length ? fresh.value : picked.value || []).map((i) => i.capturedAt).filter(Boolean)
  newDate.value = isoDay(times.length ? new Date(Math.min(...times) * 1000) : new Date())
}
const newName = computed(() => folderNameOf(newDate.value, newLabel.value))
const clash = computed(() => props.folders.some((f) => f.name === newName.value))
const destName = computed(() => (mode.value === 'new' ? newName.value : target.value))

// ---------------------------------------------------------------- importing
const job = ref(null)
const busy = ref(false)
const canImport = computed(() => !busy.value && !!fresh.value.length && !!destName.value
  && !(mode.value === 'new' && clash.value))
const pct = computed(() => (job.value?.total ? (100 * job.value.done) / job.value.total : 0))
const mb = (b) => `${(b / 1e6).toFixed(b > 1e8 ? 0 : 1)} MB`
let jobTimer = null

async function go() {
  if (!canImport.value) return
  busy.value = true
  failure.value = ''
  const folder = destName.value
  try {
    const r = await gphotos.importItems({
      sessionId: session.value.sessionId, folder, create: mode.value === 'new',
      intent: { style: style.value, target: null, albumLink: linkOk.value ? albumLink.value.trim() : '' },
    })
    job.value = { done: 0, total: r.total, bytes: 0, failed: [] }
    await follow(r.job)
  } catch (e) {
    failure.value = e.message
    busy.value = false
  }
}

function follow(id) {
  return new Promise((resolve) => {
    const tick = async () => {
      try {
        const j = await gphotos.importState(id)
        job.value = j
        if (!j.finished) { jobTimer = setTimeout(tick, 700); return }
        busy.value = false
        if (j.failed.length) failure.value = j.failed.map((f) => `${f.name}: ${f.error}`).join('\n')
        if (j.error) failure.value = [failure.value, j.error].filter(Boolean).join('\n')
        if (j.imported.length) {
          emit('imported', { folder: j.folder, imported: j.imported, content: j.content, intent: style.value })
        } else if (!j.failed.length) {
          notice.value = 'Everything picked is already in Footage.'
        }
        resolve()
      } catch (e) {
        failure.value = e.message
        jobTimer = setTimeout(tick, 2000)
      }
    }
    tick()
  })
}

function close() { if (!busy.value) emit('close') }
const onKey = (e) => { if (e.key === 'Escape') close() }

onMounted(async () => {
  window.addEventListener('keydown', onKey)
  try {
    status.value = await gphotos.status()
  } catch (e) {
    failure.value = `Couldn't reach the studio: ${e.message}`
  } finally {
    loading.value = false
  }
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  clearInterval(signTimer)
  clearTimeout(pollTimer)
  clearTimeout(jobTimer)
})
</script>

<style scoped>
.gphotos { width: min(880px, 100%); display: flex; flex-direction: column; gap: 16px; }
.top { display: flex; align-items: flex-start; gap: 12px; }
.top > div { flex: 1; min-width: 0; }
.top h2 { margin: 0; }
.top p { margin: 2px 0 0; font-size: 13px; }
.x {
  border: 0; background: transparent; font-size: 26px; line-height: 1; cursor: pointer;
  color: var(--muted); padding: 0 4px;
}
.x:hover { color: var(--ink); }
section { display: flex; flex-direction: column; gap: 8px; }
.step {
  display: inline-grid; place-items: center; width: 20px; height: 20px; align-self: center; flex: none; border-radius: 50%;
  background: var(--sage); color: var(--on-sage); font-size: 12px; font-weight: 700;
}
.sh { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.sh b { color: var(--forest); }
.setup, .signin { padding: 14px 16px; border-radius: var(--radius); background: var(--sage-soft); }
.setup ol { margin: 4px 0 0; padding-left: 20px; display: flex; flex-direction: column; gap: 4px; }
.setup pre { margin: 6px 0 0; padding: 8px 10px; border-radius: 8px; background: var(--paper); font-size: 12px; }
.signin p { margin: 0; }
.signin .btn { align-self: flex-start; }
.styles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.style {
  display: flex; flex-direction: column; align-items: flex-start; gap: 6px; padding: 12px; text-align: left;
  border: 1px solid var(--line); border-radius: var(--radius); background: transparent; color: inherit; font: inherit; cursor: pointer;
}
.style small { color: var(--muted); font-size: 12px; line-height: 1.35; }
.style.active { border-color: var(--sage); background: var(--sage-soft); }
.strip { display: flex; gap: 4px; }
.mini { display: flex; flex-direction: column; gap: 2px; width: 14px; height: 24px; }
.mini i { flex: 1; border-radius: 2px; }
.mini.b i:first-child { background: #e9b27a; } .mini.b i:last-child { display: none; }
.mini.a1 i:first-child { background: #b8cfa8; } .mini.a1 i:last-child { display: none; }
.mini.ab i:first-child { background: #b8cfa8; } .mini.ab i:last-child { background: #e9b27a; }
.linkrow { display: flex; gap: 8px; }
.linkrow input { flex: 1; min-width: 0; }
.pickrow { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.pickrow small { flex: 1; min-width: 260px; }
.picked { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.dupnote { padding: 4px 10px; font-size: 13px; border-radius: 8px; background: var(--sage-soft); }
.spinner {
  width: 16px; height: 16px; border-radius: 50%; border: 2px solid var(--sage); border-top-color: transparent;
  animation: spin 0.9s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.progress { gap: 4px; }
.bar { height: 8px; border-radius: 999px; background: var(--line); overflow: hidden; }
.bar i { display: block; height: 100%; background: var(--sage); transition: width 0.3s; }
.link {
  border: 0; background: none; padding: 0; color: var(--forest); font-weight: 600;
  cursor: pointer; font-size: 13px; text-decoration: underline; text-underline-offset: 2px;
}
.small { font-size: 12px; }
.err { color: var(--danger); white-space: pre-line; margin: 0; }
.ok { margin: 0; color: var(--forest); font-weight: 600; }
.controls { display: flex; align-items: center; gap: 8px; }
.signout { color: var(--muted); }
</style>
