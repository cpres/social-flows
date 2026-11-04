// A reel in lanes and scenes (studio/scenes.py has the full story).
// Lane A: the main, continuous footage (settings.laneA, part ids). Lane B:
// the other kept parts, the cut list. Scenes say what's on screen, one after
// another: soloA, stack (A primary), soloB, swap (B primary). A B scene holds
// the kept parts from its `from` to the next B scene's; a soloA scene holds
// none (B waits). The same rules as scenes.py and the engine (montage.py:
// scene_slots, resolve_a, scene_a_plan), so the preview matches the render.

import { quietCut } from './stack'

export const LAYOUTS = [
  { v: 'soloA', label: 'Solo A', key: '1' },
  { v: 'stack', label: 'A over B', wide: 'A | B', key: '2' },
  { v: 'soloB', label: 'Solo B', key: '3' },
  { v: 'swap', label: 'B over A', wide: 'B | A', key: '4' },
]
export const INTOS = [
  { v: 'cut', label: 'Cut', hint: 'Straight into the new layout.' },
  { v: 'slide', label: 'Slide', hint: 'The new layout slides in from the bottom (the right, in 16:9) over the last frame. 0.4s.' },
  { v: 'push', label: 'Push', hint: 'The new layout pushes the old one out of the frame. 0.4s.' },
  { v: 'dissolve', label: 'Dissolve', hint: 'A soft crossfade between the layouts. 0.4s.' },
]
export const TIMINGS = [
  { v: 'fit', label: 'Fit to scene', hint: 'Speed A up (or slow it down) so it spans the whole scene' },
  { v: 'quiet', label: 'Cut quiet moments to fit', hint: 'Real speed; where nothing much happens is cut out until it spans the scene' },
  { v: 'hold', label: 'Its own speed, then hold', hint: 'A plays at the speed you pick; its last frame holds if it runs out' },
  { v: 'range', label: 'Real speed, pick a range', hint: 'Choose where A starts (I in the A clip); it plays 1× for the scene' },
]
export const SCENE_IN = 0.4
export const SOLO_A_DEFAULT = 4
export const SOLO_A_MIN = 1
export const showsA = (sc) => sc.layout !== 'soloB'
export const showsB = (sc) => sc.layout !== 'soloA'
export const fitted = (sc) => sc.layout !== 'soloA' && ['fit', 'quiet'].includes(sc.a?.timing)
export const newId = () => Math.random().toString(16).slice(2, 10)

// The scenes as they play: each B scene with its parts (ids), in order;
// scenes that lost their parts or their A clip dropped or made Solo B.
export function normalize(scenes, keptIds, aIds) {
  const out = []
  const order = new Map(keptIds.map((id, i) => [id, i]))
  let last = -1
  for (const raw of scenes || []) {
    if (!LAYOUTS.some((l) => l.v === raw.layout)) continue
    const sc = { ...raw }
    if (sc.layout !== 'soloB') {
      if (!aIds.length) {
        if (sc.layout === 'soloA') continue
        sc.layout = 'soloB'
      } else sc.a = { ...(sc.a || {}), item: aIds.includes(sc.a?.item) ? sc.a.item : aIds[0] }
    }
    if (sc.layout === 'soloA') { sc.parts = []; out.push(sc); continue }
    let at = order.get(sc.from)
    if (!out.some((o) => o.layout !== 'soloA')) at = keptIds.length ? 0 : undefined
    if (at === undefined || at <= last) continue
    sc._at = at
    last = at
    out.push(sc)
  }
  const bs = out.filter((sc) => sc.layout !== 'soloA')
  bs.forEach((sc, i) => {
    const end = i + 1 < bs.length ? bs[i + 1]._at : keptIds.length
    sc.parts = keptIds.slice(sc._at, end)
    sc.from = sc.parts[0]
    delete sc._at
  })
  if (keptIds.length && !bs.length) out.push({ id: newId(), layout: 'soloB', from: keptIds[0], parts: [...keptIds], into: 'cut' })
  return out.filter((sc) => sc.layout === 'soloA' || sc.parts.length)
}

// How long a Solo A scene runs: its A range at its speed, or its length.
export function soloSeconds(sc) {
  const a = sc.a || {}
  if (a.in != null && a.out != null) return Math.max(SOLO_A_MIN, (a.out - a.in) / (a.speed || 1))
  return Math.max(SOLO_A_MIN, sc.len || SOLO_A_DEFAULT)
}

// Which framing a lane uses in a scene: full, half or square.
export function slotShape(sc, lane) {
  if (sc.layout === 'soloA' || sc.layout === 'soloB') return 'full'
  const secondary = sc.layout === 'stack' ? 'B' : 'A'
  return sc.split === 'square' && lane === secondary ? 'square' : 'half'
}

// A part's framing in a slot shape: {x, y, zoom}.
export function frameFor(p, shape, lane) {
  const legacy = { x: p.focusX, y: p.focusY, zoom: p.zoom || 1 }
  if (shape === 'full' || p.frames == null) return legacy
  const f = p.frames[shape]
  if (f) return { x: f.x, y: f.y, zoom: f.zoom || 1 }
  return { x: legacy.x, y: lane === 'B' ? 1 : 0.35, zoom: 1 }
}

// Where each lane sits in a w × h frame: { A: {w, h, x, y}, B: ..., divider }.
export function sceneSlots(sc, w, h, dividerPx) {
  if (sc.layout === 'soloA') return { A: { w, h, x: 0, y: 0 } }
  if (sc.layout === 'soloB') return { B: { w, h, x: 0, y: 0 } }
  const axis = w > h ? 'x' : 'y'
  const [full, cross] = axis === 'x' ? [w, h] : [h, w]
  const d = Math.min(Math.max(Math.floor(dividerPx / 2) * 2, 0), 40)
  let first
  let second
  if (sc.split === 'square' && full - d - cross >= full * 0.25) {
    second = cross
    first = full - d - second
  } else {
    const split = sc.split === 'square' ? 0.5 : Math.min(Math.max(Number(sc.split) || 0.5, 0.2), 0.8)
    first = Math.round(((full - d) * split) / 2) * 2
    second = full - d - first
  }
  const [p, q] = sc.layout === 'stack' ? ['A', 'B'] : ['B', 'A']
  if (axis === 'y') {
    return { [p]: { w, h: first, x: 0, y: 0 }, [q]: { w, h: second, x: 0, y: first + d },
             divider: d ? { w, h: d, x: 0, y: first } : null, axis, first, second, d, full }
  }
  return { [p]: { w: first, h, x: 0, y: 0 }, [q]: { w: second, h, x: first + d, y: 0 },
           divider: d ? { w: d, h, x: first, y: 0 } : null, axis, first, second, d, full }
}

// Each scene's stretch of its A clip, [in, out] (or null). items: id → part.
export function resolveA(scenes, secs, items) {
  const out = scenes.map(() => null)
  const cursor = new Map()
  const shows = scenes.map((sc, i) => i).filter((i) => showsA(scenes[i]) && scenes[i].a && items.get(scenes[i].a.item))
  shows.forEach((i, n) => {
    const a = scenes[i].a
    const it = items.get(a.item)
    const start = it.start
    const end = it.start + it.length
    const speed = a.speed || 1
    let ain = a.in != null ? a.in : (cursor.has(a.item) ? cursor.get(a.item) : start)
    ain = Math.min(Math.max(ain, start), end - 0.2)
    let aout
    if (!fitted(scenes[i])) aout = Math.min(end, ain + secs[i] * speed)
    else if (a.out != null) aout = Math.min(Math.max(a.out, ain + 0.2), end)
    else {
      let stop = end
      let need = 0
      let share = secs[i]
      for (const j of shows.slice(n + 1)) {
        const b = scenes[j].a
        if (b.item !== a.item) continue
        if (b.in != null) { stop = Math.min(stop, b.in); break }
        if (fitted(scenes[j])) {
          if (b.out != null) { stop = Math.min(stop, b.out); break }
          share += secs[j]
        } else need += secs[j] * (b.speed || 1)
      }
      const room = Math.max(stop - ain - need, 0.2)
      aout = Math.min(end, ain + (room * secs[i]) / Math.max(share, 1e-6))
    }
    cursor.set(a.item, aout)
    out[i] = [round3(ain), round3(Math.max(aout, ain + 0.2))]
  })
  return out
}
const round3 = (v) => Math.round(v * 1000) / 1000

// The pieces of the A clip a scene plays, and how fast.
export function sceneAPlan(sc, range, seconds, points) {
  const [ain, aout] = range
  const length = aout - ain
  const timing = sc.a?.timing || 'fit'
  if (sc.layout === 'soloA' || timing === 'hold' || timing === 'range') return { pieces: [[ain, length]], rate: sc.a?.speed || 1 }
  if (timing === 'quiet' && points) {
    const pieces = quietCut(points, ain, length, seconds)
    return { pieces, rate: Math.max(1, pieces.reduce((s, [, l]) => s + l, 0) / seconds) }
  }
  return { pieces: [[ain, length]], rate: length / Math.max(seconds, 0.04) }
}

export function layoutLabel(v, wide) {
  const l = LAYOUTS.find((x) => x.v === v)
  return l ? (wide && l.wide) || l.label : v
}
