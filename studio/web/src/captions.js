// Voice and captions, as the engine does them (montage.py, "voice" and
// "captions"), so what plays here is what renders: where each voice piece
// lands on the reel, which lines are on screen when, and how they fade.

export const CAPTION_STYLES = [
  { v: 'stanza', label: 'Stanza', size: 4.3, font: 'playfair', bg: 'band',
    hint: 'The whole stanza shows; the line being said is bright, the rest dim' },
  { v: 'unfold', label: 'Unfold', size: 4.3, font: 'garamond-italic', bg: 'scrim',
    hint: 'Lines fade in as they’re said and stay until the stanza ends' },
  { v: 'breath', label: 'Breath', size: 6.2, font: 'cormorant-italic', bg: 'shadow',
    hint: 'One line at a time, centred, drifting up as it comes in' },
  { v: 'page', label: 'Page', size: 4.3, font: 'courier', bg: 'paper',
    hint: 'Set left like a printed page, under a small title' },
]

// The files are in brand/fonts; each gets its own family name here so the
// browser never fakes an italic or a weight.
export const CAPTION_FONTS = [
  { v: 'playfair', label: 'Playfair Display', file: 'PlayfairDisplay[wght].ttf', weight: 600, scale: 1 },
  { v: 'playfair-italic', label: 'Playfair italic', file: 'PlayfairDisplay-Italic[wght].ttf', weight: 500, scale: 1 },
  { v: 'garamond-italic', label: 'EB Garamond italic', file: 'EBGaramond-Italic[wght].ttf', weight: 400, scale: 1.12 },
  { v: 'cormorant-italic', label: 'Cormorant italic', file: 'CormorantGaramond-Italic[wght].ttf', weight: 500, scale: 1.18 },
  { v: 'courier', label: 'Courier Prime', file: 'CourierPrime-Regular.ttf', weight: 400, scale: 0.9 },
  { v: 'roboto', label: 'Roboto', file: 'Roboto[wdth,wght].ttf', weight: 400, scale: 0.96 },
  { v: 'caveat', label: 'Caveat (handwritten)', file: 'Caveat[wght].ttf', weight: 500, scale: 1.32 },
]

export const CAPTION_BGS = [
  { v: 'scrim', label: 'See-through layer' },
  { v: 'band', label: 'Band' },
  { v: 'paper', label: 'Paper panel' },
  { v: 'blur', label: 'Blur behind' },
  { v: 'shadow', label: 'Shadow only' },
]

export const CAPTION_SIZES = [{ v: 0.85, label: 'Small' }, { v: 1, label: 'Medium' }, { v: 1.18, label: 'Large' }]

// The panel's sides and the padding inside it, in % of the frame's width.
export const CAPTION_BOX = { band: [0, 11, 3.4], paper: [9, 5.4, 4.4], blur: [7, 4, 3.6], scrim: [11, 0, 0], shadow: [11, 0, 0] }
export const CAPTION_LEADING = 1.32
const DIM = 0.38       // stanza: the lines not being said
const PAST = 0.82      // unfold: lines already said
const X = 0.3          // crossfade as a line brightens or dims
const APPEAR = 0.5     // unfold and page: a new line fading in

export const VOICE_TAIL = 0.8   // the last part holds this long after the voice
const DUCK_RAMP = 0.4

export const fontOf = (v) => CAPTION_FONTS.find((f) => f.v === v) || CAPTION_FONTS[0]
export const styleOf = (v) => CAPTION_STYLES.find((s) => s.v === v) || CAPTION_STYLES[2]
export const fontFamily = (v) => `"Caption ${fontOf(v).v}", Georgia, serif`

// @font-face for every caption font, once.
let fontsAdded = false
export function addCaptionFonts() {
  if (fontsAdded) return
  fontsAdded = true
  const css = CAPTION_FONTS.map((f) => `@font-face { font-family: "Caption ${f.v}"; `
    + `src: url("/api/fonts/${encodeURIComponent(f.file)}"); font-weight: 100 900; font-style: normal; font-display: swap; }`).join('\n')
  const el = document.createElement('style')
  el.textContent = css
  document.head.appendChild(el)
}

// The pieces one after another, each after its breath, and their lines on the
// reel's clock (as the server's voice_timeline).
export function voiceTimeline(pieces) {
  const out = { pieces: [], lines: [], end: 0 }
  let t = 0
  for (const p of pieces || []) {
    const start = Number(p.start) || 0
    const end = Number(p.end) || 0
    if (end - start < 0.1) continue
    t += Math.max(0, Number(p.gap) || 0)
    out.pieces.push({ ...p, at: t, length: end - start })
    for (const [i, l] of (p.lines || []).entries()) {
      const ls = Math.max(l.s, start)
      const le = Math.min(l.e, end)
      if (le - ls < 0.05 || !String(l.text || '').trim()) continue
      out.lines.push({ start: t + ls - start, end: t + le - start, text: String(l.text).trim().replace(/\s+/g, ' '),
                       stanza: !!l.br, pieceId: p.id, index: i })
    }
    t += end - start
  }
  out.end = out.pieces.length ? t : 0
  return out
}

// The song's volume at reel time t with a voice: `between`, dipping to
// `under` while the voice speaks.
export function songLevel(pieces, under, between, t) {
  let duck = 0
  for (const p of pieces) {
    const a = Math.min(Math.max((t - (p.at - DUCK_RAMP)) / DUCK_RAMP, 0), 1)
    const b = Math.min(Math.max((p.at + p.length + DUCK_RAMP - t) / DUCK_RAMP, 0), 1)
    duck = Math.max(duck, a * b)
  }
  return between + (under - between) * duck
}

// What's on screen together: a stanza, or for breath one line. Each
// { a, b, fi, fo, lines }, never overlapping the next.
export function captionGroups(lines, style) {
  const ls = lines.filter((l) => l.text.trim()).sort((p, q) => p.start - q.start)
  let sets
  let lead, tail, fi, fo
  if (style === 'breath') {
    sets = ls.map((l) => [l]);
    [lead, tail, fi, fo] = [0.35, 0.6, 0.7, 0.6]
  } else {
    sets = []
    for (const l of ls) {
      if (!sets.length || l.stanza) sets.push([])
      sets[sets.length - 1].push(l)
    }
    [lead, tail, fi, fo] = [0.45, 0.8, 0.5, 0.5]
  }
  const groups = sets.map((g) => ({ a: Math.max(0, g[0].start - lead), b: g[g.length - 1].end + tail, lines: g }))
  for (let i = 1; i < groups.length; i++) {
    const prev = groups[i - 1]
    const g = groups[i]
    if (prev.b > g.a - 0.05) {
      prev.b = Math.max(prev.lines[prev.lines.length - 1].end + 0.05, g.a - 0.05)
      g.a = Math.max(g.a, prev.b)
    }
  }
  for (const g of groups) {
    const span = g.b - g.a
    g.fi = Math.min(fi, span / 2)
    g.fo = Math.min(fo, span / 2)
    g.segs = segments(g, style)
  }
  return groups
}

// For each line of a group, the stretches it's on screen at one opacity:
// [{ alpha, t0, t1, fi, fo }]. Changes of opacity crossfade.
function segments(group, style) {
  const { lines: ls, a, b } = group
  const last = ls.length - 1
  return ls.map((l, k) => {
    let points
    if (style === 'stanza') {
      points = k ? [[a, DIM], [l.start - 0.15, 1]] : [[a, 1]]
      if (k < last) points.push([ls[k + 1].start - 0.15, DIM])
    } else if (style === 'unfold' || style === 'page') {
      const at = k === 0 ? a : Math.max(a, l.start - 0.2)
      points = [[at, 1]]
      if (style === 'unfold' && k < last) points.push([Math.max(at, ls[k + 1].start - 0.2), PAST])
    } else {
      points = [[a, 1]]
    }
    const firstFade = points[0][0] <= a + 1e-6 ? group.fi : APPEAR
    const segs = []
    points.forEach(([t, alpha], i) => {
      let t0 = i === 0 ? t : t - X / 2
      let t1 = i + 1 < points.length ? points[i + 1][0] + X / 2 : b
      t0 = Math.max(t0, a)
      t1 = Math.min(t1, b)
      if (t1 - t0 < 0.04) return
      const fin = i === 0 ? firstFade : X
      const fout = i + 1 < points.length ? X : group.fo
      segs.push({ alpha, t0, t1, fi: Math.min(fin, (t1 - t0) / 2), fo: Math.min(fout, (t1 - t0) / 2) })
    })
    return segs
  })
}

// How visible something is at t that's on from t0 to t1, fading fi in, fo out.
export function envelope(t, t0, t1, fi, fo) {
  if (t < t0 || t > t1) return 0
  let v = 1
  if (fi > 0) v = Math.min(v, (t - t0) / fi)
  if (fo > 0) v = Math.min(v, (t1 - t) / fo)
  return Math.max(0, Math.min(v, 1))
}

export function lineOpacity(segs, t) {
  return Math.min(1, segs.reduce((sum, s) => sum + s.alpha * envelope(t, s.t0, s.t1, s.fi, s.fo), 0))
}
