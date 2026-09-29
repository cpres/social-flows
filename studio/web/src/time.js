// 75.25 -> "1:15.3"
export function fmtTime(s) {
  s = Math.max(0, s || 0)
  const m = Math.floor(s / 60)
  const sec = s - m * 60
  return `${m}:${sec.toFixed(1).padStart(4, '0')}`
}

// "1:15.5" | "75.5" -> 75.5 (NaN if unreadable)
export function parseTime(text) {
  const parts = String(text).trim().split(':')
  if (parts.some((p) => p === '' || isNaN(Number(p)))) return NaN
  return parts.reduce((acc, p) => acc * 60 + Number(p), 0)
}

// 2750 -> "45m 50s"
export function fmtDuration(s) {
  s = Math.round(s || 0)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h) return `${h}h ${m}m`
  if (m) return `${m}m ${sec}s`
  return `${sec}s`
}

// "2026-09-24" -> "Thu 24 Sep 2026"; anything else passes through
export function folderTitle(name) {
  const m = /^(\d{4})-(\d{2})-(\d{2})(.*)$/.exec(name)
  if (!m) return name
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  const date = d.toLocaleDateString(undefined, {
    weekday: 'short', day: 'numeric', month: 'short', year: 'numeric',
  })
  const rest = m[4].replace(/^[-_ ]+/, '')
  return rest ? `${date} · ${rest}` : date
}

export function clockTime(epochSeconds) {
  return new Date(epochSeconds * 1000).toLocaleTimeString(undefined, {
    hour: 'numeric', minute: '2-digit',
  })
}

export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))

// Keep a part inside its clip: at least 0.2s, never past the end.
export function fitRange(start, length, duration) {
  if (!(duration > 0)) return { start: Math.max(0, start), length: Math.max(0.2, length) }
  length = clamp(length, 0.2, duration)
  start = clamp(start, 0, duration - length)
  return { start: Math.round(start * 100) / 100, length: Math.round(length * 100) / 100 }
}

// Same rule as the engine: 30% in, not in the first 2s.
export function defaultStart(duration, length) {
  if (!(duration > 0)) return 0
  let s = duration * 0.3
  s = Math.max(Math.min(s, duration - 0.5), Math.min(2, duration / 3))
  return Math.round(Math.max(0, Math.min(s, duration - length)) * 100) / 100
}

const REEL_COLORS = ['#c0703a', '#4f7fa8', '#9a5fa0', '#c9a227', '#3f8f7a', '#b84d5f', '#6b6fc4', '#7a8f3a']
export const reelColor = (id) => REEL_COLORS[(id - 1) % REEL_COLORS.length]
