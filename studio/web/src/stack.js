// A Stack reel whose layout changes: the top clip alone, the two split, or
// a part underneath alone, with the panes sliding between. The same rules
// as the engine (montage.py: layout_keys, x_at, quiet_cut, top_plan), so the
// preview moves where the render does.
//
// x is where the layout is: -1 the top clip alone, 0 split, 1 the part
// underneath (or on the right, in a wide reel) alone.

export const SLIDE = 0.5        // seconds the panes take to slide
export const QUIET_KEEP = 3.0   // quiet cuts never leave a piece shorter than this
export const QUIET_GAP = 12.0   // ... and take out about this much at a time, at most
export const QUIET_LEVEL = 0.22 // "nothing much happening"
export const QUIET_MIN = 1.5    // a lull has to last this long to be cut out

// marks: [{ at, x }] where each stretch of the reel starts and its layout;
// total: where the reel ends. Returns [[t, x]]: between two keys x eases
// from one to the other.
export function layoutKeys(marks, total) {
  if (!marks.length) return [[0, 0]]
  const changes = [marks[0]]
  for (const m of marks.slice(1)) if (m.x !== changes[changes.length - 1].x) changes.push(m)
  const keys = [[changes[0].at, changes[0].x]]
  changes.slice(1).forEach((c, i) => {
    const next = i + 2 < changes.length ? changes[i + 2].at : total
    const slide = Math.max(1 / 30, Math.min(SLIDE, next - c.at))
    keys.push([c.at, keys[keys.length - 1][1]], [c.at + slide, c.x])
  })
  keys[0][0] = 0
  return keys
}

export function xAt(keys, t) {
  let x = keys[0][1]
  for (let i = 0; i + 1 < keys.length; i++) {
    const [t0, x0] = keys[i]
    const [t1, x1] = keys[i + 1]
    if (t < t0) break
    if (t < t1 && t1 > t0) return x0 + (x1 - x0) * (0.5 - 0.5 * Math.cos((Math.PI * (t - t0)) / (t1 - t0)))
    x = x1
  }
  return x
}

// How long the top clip has been on screen by reel time t: it pauses while
// the part underneath is alone.
export function shownBy(keys, t) {
  let hidden = 0
  for (let i = 0; i + 1 < keys.length; i++) {
    const [a, xa] = keys[i]
    const [b, xb] = keys[i + 1]
    if (xa === 1 && xb === 1 && a < t) hidden += Math.min(b, t) - a
  }
  const [last, xl] = keys[keys.length - 1]
  if (xl === 1 && t > last) hidden += t - last
  return Math.max(0, t - hidden)
}

// Pieces [[start, length]] of start..start+length with its quiet moments
// taken out (points: [[seconds, 0..1]] of how much happens). With need,
// about length - need is taken out, the lulls first, then the quietest of
// what's left; without it, every lull. As montage.py's quiet_cut.
export function quietCut(points, start, length, need = null) {
  const end = start + length
  const step = 0.25
  const n = Math.floor(length / step)
  if (n < 4) return [[start, length]]
  const pts = points.filter(([t]) => t >= start - 2 && t <= end + 2).sort((p, q) => p[0] - q[0])
  const level = (t) => {
    if (!pts.length) return 1
    if (t <= pts[0][0]) return pts[0][1]
    for (let i = 0; i + 1 < pts.length; i++) {
      const [ta, va] = pts[i]
      const [tb, vb] = pts[i + 1]
      if (t <= tb) return va + ((vb - va) * (t - ta)) / Math.max(tb - ta, 1e-6)
    }
    return pts[pts.length - 1][1]
  }
  const raw = Array.from({ length: n }, (_, i) => level(start + (i + 0.5) * step))
  const act = raw.map((_, i) => {
    const w = raw.slice(Math.max(0, i - 2), i + 3)
    return w.reduce((s, v) => s + v, 0) / w.length
  })
  const mean = (a, k) => act.slice(a, a + k).reduce((s, v) => s + v, 0) / k
  const keepN = Math.floor(QUIET_KEEP / step)
  const gaps = []
  const free = (a, k) => a >= keepN && a + k <= n - keepN
    && gaps.every(([g, gk]) => a + k + keepN <= g || g + gk + keepN <= a)

  const lulls = []
  const minK = Math.floor(QUIET_MIN / step)
  for (let i = 0; i < n;) {
    if (act[i] < QUIET_LEVEL) {
      let j = i
      while (j < n && act[j] < QUIET_LEVEL) j++
      if (j - i - 2 >= minK) lulls.push([mean(i, j - i), i + 1, j - i - 2])
      i = j
    } else i++
  }
  let drop = need !== null ? Math.round(Math.max(length - need, 0) / step) : n
  for (let [, a, k] of lulls.sort((p, q) => p[0] - q[0] || p[1] - q[1])) {
    if (drop <= 0) break
    if (k > drop) { a += Math.floor((k - drop) / 2); k = drop }
    while (k >= 2 && !free(a, k)) { a += 1; k -= 2 }
    if (k >= 2) { gaps.push([a, k]); drop -= k }
  }
  if (need !== null) {
    let k = Math.min(drop, Math.floor(QUIET_GAP / step))
    while (drop > 0 && k >= 2) {
      k = Math.min(k, drop)
      let best = null
      for (let a = 0; a <= n - k; a++) {
        if (!free(a, k)) continue
        const score = mean(a, k)
        if (!best || score < best[0]) best = [score, a]
      }
      if (!best) { k = Math.floor(k / 2); continue }
      gaps.push([best[1], k])
      drop -= k
    }
  }
  const pieces = []
  let at = 0
  for (const [a, k] of gaps.sort((p, q) => p[0] - q[0])) {
    pieces.push([round3(start + at * step), round3((a - at) * step)])
    at = a + k
  }
  pieces.push([round3(start + at * step), round3(end - (start + at * step))])
  return pieces.filter(([, l]) => l > 0.05)
}
const round3 = (v) => Math.round(v * 1000) / 1000

// How the top clip fills the time it's on screen (shown, in seconds): the
// pieces of it that play and how fast.
export function topPlan({ start, length, fit, by, points, speed = 1 }, shown) {
  let pieces = [[start, length]]
  let rate = fit ? 1 : speed   // fit off: its own speed
  if (fit && shown > 0) {
    if (by === 'quiet') {
      pieces = quietCut(points || [], start, length, shown)
      rate = Math.max(1, pieces.reduce((s, [, l]) => s + l, 0) / shown)
    } else rate = length / shown
  }
  return { pieces, rate }
}

// Where in the top clip it is after `shown` seconds on screen.
export function topSource({ pieces, rate }, shown) {
  let left = Math.max(0, shown) * rate
  for (const [s, l] of pieces) {
    if (left < l) return s + left
    left -= l
  }
  const [s, l] = pieces[pieces.length - 1]
  return s + l - 0.05
}

// Where each pane sits at layout x, in the frame's pixels along the split:
// the top pane, the divider and the other pane (as the engine's overlays).
export function panePositions(x, { full, top, under, divider: d }) {
  if (x < 0) {
    const pa = ((full - top) / 2) * -x
    const pb = full - under + (d + under) * -x
    return { a: pa, b: pb, d: pb - d }
  }
  const pa = -(top + d) * x
  return { a: pa, b: top + d + ((full - under) / 2 - (top + d)) * x, d: pa + top }
}

// The panes' sizes for a frame w × h (the engine's load_top): side by side
// when it's wider than tall.
export function stackGeometry(w, h, split, dividerPx) {
  const axis = w > h ? 'x' : 'y'
  const full = axis === 'x' ? w : h
  const divider = Math.max(0, Math.round(dividerPx / 2) * 2)
  const top = Math.round(((full - divider) * split) / 2) * 2
  return { axis, full, top, under: full - divider - top, divider, w, h }
}
