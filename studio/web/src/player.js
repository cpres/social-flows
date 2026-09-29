import { onBeforeUnmount, onMounted, ref } from 'vue'

// Playhead tracking plus "play just this part, on a loop".
export function usePlayer(range) {
  const video = ref(null)
  const playhead = ref(0)
  const playing = ref(false)
  const looping = ref(false)
  const failed = ref(false)

  let raf
  function tick() {
    const v = video.value
    if (v) {
      playhead.value = v.currentTime
      const r = range()
      if (looping.value && r && !v.paused && v.currentTime >= r.start + r.length) v.currentTime = r.start
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
    if (v.paused) v.play()
    else { v.pause(); looping.value = false }
  }
  function playPart() {
    const v = video.value
    const r = range()
    if (!v || !r) return
    if (looping.value && !v.paused) { v.pause(); looping.value = false; return }
    looping.value = true
    v.currentTime = r.start
    v.play()
  }
  function reset() {
    looping.value = false
    failed.value = false
  }
  const events = {
    onPlay: () => { playing.value = true },
    onPause: () => { playing.value = false },
    onError: () => { failed.value = true },
  }
  return { video, playhead, playing, looping, failed, seek, toggle, playPart, reset, events }
}
