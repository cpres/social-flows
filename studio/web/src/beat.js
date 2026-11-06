// The beat builder: what's asked for when a beat is made for a reel. The
// reel's `beat` setting (studio/beats.py) holds it; this works out the
// curve, the tempo and key the levers point to, and the prompt.

import { fmtTime } from './time'

// Ten vibe levers, 0..5 notches each. `word` goes in the prompt from 2
// notches up, `strong` from 4.
export const LEVERS = [
  { v: 'funky', label: 'Funky', hint: 'syncopated bass, clav, wah', word: 'funky', strong: 'very funky' },
  { v: 'happy', label: 'Happy', hint: 'major keys, bright chords', word: 'happy', strong: 'joyful' },
  { v: 'chill', label: 'Chill', hint: 'softer, more space, slower', word: 'chill', strong: 'very laid-back' },
  { v: 'upbeat', label: 'Upbeat', hint: 'tempo and drive', word: 'upbeat', strong: 'driving' },
  { v: 'grungy', label: 'Grungy', hint: 'distortion, dirt, tape', word: 'grungy', strong: 'dirty, distorted' },
  { v: 'futuristic', label: 'Futuristic', hint: 'synths, glitch, sidechain', word: 'futuristic', strong: 'glitchy, synth-heavy' },
  { v: 'ecstatic', label: 'Ecstatic', hint: 'conscious-dance lift, chants, swells', word: 'ecstatic', strong: 'euphoric, with chants and swells' },
  { v: 'drummy', label: 'Drummy', hint: 'more percussion, fills', word: 'drummy', strong: 'percussion-heavy' },
  { v: 'bass', label: 'Bass', hint: 'low-end weight', word: 'bass', strong: 'heavy bass' },
  { v: 'earthy', label: 'Earthy', hint: 'hand drums, kalimba, birds', word: 'earthy', strong: 'earthy, hand drums and kalimba' },
]
const ORDER = LEVERS.map((l) => l.v)
const levers = (arr) => Object.fromEntries(ORDER.map((k, i) => [k, arr[i]]))

// Vibe presets: all ten levers at once (in the order above).
export const VIBES = [
  { v: 'garden', label: 'Garden morning', levers: levers([2, 4, 2, 2, 0, 0, 1, 2, 2, 5]) },
  { v: 'ecstatic', label: 'Ecstatic dance', levers: levers([2, 3, 0, 4, 0, 2, 5, 5, 4, 3]) },
  { v: 'street', label: 'Street grit', levers: levers([3, 1, 1, 3, 4, 1, 0, 4, 4, 0]) },
  { v: 'lofi', label: 'Lo-fi chill', levers: levers([1, 2, 5, 0, 2, 0, 0, 2, 2, 2]) },
]

// Clicking a notch sets that level; clicking the level it's at lowers it by one (so 1 → 0).
export const leverClick = (now, notch) => (notch === now ? notch - 1 : notch)

// What the levers point to: tempo ≈ 88 + 7·upbeat − 5·chill + 3·ecstatic + funky.
export function derivedTempo(l) {
  const t = 88 + 7 * (l.upbeat || 0) - 5 * (l.chill || 0) + 3 * (l.ecstatic || 0) + (l.funky || 0)
  return Math.round(Math.min(180, Math.max(60, t)))
}
// Major if happy ≥ 3, dorian at 1–2, minor at 0; on the reference song's tonic (else C).
export function derivedKey(l, refKey) {
  const tonic = String(refKey || '').trim().split(/\s+/)[0] || 'C'
  const h = l.happy || 0
  return `${tonic} ${h >= 3 ? 'major' : h >= 1 ? 'dorian' : 'minor'}`
}

// ---------------------------------------------------------------- the energy curve

// The curve's value at x (0..1): monotone cubic through the points, so it's
// smooth but never overshoots past a point (and stays in 0..1).
export function curveAt(points, x) {
  const p = points
  if (!p.length) return 0.5
  if (x <= p[0][0]) return p[0][1]
  if (x >= p[p.length - 1][0]) return p[p.length - 1][1]
  const n = p.length
  const d = []   // secant slopes
  for (let i = 0; i < n - 1; i++) d.push((p[i + 1][1] - p[i][1]) / Math.max(p[i + 1][0] - p[i][0], 1e-6))
  const m = [d[0]]
  for (let i = 1; i < n - 1; i++) m.push(d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2)
  m.push(d[n - 2])
  for (let i = 0; i < n - 1; i++) {   // Fritsch–Carlson: keep it monotone between points
    if (d[i] === 0) { m[i] = 0; m[i + 1] = 0; continue }
    const a = m[i] / d[i]
    const b = m[i + 1] / d[i]
    const s = a * a + b * b
    if (s > 9) { const t = 3 / Math.sqrt(s); m[i] = t * a * d[i]; m[i + 1] = t * b * d[i] }
  }
  let i = 0
  while (x > p[i + 1][0]) i++
  const h = p[i + 1][0] - p[i][0]
  const t = (x - p[i][0]) / h
  const t2 = t * t
  const t3 = t2 * t
  const y = (2 * t3 - 3 * t2 + 1) * p[i][1] + (t3 - 2 * t2 + t) * h * m[i] + (-2 * t3 + 3 * t2) * p[i + 1][1] + (t3 - t2) * h * m[i + 1]
  return Math.min(1, Math.max(0, y))
}

// The reel's scenes as fractions of it: [{ layout, a, b }].
export const sceneFractions = (scenes, length) => scenes.map((s) => ({
  layout: s.layout, a: s.start / (length || 1), b: Math.min(1, s.end / (length || 1)),
}))

// Curve presets. "Follow my scenes": low while A plays alone at the start,
// building through the splits, peaking on Solo B, cooling at the end.
export const CURVES = [
  { v: 'follow', label: 'Follow my scenes' },
  { v: 'arc', label: 'Arc' },
  { v: 'slow', label: 'Slow build' },
  { v: 'peaks', label: 'Two peaks' },
  { v: 'steady', label: 'Steady' },
]
export function presetCurve(v, scenes = []) {
  if (v === 'arc') return [[0, 0.15], [0.35, 0.55], [0.65, 0.9], [1, 0.2]]
  if (v === 'slow') return [[0, 0.1], [0.5, 0.35], [0.85, 0.9], [1, 0.7]]
  if (v === 'peaks') return [[0, 0.2], [0.3, 0.8], [0.5, 0.35], [0.8, 0.95], [1, 0.2]]
  if (v === 'steady') return [[0, 0.6], [1, 0.6]]
  return followScenes(scenes)
}
function followScenes(scenes) {
  if (!scenes.length) return presetCurve('arc')
  // A gentle rise over the whole reel, each scene placed against it by what
  // it shows: Solo A under it, splits on it, Solo B lifted as a peak.
  const base = (x) => 0.25 + 0.55 * x
  const OFF = { soloA: -0.12, stack: 0, swap: 0.03, soloB: 0.18 }
  const clamp = (v) => Math.min(1, Math.max(0.08, v))
  const pts = []
  const n = scenes.length
  scenes.forEach((s, k) => {
    const off = OFF[s.layout] ?? 0
    const at = (f) => s.a + (s.b - s.a) * f
    const from = clamp(base(s.a) + off)
    if (k === n - 1 && n > 1 && s.layout !== 'soloB') {   // the last scene cools off
      pts.push([s.a, Math.min(from, 0.6)])
      return
    }
    if (s.layout === 'soloB') pts.push([s.a, from], [at(0.5), clamp(base(at(0.5)) + off + 0.05)])
    else pts.push([s.a, from], [at(0.92), clamp(base(at(0.92)) + off)])
  })
  pts.push([1, 0.2])   // cool at the end
  // One point per place: where two land within 2% of each other, the later one wins.
  const out = []
  for (const p of pts.sort((x, y) => x[0] - y[0])) {
    const r = [Math.round(Math.min(1, Math.max(0, p[0])) * 1000) / 1000, Math.round(p[1] * 100) / 100]
    if (out.length && r[0] - out[out.length - 1][0] < 0.02) out[out.length - 1] = [out[out.length - 1][0], r[1]]
    else out.push(r)
  }
  out[0][0] = 0
  out[out.length - 1][0] = 1
  return out
}

// How high the energy goes: the curve's top, squashed down under a ceiling.
export const TOPS = [
  { v: 1, label: 'Full', hint: 'Builds all the way to a big peak' },
  { v: 0.8, label: 'Lively', hint: 'Lifts well, but stops short of a big peak' },
  { v: 0.62, label: 'Mid', hint: 'Stays in a groove, with a gentle lift' },
  { v: 0.45, label: 'Chill', hint: 'Stays relaxed the whole way, a small rise at most' },
]
export const topOf = (points) => Math.max(...points.map((p) => p[1]))
// The curve with its highest point at `top`, its shape kept and its calm
// parts left where they are (unless the top comes down past them). Only ever
// squashes, unless `stretch` (dragging the line back up on a curve of your own).
export function capCurve(points, top, stretch = false) {
  const ys = points.map((p) => p[1])
  const lo = Math.min(...ys)
  const hi = Math.max(...ys)
  const t = Math.min(1, Math.max(0.1, top))
  if (!stretch && hi <= t + 1e-3) return points
  const r = (v) => Math.round(Math.min(1, Math.max(0, v)) * 100) / 100
  if (hi - lo < 0.01) return points.map(([x]) => [x, r(t)])
  const lo2 = Math.max(0, Math.min(lo, t - 0.08))
  return points.map(([x, y]) => [x, r(lo2 + ((y - lo) * (t - lo2)) / (hi - lo))])
}

// What each scene does in the music, for the strip under the curve: intro, build, peak, cool or steady.
export function sceneRole(points, s, k, n) {
  // Judged on the scene's inner 80%, so a rise into the next scene doesn't count.
  const w = s.b - s.a
  const a = curveAt(points, s.a + w * 0.1)
  const b = curveAt(points, s.b - w * 0.1)
  const top = Math.max(...Array.from({ length: 9 }, (_, i) => curveAt(points, s.a + w * (0.1 + (0.8 * i) / 8))))
  if (n === 1) return 'arc'
  if (k === 0 && n > 1 && top < 0.45) return 'intro'
  if (top >= 0.8 && top - Math.min(a, b) > 0.05) return 'peak'
  if (b - a > 0.12) return 'build'
  if (a - b > 0.12) return k === n - 1 ? 'cool' : 'drop'
  if (k === n - 1 && b < 0.4) return 'cool'
  return 'steady'
}

// Where the curve peaks (0..1).
export function peakOf(points) {
  let best = 0
  for (let i = 1; i <= 200; i++) if (curveAt(points, i / 200) > curveAt(points, best / 200) + 1e-6) best = i
  return best / 200
}

// ---------------------------------------------------------------- the prompt

export function beatPrompt({ tempo, key, from, levers: l, curve, hits, end, length, edges, ceiling }) {
  // Whole seconds, as people say them; tenths too in a short reel, where they matter.
  const t = (s) => (length < 30 ? fmtTime(s) : fmtTime(Math.round(s)).replace(/\.\d$/, ''))
  const parts = [`${tempo} BPM, ${key}`]
  if (from?.kind === 'song') parts[0] += from.category ? `, in the groove of your ${from.category} song` : `, in the groove of “${from.title || from.name}”`
  const words = LEVERS.filter((x) => (l[x.v] || 0) >= 2).map((x) => (l[x.v] >= 4 ? x.strong : x.word))
  const lines = [`${parts[0]}.`]
  if (words.length) lines.push(`${words.join(', ')}.`)
  const lo = Math.min(...curve.map((p) => p[1]))
  const hi = Math.max(...curve.map((p) => p[1]))
  const shape = []
  if (hi - lo < 0.15) shape.push((ceiling ?? 1) <= 0.65 ? 'Stays relaxed and steady throughout, no big drops' : 'Steady energy throughout')
  else {
    const start = curve[0][1]
    const opening = start < 0.35 ? 'Starts calm' : start > 0.7 ? 'Starts lively' : 'Starts mid'
    const top = ceiling ?? 1
    shape.push(top <= 0.65 ? `${opening}, stays relaxed and steady the whole way, lifting gently around ${t(peakOf(curve) * length)}, no big drops`
      : top < 0.95 ? `${opening}, lifts to a moderate high around ${t(peakOf(curve) * length)} without a big peak`
        : `${opening}, builds to a peak at ${t(peakOf(curve) * length)}`)
  }
  if (hits && edges.length) shape.push(`hits at ${edges.map((e) => t(e)).join(', ')}`)
  shape.push(end ? `resolves on the last frame at ${t(length)}` : `fades out by ${t(length)}`)
  lines.push(`${shape.join(', ')}.`)
  return lines.join(' ')
}

// A new reel's beat: from scratch, following its scenes, Garden morning.
export function newBeat(scenes) {
  return {
    from: { kind: 'scratch' }, curve: presetCurve('follow', scenes), preset: 'follow', hits: true, end: true,
    levers: { ...VIBES[0].levers }, vibe: VIBES[0].v, tempo: null, key: null, prompt: null, ceiling: null,
  }
}
