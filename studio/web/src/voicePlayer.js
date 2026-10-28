import { api } from './api'

// Plays a reel's voice pieces from any point on the reel, each starting
// exactly when it lands (Web Audio, so pieces of different takes line up).
// The takes are fetched and decoded once, ahead of time where possible.
export function useVoicePlayer() {
  let ctx = null
  const buffers = new Map()   // "folder/file" -> Promise<AudioBuffer>
  let playing = []

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
      if (end <= from) continue
      load(p).then((buf) => {
        if (!playing.includes(token)) return
        const late = c.currentTime - t0            // time spent loading
        const now = from + Math.max(0, late)
        if (end <= now) return
        const offset = p.start + Math.max(0, now - p.at)
        const when = c.currentTime + Math.max(0, p.at - now)
        const dur = end - Math.max(now, p.at)
        const src = c.createBufferSource()
        src.buffer = buf
        const gain = c.createGain()
        gain.gain.setValueAtTime(0, when)
        gain.gain.linearRampToValueAtTime(1, when + 0.04)
        gain.gain.setValueAtTime(1, Math.max(when + 0.04, when + dur - 0.08))
        gain.gain.linearRampToValueAtTime(0, when + dur)
        src.connect(gain).connect(c.destination)
        src.start(when, offset, dur)
        playing.push(src)
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
