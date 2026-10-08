import { onBeforeUnmount, onMounted, ref } from 'vue'

// Playhead tracking plus "play just this part": plays from its start and
// stops at its end.
export function usePlayer(range) {
  const video = ref(null)
  const playhead = ref(0)
  const playing = ref(false)
  const playingPart = ref(false)
  const failed = ref(false)

  let raf
  function tick() {
    const v = video.value
    if (v) {
      playhead.value = v.currentTime
      const r = range()
      if (playingPart.value && r && !v.paused && v.currentTime >= r.start + r.length) {
        v.pause()
        v.currentTime = r.start + r.length
        playingPart.value = false
      }
    }
    raf = requestAnimationFrame(tick)
  }
  onMounted(() => { raf = requestAnimationFrame(tick) })
  onBeforeUnmount(() => cancelAnimationFrame(raf))

  function seek(t) {
    playhead.value = t
    if (video.value) video.value.currentTime = t
  }
  function toggle() {
    const v = video.value
    if (!v) return
    if (v.paused) v.play().catch(() => {})
    else { v.pause(); playingPart.value = false }
  }
  function playPart() {
    const v = video.value
    const r = range()
    if (!v || !r) return
    if (playingPart.value && !v.paused) { v.pause(); playingPart.value = false; return }
    playingPart.value = true
    v.currentTime = r.start
    v.play().catch(() => {})
  }
  function reset() {
    playingPart.value = false
    failed.value = false
  }
  const events = {
    onPlay: () => { playing.value = true },
    onPause: () => { playing.value = false },
    // The file can stop a little short of the length the server measured
    // (the container's duration, not the last frame), so a part that runs
    // to the clip's end never reaches it: treat the clip ending as its end.
    onEnded: () => { playing.value = false; playingPart.value = false },
    onError: () => { failed.value = true },
  }
  return { video, playhead, playing, playingPart, failed, seek, toggle, playPart, reset, events }
}
