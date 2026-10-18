// Smart hold: how long each part of a reel stays on screen, from what's in it.
//
//   clip    a part of a video: the pace length, and the longest
//   medium  a photo with people or animals in it
//   small   a photo with neither, which reads at a glance
//   burst   look-alike photos shot together: each one flicks by
//
// On the beat, each style is a smaller share of a clip's beats (½, ¼, ⅛ of
// them) but never so short it can't be seen, and a run of photos ends on a
// whole beat, so the cuts after it are still on the beat.

import { clamp } from './time'

export const STYLES = {
  clip: { label: 'Clip', icon: '▶', hint: 'a part of a clip: the longest' },
  medium: { label: 'Medium', icon: '◉', hint: 'people or animals in it' },
  small: { label: 'Small', icon: '○', hint: 'no people or animals: quicker' },
  burst: { label: 'Burst', icon: '⁂', hint: 'look-alike photos: each flicks by' },
}
export const PHOTO_STYLES = ['medium', 'small', 'burst']

const SHARE = { clip: 1, medium: 0.7, small: 0.45, burst: 0.2 }   // of a clip's length
const HALVINGS = { clip: 0, medium: 1, small: 2, burst: 3 }        // of a clip's beats
const SHORTEST = { clip: 0.2, medium: 0.6, small: 0.35, burst: 0.2 } // seconds, to be seen at all
const LONGEST_BURST = 0.5                                          // seconds
const BURST_GAP = 15 * 60   // photos taken further apart than this aren't one burst

const round1 = (t) => Math.round(t * 10) / 10

// How long each style plays: { clip: { seconds, beats }, medium: …, small: …,
// burst: … }. len is the clip length in seconds; with period (seconds per
// beat), lengths are beats instead, beatsPerCut for a clip. beats is 0 off
// the beat. Each style is no longer than the one before it.
export function holdLengths(len, period = 0, beatsPerCut = 4) {
  const out = {}
  let longer = Infinity
  for (const style of Object.keys(STYLES)) {
    if (period) {
      let b = beatsPerCut / 2 ** HALVINGS[style]
      while (b * period < SHORTEST[style] && b < beatsPerCut) b *= 2
      if (style === 'burst') while (b * period > LONGEST_BURST && (b / 2) * period >= SHORTEST.burst) b /= 2
      b = Math.min(Math.max(b, 0.25), longer)
      out[style] = { beats: b, seconds: b * period }
      longer = b
    } else {
      const t = style === 'clip' ? len
        : Math.min(round1(clamp(len * SHARE[style], SHORTEST[style], style === 'burst' ? LONGEST_BURST : len)), longer)
      out[style] = { beats: 0, seconds: t }
      longer = t
    }
  }
  return out
}

// ---------------------------------------------------------------- look-alikes

// A look (from the server, see studio/looks.py) is base64: 8×8 grey, then
// 4×4 RGB.
const decoded = new Map()
function pixels(look) {
  if (!decoded.has(look)) decoded.set(look, Uint8Array.from(atob(look), (c) => c.charCodeAt(0)))
  return decoded.get(look)
}

// How alike the layout of light and dark is (-1..1), letting one be moved a
// pixel either way (an eighth of the frame), as a second shot usually is.
function structure(a, b) {
  let best = -1
  for (let dy = -1; dy <= 1; dy++) {
    for (let dx = -1; dx <= 1; dx++) {
      const A = []
      const B = []
      for (let y = Math.max(0, dy); y < 8 + Math.min(0, dy); y++) {
        for (let x = Math.max(0, dx); x < 8 + Math.min(0, dx); x++) {
          A.push(a[y * 8 + x])
          B.push(b[(y - dy) * 8 + x - dx])
        }
      }
      const ma = A.reduce((s, v) => s + v, 0) / A.length
      const mb = B.reduce((s, v) => s + v, 0) / B.length
      let ab = 0
      let aa = 0
      let bb = 0
      for (let i = 0; i < A.length; i++) {
        ab += (A[i] - ma) * (B[i] - mb)
        aa += (A[i] - ma) ** 2
        bb += (B[i] - mb) ** 2
      }
      if (aa && bb) best = Math.max(best, ab / Math.sqrt(aa * bb))
    }
  }
  return best
}

// How different the colours are (0..2), block by block, ignoring how bright
// each block is, so one shot a little darker than the other still matches.
function colourGap(a, b) {
  let gap = 0
  for (let k = 0; k < 16; k++) {
    const p = [0, 1, 2].map((c) => a[64 + k * 3 + c] + 8)
    const q = [0, 1, 2].map((c) => b[64 + k * 3 + c] + 8)
    const sp = p[0] + p[1] + p[2]
    const sq = q[0] + q[1] + q[2]
    gap += Math.abs(p[0] / sp - q[0] / sq) + Math.abs(p[1] / sp - q[1] / sq) + Math.abs(p[2] / sp - q[2] / sq)
  }
  return gap / 16
}

// Two shots of the same thing: the same light and dark (allowing a small
// reframe) in much the same colours, or almost exactly the same picture.
export function alike(lookA, lookB) {
  if (!lookA || !lookB) return false
  const a = pixels(lookA)
  const b = pixels(lookB)
  const s = structure(a, b)
  return s >= 0.85 || (s >= 0.6 && colourGap(a, b) <= 0.06)
}

// ---------------------------------------------------------------- styles

// What's in a photo, from its look: 'people', 'animals', 'none', or
// 'unknown' (not looked at yet, or this Mac can't tell).
export function subjectOf(look) {
  if (!look || look.people == null) return 'unknown'
  return look.people ? 'people' : look.animals ? 'animals' : 'none'
}

// Each photo's style: Map mediaId -> { style, auto, why, group }. entries
// are in the order they play ({ mediaId, kind, media }); two photos next to
// each other there that look alike, and were taken within a few minutes, are
// a burst; one set to Burst by hand joins the burst before it. Clips in
// between keep photos apart. looks: mediaId -> the server's look; chosen:
// mediaId -> a style picked by hand. why is 'alike' or what subjectOf found;
// group is the same for every photo in one burst.
export function photoStyles(entries, looks, chosen = {}) {
  const out = new Map()
  const link = entries.map((e, i) => {
    const p = entries[i - 1]
    return !!(p && p.kind === 'photo' && e.kind === 'photo'
      && Math.abs(p.media.capturedAt - e.media.capturedAt) <= BURST_GAP
      && alike(looks[p.mediaId]?.look, looks[e.mediaId]?.look))
  })
  // A photo picked as Medium or Small by hand drops out of its burst.
  const free = (i) => i >= 0 && i < entries.length && (!chosen[entries[i].mediaId] || chosen[entries[i].mediaId] === 'burst')
  let group = null
  let bursts = 0
  entries.forEach((e, i) => {
    if (e.kind !== 'photo') { group = null; return }
    const subject = subjectOf(looks[e.mediaId])
    const inBurst = (link[i] && free(i - 1)) || (link[i + 1] && free(i + 1))
    const auto = inBurst ? 'burst' : subject === 'none' ? 'small' : 'medium'
    const style = chosen[e.mediaId] || auto
    if (style !== 'burst') group = null
    else if (!(group && (link[i] || chosen[e.mediaId] === 'burst'))) group = `burst${++bursts}`
    out.set(e.mediaId, { style, auto, why: inBurst ? 'alike' : subject, group: style === 'burst' ? group : null })
  })
  return out
}

// How long each entry plays, in order: [{ seconds, beats }]. styles are the
// entries' styles in the order they play; sizes come from holdLengths. On
// the beat, the last photo of a run that would end between beats holds to
// the next whole beat.
export function timeline(styles, sizes) {
  const out = styles.map((s) => ({ ...sizes[s] }))
  const period = sizes.clip.beats ? sizes.clip.seconds / sizes.clip.beats : 0
  if (!period) return out
  let run = 0
  styles.forEach((s, i) => {
    if (s === 'clip') return
    run += out[i].beats
    if (i < styles.length - 1 && styles[i + 1] !== 'clip') return
    const pad = Math.ceil(run - 1e-6) - run
    if (pad > 1e-6) {
      out[i].beats += pad
      out[i].seconds = out[i].beats * period
    }
    run = 0
  })
  return out
}
