import { lowMade, lowQuality } from './quality'

// ---- Plumbing ---------------------------------------------------------------

// A URL with every interpolated value encoded: path`/api/music/${name}/file`.
const path = (strings, ...values) =>
  strings.reduce((out, s, i) => out + encodeURIComponent(values[i - 1]) + s)

// `url` with a query string from `params`, leaving out undefined values.
const withQuery = (url, params) => {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined))
  return `${url}?${q}`
}

// The server's `detail` for a failed request, else its status text.
async function fail(res) {
  const body = await res.json().catch(() => ({}))
  throw new Error(body.detail || res.statusText)
}

const json = (res) => (res.ok ? res.json() : fail(res))
// An image response as a blob URL to show.
const blobUrl = async (res) => (res.ok ? URL.createObjectURL(await res.blob()) : fail(res))

const get = (url) => fetch(url).then(json)
const send = (method, url, body, init = {}) =>
  fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    ...init,
  }).then(json)

// ---- Endpoints --------------------------------------------------------------

export const api = {
  // Shoot folders.
  home: () => get('/api/folders'),
  folder: (name) => get(path`/api/folders/${name}`),
  folderToReel: (name, reelName, opts = {}) => send('POST', path`/api/folders/${name}/to-reel`, { name: reelName, ...opts }),
  // A Relay reel from a folder at each dial setting: { photo, cap, quiet } -> { plans: [{ dial, stats, bar }], approx }.
  relayPlan: (name, opts = {}) => send('POST', path`/api/folders/${name}/relay-plan`, opts),
  // Move files to another shoot folder: { files, to, create } -> { folder, moved, failed, emptied }.
  moveFiles: (name, body) => send('POST', path`/api/folders/${name}/move`, body),
  // Delete files (to the Trash): { files } -> { deleted, failed, parts, emptied }.
  deleteFiles: (name, files) => send('POST', path`/api/folders/${name}/delete`, { files }),

  // Reels.
  reels: () => get('/api/reels'),
  reel: (id) => get(path`/api/reels/${id}`),
  createReel: (name) => send('POST', '/api/reels', { name }),
  updateReel: (id, patch) => send('PATCH', path`/api/reels/${id}`, patch),
  deleteReel: (id) => send('DELETE', path`/api/reels/${id}`),
  duplicateReel: (id, name) => send('POST', path`/api/reels/${id}/duplicate`, { name }),
  // The name a new reel would get: this one, or its next "take N" if it's taken.
  freeReelName: (name) => get(withQuery('/api/reel-name', { name })),
  reorder: (id, itemIds) => send('PUT', path`/api/reels/${id}/order`, { itemIds }),
  exportReel: (id) => send('POST', path`/api/reels/${id}/export`),
  // The title or end card drawn over a frame of the reel: a blob URL to show.
  cardPreview: (id, kind) => fetch(path`/api/reels/${id}/card/${kind}`).then(blobUrl),
  // The captions at reel time t over the frame of `item` at `src`, as the render draws them.
  captionPreview: (id, item, src, t) =>
    fetch(withQuery(path`/api/reels/${id}/captions/preview`, { item, src: src.toFixed(2), t: t.toFixed(2) })).then(blobUrl),
  // Make low-quality copies of a reel's videos: -> { ready, total }.
  lowCopies: (reelId) => send('POST', path`/api/reels/${reelId}/low-copies`),

  // A reel's parts.
  addItem: (reelId, item) => send('POST', path`/api/reels/${reelId}/items`, item),
  updateItem: (id, patch) => send('PATCH', path`/api/items/${id}`, patch),
  deleteItem: (id) => send('DELETE', path`/api/items/${id}`),
  // Replace a reel's parts with this list, in order (Weave).
  saveItems: (reelId, items) => send('PUT', path`/api/reels/${reelId}/items`, { items }),
  // Plan a relay reel again around parts taken out, added or trimmed: -> { ok, stats }.
  restitch: (reelId) => send('POST', path`/api/reels/${reelId}/restitch`),

  // Rendering.
  render: (id) => send('POST', path`/api/reels/${id}/render`),
  lastRender: (id) => get(path`/api/reels/${id}/render`),
  renderStatus: (jobId) => get(path`/api/renders/${jobId}`),
  renderVideo: (jobId) => path`/api/renders/${jobId}/video`,
  reveal: (jobId) => send('POST', path`/api/renders/${jobId}/reveal`),
  // Every finished video in the renders folder (survives restarts).
  rendered: () => get('/api/rendered'),
  renderedFile: (name) => path`/api/rendered/${name}/file`,
  renderedThumb: (name, v = '') => withQuery(path`/api/rendered/${name}/thumb`, { v }),
  revealRendered: (name) => send('POST', path`/api/rendered/${name}/reveal`),
  shareRendered: (name) => send('POST', path`/api/rendered/${name}/share`),

  // Media files.
  media: (folder, file) => {
    const url = path`/api/media/${folder}/${file}`
    return lowQuality.value && lowMade.has(`${folder}/${file}`) ? `${url}?q=low` : url
  },
  thumb: (folder, file, t = 0, w = 480) =>
    withQuery(path`/api/thumb/${folder}/${file}`, { t: Math.max(0, t).toFixed(1), w }),
  // The part of a file picked in its shoot, kept until it's changed (see db.py).
  savePick: (mediaId, pick) => send('PUT', path`/api/media/${mediaId}/pick`, pick),
  deletePick: (mediaId) => send('DELETE', path`/api/media/${mediaId}/pick`),
  // Dragged to another spot in its shoot: the time it's taken as from now on (null: its own) -> the file.
  moveInShoot: (mediaId, at) => send('PUT', path`/api/media/${mediaId}/moved`, { at }),
  // A clip's highlights: moments pinned on it, in seconds (see Weave's Moments).
  saveHighlights: (mediaId, highlights, amount) => send('PUT', path`/api/media/${mediaId}/highlights`,
    amount === undefined ? { highlights } : { highlights, amount }),
  // A long clip's highlights, how much of it is wanted, and its suggested moments.
  moments: (mediaId) => get(path`/api/media/${mediaId}/moments`),
  // How much happens along a clip: { points: [[seconds, 0..1], ...] }.
  activity: (folder, file) => get(path`/api/activity/${folder}/${file}`),
  // How loud each video is along its length (audio.py): { mediaId: { step, db: [dBFS], duration, hasAudio } }.
  envelopes: (mediaIds) => send('POST', '/api/envelopes', { mediaIds }),
  // What's in these photos, for Smart hold: { detects, looks: { mediaId: { people, animals, look } } }.
  looks: (mediaIds) => send('POST', '/api/looks', { mediaIds }),

  // Music.
  music: () => get('/api/music'),
  musicBeats: (name) => get(path`/api/music/${name}/beats`),
  musicFile: (name) => path`/api/music/${name}/file`,
  musicEnvelope: (name) => get(path`/api/music/${name}/envelope`),
  musicStyle: (name) => get(path`/api/music/${name}/style`),
  // Name a song and put it in categories: { title, artist, categories }; returns the shelf.
  saveSong: (name, info) => send('PUT', path`/api/music/${name}/info`, info),
  // AI music for a reel (compose.py): the plan (length, arc, prompt), then the track.
  composePlan: (id, body) => send('POST', path`/api/reels/${id}/compose/plan`, body),
  compose: (id, body) => send('POST', path`/api/reels/${id}/compose`, body),

  // The beat builder: the reel's length at a tempo, and a song's measured style.
  beatLength: (reelId, bpm) => get(withQuery(path`/api/reels/${reelId}/beat/length`, { bpm })),
  beatPreview: (reelId) => get(path`/api/reels/${reelId}/beat/preview`),
  beatGenerate: (reelId, body = {}) => send('POST', path`/api/reels/${reelId}/beat/generate`, body),
  beatJob: (jobId) => get(path`/api/beat/jobs/${jobId}`),
  beatLastJob: (reelId) => get(path`/api/reels/${reelId}/beat/job`),
  beatTakes: (reelId) => get(path`/api/reels/${reelId}/beat/takes`),
  beatTakeAudio: (reelId, take) => path`/api/reels/${reelId}/beat/takes/${take}/audio`,
  beatTakeEnvelope: (reelId, take) => get(path`/api/reels/${reelId}/beat/takes/${take}/envelope`),
  beatUse: (reelId, take) => send('POST', path`/api/reels/${reelId}/beat/takes/${take}/use`),
  beatStar: (reelId, take, starred) => send('POST', path`/api/reels/${reelId}/beat/takes/${take}/star`, { starred }),
  beatDelete: (reelId, take) => send('DELETE', path`/api/reels/${reelId}/beat/takes/${take}`),
  beatAdapts: () => get('/api/beat/adapts'),
  beatInstruments: () => get('/api/beat/instruments'),
  beatStyles: () => get('/api/beat/styles'),
  beatVoices: () => get('/api/beat/voices'),

  // Weave's draft for a shoot ({ folder }) or a reel being re-woven ({ reel }).
  weaveDraft: (q) => get(withQuery('/api/weave/draft', q)),
  // keepalive: a save sent as the page closes still arrives.
  saveWeaveDraft: (body) => send('PUT', '/api/weave/draft', body, { keepalive: true }),
  deleteWeaveDraft: (q) => send('DELETE', withQuery('/api/weave/draft', q)),

  // AirDropped files waiting in ~/Downloads, and moving them into a shoot.
  importList: () => get('/api/import'),
  importThumb: (file, w = 320) => withQuery(path`/api/import/thumb/${file}`, { w }),
  importFiles: (body) => send('POST', '/api/import', body),
  importMusic: (files) => send('POST', '/api/import/music', { files }),

  // A voice track's takes: recordings in the shoot folders, and what's said in them.
  voiceFolders: () => get('/api/voice/folders'),
  voiceTakes: (folder) => get(path`/api/voice/takes/${folder}`),
  voiceAudio: (folder, file) => path`/api/voice/audio/${folder}/${file}`,
  voicePeaks: (folder, file) => get(path`/api/voice/peaks/${folder}/${file}`),
  voiceEnvelope: (folder, file) => get(path`/api/voice/envelope/${folder}/${file}`),
  transcribe: (folder, file, again = false) => {
    const url = path`/api/voice/transcribe/${folder}/${file}`
    return send('POST', again ? `${url}?again=true` : url)
  },
  transcript: (folder, file) => get(path`/api/voice/transcript/${folder}/${file}`),
  // Time pasted text to a stretch of a take: { folder, file, start, end, text } -> { lines }.
  alignText: (body) => send('POST', '/api/voice/align', body),
  voiceDownloads: () => get('/api/voice/downloads'),
  // Recordings from Downloads into the Voice folder, for a reading (or none); they start transcribing.
  importVoice: (files, readingId = null) => send('POST', '/api/voice/import', { files, readingId }),
  tagTake: (folder, file, readingId) => send('PUT', '/api/voice/tag', { folder, file, readingId }),
  // Readings: voice tracks that reels use (several reels can share one).
  readings: () => get('/api/readings'),
  createReading: (body) => send('POST', '/api/readings', body),
  saveReading: (id, body) => send('PUT', path`/api/readings/${id}`, body),
  deleteReading: (id) => send('DELETE', path`/api/readings/${id}`),
}

// Google Photos, through Google's own picker (gphotos.py): sign-in, a picking
// session, and downloading what was picked into a shoot folder.
export const gphotos = {
  status: () => get('/api/gphotos/status'),                          // -> { configured, signedIn }
  signOut: () => send('POST', '/api/gphotos/signout'),
  newSession: () => send('POST', '/api/gphotos/session'),            // -> { sessionId, pickerUri, pollSeconds, timeoutSeconds }
  session: (id) => get(path`/api/gphotos/session/${id}`),            // -> { ready, items }
  // { sessionId, folder, create, intent: { style, target, albumLink } } -> { job, total, skipped }
  importItems: (body) => send('POST', '/api/gphotos/import', body),
  importState: (job) => get(path`/api/gphotos/import/${job}`),
}

// ---- Helpers ----------------------------------------------------------------

// Saves the latest patch for each key after a short pause, so dragging a
// handle doesn't send a request per pixel.
export function debouncedSaver(save, wait = 400) {
  const timers = new Map()
  const pending = new Map()
  const flush = (key) => {
    clearTimeout(timers.get(key))
    timers.delete(key)
    const patch = pending.get(key)
    pending.delete(key)
    return patch ? save(key, patch) : Promise.resolve()
  }
  return {
    queue(key, patch) {
      pending.set(key, { ...(pending.get(key) || {}), ...patch })
      clearTimeout(timers.get(key))
      timers.set(key, setTimeout(() => flush(key), wait))
    },
    flushAll: () => Promise.all([...pending.keys()].map(flush)),
  }
}
