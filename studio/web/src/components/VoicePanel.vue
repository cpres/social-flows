<template>
  <section class="panel voicepanel">
    <div class="vcol">
      <header class="vhead">
        <h3>Voice</h3>
        <span class="muted small" v-if="tl.pieces.length">
          {{ tl.pieces.length }} piece{{ tl.pieces.length === 1 ? '' : 's' }} · ends at {{ fmtTime(tl.end) }}
        </span>
        <button class="btn small" :class="{ active: adding }" @click="toggleAdd">{{ adding ? 'Close' : '+ Add a piece' }}</button>
      </header>
      <!-- the reading this reel uses: kept on its own, so other reels (another cut, a restart) can use it too -->
      <div class="readingbar">
        <label class="field">
          Reading
          <select :value="settings.readingId ?? ''" @change="useReading($event.target.value)">
            <option value="">{{ readings.length ? 'None' : 'None yet: adding a piece starts one' }}</option>
            <option v-for="r in readings" :key="r.id" :value="r.id">
              {{ r.name }}{{ r.length ? ` · ${fmtTime(r.length)}` : '' }}{{ usedElsewhere(r).length ? ` · in ${usedElsewhere(r).map((x) => x.name).join(', ')}` : '' }}
            </option>
          </select>
        </label>
        <button class="link" v-if="reading" @click="renameReading">Rename</button>
        <button class="link" v-if="reading" @click="copyReading" title="A copy of this reading for this reel alone">Make a copy</button>
        <button class="link" @click="newReading">New reading</button>
      </div>
      <p v-if="reading && usedElsewhere(reading).length" class="muted small shared">
        Also in {{ usedElsewhere(reading).map((x) => x.name).join(', ') }}: changes here change it there too.
        <button class="link" @click="copyReading">Make a copy for this reel</button>
      </p>
      <p class="muted small" v-if="!pieces.length && !adding">
        A reading over the footage, made of pieces of one or more takes: voice memos or the sound of a video.
        Pieces play one after another, with a breath between, and the song stays low under them.
      </p>

      <!-- adding: pick a take, then the lines to use from it -->
      <div class="adder" v-if="adding">
        <div class="addrow">
          <label class="field">
            Takes from
            <select v-model="addFolder">
              <option v-for="f in folders" :key="f.name" :value="f.name">
                {{ f.name === voiceFolder ? 'Voice folder (your recordings)' : folderTitle(f.name) }}{{ f.audio ? ` · 🎙 ${f.audio}` : '' }}{{ f.video ? ` · 🎬 ${f.video}` : '' }}
              </option>
            </select>
          </label>
        </div>
        <div class="downloads" v-if="downloads.length">
          <span class="muted small">Recordings in Downloads:</span>
          <span v-for="d in downloads.slice(0, 6)" :key="d.name" class="dl">
            {{ d.name }} <span class="muted">{{ fmtTime(d.duration) }}</span>
            <button class="link" @click="bringIn(d.name)">Move to the Voice folder</button>
          </span>
        </div>
        <ul class="takes" v-if="takes.length">
          <li v-for="t in sortedTakes" :key="t.file" :class="{ on: take && take.file === t.file }">
            <button class="takename" @click="pickTake(t)">
              <span>{{ t.kind === 'audio' ? '🎙' : '🎬' }}</span> {{ t.file }}
              <span class="muted mono">{{ fmtTime(t.duration) }}</span>
              <span v-if="t.readingId && t.readingId === settings.readingId" class="tag mine">this reading</span>
              <span v-else-if="t.readingId && readingName(t.readingId)" class="tag">{{ readingName(t.readingId) }}</span>
            </button>
            <span class="tstate muted small">
              <template v-if="t.status === 'done'">transcribed</template>
              <template v-else-if="t.status === 'running'">{{ t.stage === 'loading' ? 'loading the speech model…' : `listening… ${Math.round((t.progress || 0) * 100)}%` }}</template>
              <template v-else-if="t.status === 'failed'"><span class="warn" :title="t.error">couldn't transcribe</span></template>
            </span>
          </li>
        </ul>
        <p v-else class="muted small">No recordings in this folder. AirDrop a voice memo, or film the reading; both work as takes.</p>

        <div class="takebox" v-if="take">
          <div class="takehead">
            <strong>{{ take.file }}</strong>
            <button class="btn small" @click="playClip(take, 0, take.duration)">{{ auditioning === 'take' ? '■ Stop' : '▶ Listen' }}</button>
            <button
              v-if="take.status !== 'done' && take.status !== 'running'" class="btn small primary" @click="startTranscribe(take)"
              :disabled="!canTranscribe" :title="canTranscribe ? `Writes down what's said, once (${model})` : ''"
            >Transcribe</button>
            <button class="btn small" @click="addPiece(true)" title="Use the whole take as one piece">Use the whole take</button>
          </div>
          <p v-if="!canTranscribe && take.status !== 'done'" class="muted small">
            Transcribing isn't installed. Quit the studio and start it again with <code>./studio/run.sh</code> (it installs it) to pick lines by what's said
            and get captions. You can still use the whole take and trim it.
          </p>
          <p v-if="take.status === 'running'" class="muted small">
            {{ take.stage === 'loading' ? 'Loading the speech model (the first time, it downloads about 1.6 GB)…' : `Listening… ${Math.round((take.progress || 0) * 100)}%` }}
          </p>
          <template v-if="transcript">
            <p class="muted small">Click the first line you want, then shift-click the last. ▶ plays a line.</p>
            <ol class="tlines">
              <template v-for="(l, i) in transcript.lines" :key="i">
                <li v-if="l.br && i" class="gap" aria-hidden="true"></li>
                <li :class="{ picked: inRange(i) }" @click="pickLine(i, $event.shiftKey)">
                  <span class="mono muted">{{ fmtTime(l.s) }}</span>
                  <span class="tx">{{ l.text }}</span>
                  <button class="link" @click.stop="playClip(take, l.s, l.e, `l${i}`)">{{ auditioning === `l${i}` ? '■' : '▶' }}</button>
                </li>
              </template>
            </ol>
            <p v-if="!transcript.lines.length" class="muted small">Nothing was heard in this take.</p>
            <div class="addgo" v-if="range">
              <button class="btn primary" @click="addPiece(false)">
                Add line{{ range[0] === range[1] ? ` ${range[0] + 1}` : `s ${range[0] + 1}–${range[1] + 1}` }} as a piece
              </button>
              <span class="muted small">{{ fmtTime(pickStart) }} → {{ fmtTime(pickEnd) }} of the take</span>
            </div>
          </template>
        </div>
      </div>

      <!-- the voice track: pieces in order -->
      <ol class="pieces" v-if="pieces.length">
        <li v-for="(p, i) in pieces" :key="p.id" class="piece" :class="{ open: openId === p.id }">
          <div class="pgap">
            <label :for="`gap-${p.id}`">{{ i === 0 ? 'Starts after' : 'Breath before' }}</label>
            <input
              :id="`gap-${p.id}`" type="number" min="0" max="10" step="0.1" :value="p.gap"
              @change="p.gap = clampNum($event.target.value, 0, 10)"
            /> s
          </div>
          <div class="phead">
            <span class="pnum">{{ i + 1 }}</span>
            <button class="pname" @click="openId = openId === p.id ? null : p.id">
              <span class="pfile">{{ p.file }}</span>
              <span class="muted small">{{ fmtTime(at(p)) }} on the reel · {{ (p.end - p.start).toFixed(1) }}s · {{ folderTitle(p.folder) }}</span>
            </button>
            <button class="btn small" @click="playClip(p, p.start, p.end, p.id)">{{ auditioning === p.id ? '■' : '▶' }}</button>
            <button class="btn small" @click="move(i, -1)" :disabled="i === 0" title="Earlier">↑</button>
            <button class="btn small" @click="move(i, 1)" :disabled="i === pieces.length - 1" title="Later">↓</button>
            <button class="btn small" @click="openId = openId === p.id ? null : p.id">{{ openId === p.id ? 'Close' : 'Lines' }}</button>
            <button class="btn small danger" @click="remove(i)" title="Take this piece out">✕</button>
          </div>
          <div class="pbody" v-if="openId === p.id">
            <div class="trim">
              <label class="field">
                From (in the take)
                <span class="nudge">
                  <button class="btn small" @click="trim(p, 'start', -0.1)">−</button>
                  <input :value="fmtTime(p.start)" @change="setTrim(p, 'start', $event)" />
                  <button class="btn small" @click="trim(p, 'start', 0.1)">+</button>
                </span>
              </label>
              <label class="field">
                To
                <span class="nudge">
                  <button class="btn small" @click="trim(p, 'end', -0.1)">−</button>
                  <input :value="fmtTime(p.end)" @change="setTrim(p, 'end', $event)" />
                  <button class="btn small" @click="trim(p, 'end', 0.1)">+</button>
                </span>
              </label>
            </div>
            <ol class="lines">
              <template v-for="(l, j) in p.lines" :key="j">
                <li v-if="l.br && j" class="gap" aria-hidden="true"></li>
                <li :class="{ outside: l.e <= p.start || l.s >= p.end }">
                  <span class="mono muted">{{ fmtTime(at(p) + Math.max(0, l.s - p.start)) }}</span>
                  <button
                    class="br" :class="{ on: l.br }" @click="l.br = !l.br"
                    :title="l.br ? 'A new stanza starts here (click to join it to the one before)' : 'Start a new stanza here'"
                  >¶</button>
                  <input
                    class="tx" :value="l.text" @change="l.text = $event.target.value"
                    @keydown.enter.prevent="split(p, j, $event.target)" title="Enter splits the line at the cursor"
                  />
                  <button class="link" @click="playClip(p, l.s, l.e, `${p.id}-${j}`)">{{ auditioning === `${p.id}-${j}` ? '■' : '▶' }}</button>
                  <button
                    class="fxbtn" :class="{ on: fxOf(p, l), open: isFxOpen(p, j) }" @click="toggleFx(p, j)"
                    :title="fxOf(p, l) ? `${fxInfo(fxOf(p, l).effect).label} on “${fxWords(p, l)}” (click to change)` : 'Put an effect on words in this line'"
                  >{{ fxOf(p, l) ? `${fxInfo(fxOf(p, l).effect).icon} ${fxInfo(fxOf(p, l).effect).label}` : '✦' }}</button>
                  <button class="link" v-if="j < p.lines.length - 1" @click="join(p, j)" title="Join with the next line">join ↓</button>
                  <button class="link danger" @click="p.lines.splice(j, 1)" title="No caption for this line">✕</button>
                </li>
                <li v-if="isFxOpen(p, j)" class="fxedit">
                  <p class="muted small">Click the first word to lift out, shift-click the last (all of them to start with).</p>
                  <div class="words">
                    <button
                      v-for="(w, k) in lineWords(l)" :key="k" class="word" :class="{ on: k >= fxSel[0] && k <= fxSel[1] }"
                      @click="pickWord(p, l, k, $event.shiftKey)"
                    >{{ w[0] }}</button>
                  </div>
                  <div class="fxpick">
                    <button
                      v-for="f in VOICE_FX" :key="f.v" class="btn small" :class="{ active: fxOf(p, l)?.effect === f.v }"
                      @click="setFx(p, l, { effect: f.v })" :title="f.hint"
                    >{{ f.icon }} {{ f.label }}</button>
                  </div>
                  <div class="fxpick" v-if="fxOf(p, l)">
                    <button
                      v-for="a in FX_AMOUNTS" :key="a.v" class="btn small" :class="{ active: Math.abs((fxOf(p, l).amount || 1) - a.v) < 0.01 }"
                      @click="setFx(p, l, { amount: a.v })"
                    >{{ a.label }}</button>
                    <span class="spacer"></span>
                    <button class="btn small" @click="hearFx(p, fxOf(p, l))">▶ Hear it</button>
                    <button class="link danger" @click="removeFx(p, l)">Remove effect</button>
                  </div>
                  <p class="muted small" v-if="fxOf(p, l)">{{ fxInfo(fxOf(p, l).effect).hint }}. Play reel gives a rough version; the render does the real thing.</p>
                </li>
              </template>
            </ol>
            <!-- the lines come from what's said: transcribe right here, they fill in when it's done -->
            <div class="lineacts">
              <span v-if="stateOf(p).busy" class="small muted">Starting…</span>
              <span v-else-if="stateOf(p).status === 'running'" class="small">
                {{ stateOf(p).stage === 'loading' ? 'Loading the speech model (the first time, it downloads about 1.6 GB)…'
                  : `Transcribing… ${Math.round((stateOf(p).progress || 0) * 100)}%` }}
                <span class="muted">The lines fill in when it's done.</span>
              </span>
              <button
                v-else-if="stateOf(p).status !== 'done' && stateOf(p).status !== 'failed'" class="btn small primary" @click="captureLines(takeOf(p))"
                :disabled="!canTranscribe" :title="canTranscribe ? 'Write down what\'s said; the lines fill in when it\'s done' : ''"
              >Transcribe</button>
              <button v-else class="btn small" @click="redoLines(p)">
                {{ p.lines.length ? 'Lines from what\'s said again' : 'Lines from what\'s said' }}
              </button>
              <button class="btn small" :class="{ active: pasteFor === p.id }" @click="pasteFor = pasteFor === p.id ? null : p.id">Paste the written text</button>
            </div>
            <div class="paste" v-if="pasteFor === p.id">
              <textarea v-model="pasteText" rows="6" placeholder="One caption line per line; a blank line between stanzas."></textarea>
              <button class="btn small primary" @click="timeText(p)" :disabled="!pasteText.trim()">Time it to the voice</button>
              <span class="muted small">Your words and line breaks are kept; each line is timed to where it's said.</span>
            </div>
            <p v-if="stateOf(p).status === 'failed'" class="small">
              <span class="warn">Couldn't transcribe: {{ stateOf(p).error }}</span>
              <button class="link" @click="captureLines(takeOf(p), true)" v-if="canTranscribe">Try again</button>
            </p>
            <p v-else-if="!canTranscribe && stateOf(p).status !== 'done'" class="muted small">
              Transcribing isn't installed: quit the studio and start it again with <code>./studio/run.sh</code>, which installs it.
              Or paste the text.
            </p>
            <p v-if="lineNote" class="muted small">{{ lineNote }}</p>
          </div>
        </li>
      </ol>

      <div class="levels" v-if="pieces.length">
        <label class="field">
          Song under the voice
          <select v-model.number="settings.voiceSongUnder">
            <option v-for="v in [0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4]" :key="v" :value="v">{{ Math.round(v * 100) }}%</option>
          </select>
        </label>
        <label class="field">
          Song in the breaths
          <select v-model.number="settings.voiceSongBetween">
            <option v-for="v in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8]" :key="v" :value="v">{{ Math.round(v * 100) }}%</option>
          </select>
        </label>
        <label class="field check">
          <span><input type="checkbox" v-model="settings.voiceClean" /> Clean up the voice</span>
          <small>Cuts low rumble and steady hiss.</small>
        </label>
        <label class="field check">
          <span><input type="checkbox" v-model="settings.voiceFit" /> Fit to the voice</span>
          <small>{{ settings.voiceFit ? 'The last part holds until the reading ends, then the end card.' : 'The voice is cut where the parts end.' }}</small>
        </label>
      </div>
    </div>

    <!-- how the captions look -->
    <div class="ccol">
      <header class="vhead">
        <h3>Captions</h3>
        <label class="check"><input type="checkbox" v-model="settings.captions" /> Show the words</label>
      </header>
      <div class="stylepick">
        <button
          v-for="s in CAPTION_STYLES" :key="s.v" class="btn small" :class="{ active: settings.captionStyle === s.v }"
          @click="setStyle(s.v)" :title="s.hint"
        >{{ s.label }}</button>
      </div>
      <p class="muted small">{{ styleOf(settings.captionStyle).hint }}.</p>
      <div class="cfields">
        <label class="field">
          Font
          <select v-model="settings.captionFont">
            <option v-for="f in CAPTION_FONTS" :key="f.v" :value="f.v">{{ f.label }}</option>
          </select>
        </label>
        <label class="field">
          Background
          <select v-model="settings.captionBg">
            <option v-for="b in CAPTION_BGS" :key="b.v" :value="b.v">{{ b.label }}</option>
          </select>
        </label>
        <label class="field">
          Size
          <select v-model.number="settings.captionSize">
            <option v-for="z in CAPTION_SIZES" :key="z.v" :value="z.v">{{ z.label }}</option>
          </select>
        </label>
        <label class="field check fxshow">
          <span><input type="checkbox" v-model="settings.captionFx" /> Show effects in the words</span>
          <small>Echo leaves ghosts, hall glows, waver trembles, pulse throbs, doubled drifts.</small>
        </label>
        <label class="field" v-if="settings.captionStyle === 'page'">
          Title over the words
          <input v-model="settings.captionTitle" placeholder="Planting garlic in October" />
        </label>
      </div>

      <!-- why there are no captions yet, and what to do about it -->
      <div class="nolines" v-if="!tl.lines.length">
        <p v-if="!pieces.length"><b>No captions yet.</b> Add a piece of a recording under <em>Voice</em>, and its words show up here.</p>
        <template v-else>
          <p><b>No captions yet:</b> the voice has no lines.</p>
          <div v-for="w in waiting" :key="w.key" class="wtake">
            <span class="mono">{{ w.file }}</span>
            <span class="small">
              <template v-if="w.busy">getting its words…</template>
              <template v-else-if="w.status === 'running'">
                {{ w.stage === 'loading' ? 'loading the speech model (the first time, it downloads about 1.6 GB)…' : `transcribing… ${Math.round((w.progress || 0) * 100)}%` }}
                The captions fill in when it's done.
              </template>
              <template v-else-if="w.status === 'failed'"><span class="warn">couldn't transcribe: {{ w.error }}</span></template>
              <template v-else-if="w.status === 'done' && !w.words">the transcript has no words in it.</template>
              <template v-else-if="w.status === 'done' && !w.inside">
                it heard {{ w.words }} words, but none between {{ fmtTime(w.start) }} and {{ fmtTime(w.end) }}, the part of the take this piece uses.
              </template>
              <template v-else-if="w.status === 'done'">it heard {{ w.words }} words ({{ w.inside }} in this piece).</template>
              <template v-else-if="!canTranscribe">transcribing isn't installed: quit the studio and start it again with <code>./studio/run.sh</code>, which installs it.</template>
              <template v-else>not transcribed yet.</template>
            </span>
            <span class="wbtns">
              <button
                v-if="w.status !== 'running' && (canTranscribe || w.status === 'done')" class="btn small primary"
                @click="captureLines(w)" :disabled="w.busy"
              >Make captions from what's said</button>
              <button
                v-if="canTranscribe && (w.status === 'done' || w.status === 'failed')" class="link"
                @click="captureLines(w, true)" :disabled="w.busy" title="Throw away what it heard and listen again"
              >Transcribe again</button>
            </span>
          </div>
          <p class="small muted">Or type the words yourself: open the piece's <em>Lines</em> and use <em>Paste the written text</em>.</p>
        </template>
      </div>

      <div class="cpreview">
        <div class="pframe" :style="{ aspectRatio: frameRatio }">
          <img v-if="previewThumb" :src="previewThumb" alt="" />
          <img v-if="rendered" class="rendered" :src="rendered" alt="As rendered" />
          <CaptionLayer
            v-if="settings.captions && !rendered" :lines="tl.lines" :variant="settings.captionStyle" :font="settings.captionFont"
            :bg="settings.captionBg" :size="Number(settings.captionSize) || 1" :title="settings.captionTitle || ''" :t="pt"
            :fx="settings.captionFx !== false" :ratio="ratio"
          />
        </div>
        <div class="pctl">
          <label class="field">
            At <span class="mono">{{ fmtTime(pt) }}</span>
            <input type="range" min="0" :max="Math.max(reelLength, tl.end, 1)" step="0.05" v-model.number="pt" @input="rendered = ''" />
          </label>
          <div class="jumps" v-if="tl.lines.length">
            <button class="link" @click="stepLine(-1)">← line</button>
            <button class="link" @click="stepLine(1)">line →</button>
          </div>
          <button class="btn small" @click="renderFrame" :disabled="!tl.lines.length || !settings.captions || busyFrame">
            {{ busyFrame ? 'Drawing…' : 'Show as rendered' }}
          </button>
          <button v-if="rendered" class="link" @click="rendered = ''">Back to the live preview</button>
          <p class="warn small" v-if="frameError">{{ frameError }}</p>
          <p class="muted small">Play reel shows the captions and plays the voice too.</p>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { fmtTime, folderTitle, parseTime } from '../time'
import {
  CAPTION_BGS, CAPTION_FONTS, CAPTION_SIZES, CAPTION_STYLES, FX_AMOUNTS, fxInfo, fxTail, styleOf, VOICE_FX, voiceTimeline,
} from '../captions'
import { useVoicePlayer } from '../voicePlayer'
import { shapeOf } from '../shapes'
import CaptionLayer from './CaptionLayer.vue'

const props = defineProps({
  reelId: { type: Number, required: true },
  settings: { type: Object, required: true },     // the reel's settings (saved by the reel page)
  reelLength: { type: Number, default: 0 },
  partAt: { type: Function, required: true },     // reel time -> { item, src, thumb } or null
  flush: { type: Function, default: () => Promise.resolve() },
  reelName: { type: String, default: '' },
})
const settings = props.settings
// The preview frame takes the reel's shape (a Stack reel is always tall).
const frameShape = computed(() => shapeOf(settings.format === 'stack' ? 'tall' : settings.shape))
const frameRatio = computed(() => `${frameShape.value.w} / ${frameShape.value.h}`)
const ratio = computed(() => frameShape.value.w / frameShape.value.h)
if (!Array.isArray(settings.voice)) settings.voice = []
const pieces = computed(() => settings.voice)
const tl = computed(() => voiceTimeline(settings.voice))
const at = (p) => tl.value.pieces.find((q) => q.id === p.id)?.at ?? 0
const clampNum = (v, lo, hi) => Math.min(hi, Math.max(lo, Math.round((Number(v) || 0) * 100) / 100))
const newId = () => Math.random().toString(36).slice(2, 10)

// ---------------------------------------------------------------- readings

// The voice track lives in a reading (saved apart from the reel, by the reel
// page), so a restarted reel, or another cut of the same piece, can use it.
const readings = ref([])
const reading = computed(() => readings.value.find((r) => r.id === settings.readingId) || null)
const usedElsewhere = (r) => r.reels.filter((x) => x.id !== props.reelId)
const readingName = (rid) => readings.value.find((r) => r.id === rid)?.name || ''
async function loadReadings() {
  try { readings.value = await api.readings() } catch { /* an older server */ }
}
async function useReading(value) {
  await props.flush()   // anything unsaved goes to the reading it was made in
  if (!value) {
    settings.readingId = null
    settings.voice = []
    return
  }
  await loadReadings()
  const r = readings.value.find((x) => x.id === Number(value))
  if (!r) return
  settings.readingId = r.id
  settings.voice = JSON.parse(JSON.stringify(r.pieces))
  openId.value = null
}
// A reading for this reel to put its pieces in, made the first time it needs one.
async function ensureReading() {
  if (settings.readingId) return settings.readingId
  const r = await api.createReading({ name: props.reelName || 'Reading', pieces: settings.voice })
  settings.readingId = r.id
  await loadReadings()
  return r.id
}
async function newReading() {
  const name = window.prompt('Name the new reading', props.reelName || '')
  if (name === null) return
  await props.flush()
  const r = await api.createReading({ name: name.trim() || props.reelName || 'Reading' })
  await loadReadings()
  await useReading(r.id)
  adding.value = true
}
async function copyReading() {
  const r0 = reading.value
  const suggest = props.reelName && props.reelName !== r0.name ? props.reelName : `${r0.name} (copy)`
  const name = window.prompt('Name the copy (for this reel alone)', suggest)
  if (name === null) return
  await props.flush()
  const r = await api.createReading({ name: name.trim() || `${r0.name} (copy)`, copyOf: r0.id })
  await loadReadings()
  await useReading(r.id)
}
async function renameReading() {
  const name = window.prompt('Rename this reading', reading.value.name)
  if (!name?.trim()) return
  await api.saveReading(reading.value.id, { name: name.trim() })
  await loadReadings()
}

// ---------------------------------------------------------------- takes

const folders = ref([])
const canTranscribe = ref(false)
const model = ref('')
const adding = ref(false)
const addFolder = ref('')
const takes = ref([])
const downloads = ref([])
const take = ref(null)
const transcript = ref(null)
const range = ref(null)

const voiceFolder = ref('Voice')
onMounted(async () => {
  loadReadings()
  try {
    const r = await api.voiceFolders()
    folders.value = r.folders
    voiceFolder.value = r.voiceFolder || 'Voice'
    canTranscribe.value = r.transcribe
    model.value = r.model
  } catch { /* an older server */ }
  if (!pieces.value.length) adding.value = true
})

// The Voice folder, unless this reading's last piece came from a shoot.
function defaultFolder() {
  const last = pieces.value[pieces.value.length - 1]
  if (last && folders.value.some((f) => f.name === last.folder)) return last.folder
  return voiceFolder.value
}
// This reading's takes first, then the ones not in any reading, then the rest.
const sortedTakes = computed(() => {
  const rank = (t) => (t.readingId && t.readingId === settings.readingId ? 0 : t.readingId ? 2 : 1)
  return [...takes.value].sort((a, b) => rank(a) - rank(b))
})
watch([adding, folders], () => { if (adding.value && !addFolder.value) addFolder.value = defaultFolder() })
watch(addFolder, (f) => { take.value = null; transcript.value = null; if (f) loadTakes() })

async function loadTakes() {
  const folder = addFolder.value
  const [r, d] = await Promise.all([api.voiceTakes(folder), api.voiceDownloads().catch(() => ({ files: [] }))])
  if (folder !== addFolder.value) return
  takes.value = r.takes
  canTranscribe.value = r.transcribe
  downloads.value = d.files
  if (takes.value.some((t) => t.status === 'running')) pollTakes()
}
function toggleAdd() {
  adding.value = !adding.value
  if (adding.value && addFolder.value) loadTakes()
}
async function bringIn(name) {
  const r = await api.importVoice([name], settings.readingId)
  addFolder.value = r.folder
  await loadTakes()
  const t = takes.value.find((x) => x.file === r.file)
  if (t) pickTake(t)
}

async function pickTake(t) {
  take.value = t
  transcript.value = null
  range.value = null
  if (t.status === 'done') transcript.value = await api.transcript(t.folder, t.file)
}
async function startTranscribe(t) {
  try {
    Object.assign(t, await api.transcribe(t.folder, t.file))
    pollTakes()
  } catch (e) {
    Object.assign(t, { status: 'failed', error: e.message })
  }
}
let poll
function pollTakes() {
  clearInterval(poll)
  poll = setInterval(async () => {
    const running = takes.value.filter((t) => t.status === 'running')
    if (!running.length) { clearInterval(poll); return }
    for (const t of running) {
      const r = await api.transcript(t.folder, t.file).catch(() => null)
      if (!r) continue
      Object.assign(t, { status: r.status, progress: r.progress, stage: r.stage, error: r.error })
      if (r.status === 'done' && take.value === t) transcript.value = r
    }
  }, 1000)
}
onBeforeUnmount(() => clearInterval(poll))

function pickLine(i, shift) {
  if (shift && range.value) range.value = [Math.min(range.value[0], i), Math.max(range.value[1], i)]
  else range.value = [i, i]
}
const inRange = (i) => range.value && i >= range.value[0] && i <= range.value[1]
// A piece from the picked lines: a little before the first word, a little
// after the last, without catching the words either side.
const pickBounds = computed(() => {
  if (!range.value || !transcript.value) return [0, 0]
  const ls = transcript.value.lines.slice(range.value[0], range.value[1] + 1)
  const words = transcript.value.words
  const first = ls[0]
  const last = ls[ls.length - 1]
  const before = [...words].reverse().find((w) => w.e <= first.s + 0.001 && w.s < first.s)
  const after = words.find((w) => w.s >= last.e - 0.001 && w.e > last.e)
  const start = Math.max(0, first.s - 0.12, before ? before.e + 0.02 : 0)
  const end = Math.min(take.value.duration || last.e + 0.3, last.e + 0.3, after ? after.s - 0.02 : Infinity)
  return [Math.round(start * 100) / 100, Math.round(end * 100) / 100]
})
const pickStart = computed(() => pickBounds.value[0])
const pickEnd = computed(() => pickBounds.value[1])

// ---------------------------------------------------------------- lines from transcripts

// A piece added before its take was transcribed (or used whole) has no lines;
// they're filled in from the transcript once it's there, once per piece, so
// lines you clear yourself stay cleared.
const pieceStates = ref({})   // "folder/file" -> what transcribing it says
const keyOf = (p) => `${p.folder}/${p.file}`
// With no captions at all: every take the voice uses, and what its transcript says.
const waiting = computed(() => {
  const seen = new Set()
  return pieces.value.filter((p) => !seen.has(keyOf(p)) && seen.add(keyOf(p))).map((p) => {
    const st = pieceStates.value[keyOf(p)] || {}
    const words = st.words || []
    const inside = words.filter((w) => w.e > p.start && w.s < p.end).length
    return { key: keyOf(p), folder: p.folder, file: p.file, start: p.start, end: p.end, status: 'none', ...st,
             words: words.length, inside }
  })
})
// The button: the take's words become the lines of every piece that uses it
// (transcribing it first if it hasn't been, or again if asked).
const forced = new Set()
async function captureLines(w, again = false) {
  pieceStates.value = { ...pieceStates.value, [w.key]: { ...(pieceStates.value[w.key] || {}), busy: true } }
  try {
    let r = await api.transcript(w.folder, w.file)
    if (again || r.status !== 'done') {
      await api.transcribe(w.folder, w.file, again)
      r = await api.transcript(w.folder, w.file)
    }
    pieceStates.value = { ...pieceStates.value, [w.key]: r }
    forced.add(w.key)
    fillLines()
  } catch (e) {
    pieceStates.value = { ...pieceStates.value, [w.key]: { status: 'failed', error: e.message } }
  }
}
// What each take's transcript says, for the message above (once there are no captions).
let checkTimer
async function checkTakes() {
  clearTimeout(checkTimer)
  let running = false
  for (const w of waiting.value) {
    if (pieceStates.value[w.key]?.status === 'done' || pieceStates.value[w.key]?.busy) continue
    const r = await api.transcript(w.folder, w.file).catch(() => null)
    if (r) pieceStates.value = { ...pieceStates.value, [w.key]: r }
    if (r?.status === 'running') running = true
  }
  if (running) checkTimer = setTimeout(checkTakes, 2000)
}
onBeforeUnmount(() => clearTimeout(checkTimer))
let fillTimer
async function fillLines() {
  clearTimeout(fillTimer)
  const empty = pieces.value.filter((p) => forced.has(keyOf(p)) || (!p.lines?.length && !p.linesFilled))
  let running = false
  for (const key of new Set(empty.map(keyOf))) {
    const p0 = empty.find((p) => keyOf(p) === key)
    const r = await api.transcript(p0.folder, p0.file).catch(() => null)
    if (!r) continue
    pieceStates.value = { ...pieceStates.value, [key]: r }
    if (r.status === 'running') running = true
    if (r.status !== 'done') continue
    forced.delete(key)
    for (const p of empty.filter((q) => keyOf(q) === key)) {
      p.lines = copyLines(r.lines.filter((l) => l.e > p.start + 0.05 && l.s < p.end - 0.05))
      p.linesFilled = true
    }
  }
  if (running) fillTimer = setTimeout(fillLines, 2000)
  else checkTakes()
}
onMounted(fillLines)
watch(() => pieces.value.map(keyOf).join('|'), () => fillLines())
onBeforeUnmount(() => clearTimeout(fillTimer))

const copyLines = (ls) => ls.map((l, i) => ({ s: l.s, e: l.e, text: l.text, br: i === 0 ? true : !!l.br,
                                              words: l.words ? l.words.map((w) => [...w]) : [] }))

async function addPiece(whole) {
  const t = take.value
  const rid = await ensureReading()
  if (t.folder === voiceFolder.value && !t.readingId) {   // mark the take as this reading's
    api.tagTake(t.folder, t.file, rid).catch(() => {})
    t.readingId = rid
  }
  let start = 0
  let end = t.duration
  let lines = transcript.value ? copyLines(transcript.value.lines) : []
  if (!whole && range.value) {
    [start, end] = pickBounds.value
    lines = copyLines(transcript.value.lines.slice(range.value[0], range.value[1] + 1))
  }
  if (!pieces.value.length && settings.originalAudio) settings.originalAudio = false   // the clips' sound would talk over it
  const p = { id: newId(), folder: t.folder, file: t.file, start, end, gap: pieces.value.length ? 0.6 : 0.5, lines }
  settings.voice.push(p)
  openId.value = p.id
  range.value = null
  adding.value = false
}

// ---------------------------------------------------------------- pieces

const openId = ref(null)
const pasteFor = ref(null)
const pasteText = ref('')
const lineNote = ref('')

function move(i, d) {
  const [p] = settings.voice.splice(i, 1)
  settings.voice.splice(i + d, 0, p)
}
function remove(i) {
  if (!window.confirm('Take this piece out of the voice track?')) return
  settings.voice.splice(i, 1)
}
function trim(p, key, d) {
  p[key] = clampNum(p[key] + d, 0, 36000)
  if (p.end - p.start < 0.2) p[key] = key === 'start' ? p.end - 0.2 : p.start + 0.2
}
function setTrim(p, key, e) {
  const t = parseTime(e.target.value)
  if (!isNaN(t) && t >= 0) p[key] = Math.round(t * 100) / 100
  if (p.end - p.start < 0.2) p[key] = key === 'start' ? Math.max(0, p.end - 0.2) : p.start + 0.2
  e.target.value = fmtTime(p[key])
}

// Enter splits a line at the cursor: at the word there, when the words are known.
function split(p, j, input) {
  const l = p.lines[j]
  const text = input.value
  const cut = input.selectionStart
  const a = text.slice(0, cut).trim()
  const b = text.slice(cut).trim()
  if (!a || !b) return
  const n = a.split(/\s+/).length
  let mid
  if (l.words?.length && l.words.map((w) => w[0]).join(' ') === text.trim().replace(/\s+/g, ' ') && n < l.words.length) {
    mid = [l.words[n - 1][2], l.words[n][1]]
  } else {
    const t = l.s + (l.e - l.s) * (a.length / (a.length + b.length))
    mid = [t, t]
  }
  const first = { ...l, text: a, e: mid[0], words: l.words?.slice(0, n) || [] }
  const second = { s: mid[1], e: l.e, text: b, br: false, words: l.words?.slice(n) || [] }
  p.lines.splice(j, 1, first, second)
}
function join(p, j) {
  const [a, b] = [p.lines[j], p.lines[j + 1]]
  p.lines.splice(j, 2, { ...a, e: b.e, text: `${a.text} ${b.text}`, words: [...(a.words || []), ...(b.words || [])] })
}
// Every piece's take: whether it's transcribed, to show beside its lines.
const stateOf = (p) => pieceStates.value[keyOf(p)] || { status: 'none' }
const takeOf = (p) => ({ key: keyOf(p), folder: p.folder, file: p.file })
function redoLines(p) {
  if (p.lines.length && !window.confirm('Replace these lines (and your edits to them) with what\'s said?')) return
  captureLines(takeOf(p))
}
async function timeText(p) {
  lineNote.value = ''
  try {
    const r = await api.alignText({ folder: p.folder, file: p.file, start: p.start, end: p.end, text: pasteText.value })
    p.lines = copyLines(r.lines)
    pasteFor.value = null
    pasteText.value = ''
  } catch (e) {
    lineNote.value = e.message
  }
}

// ---------------------------------------------------------------- effects

// An effect lifts out a phrase: some or all of a line's words, played through
// echo, hall, waver, pulse or doubled. Stored on the piece in take time.
const fxOpen = ref(null)       // { id, j }: the line whose effect is being edited
const fxSel = ref([0, 0])      // the words picked in it
// (by a tenth of a second: an effect's soft edges may touch the next line)
const overlaps = (f, l) => Math.min(f.e, l.e) - Math.max(f.s, l.s) > 0.1
const fxOf = (p, l) => (p.fx || []).find((f) => overlaps(f, l)) || null
const isFxOpen = (p, j) => fxOpen.value && fxOpen.value.id === p.id && fxOpen.value.j === j
// A line's words with their times: the transcript's while the text still
// matches them, else the whole line as one.
function lineWords(l) {
  const w = l.words || []
  if (w.length && w.map((x) => x[0]).join(' ') === String(l.text).trim().replace(/\s+/g, ' ')) return w
  return [[l.text, l.s, l.e]]
}
function fxWords(p, l) {
  const f = fxOf(p, l)
  const ws = lineWords(l).filter((w) => w[2] > f.s + 0.02 && w[1] < f.e - 0.02)
  return (ws.length ? ws : lineWords(l)).map((w) => w[0]).join(' ')
}
function toggleFx(p, j) {
  if (isFxOpen(p, j)) { fxOpen.value = null; return }
  fxOpen.value = { id: p.id, j }
  const l = p.lines[j]
  const ws = lineWords(l)
  const f = fxOf(p, l)
  const inside = f ? ws.map((w, k) => (w[2] > f.s + 0.02 && w[1] < f.e - 0.02 ? k : -1)).filter((k) => k >= 0) : []
  fxSel.value = inside.length ? [inside[0], inside[inside.length - 1]] : [0, ws.length - 1]
}
function pickWord(p, l, k, shift) {
  fxSel.value = shift ? [Math.min(fxSel.value[0], k), Math.max(fxSel.value[1], k)] : [k, k]
  if (fxOf(p, l)) setFx(p, l, {})
}
// Put (or change) the effect on the picked words; one effect per line.
function setFx(p, l, patch) {
  const ws = lineWords(l)
  const [a, b] = fxSel.value
  const old = fxOf(p, l)
  const f = {
    id: old?.id || newId(), effect: old?.effect || 'echo', amount: old?.amount || 1, ...patch,
    s: Math.round(Math.max(l.s - 0.04, ws[a][1] - 0.04) * 1000) / 1000,
    e: Math.round(Math.min(l.e + 0.05, ws[b][2] + 0.08) * 1000) / 1000,
  }
  p.fx = [...(p.fx || []).filter((x) => !overlaps(x, l)), f].sort((x, y) => x.s - y.s)
}
function removeFx(p, l) {
  p.fx = (p.fx || []).filter((x) => !overlaps(x, l))
}
// Hear the phrase with its effect: from a moment before to the end of its echo.
const fxPlayer = useVoicePlayer()
function hearFx(p, f) {
  stopEar()
  const start = Math.max(p.start, f.s - 0.8)
  const end = Math.min(p.end, f.e + 0.6)
  fxPlayer.play([{ ...p, start, at: 0, length: end - start, fx: [f] }], 0)
}
onBeforeUnmount(() => fxPlayer.stop())

// ---------------------------------------------------------------- listening

// Listening to a take, a piece or a line: the same player Play reel uses,
// which loads the take first and then plays exactly the stretch asked for.
const earPlayer = useVoicePlayer()
const auditioning = ref(null)
let earTimer
function stopEar() {
  clearTimeout(earTimer)
  earPlayer.stop()
  auditioning.value = null
}
function playClip(src, s, e, key = 'take') {
  if (auditioning.value === key) { stopEar(); return }
  stopEar()
  fxPlayer.stop()
  auditioning.value = key
  earPlayer.play([{ folder: src.folder, file: src.file, start: s, at: 0, length: e - s, fx: [] }], 0, { wait: true },
    () => { earTimer = setTimeout(() => { if (auditioning.value === key) auditioning.value = null }, (e - s) * 1000 + 200) })
}
watch(() => pieces.value.map((p) => `${p.folder}/${p.file}`).join('|'), () => earPlayer.prepare(pieces.value), { immediate: true })
onBeforeUnmount(stopEar)

// ---------------------------------------------------------------- caption look

function setStyle(v) {
  const s = styleOf(v)
  settings.captionStyle = v
  settings.captionFont = s.font
  settings.captionBg = s.bg
  rendered.value = ''
}

const pt = ref(0)
watch(() => tl.value.lines.length, (n, old) => {
  if (n && !old) pt.value = Math.round((tl.value.lines[0].start + 0.8) * 100) / 100
}, { immediate: true })
const previewPart = computed(() => props.partAt(pt.value))
const previewThumb = computed(() => previewPart.value?.thumb || '')
function stepLine(d) {
  const ls = tl.value.lines
  const cur = ls.findIndex((l) => l.start + 0.01 >= pt.value)
  let i = d > 0 ? (cur < 0 ? ls.length - 1 : (ls[cur].start <= pt.value + 0.3 ? cur + 1 : cur)) : Math.max(0, (cur < 0 ? ls.length : cur) - 1)
  i = Math.min(Math.max(i, 0), ls.length - 1)
  pt.value = Math.round((ls[i].start + 0.6) * 100) / 100
  rendered.value = ''
}
const rendered = ref('')
const busyFrame = ref(false)
const frameError = ref('')
async function renderFrame() {
  const part = previewPart.value
  if (!part) return
  busyFrame.value = true
  frameError.value = ''
  try {
    await props.flush()
    if (rendered.value) URL.revokeObjectURL(rendered.value)
    rendered.value = await api.captionPreview(props.reelId, part.item, part.src, pt.value)
  } catch (e) {
    frameError.value = e.message
  } finally {
    busyFrame.value = false
  }
}
watch(() => [settings.captionStyle, settings.captionFont, settings.captionBg, settings.captionSize, settings.captionTitle,
  settings.captionFx],
  () => { rendered.value = '' })
</script>

<style scoped>
.voicepanel { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(300px, 1fr); gap: 28px; align-items: start; }
@media (max-width: 1000px) { .voicepanel { grid-template-columns: 1fr; } }
.vhead { display: flex; align-items: baseline; gap: 12px; margin-bottom: 8px; }
.vhead h3 { margin: 0; }
.vhead .btn, .vhead .check { margin-left: auto; }
.check { display: flex; align-items: center; gap: 6px; font-size: 14px; cursor: pointer; }
.small { font-size: 12px; }
.warn { color: var(--danger); }
.danger { color: var(--danger); }
.spacer { flex: 1; }
.link { background: none; border: 0; padding: 2px 4px; color: var(--forest); font: inherit; font-size: 13px; cursor: pointer; text-decoration: underline; text-underline-offset: 2px; }
.link:disabled { opacity: 0.5; cursor: default; }
.readingbar { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; margin-bottom: 8px; }
.readingbar .field { flex: 1 1 260px; }
.shared { margin: 0 0 10px; padding: 6px 10px; border-radius: 8px; background: var(--sage-soft); }
.tag { font-size: 11px; padding: 0 7px; border-radius: 999px; background: rgb(128 128 128 / 14%); color: var(--muted); white-space: nowrap; }
.tag.mine { background: var(--sage-soft); color: var(--forest); font-weight: 600; }
.adder { border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; background: var(--cream); margin-bottom: 14px; display: grid; gap: 10px; }
.addrow { display: flex; gap: 12px; }
.addrow .field { flex: 1; }
.downloads { display: flex; flex-wrap: wrap; gap: 6px 14px; align-items: baseline; font-size: 13px; }
.dl { display: inline-flex; gap: 6px; align-items: baseline; }
.takes { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; max-height: 200px; overflow-y: auto; }
.takes li { display: flex; align-items: center; gap: 10px; padding: 2px 6px; border-radius: 6px; }
.takes li.on { background: var(--sage-soft); }
.takename { flex: 1; text-align: left; background: none; border: 0; padding: 4px 0; cursor: pointer; display: flex; gap: 6px; align-items: baseline; min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.takebox { border-top: 1px solid var(--line); padding-top: 10px; }
.takehead { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.tlines, .lines { list-style: none; margin: 8px 0 0; padding: 0; display: grid; gap: 1px; }
.tlines { max-height: 320px; overflow-y: auto; }
.tlines li, .lines li { display: flex; gap: 10px; align-items: baseline; padding: 4px 8px; border-radius: 6px; }
.tlines li { cursor: pointer; user-select: none; }
.tlines li:hover { background: rgb(138 163 124 / 14%); }
.tlines li.picked { background: var(--sage-soft); box-shadow: inset 3px 0 0 var(--forest); }
li.gap { height: 8px; padding: 0; }
.tx { flex: 1; min-width: 0; font-size: 15px; }
.mono { font-variant-numeric: tabular-nums; }
.tlines .mono, .lines .mono { width: 52px; flex: none; font-size: 12px; }
.addgo { display: flex; gap: 12px; align-items: center; margin-top: 10px; flex-wrap: wrap; }
.pieces { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
.pgap { display: flex; gap: 6px; align-items: center; font-size: 12px; color: var(--muted); padding: 2px 0 2px 34px; }
.pgap input { width: 62px; border: 1px solid var(--line); border-radius: 6px; padding: 2px 6px; background: var(--paper); font-size: 13px; }
.phead { display: flex; gap: 6px; align-items: center; padding: 6px 8px; border: 1px solid var(--line); border-radius: 10px; background: var(--paper); }
.piece.open .phead { border-color: var(--sage); }
.pnum { width: 20px; text-align: center; font-weight: 700; color: var(--forest); }
.pname { flex: 1; min-width: 0; display: grid; background: none; border: 0; padding: 0; cursor: pointer; font: inherit; text-align: left; }
.pfile { font-weight: 600; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.pname .small { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.pbody { padding: 10px 6px 12px 34px; display: grid; gap: 8px; }
.trim { display: flex; gap: 16px; flex-wrap: wrap; }
.nudge { display: flex; gap: 4px; align-items: center; }
.nudge input { width: 88px; }
.lines li { padding: 2px 4px; }
.lines li.outside { opacity: 0.45; }
.lines .tx { border: 1px solid transparent; border-radius: 6px; padding: 3px 6px; background: transparent; color: var(--ink); }
.lines .tx:hover { border-color: var(--line); }
.lines .tx:focus { border-color: var(--sage); background: var(--paper); outline: none; }
.br { border: 1px solid var(--line); background: var(--paper); border-radius: 6px; width: 24px; height: 24px; cursor: pointer; color: var(--muted); flex: none; }
.br.on { background: var(--sage-soft); border-color: var(--sage); color: var(--forest); font-weight: 700; }
.lineacts { display: flex; gap: 8px; flex-wrap: wrap; }
.fxbtn {
  flex: none; border: 1px dashed var(--line); background: transparent; border-radius: 999px; padding: 1px 9px;
  font-size: 12px; color: var(--muted); cursor: pointer; white-space: nowrap;
}
.fxbtn:hover, .fxbtn.open { border-color: var(--warn); color: var(--warn); }
.fxbtn.on { border-style: solid; border-color: var(--warn); background: rgb(181 100 45 / 12%); color: var(--ink); font-weight: 600; }
.lines li.fxedit { display: grid; gap: 8px; margin: 2px 0 8px 62px; padding: 10px 12px; border: 1px solid var(--warn); border-radius: 10px; background: var(--paper); }
.fxedit p { margin: 0; }
.words { display: flex; flex-wrap: wrap; gap: 4px; }
.word { border: 1px solid var(--line); background: var(--cream); border-radius: 6px; padding: 2px 7px; font: inherit; font-size: 15px; cursor: pointer; color: var(--ink); }
.word.on { background: rgb(181 100 45 / 18%); border-color: var(--warn); }
.fxpick { display: flex; gap: 4px; flex-wrap: wrap; align-items: center; }
.paste { display: grid; gap: 6px; justify-items: start; }
.paste textarea { width: 100%; border: 1px solid var(--line); border-radius: 8px; padding: 8px; background: var(--paper); color: var(--ink); font: inherit; font-size: 15px; resize: vertical; }
.levels { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px 18px; margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--line); }
.field.check span { display: flex; gap: 6px; align-items: center; color: var(--ink); font-size: 14px; }
.stylepick { display: flex; gap: 4px; flex-wrap: wrap; }
.cfields { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 14px; margin: 10px 0 14px; }
.fxshow { grid-column: 1 / -1; }
.cpreview { display: flex; gap: 16px; align-items: flex-start; flex-wrap: wrap; }
.pframe { position: relative; width: 216px; aspect-ratio: 9 / 16; max-width: 100%; border-radius: 10px; overflow: hidden; background: var(--stage); flex: none; }
.pframe img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.pframe img.rendered { z-index: 3; object-fit: fill; }
.pctl { flex: 1; min-width: 160px; display: grid; gap: 8px; justify-items: start; }
.pctl .field { width: 100%; }
.pctl input[type='range'] { padding: 0; accent-color: var(--forest); }
.jumps { display: flex; gap: 10px; }
.nolines { margin: 0 0 12px; padding: 10px 12px; border-radius: 10px; background: var(--sage-soft); font-size: 14px; }
.nolines p { margin: 0 0 6px; }
.nolines p:last-child { margin-bottom: 0; }
.wtake { display: grid; gap: 4px; padding: 6px 0; border-top: 1px solid rgb(128 128 128 / 18%); }
.wbtns { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
</style>
