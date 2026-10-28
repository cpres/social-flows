const enc = encodeURIComponent

async function json(res) {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || res.statusText)
  }
  return res.json()
}

const send = (method, url, body) =>
  fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then(json)

export const api = {
  home: () => fetch('/api/folders').then(json),
  folder: (name) => fetch(`/api/folders/${enc(name)}`).then(json),
  folderToReel: (name, reelName) => send('POST', `/api/folders/${enc(name)}/to-reel`, { name: reelName }),
  // Move files to another shoot folder: { files, to, create } -> { folder, moved, failed, emptied }.
  moveFiles: (name, body) => send('POST', `/api/folders/${enc(name)}/move`, body),

  reels: () => fetch('/api/reels').then(json),
  reel: (id) => fetch(`/api/reels/${id}`).then(json),
  createReel: (name) => send('POST', '/api/reels', { name }),
  updateReel: (id, patch) => send('PATCH', `/api/reels/${id}`, patch),
  deleteReel: (id) => send('DELETE', `/api/reels/${id}`),
  reorder: (id, itemIds) => send('PUT', `/api/reels/${id}/order`, { itemIds }),
  exportReel: (id) => send('POST', `/api/reels/${id}/export`),
  // The title or end card drawn over a frame of the reel: a blob URL to show.
  cardPreview: (id, kind) => fetch(`/api/reels/${id}/card/${kind}`).then(async (res) => {
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText)
    return URL.createObjectURL(await res.blob())
  }),
  render: (id) => send('POST', `/api/reels/${id}/render`),
  lastRender: (id) => fetch(`/api/reels/${id}/render`).then(json),
  renderStatus: (jobId) => fetch(`/api/renders/${jobId}`).then(json),
  renderVideo: (jobId) => `/api/renders/${jobId}/video`,
  reveal: (jobId) => send('POST', `/api/renders/${jobId}/reveal`),

  // Every finished video in the renders folder (survives restarts).
  rendered: () => fetch('/api/rendered').then(json),
  renderedFile: (name) => `/api/rendered/${enc(name)}/file`,
  renderedThumb: (name, v = '') => `/api/rendered/${enc(name)}/thumb?v=${v}`,
  revealRendered: (name) => send('POST', `/api/rendered/${enc(name)}/reveal`),
  shareRendered: (name) => send('POST', `/api/rendered/${enc(name)}/share`),
  duplicateReel: (id, name) => send('POST', `/api/reels/${id}/duplicate`, { name }),
  music: () => fetch('/api/music').then(json),
  musicBeats: (name) => fetch(`/api/music/${enc(name)}/beats`).then(json),
  musicFile: (name) => `/api/music/${enc(name)}/file`,
  // Name a song and put it in categories: { title, artist, categories }; returns the shelf.
  saveSong: (name, info) => send('PUT', `/api/music/${enc(name)}/info`, info),

  // The part of a file picked in its shoot, kept until it's changed (see db.py).
  savePick: (mediaId, pick) => send('PUT', `/api/media/${mediaId}/pick`, pick),
  deletePick: (mediaId) => send('DELETE', `/api/media/${mediaId}/pick`),
  addItem: (reelId, item) => send('POST', `/api/reels/${reelId}/items`, item),
  updateItem: (id, patch) => send('PATCH', `/api/items/${id}`, patch),
  deleteItem: (id) => send('DELETE', `/api/items/${id}`),
  // Replace a reel's parts with this list, in order (Weave).
  saveItems: (reelId, items) => send('PUT', `/api/reels/${reelId}/items`, { items }),
  // How much happens along a clip: { points: [[seconds, 0..1], ...] }.
  activity: (folder, file) => fetch(`/api/activity/${enc(folder)}/${enc(file)}`).then(json),
  // Weave's draft for a shoot ({ folder }) or a reel being re-woven ({ reel }).
  weaveDraft: (q) => fetch(`/api/weave/draft?${new URLSearchParams(q)}`).then(json),
  // keepalive: a save sent as the page closes still arrives.
  saveWeaveDraft: (body) => fetch('/api/weave/draft', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), keepalive: true,
  }).then(json),
  deleteWeaveDraft: (q) => send('DELETE', `/api/weave/draft?${new URLSearchParams(q)}`),
  // What's in these photos, for Smart hold: { detects, looks: { mediaId: { people, animals, look } } }.
  looks: (mediaIds) => send('POST', '/api/looks', { mediaIds }),

  // AirDropped files waiting in ~/Downloads, and moving them into a shoot.
  importList: () => fetch('/api/import').then(json),
  importThumb: (file, w = 320) => `/api/import/thumb/${enc(file)}?w=${w}`,
  importFiles: (body) => send('POST', '/api/import', body),
  importMusic: (files) => send('POST', '/api/import/music', { files }),

  // A voice track's takes: recordings in the shoot folders, and what's said in them.
  voiceFolders: () => fetch('/api/voice/folders').then(json),
  voiceTakes: (folder) => fetch(`/api/voice/takes/${enc(folder)}`).then(json),
  voiceAudio: (folder, file) => `/api/voice/audio/${enc(folder)}/${enc(file)}`,
  voicePeaks: (folder, file) => fetch(`/api/voice/peaks/${enc(folder)}/${enc(file)}`).then(json),
  transcribe: (folder, file) => send('POST', `/api/voice/transcribe/${enc(folder)}/${enc(file)}`),
  transcript: (folder, file) => fetch(`/api/voice/transcript/${enc(folder)}/${enc(file)}`).then(json),
  // Time pasted text to a stretch of a take: { folder, file, start, end, text } -> { lines }.
  alignText: (body) => send('POST', '/api/voice/align', body),
  voiceDownloads: () => fetch('/api/voice/downloads').then(json),
  importVoice: (file, folder) => send('POST', '/api/voice/import', { file, folder }),
  // The captions at reel time t over the frame of `item` at `src`, as the render draws them.
  captionPreview: (id, item, src, t) => fetch(`/api/reels/${id}/captions/preview?item=${item}&src=${src.toFixed(2)}&t=${t.toFixed(2)}`)
    .then(async (res) => {
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText)
      return URL.createObjectURL(await res.blob())
    }),

  media: (folder, file) => `/api/media/${enc(folder)}/${enc(file)}`,
  thumb: (folder, file, t = 0, w = 480) =>
    `/api/thumb/${enc(folder)}/${enc(file)}?t=${Math.max(0, t).toFixed(1)}&w=${w}`,
}

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
