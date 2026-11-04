// What a reel will sound like, for the audio rows under its timeline.
//
// Each source file's loudness is measured once on the server (audio.py:
// dBFS per 40ms window). Here every stretch of the reel that plays a file is
// a segment: where it sits on the reel's clock, where it reads from in the
// file, how fast, and how loud the render makes it. Summing the segments'
// power gives what will actually be heard, without running ffmpeg again.
//
// The rules mirror the render (montage.py): which lane's sound a scene keeps
// (compose_scene), A losing its sound when it isn't at 1× (render_scene_a),
// the glasses bed under a song, the song's level and fade, and the voice
// evened out to the same loudness (finish).

export const FLOOR = -70        // dBFS: silence (audio.py)
export const SHOW_FLOOR = -54   // dBFS at the bottom of a drawn row
export const BAR = 0.4          // seconds per bar in the drawn rows
export const SOURCES = ['A', 'B', 'music', 'voice']
const VOICE_LUFS = -16          // finish(): each voice piece is loudnorm'd to this
const MUSIC_FADE = 2.0          // finish(): the song fades out over the last 2s
// The song ducks under loud glasses audio: the same numbers as montage.py's.
export const DUCK_DB = 9
const DUCK_ATTACK = 0.15
const DUCK_RELEASE = 0.4
const DUCK_THRESHOLD = -38      // dBFS of the kept glasses audio, over 0.2s
const DUCK_GAP = 0.5
const DUCK_MIN = 0.15
const WIN = 0.04                // the render measures in 40ms windows

const power = (db) => 10 ** (db / 10)
const isVideo = (p) => p?.media?.kind === 'video'

// The lane whose sound a scene keeps: the primary slot's. A in Solo A and
// A over B, B in Solo B and B over A.
export function primaryLane(sc) {
  return sc.layout === 'soloA' || sc.layout === 'stack' ? 'A' : 'B'
}

// Which glasses audio a reel keeps: primary | A | off (older reels: originalAudio).
export const GLASSES = [
  { v: 'primary', label: 'Follows primary slot', hint: 'The sound of whichever lane is top / left, or the one on its own. Swapping moves the sound with it.' },
  { v: 'A', label: 'A only', hint: 'Lane A\'s sound whenever it\'s on screen at real speed; never B\'s' },
  { v: 'off', label: 'Off', hint: 'No glasses audio: the song and voice only' },
]
export function glassesMode(settings) {
  if (GLASSES.some((g) => g.v === settings.glassesAudio)) return settings.glassesAudio
  return settings.originalAudio ? 'primary' : 'off'
}

// Every segment of every source: { A: [...], B: [...], music: [...], voice: [...] }.
// A segment: { key (which envelope), at, len (reel seconds), from (file
// seconds), rate, gain (a number or t => number), audible, loudnorm? }.
export function audioSegments(r) {
  const { sceneList, sceneTimes, stretches, aPlans, aSecs, handoffs, byId, reelLength, settings } = r
  const out = { A: [], B: [], music: [], voice: [] }
  const withSong = !!settings.music && settings.musicInVideo !== false
  const mode = glassesMode(settings)
  const glasses = mode !== 'off' ? (withSong ? Number(settings.originalVolume ?? 0.35) : 1) : 0

  sceneList.forEach((sc, k) => {
    // A relay: A's slot is the Solo B shot before, carrying on from where its part ended.
    const carry = r.carryOf?.(k)
    if (carry) {
      if (!isVideo(carry)) return
      const audible = glasses > 0 && (mode === 'A' || primaryLane(sc) === 'A')
      out.A.push({ key: carry.media.id, at: sceneTimes[k].start, len: sceneTimes[k].end - sceneTimes[k].start,
                   from: carry.start + carry.length, rate: 1, gain: glasses, audible, scene: k })
      return
    }
    const plan = aPlans[k]
    if (!plan) return
    const item = byId.get(sc.a.item)
    if (!isVideo(item)) return
    const audible = glasses > 0 && (mode === 'A' || primaryLane(sc) === 'A') && Math.abs(plan.rate - 1) < 0.01
    let t = sceneTimes[k].start + (handoffs[k] || 0)
    let left = aSecs[k]
    for (const [from, length] of plan.pieces) {
      const len = Math.min(length / plan.rate, left)
      if (len <= 0.001) break
      out.A.push({ key: item.media.id, at: t, len, from, rate: plan.rate, gain: glasses, audible, scene: k })
      t += len
      left -= len
    }
  })

  const parts = stretches.filter((st) => st.kind === 'part')
  parts.forEach((st, i) => {
    if (!isVideo(st.part)) return
    const sc = sceneList[st.scene]
    // The last part plays on to the end of the reel (held for the voice or the end card).
    const end = i === parts.length - 1 && st.scene === sceneList.length - 1 ? Math.max(st.end, reelLength) : st.end
    const audible = glasses > 0 && mode === 'primary' && (primaryLane(sc) === 'B' || (!aPlans[st.scene] && !r.carryOf?.(st.scene)))
    out.B.push({ key: st.part.media.id, at: st.start, len: end - st.start, from: st.part.start, rate: 1,
                 gain: glasses, audible, scene: st.scene })
  })

  if (withSong && reelLength > 0) {
    const fade = Math.min(MUSIC_FADE, reelLength / 3)
    // Without ducking, the song stays at its level, even through the voice.
    const level = settings.duckMusic === false && r.voicePieces?.length
      ? () => Number(settings.voiceSongBetween ?? 0.3)
      : r.songVolume || (() => Number(settings.musicVolume ?? 0.8))
    out.music.push({
      key: 'music', at: 0, len: reelLength, from: Number(settings.musicStart) || 0, rate: 1, audible: true,
      gain: (t) => level(t) * Math.min(1, Math.max(0, (reelLength - t) / fade)) * duckAt(out.duck, t),
    })
  }
  out.duck = []   // filled by withDucking(), once the envelopes are in

  // The voice is evened out in mono, then made stereo (3dB down a side).
  for (const p of r.voicePieces || []) {
    out.voice.push({ key: `${p.folder}/${p.file}`, at: p.at, len: p.length, from: Number(p.start) || 0, rate: 1,
                     gain: Math.SQRT1_2, audible: true, loudnorm: VOICE_LUFS, mono: true })
  }
  return out
}

// The gain that brings a voice piece to `target`: its speaking windows (not
// the pauses) averaged, as loudnorm roughly does.
const normCache = new WeakMap()
function normGain(seg, env) {
  if (normCache.has(seg)) return normCache.get(seg)
  let sum = 0
  let n = 0
  const a = Math.floor(seg.from / env.step)
  const b = Math.ceil((seg.from + seg.len) / env.step)
  for (let i = a; i < b && i < env.db.length; i++) {
    if (env.db[i] > -50) { sum += power(env.db[i]); n++ }
  }
  const g = n ? Math.sqrt(power(seg.loudnorm) / (sum / n)) : 1
  normCache.set(seg, g)
  return g
}

// A segment's power at reel time t (0 where it isn't playing or the file has no sound there).
export function segPower(seg, env, t) {
  if (!env?.hasAudio || t < seg.at || t >= seg.at + seg.len) return 0
  const i = Math.floor((seg.from + (t - seg.at) * seg.rate) / env.step)
  const db = env.db[i]
  if (db === undefined || db <= FLOOR) return 0
  let g = (typeof seg.gain === 'function' ? seg.gain(t) : seg.gain) * (seg.loudnorm ? normGain(seg, env) : 1)
  // The render makes every source stereo; ffmpeg spreads mono 3dB down a side.
  if (!seg.mono && env.channels === 1) g *= Math.SQRT1_2
  return power(db) * g * g
}

const height = (p) => (p > 0 ? Math.min(1, Math.max(0, (10 * Math.log10(p) - SHOW_FLOOR) / -SHOW_FLOOR)) : 0)

// Walks bars of BAR seconds, averaging power over the 40ms windows in each.
function bars(reelLength, step, each) {
  const n = Math.ceil(reelLength / step)
  const out = []
  for (let b = 0; b < n; b++) {
    const t0 = b * step
    const t1 = Math.min(reelLength, t0 + step)
    const samples = Math.max(1, Math.round((t1 - t0) / 0.04))
    out.push(each(t0, t1, samples))
  }
  return out
}

// The mix strip: [{ t, h (0..1), src (the loudest source) }], what will be heard.
export function mixBars(segs, envs, reelLength, step = BAR) {
  if (!reelLength) return []
  return bars(reelLength, step, (t0, t1, samples) => {
    const by = {}
    let total = 0
    for (const s of SOURCES) {
      let p = 0
      for (const seg of segs[s]) {
        if (!seg.audible || seg.at >= t1 - 1e-3 || seg.at + seg.len <= t0 + 1e-3) continue
        for (let j = 0; j < samples; j++) p += segPower(seg, envs[seg.key], t0 + ((j + 0.5) * (t1 - t0)) / samples)
      }
      by[s] = p / samples
      total += by[s]
    }
    const src = total > 0 ? SOURCES.reduce((a, b) => (by[b] > by[a] ? b : a)) : null
    return { t: t0, h: height(total), src }
  })
}

// One source's own row: [{ t, h, on }], on = it's heard there (else drawn dim).
// Drawn at the source's own level (before the mix's gains), so a muted clip
// still shows what's in it.
export function trackBars(list, envs, reelLength, step = BAR) {
  if (!reelLength) return []
  return bars(reelLength, step, (t0, t1, samples) => {
    let p = 0
    let on = false
    let any = false
    for (const seg of list) {
      if (seg.at >= t1 - 1e-3 || seg.at + seg.len <= t0 + 1e-3) continue
      any = true
      on = on || seg.audible
      const raw = { ...seg, gain: 1, loudnorm: 0, mono: true }
      for (let j = 0; j < samples; j++) p += segPower(raw, envs[seg.key], t0 + ((j + 0.5) * (t1 - t0)) / samples)
    }
    return { t: t0, h: any ? height(p / samples) : 0, on }
  })
}

// Orange bands: where one scene comes in over the last (its move, or a
// moment either side of a cut). A reel with one scene marks its part
// transitions instead.
export function transitionBands({ sceneList, sceneTimes, stretches, handoffs, settings, sceneIn }) {
  const out = []
  if (sceneList.length > 1) {
    sceneList.forEach((sc, k) => {
      if (!k) return
      const t = sceneTimes[k].start
      const into = sc.into || 'cut'
      if (into === 'cut') out.push({ start: t - 0.1, end: t + 0.1, k })
      else out.push({ start: t, end: t + (into === 'handoff' ? (handoffs[k] || 0) + sceneIn : sceneIn), k })
    })
    return out
  }
  const parts = stretches.filter((st) => st.kind === 'part')
  parts.forEach((st, i) => {
    if (i === parts.length - 1) return
    const tr = st.part.transition || settings.transition || 'cut'
    if (tr !== 'cut') out.push({ start: st.end - 0.15, end: st.end + 0.15, k: i + 1 })
  })
  return out
}

// ---------------------------------------------------------------- ducking

// How far the song is turned down at t, by the loud glasses runs: 1, dropping
// DUCK_DB over DUCK_ATTACK into a run and back over DUCK_RELEASE after
// (montage.py's duck_level).
const DUCK_DEPTH = 1 - 10 ** (-DUCK_DB / 20)
export function duckAt(runs, t) {
  if (!runs?.length) return 1
  let e = 0
  for (const [a, b] of runs) {
    if (t < a || t > b + DUCK_RELEASE) continue
    e += Math.min(1, Math.max(0, (t - a) / DUCK_ATTACK)) * Math.min(1, Math.max(0, (b + DUCK_RELEASE - t) / DUCK_RELEASE))
  }
  return 1 - DUCK_DEPTH * Math.min(1, e)
}

// Where the kept glasses audio is loud enough to duck the song: [[start,
// end]], found as montage.py's loud_runs() finds them in the render (40ms
// windows, averaged over 0.2s, over DUCK_THRESHOLD; short gaps joined, short
// moments dropped). Sets segs.duck, which the song's gain reads.
export function withDucking(segs, envs, reelLength, settings) {
  segs.duck = []
  if (settings.duckMusic === false || !segs.music.length) return segs
  const glasses = [...segs.A, ...segs.B].filter((s) => s.audible)
  if (!glasses.length) return segs
  const n = Math.ceil(reelLength / WIN)
  const powers = new Array(n).fill(0)
  for (const seg of glasses) {
    const env = envs[seg.key]
    if (!env) continue
    const i0 = Math.max(0, Math.floor(seg.at / WIN))
    const i1 = Math.min(n, Math.ceil((seg.at + seg.len) / WIN))
    for (let i = i0; i < i1; i++) powers[i] += segPower(seg, env, (i + 0.5) * WIN)
  }
  const on = powers.map((_, i) => {
    const near = powers.slice(Math.max(0, i - 2), i + 3)
    const p = near.reduce((a, b) => a + b, 0) / near.length
    return p > 0 && 10 * Math.log10(p) > DUCK_THRESHOLD
  })
  const runs = []
  on.forEach((x, i) => {
    if (!x) return
    const t = i * WIN
    if (runs.length && t - runs[runs.length - 1][1] < DUCK_GAP) runs[runs.length - 1][1] = t + WIN
    else runs.push([t, t + WIN])
  })
  segs.duck = runs.filter(([a, b]) => b - a >= DUCK_MIN)
  return segs
}

// The song's own row: its level (before its gains), drawn dim where it's ducked.
export function musicBars(segs, envs, reelLength, step = BAR) {
  const bars = trackBars(segs.music, envs, reelLength, step)
  return bars.map((b) => ({ ...b, on: b.on && duckAt(segs.duck, b.t + step / 2) > 0.85 }))
}
