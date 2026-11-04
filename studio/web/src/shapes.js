// The shape a reel renders at (the server's SHAPES). The first two are the
// main ones: a tall reel for Instagram, TikTok and Shorts, and a wide video
// for YouTube. A Stack reel is always tall.
export const SHAPES = [
  { v: 'tall', label: 'Reels 9:16', short: '9:16', w: 1080, h: 1920, hint: 'Instagram Reels, TikTok, YouTube Shorts' },
  { v: 'wide', label: 'YouTube 16:9', short: '16:9', w: 1920, h: 1080, hint: 'A regular YouTube video' },
  { v: 'portrait', label: '4:5', short: '4:5', w: 1080, h: 1350, hint: 'The Instagram feed' },
  { v: 'square', label: 'Square', short: '1:1', w: 1080, h: 1080, hint: 'Keeps the whole width of tall glasses footage' },
]
export const shapeOf = (v) => SHAPES.find((s) => s.v === v) || SHAPES[0]
export const shapeRatio = (v) => { const s = shapeOf(v); return s.w / s.h }
