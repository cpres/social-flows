// Display low quality: the editor plays small copies of the videos (made
// once per file by the server) so previewing is quick. Renders always use
// the originals. Remembered in this browser.
import { ref, watch } from 'vue'

const KEY = 'footage-studio:low-quality'
export const lowQuality = ref((() => { try { return localStorage.getItem(KEY) === '1' } catch { return false } })())
watch(lowQuality, (v) => { try { localStorage.setItem(KEY, v ? '1' : '0') } catch { /* storage unavailable */ } })
