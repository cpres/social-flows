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

  reels: () => fetch('/api/reels').then(json),
  reel: (id) => fetch(`/api/reels/${id}`).then(json),
  createReel: (name) => send('POST', '/api/reels', { name }),
  updateReel: (id, patch) => send('PATCH', `/api/reels/${id}`, patch),
  deleteReel: (id) => send('DELETE', `/api/reels/${id}`),
  reorder: (id, itemIds) => send('PUT', `/api/reels/${id}/order`, { itemIds }),
  exportReel: (id) => send('POST', `/api/reels/${id}/export`),
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
