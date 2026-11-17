// The styles a reel can be made in, as the New reel dialog offers them (and
// Import from Google Photos asks up front). footage: needs a shoot to start from.
export const STYLES = [
  { v: 'standard', label: 'Standard', hint: 'One part after another, full frame.', frames: ['b', 'b', 'b'] },
  { v: 'weave', label: 'Weave', hint: 'Clips cut into parts and interleaved: a bit of each, then back for more.', frames: ['b', 'a1', 'b'], footage: true },
  { v: 'stack', label: 'Stack', hint: 'The longest clip on top the whole way, the others underneath, at real speed.', frames: ['ab', 'ab', 'ab'], footage: true },
  { v: 'relay', label: 'Relay', hint: 'Long-form: each clip plays at its own length and hands the frame on to the next; photos come in under long clips for a moment.', frames: ['b', 'ab', 'b', 'ab'], footage: true },
]

// "6m 40s of video, 12 photos. Suggested reel: about 1:45." from a folder's content.
export function contentLine(c) {
  if (!c) return ''
  const bits = []
  if (c.videoSeconds) bits.push(`${dur(c.videoSeconds)} of video`)
  if (c.photoCount) bits.push(`${c.photoCount} photo${c.photoCount === 1 ? '' : 's'}`)
  if (!bits.length) return ''
  const s = c.suggestedTarget
  return `${bits.join(', ')}. ${s ? `Suggested reel: about ${clock(s)}.` : 'Under a minute in all: play everything.'}`
}

const dur = (s) => {
  s = Math.round(s)
  const m = Math.floor(s / 60)
  return m ? `${m}m ${s % 60}s` : `${s}s`
}
// 105 -> "1:45"
export const clock = (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`
