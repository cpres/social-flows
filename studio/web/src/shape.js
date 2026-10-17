import { ref, watch } from 'vue'

// A reel is portrait (the default, for Reels and Stories) or landscape. Same
// sizes as the server's ORIENTATIONS.
export const SHAPES = [
  { v: 'portrait', label: 'Portrait', icon: '▯', ratio: '9:16', w: 1080, h: 1920 },
  { v: 'landscape', label: 'Landscape', icon: '▭', ratio: '16:9', w: 1920, h: 1080 },
]
export const shapeOf = (v) => SHAPES.find((s) => s.v === v) || SHAPES[0]
export const aspect = (v) => shapeOf(v).w / shapeOf(v).h

// The shape the shoot page frames clips for, before they're in a reel.
// Remembered per browser.
const KEY = 'footage-studio-shoot-shape'

function initial() {
  try {
    const saved = localStorage.getItem(KEY)
    if (SHAPES.some((s) => s.v === saved)) return saved
  } catch { /* storage unavailable */ }
  return 'portrait'
}

export const shootShape = ref(initial())
watch(shootShape, (v) => {
  try { localStorage.setItem(KEY, v) } catch { /* storage unavailable */ }
})
