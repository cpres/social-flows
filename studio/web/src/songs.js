import { fmtDuration } from './time'

// How a song shows in a list: "Bass Instrumental Soft — Pietix · 2m 45s · 92 bpm"
export function songLabel(t) {
  return `${t.title || t.name}${t.artist ? ` — ${t.artist}` : ''}${t.duration ? ` · ${fmtDuration(t.duration)}` : ''}`
    + `${t.bpm ? ` · ${Math.round(t.bpm)} bpm` : ''}`
}

// A reel's song by its name, when the music folder has it; else the file name.
export function songTitle(shelf, name) {
  const t = shelf.tracks.find((x) => x.name === name)
  return t?.title || String(name).replace(/\.[^.]+$/, '').replace(/^.*\//, '')
}
