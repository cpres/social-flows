const enc = encodeURIComponent

async function json(res) {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || res.statusText)
  }
  return res.json()
}

export const api = {
  folders: () => fetch('/api/folders').then(json),
  folder: (name) => fetch(`/api/folders/${enc(name)}`).then(json),
  save: (name, body) =>
    fetch(`/api/folders/${enc(name)}/selections`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(json),
  exportFolder: (name) => fetch(`/api/folders/${enc(name)}/export`, { method: 'POST' }).then(json),
  media: (name, file) => `/api/media/${enc(name)}/${enc(file)}`,
  thumb: (name, file, t = 0, w = 480) =>
    `/api/thumb/${enc(name)}/${enc(file)}?t=${Math.max(0, t).toFixed(1)}&w=${w}`,
}
