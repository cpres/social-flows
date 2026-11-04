// Quiet moments: where nothing much happens in a clip, to cut out (the
// same rule as the engine's quiet_cut), and where a clip played in pieces
// is after so many seconds. Used for lane A's "cut quiet moments to fit"
// and B's "Take out quiet moments".

export const QUIET_KEEP = 3.0   // quiet cuts never leave a piece shorter than this
export const QUIET_GAP = 12.0   // ... and take out about this much at a time, at most
export const QUIET_LEVEL = 0.22 // "nothing much happening"
export const QUIET_MIN = 1.5    // a lull has to last this long to be cut out

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

// Where in the clip it is after `shown` seconds of its pieces at `rate`.
export function topSource({ pieces, rate }, shown) {
  let left = Math.max(0, shown) * rate
  for (const [s, l] of pieces) {
    if (left < l) return s + left
    left -= l
  }
  const [s, l] = pieces[pieces.length - 1]
  return s + l - 0.05
}
