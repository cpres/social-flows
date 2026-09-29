import { ref, watch } from 'vue'

// light (cream) | grey (cool grey) | dark. Remembered per browser; until you
// pick one it follows the system's dark mode.
export const THEMES = [
  { v: 'light', label: 'Light' },
  { v: 'grey', label: 'Grey' },
  { v: 'dark', label: 'Dark' },
]
const KEY = 'footage-studio-theme'

function initial() {
  try {
    const saved = localStorage.getItem(KEY)
    if (THEMES.some((t) => t.v === saved)) return saved
  } catch { /* storage unavailable */ }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export const theme = ref(initial())
const apply = (t) => { document.documentElement.dataset.theme = t }
apply(theme.value)
watch(theme, (t) => {
  apply(t)
  try { localStorage.setItem(KEY, t) } catch { /* storage unavailable */ }
})
