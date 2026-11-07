// Display low quality: the editor plays small copies of the videos (made
// once per file by the server) so previewing is quick. Renders always use
// the originals. Remembered in this browser.
import { reactive, ref, watch } from 'vue'

const KEY = 'footage-studio:low-quality'
export const lowQuality = ref((() => { try { return localStorage.getItem(KEY) === '1' } catch { return false } })())
watch(lowQuality, (v) => { try { localStorage.setItem(KEY, v ? '1' : '0') } catch { /* storage unavailable */ } })

// The videos (folder/file) whose small copy is made. A video's URL asks for
// the copy only once it's here, so the URL changes when it's ready and the
// player switches over; until then the original plays.
export const lowMade = reactive(new Set())
export function noteLowMade(paths) { for (const p of paths || []) lowMade.add(p) }
