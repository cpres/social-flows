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
  { v: 'handoff', label: 'Hand off', hint: 'The full-frame shot before moves into A\'s slot as B comes in, stays there a few seconds, then dissolves into A (which starts then). In a relay it carries on there instead.', when: (prev, sc) => prev?.layout === 'soloB' && ['stack', 'swap'].includes(sc.layout) },
  { v: 'takeover', label: 'Take over', hint: 'B grows from its slot to the full frame as A slides out. 0.6s.', when: (prev, sc) => ['stack', 'swap'].includes(prev?.layout) && sc.layout === 'soloB' },
]
export const HANDOFF_DEFAULT = 3
// A relay: a split after Solo B whose A slot is that shot carrying on.
export const isRelay = (scenes, k) => !!(k && scenes[k].relay && scenes[k].into === 'handoff'
  && scenes[k - 1].layout === 'soloB' && ['stack', 'swap'].includes(scenes[k].layout))
// Seconds scene k is handed off from the Solo B scene before it (0: none).
export function handoffSecs(scenes, k, secs) {
  const sc = scenes[k]
  if (!k || sc.into !== 'handoff' || scenes[k - 1].layout !== 'soloB' || !['stack', 'swap'].includes(sc.layout) || sc.relay) return 0
  return Math.max(0, Math.min(sc.handoff ?? HANDOFF_DEFAULT, secs[k] - 0.5))
}
// How A plays in a scene. Real speed unless a speed is asked for.
export const TIMINGS = [
  { v: 'real', label: 'Real speed', hint: 'A plays 1× for as long as the scene lasts, carrying on from the scene before' },
  { v: 'quiet', label: 'Real speed, skip quiet moments', hint: 'Still 1×, but it jumps over stretches where nothing much happens, so more of A gets in' },
  { v: 'hold', label: 'Pick a speed', hint: 'A plays at the speed you pick (½× to 4×)', speed: true },
  { v: 'fit', label: 'Speed up to fit its range', hint: 'A\'s start → end squeezed into the scene: a timelapse', speed: true },
]
// The timing a scene uses: Solo A plays at its own speed (1× unless picked).
export function aTiming(sc) {
  if (sc.layout === 'soloA') return 'hold'
  const t = sc.a?.timing || 'real'
  return t === 'range' ? 'real' : ['real', 'quiet', 'hold', 'fit'].includes(t) ? t : 'real'
}
export const SCENE_IN = 0.8      // seconds a scene's slide, push or dissolve takes (as montage.py)
export const SCENE_MOVE = 1.0    // ... and a hand off or take over
export const SOLO_A_DEFAULT = 4
export const SOLO_A_MIN = 1
export const showsA = (sc) => sc.layout !== 'soloB'
export const showsB = (sc) => sc.layout !== 'soloA'
export const fitted = (sc) => aTiming(sc) === 'fit'
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
        if (!sc.relay) sc.layout = 'soloB'   // a relay's A slot is the shot before, not lane A
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
// Until it's framed in a half or square slot, a part shows the bottom of its
// shot there (in glasses footage, where the hands are); a part from before
// slots that was framed keeps that framing. As scenes.py frame_for.
export function frameFor(p, shape, lane) {   // eslint-disable-line no-unused-vars
  const legacy = { x: p.focusX, y: p.focusY, zoom: p.zoom || 1 }
  if (shape === 'full') return legacy
  if (p.frames == null && !(legacy.x === 0.5 && legacy.y === 0.5 && legacy.zoom === 1)) return legacy
  const f = p.frames?.[shape]
  if (f) return { x: f.x, y: f.y, zoom: f.zoom || 1 }
  return { x: legacy.x, y: 1, zoom: 1 }
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

// seconds of the clip from ain at real speed, skipping its lulls: pieces.
// Shorter than asked when the clip runs out. As montage.py quiet_fill.
export function quietFill(points, ain, end, seconds) {
  const pieces = end - ain > seconds ? quietCut(points || [], ain, end - ain) : [[ain, end - ain]]
  const out = []
  let got = 0
  for (const [st, l] of pieces) {
    const take = Math.min(l, seconds - got)
    if (take <= 0.04) break
    out.push([round3(st), round3(take)])
    got += take
  }
  return out.length ? out : [[ain, Math.min(seconds, Math.max(end - ain, 0.2))]]
}

// Each scene's stretch of its A clip, [in, out] (or null). items: id → part;
// pointsOf(id): its movement measure (for skipping quiet moments). At real
// speed a scene takes as much of the clip as it lasts, carrying on from the
// scene before, up to the clip's end; only fit squeezes A's range in. As
// montage.py resolve_a.
export function resolveA(scenes, secs, items, pointsOf = () => null) {
  const out = scenes.map(() => null)
  const cursor = new Map()
  const shows = scenes.map((sc, i) => i).filter((i) => showsA(scenes[i]) && scenes[i].a && !isRelay(scenes, i) && items.get(scenes[i].a.item))
  shows.forEach((i, n) => {
    const a = scenes[i].a
    const timing = aTiming(scenes[i])
    const it = items.get(a.item)
    const start = it.start
    const end = timing === 'fit' ? it.start + it.length : (it.media.duration || it.start + it.length)
    const speed = a.speed || 1
    let ain = a.in != null ? a.in : (cursor.has(a.item) ? cursor.get(a.item) : start)
    ain = Math.min(Math.max(ain, start), end - 0.2)
    let aout
    if (timing === 'quiet') {
      const pieces = quietFill(pointsOf(a.item), ain, end, secs[i])
      const [ls, ll] = pieces[pieces.length - 1]
      aout = ls + ll
    } else if (timing !== 'fit') aout = Math.min(end, ain + secs[i] * (timing === 'hold' ? speed : 1))
    else if (a.out != null) aout = Math.min(Math.max(a.out, ain + 0.2), end)
    else {
      let stop = end
      let need = 0
      let share = secs[i]
      for (const j of shows.slice(n + 1)) {
        const b = scenes[j].a
        if (b.item !== a.item) continue
        if (b.in != null) { stop = Math.min(stop, b.in); break }
        if (aTiming(scenes[j]) === 'fit') {
          if (b.out != null) { stop = Math.min(stop, b.out); break }
          share += secs[j]
        } else need += secs[j] * (aTiming(scenes[j]) === 'hold' ? (b.speed || 1) : 1)
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

// The pieces of the A clip a scene plays, and how fast (1× unless a speed
// was asked for). It holds its last frame if they run out before the scene.
export function sceneAPlan(sc, range, seconds, points, duration) {
  const [ain, aout] = range
  const length = aout - ain
  const timing = aTiming(sc)
  if (timing === 'hold') return { pieces: [[ain, length]], rate: sc.a?.speed || 1 }
  if (timing === 'quiet') return { pieces: quietFill(points, ain, duration || aout, seconds), rate: 1 }
  if (timing === 'fit') return { pieces: [[ain, length]], rate: length / Math.max(seconds, 0.04) }
  return { pieces: [[ain, length]], rate: 1 }
}
// How long a scene's A runs short of the scene (holding its last frame).
export const aShort = (plan, seconds) => Math.max(0, seconds - plan.pieces.reduce((s, [, l]) => s + l, 0) / plan.rate)

export function layoutLabel(v, wide) {
  const l = LAYOUTS.find((x) => x.v === v)
  return l ? (wide && l.wide) || l.label : v
}

// ---------------------------------------------------------------- relay plans

// How a relay shares out the frame (as scenes.py relay_overlaps and
// relay_plan, for the New reel dialog's estimate). clips: [{long, kind,
// duration, avail}]; mix: single | even | split. Returns {total, split}
// seconds.
export const RELAY_MIX = { single: null, even: 0.5, split: 0.8 }
export const ALONE_MIN = 1
export function relayEstimate(clips, { overlap = 3, solo = 3, cap = 0, mix = 'single' } = {}) {
  const n = clips.length
  if (!n) return { total: 0, split: 0 }
  const timeOf = (c) => (c.long ? (cap ? Math.min(c.avail, cap) : c.avail) : solo)
  const f = RELAY_MIX[mix] ?? null
  let shared
  let alones
  if (f === null) {
    shared = Array(n - 1).fill(overlap)
    alones = clips.map((c, i) => (c.long ? Math.max(solo, timeOf(c) - (i ? overlap : 0) - (i < n - 1 ? overlap : 0)) : solo))
  } else {
    const q = (2 * f) / (1 + f)
    const times = clips.map(timeOf)
    const sides = clips.map((c, i) => (i > 0) + (i < n - 1))
    const want = clips.map((c, i) => (c.long && sides[i] ? (q * times[i]) / sides[i] : null))
    shared = []
    for (let i = 0; i < n - 1; i++) {
      const w = [want[i], want[i + 1]].filter((x) => x !== null)
      shared.push(w.length ? w.reduce((a, b) => a + b, 0) / w.length : q * solo)
    }
    const shortAlone = Math.max(ALONE_MIN, solo * (1 - q))
    for (let pass = 0; pass < 3; pass++) {
      clips.forEach((c, i) => {
        const left = i ? shared[i - 1] : 0
        const right = i < n - 1 ? shared[i] : 0
        let room
        if (c.long) room = times[i] - ALONE_MIN
        else if (c.kind === 'video') room = Math.max(c.duration - shortAlone, 1)
        else return
        if (left + right > room) {
          const k = Math.max(room, 1) / (left + right)
          if (i) shared[i - 1] *= k
          if (i < n - 1) shared[i] *= k
        }
      })
    }
    shared = shared.map((o) => Math.max(o, 0.5))
    // a long clip's time alone held to the mix (as scenes.py)
    alones = clips.map((c, i) => {
      if (!c.long) return shortAlone
      const split = (i ? shared[i - 1] : 0) + (i < n - 1 ? shared[i] : 0)
      return Math.max(ALONE_MIN, Math.min(times[i] - split, (split * (1 - f)) / f))
    })
  }
  const split = shared.reduce((a, b) => a + b, 0)
  return { total: split + alones.reduce((a, b) => a + b, 0), split }
}
