// Weave: cut each clip into a few parts and interleave them, so several
// things seem to happen at once (1a 2a 3a ▣ 1b 2b ▣ 1c 2c …).
//
// A clip in the wizard is { mediaId, media, kind, on, parts: [{ id?, start,
// beats?, length? }], auto, focusX, focusY, zoom, framed }. A part is as long
// as the pace unless it was given its own length: beats on the beat, else
// seconds.

import { clamp, defaultStart } from './time'

export const SECONDS_PER_PART = 30   // a long clip gets about one part per 30s…
export const MIN_PARTS = 2           // …at least two…
export const MAX_PARTS = 6           // …and no more than six

const round2 = (t) => Math.round(t * 100) / 100
// len below is one length for every window, or one per window.
const lenAt = (len, j) => (Array.isArray(len) ? len[j] : len)

// The stretch worth cutting from: not the first 2s (the camera settling) or
// the last half second. Same rule as the engine's default start.
export function usable(duration) {
  const lo = Math.min(2, duration / 3)
  return [lo, Math.max(lo, duration - 0.5)]
}

// How many parts a clip gets: one if it isn't longer than splitOver, else
// about one per 30s of footage, as many as fit without overlapping.
export function autoParts(duration, splitOver, len) {
  if (!(duration > splitOver)) return 1
  const [lo, hi] = usable(duration)
  const fits = Math.max(1, Math.floor((hi - lo) / len))
  return Math.min(clamp(Math.round(duration / SECONDS_PER_PART), MIN_PARTS, MAX_PARTS), fits)
}

// Keep a clip's windows in order and apart where there's room: each starts
// after the one before it ends, and none runs past the end of the clip.
export function settle(starts, len, duration) {
  const s = starts.map((t, j) => clamp(t, 0, Math.max(0, duration - lenAt(len, j))))
  for (let j = 1; j < s.length; j++) s[j] = Math.max(s[j], s[j - 1] + lenAt(len, j - 1))
  for (let j = s.length - 1; j >= 0; j--) {
    const next = (j + 1 < s.length ? s[j + 1] : duration) - lenAt(len, j)
    s[j] = Math.max(0, Math.min(s[j], next))
  }
  return s.map(round2)
}

// n windows spread evenly over the usable stretch; a single one goes where
// the engine would cut by default (30% in).
export function spreadStarts(duration, n, len) {
  if (n <= 1) return [defaultStart(duration, lenAt(len, 0))]
  const [lo, hi] = usable(duration)
  const starts = Array.from({ length: n }, (_, j) => lo + ((hi - lo) * (j + 0.5)) / n - lenAt(len, j) / 2)
  return settle(starts, len, duration)
}

// Each window on the busiest stretch of its share of the clip. points are
// [seconds, 0..1] from the server's movement measure. The window starts a
// little before the peak, so the action lands inside it. Of stretches about
// as busy as the busiest, the one nearest where the window was (fallback)
// wins, and a share where nothing much moves keeps its window there.
const STILL = 0.05
export function busyStarts(points, duration, n, len, fallback) {
  if (!points?.length) return fallback
  const [lo, hi] = usable(duration)
  const step = (hi - lo) / n
  const starts = []
  for (let j = 0; j < n; j++) {
    const l = lenAt(len, j)
    const a = lo + j * step
    const b = Math.max(a, a + step - l)
    const options = points.filter(([t]) => t >= a && t <= a + step).map(([t]) => {
      const s = clamp(t - l / 3, a, b)
      const inside = points.filter(([u]) => u >= s && u <= s + l)
      return { s, score: inside.length ? inside.reduce((acc, [, v]) => acc + v, 0) / inside.length : 0 }
    })
    const top = Math.max(0, ...options.map((o) => o.score))
    const near = (o) => Math.abs(o.s - fallback[j])
    const best = options.filter((o) => o.score >= top * 0.9).sort((x, y) => near(x) - near(y))[0]
    starts.push(best && top > STILL ? best.s : fallback[j])
  }
  return settle(starts, len, duration)
}

export const letter = (j) => String.fromCharCode(97 + j)   // 0 -> a
export const partKey = (mediaId, j) => `${mediaId}:${j}`

// The woven order. Rounds = the most parts any clip has; each clip's parts
// are spread evenly across them, so every clip appears in the first round and
// ends in the last. Photos, in order, go in the gaps after rounds, the last
// one closing the reel; photos next to each other with the same groupOf (a
// burst of look-alikes) stay together in one gap. A softer transition
// (`between`) marks each gap.
//
// Returns [{ key, clip, part, j, label, number, round, kind, transition }].
export function weave(clips, between = 'dissolve', groupOf = (c) => c.mediaId) {
  const on = clips.filter((c) => c.on)
  const videos = on.filter((c) => c.kind === 'video' && c.parts.length)
  const photos = on.filter((c) => c.kind === 'photo')
  const R = Math.max(1, ...videos.map((v) => v.parts.length))
  const rounds = Array.from({ length: R }, () => [])
  videos.forEach((v, vi) => {
    const n = v.parts.length
    v.parts.forEach((part, j) => {
      const r = n === 1 ? 0 : Math.round((j * (R - 1)) / (n - 1))
      rounds[r].push({ key: partKey(v.mediaId, j), clip: v, part, j, number: vi + 1,
                       label: `${vi + 1}${letter(j)}`, round: r + 1, kind: 'video' })
    })
  })
  const units = []
  photos.forEach((p) => {
    const g = groupOf(p)
    if (units.length && units[units.length - 1].g === g) units[units.length - 1].photos.push(p)
    else units.push({ g, photos: [p] })
  })
  const gaps = Array.from({ length: R }, () => [])
  units.forEach((u, k) => {
    const g = clamp(Math.round(((k + 1) * R) / units.length) - 1, 0, R - 1)
    for (const p of u.photos) {
      gaps[g].push({ key: String(p.mediaId), clip: p, part: null, j: 0, number: 0,
                     label: '▣', round: g + 1, kind: 'photo' })
    }
  })
  // Rounds and photo gaps take turns; the last entry of each group leads into
  // the next with the softer transition. A round that would open with the
  // clip the last one ended on starts with its next clip instead, so the
  // same shot doesn't play twice in a row when it can be helped.
  const groups = []
  for (let r = 0; r < R; r++) groups.push(rounds[r], gaps[r])
  const out = []
  for (const g of groups.filter((x) => x.length)) {
    if (g.length > 1 && g[0].clip === out[out.length - 1]?.clip) g.push(g.shift())
    g.forEach((e, i) => out.push({ ...e, transition: i === g.length - 1 ? between : '' }))
  }
  if (out.length) out[out.length - 1].transition = ''
  return out
}

// Put a woven sequence in the order the user dragged it into (keys), as long
// as it holds the same entries; otherwise the woven order stands.
export function inOrder(seq, keys) {
  if (!keys || keys.length !== seq.length) return seq
  const byKey = new Map(seq.map((e) => [e.key, e]))
  if (!keys.every((k) => byKey.has(k))) return seq
  return keys.map((k) => byKey.get(k))
}

// Rebuild the wizard's clips from a reel made with Weave, so it can be
// reopened: parts grouped by clip in start order, keeping their ids, and the
// lengths of any that aren't the reel's pace (pace: { beatSync, beatsPerCut,
// len }), so they stay that long. A photo keeps its hold as a hold set by
// hand when it isn't what Weave last saved for it (weave.holds; a reel saved
// before Weave kept those keeps every photo's hold), so changes made in the
// reel come back.
// Returns { clips (in the saved order), keys (the reel's order), transitions }.
export function fromReel(items, weaveSettings, pace) {
  const own = (it) => {
    if (pace.beatSync) return it.beats && it.beats !== pace.beatsPerCut ? { beats: it.beats, length: it.length } : {}
    return Math.abs(it.length - pace.len) > 0.05 ? { length: it.length } : {}
  }
  const holds = weaveSettings?.holds
  const holdOf = (it) => {
    const beats = it.beats || pace.beatsPerCut
    const was = holds?.[it.mediaId]
    if (holds && was !== undefined && Math.abs((pace.beatSync ? beats : it.length) - was) < 0.01) return undefined
    return pace.beatSync ? { beats, length: it.length } : { length: it.length }
  }
  const byMedia = new Map()
  for (const it of items) {
    if (!byMedia.has(it.mediaId)) byMedia.set(it.mediaId, [])
    byMedia.get(it.mediaId).push(it)
  }
  const saved = (weaveSettings?.clips || []).filter((m) => byMedia.has(m))
  const order = [...saved, ...[...byMedia.keys()].filter((m) => !saved.includes(m))]
  const clips = order.map((mediaId) => {
    const its = byMedia.get(mediaId).sort((a, b) => a.start - b.start)
    const first = its[0]
    return {
      mediaId, media: first.media, kind: first.media.kind, on: true, auto: false, placed: true, framed: false,
      parts: first.media.kind === 'video' ? its.map((it) => ({ id: it.id, start: it.start, ...own(it) })) : [],
      id: first.media.kind === 'photo' ? first.id : undefined,
      hold: first.media.kind === 'photo' ? holdOf(first) : undefined,
      focusX: first.focusX, focusY: first.focusY, zoom: first.zoom || 1,
    }
  })
  // The reel's own order and transitions, keyed like weave()'s entries.
  const keys = []
  const transitions = {}
  for (const it of items) {
    const c = clips.find((x) => x.mediaId === it.mediaId)
    const key = c.kind === 'video' ? partKey(it.mediaId, c.parts.findIndex((p) => p.id === it.id)) : String(it.mediaId)
    keys.push(key)
    transitions[key] = it.transition || ''
  }
  return { clips, keys, transitions }
}
