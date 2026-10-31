import { api } from './api'
import { ECHO_GAP, fxTail } from './captions'

const FX_EDGE = 0.025   // crossfade between the plain voice and an effect, as the render

// Plays a reel's voice pieces from any point on the reel, each starting
// exactly when it lands (Web Audio, so pieces of different takes line up).
// Phrases with an effect play through a rough version of it (the render
// does the real thing). The takes are fetched and decoded once.
export function useVoicePlayer() {
  let ctx = null
  const buffers = new Map()   // "folder/file" -> Promise<AudioBuffer>
  let playing = []
  const irs = new Map()

  const keyOf = (p) => `${p.folder}/${p.file}`
  function context() {
    if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)()
    if (ctx.state === 'suspended') ctx.resume()
    return ctx
  }
  function load(p) {
    const key = keyOf(p)
    if (!buffers.has(key)) {
      const c = context()
      buffers.set(key, fetch(api.voiceAudio(p.folder, p.file))
        .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(r.statusText))))
        .then((data) => new Promise((ok, fail) => c.decodeAudioData(data, ok, fail)))
        .catch((e) => { buffers.delete(key); throw e }))
    }
    return buffers.get(key)
  }

  // The hall: a burst of noise dying away, like the render's.
  function impulse(c, length) {
    const key = length.toFixed(2)
    if (!irs.has(key)) {
      const n = Math.round(length * c.sampleRate)
      const ir = c.createBuffer(2, n, c.sampleRate)
      for (let ch = 0; ch < 2; ch++) {
        const d = ir.getChannelData(ch)
        for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * Math.exp((-6.9 * i) / n)
      }
      irs.set(key, ir)
    }
    return irs.get(key)
  }
  function lfo(c, hz, depth, target, when, until) {
    const osc = c.createOscillator()
    osc.frequency.value = hz
    const g = c.createGain()
    g.gain.value = depth
    osc.connect(g).connect(target)
    osc.start(when)
    osc.stop(until)
    playing.push(osc)
  }
  // An effect's nodes, from `input` to `output`, running from `when` to `until`.
  function effect(c, f, input, output, when, until) {
    const a = f.amount || 1
    const tap = (delay, gain) => {
      const d = c.createDelay(2)
      d.delayTime.value = delay
      const g = c.createGain()
      g.gain.value = gain
      input.connect(d).connect(g).connect(output)
      return d
    }
    if (f.effect === 'echo') {
      tap(0, 0.9)
      ;[0.5, 0.3, 0.18].forEach((dec, i) => tap(ECHO_GAP * (i + 1), Math.min(0.95, dec * a) * 0.9))
    } else if (f.effect === 'hall') {
      tap(0, 1)
      const conv = c.createConvolver()
      conv.buffer = impulse(c, fxTail('hall', a))
      const g = c.createGain()
      g.gain.value = 0.45 * a
      input.connect(conv).connect(g).connect(output)
    } else if (f.effect === 'waver') {
      const d = tap(0.006, 1)
      lfo(c, 5, 0.0012 * (0.4 + 0.6 * a), d.delayTime, when, until)
    } else if (f.effect === 'pulse') {
      const depth = Math.min(0.95, 0.35 + 0.3 * a)
      const g = c.createGain()
      g.gain.value = 1 - depth / 2
      input.connect(g)
      const out = c.createGain()
      out.gain.value = 1.2
      g.connect(out).connect(output)
      lfo(c, 6, depth / 2, g.gain, when, until)
    } else {   // doubled
      tap(0, 0.7 * 0.75)
      ;[[0.04, 0.5, 1.5, 0.0003], [0.06, 0.45, 2, 0.0004], [0.08, 0.4, 1.2, 0.0003]].forEach(([delay, dec, hz, depth]) => {
        const d = tap(delay, Math.min(0.9, dec * a) * 0.75)
        lfo(c, hz, depth, d.delayTime, when, until)
      })
    }
  }

  // Play `buf` from `offset` for `dur`, at `when`, fading in and out over `edge`.
  function source(c, buf, when, offset, dur, edge, dest) {
    const src = c.createBufferSource()
    src.buffer = buf
    const gain = c.createGain()
    gain.gain.setValueAtTime(0, when)
    gain.gain.linearRampToValueAtTime(1, when + edge)
    gain.gain.setValueAtTime(1, Math.max(when + edge, when + dur - edge))
    gain.gain.linearRampToValueAtTime(0, when + dur)
    src.connect(gain).connect(dest)
    src.start(when, offset, dur)
    playing.push(src)
    return gain
  }

  // Start the pieces playing as if the reel were at `from` (seconds) now.
  // Takes still loading join in, at the right place, once they're ready.
  function play(pieces, from) {
    stop()
    const c = context()
    const t0 = c.currentTime + 0.03
    const token = {}
    playing = [token]
    for (const p of pieces) {
      const end = p.at + p.length
      const tails = (p.fx || []).map((f) => p.at + f.e - p.start + fxTail(f.effect, f.amount))
      if (Math.max(end, ...tails) <= from) continue
      load(p).then((buf) => {
        if (!playing.includes(token)) return
        const now = from + Math.max(0, c.currentTime - t0)   // time spent loading
        const clock = (reelT) => c.currentTime + (reelT - now)   // reel time -> context time
        if (end > now) {
          const offset = p.start + Math.max(0, now - p.at)
          const g = source(c, buf, clock(Math.max(now, p.at)), offset, end - Math.max(now, p.at), 0.04, c.destination)
          // The plain voice steps aside for each phrase with an effect.
          for (const f of p.fx || []) {
            const r0 = clock(p.at + f.s - p.start)
            const r1 = clock(p.at + f.e - p.start)
            if (r1 <= c.currentTime) continue
            g.gain.setValueAtTime(1, Math.max(c.currentTime, r0))
            g.gain.linearRampToValueAtTime(0, Math.max(c.currentTime, r0 + FX_EDGE))
            g.gain.setValueAtTime(0, Math.max(c.currentTime, r1 - FX_EDGE))
            g.gain.linearRampToValueAtTime(1, Math.max(c.currentTime, r1))
          }
        }
        for (const f of p.fx || []) {
          const at = p.at + f.s - p.start
          if (at < now) continue   // started before this point: skip it rather than start mid-phrase
          const when = clock(at)
          const until = when + (f.e - f.s) + fxTail(f.effect, f.amount)
          const bus = c.createGain()
          effect(c, f, bus, c.destination, when, until)
          source(c, buf, when, f.s, f.e - f.s, FX_EDGE, bus)
        }
      }).catch(() => {})
    }
  }

  function stop() {
    for (const s of playing) if (s.stop) { try { s.stop() } catch { /* not started */ } }
    playing = []
  }

  // Fetch and decode ahead, so pressing play starts the voice straight away.
  const prepare = (pieces) => Promise.all(pieces.map((p) => load(p).catch(() => null)))

  return { play, stop, prepare, context }
}
