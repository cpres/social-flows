import { onBeforeUnmount, onMounted } from 'vue'

// Re-run `load` when you come back to the browser (e.g. after dropping new
// clips in from Finder), at most every few seconds.
export function useRefreshOnFocus(load, minGap = 3000) {
  let last = Date.now()
  const maybe = () => {
    if (document.visibilityState !== 'visible' || Date.now() - last < minGap) return
    last = Date.now()
    load()
  }
  onMounted(() => {
    window.addEventListener('focus', maybe)
    document.addEventListener('visibilitychange', maybe)
  })
  onBeforeUnmount(() => {
    window.removeEventListener('focus', maybe)
    document.removeEventListener('visibilitychange', maybe)
  })
}
