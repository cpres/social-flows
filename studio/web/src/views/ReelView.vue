<template>
  <main v-if="error" class="screen-msg">{{ error }} · <RouterLink to="/">back</RouterLink></main>
  <main v-else-if="loading" class="screen-msg muted">Loading reel…</main>
  <main v-else class="screen">
    <section class="headbar">
      <RouterLink to="/" class="back" title="Home">←</RouterLink>
      <div class="title">
        <h1>
          <span class="sw" :style="{ background: reelColor(id) }"></span>
          <span class="rename" title="Rename" @click="rename">{{ reel.name }}</span>
          <span class="formats" role="group" aria-label="Reel format">
            <button
              v-for="f in FORMATS" :key="f.v" class="btn small" :class="{ active: (settings.format || 'standard') === f.v }"
              @click="setFormat(f.v)" :title="f.hint"
            >{{ f.label }}</button>
          </span>
        </h1>
        <p class="muted">
          {{ kept.length + (topPart ? 1 : 0) }} of {{ items.length }} parts kept ·
          reel <b class="mono total">{{ fmtTime(reelLength) }}</b>
          <span class="save">{{ saveState }}</span>
        </p>
      </div>
      <button class="btn" @click="sortByShotTime" :disabled="items.length < 2">Sort by shot time</button>
      <button class="btn" @click="duplicateReel" title="Make a copy of this reel to experiment on">Duplicate</button>
      <button class="btn" :class="{ active: showSettings }" @click="showSettings = !showSettings">Settings</button>
      <button class="btn" @click="doExport" :disabled="exporting || !kept.length">
        {{ exporting ? 'Checking…' : 'Preview cut list' }}
      </button>
      <button class="btn primary" @click="startRender" :disabled="rendering || !kept.length">
        {{ rendering ? `Rendering… ${renderPct}%` : 'Render video' }}
      </button>
    </section>

    <section class="panel render" v-if="job">
      <template v-if="job.status === 'running'">
        <div class="bar"><div class="fill" :style="{ width: `${renderPct}%` }"></div></div>
        <p class="muted">{{ stageText }} · {{ elapsed }}s</p>
      </template>
      <div v-else-if="job.status === 'done'" class="result">
        <video :src="`${api.renderVideo(job.id)}?t=${job.finishedAt}`" controls playsinline></video>
        <div>
          <h3>Rendered</h3>
          <p class="mono path">{{ job.output }}</p>
          <p class="muted">Took {{ Math.round(job.finishedAt - job.startedAt) }}s.</p>
          <p v-if="job.note" class="note">🎵 {{ job.note }}</p>
          <div class="controls">
            <button class="btn primary" @click="sending = job.output.split('/').pop()">Send to phone</button>
            <button class="btn" @click="api.reveal(job.id)">Show in Finder</button>
            <button class="btn" @click="job = null">Close</button>
          </div>
          <p class="muted small"><RouterLink to="/renders">All renders →</RouterLink></p>
        </div>
      </div>
      <template v-else>
        <h3>Render failed</h3>
        <pre class="log">{{ job.log.join('\n') }}</pre>
        <button class="btn" @click="job = null">Close</button>
      </template>
      <SendToPhone v-if="sending" :name="sending" @close="sending = null" />
    </section>

    <section v-if="showSettings" class="panel settings">
      <div class="music wide2">
        <h3>Music</h3>
        <div class="musicrow">
          <label class="field">
            Song
            <select v-model="settings.music">
              <option value="">No music</option>
              <option v-if="settings.music && !shelfHas(settings.music)" :value="settings.music">{{ settings.music }}</option>
              <option v-for="t in shelf.tracks" :key="t.name" :value="t.name">
                {{ t.name.replace(/\.[^.]+$/, '') }}{{ t.bpm ? ` · ${Math.round(t.bpm)} bpm` : '' }}
              </option>
            </select>
          </label>
          <label class="field" v-if="settings.music">
            Song starts at
            <input :value="fmtTime(settings.musicStart || 0)" @change="setMusicStart($event)" />
          </label>
          <div class="field" v-if="settings.music && musicUrl">
            &nbsp;
            <button class="btn small" @click="listen">{{ listening ? '■ Stop' : '▶ Listen' }}</button>
          </div>
          <label class="field" v-if="settings.music">
            Music volume
            <input type="number" min="0" max="1" step="0.05" v-model.number="settings.musicVolume" />
          </label>
        </div>
        <p class="muted small">
          Songs come from <code>{{ shelf.dir }}</code><template v-if="!shelf.exists"> (make that folder and drop MP3s in)</template>.
          <template v-if="analyzing"> Finding the beat…</template>
          <template v-else-if="beatData"> {{ Math.round(beatData.bpm) }} bpm · one beat = {{ (60 / beatData.bpm).toFixed(2) }}s.</template>
          <span v-if="musicError" class="warn"> {{ musicError }}</span>
        </p>
        <div class="musicrow" v-if="settings.music">
          <label class="field check">
            <span><input type="checkbox" v-model="settings.beatSync" :disabled="!shelf.beatDetection" /> Cut on the beat</span>
            <small v-if="!shelf.beatDetection">Needs beat detection: start the studio with <code>./studio/run.sh --beat</code></small>
            <small v-else-if="settings.beatSync">Each part lasts whole beats; drag or pick beats per part.</small>
            <small v-else>Your lengths are used exactly; the song plays underneath.</small>
          </label>
          <label class="field" v-if="settings.beatSync">
            Beats per part (default)
            <select v-model.number="settings.beatsPerCut">
              <option v-for="b in BEAT_CHOICES" :key="b" :value="b">{{ b }}{{ period ? ` ≈ ${(b * period).toFixed(1)}s` : '' }}</option>
            </select>
          </label>
          <label class="field check">
            <span><input type="checkbox" v-model="settings.musicInVideo" /> Put the song in the video</span>
            <small v-if="settings.musicInVideo">The render includes the music.</small>
            <small v-else>Cut to the song, but leave it out, to add the same song in Instagram (which licenses it).</small>
          </label>
        </div>
      </div>
      <template v-if="isStack">
        <label class="field">
          Split, top / underneath
          <input type="range" min="0.3" max="0.7" step="0.05" v-model.number="settings.stackSplit" />
          <small class="mono">{{ Math.round(settings.stackSplit * 100) }} / {{ 100 - Math.round(settings.stackSplit * 100) }}</small>
        </label>
        <label class="field">
          Divider (px at 1080 wide)
          <input type="number" min="0" max="20" step="2" v-model.number="settings.dividerPx" />
        </label>
        <label class="field">
          Divider colour
          <input type="color" v-model="settings.dividerColor" />
        </label>
        <label class="field check">
          <span><input type="checkbox" v-model="settings.fitTop" /> Fit timelapse to underneath</span>
          <small>{{ settings.fitTop ? 'The top clip speeds up or slows down to end with the parts underneath.'
            : 'The reel runs as long as the top clip at normal speed.' }}</small>
        </label>
      </template>
      <label class="field">
        {{ isStack ? 'Underneath framing' : 'Framing' }}
        <select v-model="settings.fit">
          <option value="fill">Fill (crop to 9:16)</option>
          <option value="blur">Blurred background</option>
          <option value="pad">Brand colour bars</option>
        </select>
      </label>
      <label class="field check">
        <span><input type="checkbox" v-model="settings.originalAudio" /> Keep glasses audio</span>
        <small>{{ settings.originalAudio ? 'Mixed under any music.' : 'Off: music only, or silent.' }}</small>
      </label>
      <label class="field" v-if="settings.originalAudio">
        Glasses audio volume
        <input type="number" min="0" max="1" step="0.05" v-model.number="settings.originalVolume" />
      </label>
      <label class="field">
        Default transition
        <select v-model="settings.transition">
          <option v-for="t in TRANSITIONS" :key="t.v" :value="t.v">{{ t.label }}</option>
        </select>
      </label>
      <div class="field">
        &nbsp;
        <button class="btn small" @click="useDefaultEverywhere">Use {{ label(settings.transition || 'cut') }} between every part</button>
      </div>
      <label class="field">
        Default cut length (s)
        <input type="number" min="0.2" step="0.1" v-model.number="settings.defaultLength" />
      </label>
      <label class="field">
        Default photo hold (s)
        <input type="number" min="0.2" step="0.1" v-model.number="settings.defaultHold" />
      </label>
      <div class="field">
        &nbsp;
        <button class="btn small" @click="applyLengthToAll">Set every kept cut to {{ settings.defaultLength }}s</button>
      </div>
      <div class="field">
        &nbsp;
        <button class="btn small danger" @click="removeReel">Delete this reel</button>
      </div>
    </section>

    <!-- the reel at a glance: one block per kept part, sized by its length -->
    <section class="transport" v-if="kept.length">
      <button class="btn primary playreel" @click="toggleReel" :title="reelOn ? 'Pause (Space) · Shift+Space: from the start' : 'Play the reel (Space) · Shift+Space: from the start'">
        {{ reelOn ? '❚❚ Pause' : '▶ Play reel' }} <kbd>Space</kbd>
      </button>
      <span class="mono clock">{{ fmtTime(reelTime ?? 0) }} / {{ fmtTime(reelLength) }}</span>
      <span v-if="settings.music" class="songtag" :title="settings.music">
        ♪ {{ settings.music.replace(/\.[^.]+$/, '').replace(/^.*\//, '') }}{{ beatData ? ` · ${Math.round(beatData.bpm)} bpm` : '' }}
      </span>
      <div class="tracks">
      <div v-if="isStack" class="strip toptrack">
        <button
          v-if="topPart" class="seg topseg" :class="{ current: topPart === current }"
          @click="select(items.indexOf(topPart))" :title="`${topPart.media.file}: plays on top for the whole reel`"
        >▤ {{ topPart.media.file }} · {{ topRate.toFixed(2) }}×</button>
        <span v-else class="muted toptrack-empty">No top clip: drag one to the Top slot</span>
        <div class="reelhead" v-if="reelTime !== null" :style="{ left: `${(reelTime / (reelLength || 1)) * 100}%` }"></div>
      </div>
      <div class="strip">
        <button
          v-for="p in kept" :key="p.id" class="seg"
          :class="{ current: p === current, playing: reelOn && p === current, photo: p.media.kind === 'photo' }"
          :style="{ flexGrow: len(p) }" :title="`${p.media.file} · ${len(p).toFixed(1)}s`"
          :data-past="pastEnd(p) || null"
          @click="jumpTo(p)"
        >{{ synced ? `${beatsOf(p)}♩` : len(p).toFixed(1) }}</button>
        <div
          v-for="(x, i) in beatTicks" :key="i" class="tick" :class="{ bar: i % 4 === 0 }"
          :style="{ left: `${x}%` }"
        ></div>
        <div v-if="spare > 0" class="seg spare" :style="{ flexGrow: spare }" title="The last part holds while the top clip finishes"></div>
        <div class="reelhead" v-if="reelTime !== null" :style="{ left: `${(reelTime / (reelLength || 1)) * 100}%` }"></div>
      </div>
      </div>
    </section>
    <p v-if="isStack && topPart && kept.length" class="readout mono muted">{{ readout }}</p>

    <p v-if="!items.length" class="panel empty">
      This reel is empty. Open a shoot from the <RouterLink to="/">home page</RouterLink>,
      pick a clip, set a selection and add it to <b>{{ reel.name }}</b>.
    </p>

    <div class="workspace" v-else>
      <aside class="cliplist" ref="listEl">
        <!-- Stack: the clip on top for the whole reel, then the parts underneath -->
        <template v-if="isStack">
          <div class="slotlabel">Top (timelapse)</div>
          <div
            class="topslot" :class="{ over: dragOver === 'top', empty: !topPart }"
            @dragover.prevent="dragOver = 'top'" @dragleave="dragOver = null" @drop="dropTop"
          >
            <div
              v-if="topPart" class="row" :data-i="items.indexOf(topPart)" draggable="true"
              @dragstart="dragFrom = 'top'" @dragend="dragOver = null"
            >
              <span class="num">▤</span>
              <ClipCard
                :media="topPart.media" :thumb-time="topPart.start" :selected="topPart === current"
                :sub="folderTitle(topPart.media.folder)"
                :chip="`${fmtTime(topPart.start)} → ${fmtTime(topPart.start + topPart.length)}  ${topPart.length.toFixed(1)}s · ${topRate.toFixed(2)}×` + (topPart.lighten ? '  ☀' : '')"
                @select="select(items.indexOf(topPart))"
              />
            </div>
            <p v-else class="muted">Drop a clip here to play it on top for the whole reel</p>
          </div>
          <div class="slotlabel">Underneath</div>
        </template>
        <template v-for="(p, i) in items" :key="p.id">
        <div
          v-if="p !== topPart" class="row" :data-i="i"
          :class="{ over: dragOver === i, playing: reelOn && i === selected }"
          draggable="true" @dragstart="dragFrom = i" @dragover.prevent="dragOver = i"
          @dragleave="dragOver = null" @drop="drop(i)" @dragend="dragOver = null"
        >
          <span class="num">{{ reelOn && i === selected ? '▶' : rowNumber(p) }}</span>
          <ClipCard
            :media="p.media" :thumb-time="p.start" :selected="i === selected" :dim="!p.keep"
            :sub="folderTitle(p.media.folder)"
            :chip="(p.media.kind === 'video'
              ? `${fmtTime(p.start)} → ${fmtTime(p.start + len(p))}  ${len(p).toFixed(1)}s`
              : `hold ${len(p).toFixed(1)}s`) + (synced ? `  ${beatsOf(p)}♩` : '') + (p.lighten ? '  ☀' : '') + badge(p)"
            @select="select(i)"
          >
            <button
              class="keep" :class="{ on: p.keep }" @click.stop="setKeep(p, !p.keep)"
              :title="p.keep ? 'In the cut — click to skip (X)' : 'Skipped — click to keep (X)'"
            >{{ p.keep ? '✓' : '–' }}</button>
            <button
              v-if="isStack && p.media.kind === 'video'" class="maketop" @click.stop="makeTop(p)"
              title="Play this on top for the whole reel"
            >⤒</button>
          </ClipCard>
          <button
            v-if="hasNext(p)" class="tpill" :class="`t-${effective(p)}`"
            :title="`Transition into the next part: ${label(effective(p))}. Click to change (T).`"
            @click.stop="cycle(p)"
          >{{ icon(effective(p)) }} {{ label(effective(p)) }}</button>
        </div>
        </template>
      </aside>

      <section class="editor" v-if="current">
        <div class="preview-col">
          <div v-if="current.media.missing" class="frame-missing">
            <p class="unplayable">
              This file is missing from <code>{{ current.media.folder }}/{{ current.media.file }}</code>.
              Put it back (or in any shoot folder) and it will relink.
            </p>
          </div>
          <!-- Stack: the top clip over the parts, each pane framing its own clip -->
          <StackFrame
            v-else-if="isStack && topPart" :split="settings.stackSplit" :divider-px="settings.dividerPx"
            :divider-color="settings.dividerColor" :editing="current === topPart ? 'top' : 'under'"
            :top-t="topT" :top-rate="topRate" :top-playing="reelOn" :guides="guides"
          >
            <template #top="{ maxH, out, bindTop }">
              <ReelFrame
                v-if="current === topPart" :key="`edit-${current.mediaId}`" v-bind="frameProps" v-on="frameOn"
                fit="fill" :out="out" :max-h="maxH" muted
              />
              <ReelFrame
                v-else :key="`top-${topPart.mediaId}`" :media="topPart.media" fit="fill" :out="out" :max-h="maxH"
                cropped muted :lighten="topPart.lighten" :focus-x="topPart.focusX" :focus-y="topPart.focusY"
                :zoom="topPart.zoom || 1" :poster-time="topPart.start" :bind-video="bindTop"
              />
            </template>
            <template #under="{ maxH, out }">
              <ReelFrame
                v-if="current !== topPart" :key="`edit-${current.mediaId}`" v-bind="frameProps" v-on="frameOn"
                :out="out" :max-h="maxH"
              />
              <div v-else class="underidle">
                <img v-if="kept[0]" :src="api.thumb(kept[0].media.folder, kept[0].media.file, kept[0].start, 480)" alt="" />
                <span>The parts play here, one after another</span>
              </div>
            </template>
            <p v-if="player.failed.value" class="unplayable">
              This browser can't play this file's codec (HEVC often won't play in Chrome — try Safari).
              Thumbnails and trimming still work.
            </p>
          </StackFrame>
          <ReelFrame v-else :key="current.mediaId" v-bind="frameProps" v-on="frameOn" :guides="guides">
            <p v-if="player.failed.value" class="unplayable">
              This browser can't play this file's codec (HEVC often won't play in Chrome — try Safari).
              Thumbnails and trimming still work.
            </p>
          </ReelFrame>
          <label class="guides-toggle muted"><input type="checkbox" v-model="guides" /> Show Instagram overlays <kbd>G</kbd></label>
          <audio ref="audioEl" v-if="musicUrl" :src="musicUrl" preload="auto" @ended="onSongEnded"></audio>
          <video
            v-if="reelOn && nextMedia" class="preload" muted preload="auto"
            :src="api.media(nextMedia.folder, nextMedia.file)"
          ></video>
        </div>

        <div class="edit-col">

        <template v-if="current.media.kind === 'video' && !current.media.missing">
          <TrimBar
            :duration="current.media.duration" :start="current.start" :length="len(current)"
            :playhead="player.playhead.value" :segments="segments"
            :thumb-at="(t) => api.thumb(current.media.folder, current.media.file, t, 160)"
            @update="setRange" @seek="player.seek" @pick="pickSegment"
          />
          <div class="controls">
            <button class="btn" @click="stopReel(); player.toggle()">{{ player.playing.value && !reelOn ? 'Pause' : 'Play clip' }}</button>
            <button class="btn" :class="{ active: player.playingPart.value }" @click="playThisPart">▶ Play part <kbd>Enter</kbd></button>
            <span class="muted mono">{{ fmtTime(player.playhead.value) }}</span>
            <span class="spacer"></span>
            <button class="btn small" @click="setIn">Start here <kbd>I</kbd></button>
            <button class="btn small" @click="setOut">End here <kbd>O</kbd></button>
          </div>
        </template>

        <TimingFields
          :kind="current.media.kind" :start="current.start" :length="len(current)"
          :duration="current.media.duration" @update="setRange"
        >
          <p v-if="current === topPart" class="topnote muted">
            ▤ On top for the whole reel: {{ fmtTime(current.length) }} of the clip
            {{ settings.fitTop ? `over ${fmtTime(underLength)}, at ${topRate.toFixed(2)}×` : 'at normal speed' }}.
            No cuts or transitions up here; drag the window above to reframe.
          </p>
          <label class="field check" v-if="current !== topPart">
            <span><input type="checkbox" :checked="current.keep" @change="setKeep(current, $event.target.checked)" /> In the cut <kbd>X</kbd></span>
          </label>
          <div class="tpick" v-if="synced && current !== topPart">
            <span class="muted">Beats (one beat = {{ period.toFixed(2) }}s)</span>
            <div>
              <button
                v-for="b in BEAT_CHOICES" :key="b" class="btn small" :class="{ active: beatsOf(current) === b }"
                @click="setBeats(current, b)"
              >{{ b }}</button>
              <button class="btn small" @click="beatsAll(beatsOf(current))" :title="`Make every part ${beatsOf(current)} beats`">Use on every part</button>
            </div>
          </div>
          <div class="tpick">
            <span class="muted">Lighten <kbd>L</kbd></span>
            <div>
              <button
                v-for="l in LIGHTEN" :key="l.v" class="btn small" :class="{ active: Math.abs(current.lighten - l.v) < 0.01 }"
                @click="setLighten(current, l.v)"
              >{{ l.label }}</button>
              <button class="btn small" @click="lightenAll(current.lighten)" :title="`Set every part to ${lightenLabel(current.lighten)}`">Use on every part</button>
            </div>
          </div>
          <div class="tpick" v-if="current !== topPart">
            <span class="muted">Layout</span>
            <div>
              <button
                v-for="l in LAYOUTS" :key="l.v" class="btn small" :class="{ active: (current.layout || '') === l.v }"
                @click="setLayout(current, l.v)" :title="l.hint"
              >{{ l.label }}</button>
            </div>
          </div>
          <div class="tpick" v-if="hasNext(current)">
            <span class="muted">Into next part <kbd>T</kbd></span>
            <div>
              <button
                v-for="t in TRANSITIONS" :key="t.v" class="btn small" :class="{ active: effective(current) === t.v }"
                @click="setTransition(current, t.v)" :title="t.hint"
              >{{ t.icon }} {{ t.label }}</button>
            </div>
          </div>
          <button class="btn small" @click="duplicate(current)" v-if="current.media.kind === 'video' && current !== topPart">Use another part of this clip</button>
          <button class="btn small" @click="unTop" v-if="current === topPart">Move underneath</button>
          <button class="btn small" @click="remove(current)">Remove from reel</button>
        </TimingFields>

        <p class="muted legend" v-if="segments.length">
          Coloured marks under the filmstrip are other parts of this clip:
          <span v-for="s in segments" :key="s.id" class="lg"><span class="sw" :style="{ background: s.color }"></span>{{ s.label }}</span>
        </p>
        <p class="muted keys">
          <kbd>Space</kbd> play/pause the whole reel · <kbd>Shift</kbd>+<kbd>Space</kbd> play from the start · <kbd>Enter</kbd> play just this part · <kbd>I</kbd>/<kbd>O</kbd> start/end at playhead ·
          <kbd>←</kbd>/<kbd>→</kbd> nudge 0.1s · <kbd>↑</kbd>/<kbd>↓</kbd> previous/next · <kbd>X</kbd> keep/skip ·
          <kbd>T</kbd> change transition · <kbd>L</kbd> lighten · <kbd>G</kbd> Instagram overlays · drag the list to reorder
        </p>
        </div>
      </section>
    </div>

    <div class="modal" v-if="exportResult" @click.self="exportResult = null">
      <div class="dialog">
        <h2>{{ exportResult.ok ? 'Cut list' : 'Engine reported a problem' }}</h2>
        <p class="muted" v-if="exportResult.path">Wrote <code>{{ exportResult.path }}</code></p>
        <pre>{{ exportResult.dryRun }}</pre>
        <div class="controls">
          <button class="btn primary" v-if="exportResult.ok" @click="exportResult = null; startRender()">Render video</button>
          <button class="btn" @click="exportResult = null">Close</button>
        </div>
      </div>
    </div>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, debouncedSaver } from '../api'
import { usePlayer } from '../player'
import { fitRange, fmtTime, folderTitle, parseTime, reelColor } from '../time'
import ClipCard from '../components/ClipCard.vue'
import SendToPhone from '../components/SendToPhone.vue'
import ReelFrame from '../components/ReelFrame.vue'
import StackFrame from '../components/StackFrame.vue'
import TimingFields from '../components/TimingFields.vue'
import TrimBar from '../components/TrimBar.vue'

const props = defineProps({ id: { type: [String, Number], required: true } })
const id = Number(props.id)
const route = useRoute()
const router = useRouter()

const reel = ref({ name: '' })
const items = ref([])
const otherItems = ref([])
const reels = ref([])
const settings = reactive({})
const selected = ref(0)
const loading = ref(true)
const error = ref('')
const saveState = ref('')
const showSettings = ref(false)
const exporting = ref(false)
const exportResult = ref(null)
const listEl = ref(null)
const dragFrom = ref(null)
const dragOver = ref(null)
const guides = ref(false)
const job = ref(null)
const sending = ref(null)   // render file name being sent to the phone
const clock = ref(Date.now() / 1000)

const current = computed(() => items.value[selected.value])
// A Stack reel's top clip; the kept parts play in order underneath it.
const topPart = computed(() => (settings.format === 'stack'
  ? items.value.find((p) => p.id === settings.topItemId && p.media.kind === 'video' && !p.media.missing) || null
  : null))
const kept = computed(() => items.value.filter((p) => p.keep && !p.media.missing && p !== topPart.value))
// Fit off, a Stack reel runs as long as its top clip.
const reelLength = computed(() => (topPart.value && !settings.fitTop
  ? topPart.value.length : bounds.value[bounds.value.length - 1] || 0))
const player = usePlayer(() => current.value && { start: current.value.start, length: len(current.value) })
const reelName = (rid) => reels.value.find((r) => r.id === rid)?.name ?? 'reel'

// Other parts of the same clip: elsewhere in this reel, and in other reels.
const segments = computed(() => {
  const c = current.value
  if (!c) return []
  const same = items.value.filter((p) => p.mediaId === c.mediaId && p.id !== c.id)
  const other = otherItems.value.filter((p) => p.mediaId === c.mediaId)
  return [...same, ...other].map((p) => ({
    id: p.id, start: p.start, length: p.length, color: reelColor(p.reelId), reelId: p.reelId,
    label: `${p.reelId === id ? 'also here' : reelName(p.reelId)} ${fmtTime(p.start)} (${p.length.toFixed(1)}s)`,
  }))
})

// ---------------------------------------------------------------- load & save

const saver = debouncedSaver(async (key, patch) => {
  saveState.value = '· saving…'
  try {
    if (key === 'settings') await api.updateReel(id, { settings: patch })
    else await api.updateItem(key, patch)
    saveState.value = '· saved'
  } catch (e) {
    saveState.value = `· not saved: ${e.message}`
  }
})

let ready = false
onMounted(async () => {
  try {
    const data = await api.reel(id)
    reel.value = { name: data.name }
    items.value = data.items
    otherItems.value = data.otherItems
    reels.value = data.reels
    Object.assign(settings, data.settings)
    loadShelf().then(loadBeats)
    const want = items.value.findIndex((p) => p.id === Number(route.query.item))
    if (want >= 0) selected.value = want
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
    setTimeout(() => { ready = true })
  }
})
onBeforeUnmount(() => saver.flushAll())

watch(settings, () => { if (ready) saver.queue('settings', { ...settings }) }, { deep: true })

// ---------------------------------------------------------------- selection

function select(i, fromReel = false) {
  if (i < 0 || i >= items.value.length) return
  if (!fromReel) {
    stopReel()
    restart = false   // picking a cut means "play from here"
  }
  selected.value = i
  player.reset()
  player.playhead.value = current.value.start
  // Another part of the same clip: the video stays loaded, so just move to it.
  const v = player.video.value
  if (v && v.readyState > 0 && !fromReel) player.seek(current.value.start)
  const el = listEl.value?.querySelector(`[data-i="${i}"]`)
  const list = listEl.value
  if (el && list) {
    if (el.offsetTop < list.scrollTop) list.scrollTop = el.offsetTop
    else if (el.offsetTop + el.offsetHeight > list.scrollTop + list.clientHeight)
      list.scrollTop = el.offsetTop + el.offsetHeight - list.clientHeight
  }
}

function pickSegment(segId) {
  const i = items.value.findIndex((p) => p.id === segId)
  if (i >= 0) select(i)   // another part in this reel: jump to it
  else {                  // a part in another reel: just show where it is
    const s = otherItems.value.find((p) => p.id === segId)
    if (s) player.seek(s.start)
  }
}

// ---------------------------------------------------------------- editing

function setRange({ start, length }) {
  const p = current.value
  if (synced.value && Math.abs(length - len(p)) > 0.01) {
    setBeats(p, Math.max(1, Math.round(length / period.value)))
    length = len(p)
  }
  const r = p.media.kind === 'video'
    ? fitRange(start, length, p.media.duration)
    : { start: 0, length: Math.max(0.2, Math.round(length * 100) / 100) }
  Object.assign(p, r)
  saver.queue(p.id, r)
}

function setIn() {
  const p = current.value
  const end = p.start + len(p)
  const t = player.playhead.value
  if (end - t >= 0.2) setRange({ start: t, length: end - t })
  else setRange({ start: t, length: len(p) })
}

function setOut() {
  const p = current.value
  if (player.playhead.value - p.start >= 0.2) setRange({ start: p.start, length: player.playhead.value - p.start })
}

function setFocus({ x, y, zoom }) {
  const p = current.value
  const patch = { focusX: x, focusY: y }
  if (zoom !== undefined) patch.zoom = zoom
  Object.assign(p, patch)
  saver.queue(p.id, patch)
}

function setKeep(p, keep) {
  p.keep = keep
  saver.queue(p.id, { keep })
}

function applyLengthToAll() {
  const len = Number(settings.defaultLength)
  if (!(len > 0)) return
  for (const p of items.value) {
    if (!p.keep || p.media.kind !== 'video') continue
    const r = fitRange(p.start, len, p.media.duration)
    Object.assign(p, r)
    saver.queue(p.id, r)
  }
}

async function remove(p) {
  await api.deleteItem(p.id)
  const i = items.value.indexOf(p)
  items.value.splice(i, 1)
  select(Math.min(i, items.value.length - 1))
}

// A second part of the same clip, starting just after this one.
async function duplicate(p) {
  const r = fitRange(p.start + len(p), p.length, p.media.duration)
  const item = await api.addItem(id, { mediaId: p.mediaId, ...r, focusX: p.focusX, focusY: p.focusY, zoom: p.zoom,
                                       lighten: p.lighten, layout: p.layout })
  const i = items.value.indexOf(p) + 1
  items.value.splice(i, 0, { ...item, media: p.media })
  await saveOrder()
  select(i)
}

// ---------------------------------------------------------------- order

async function saveOrder() {
  items.value.forEach((p, i) => { p.position = i })
  await api.reorder(id, items.value.map((p) => p.id))
}

async function drop(to) {
  const from = dragFrom.value
  dragOver.value = null
  if (from === 'top') return unTop(to)   // the top clip dragged into the list
  if (from === null || from === to) return
  const cur = current.value
  const [moved] = items.value.splice(from, 1)
  items.value.splice(to, 0, moved)
  selected.value = items.value.indexOf(cur)
  await saveOrder()
}

async function sortByShotTime() {
  const cur = current.value
  items.value.sort((a, b) => a.media.capturedAt - b.media.capturedAt || a.start - b.start)
  selected.value = items.value.indexOf(cur)
  await saveOrder()
}

// ---------------------------------------------------------------- reel

async function rename() {
  const name = window.prompt('Rename reel', reel.value.name)
  if (!name?.trim() || name.trim() === reel.value.name) return
  try {
    await api.updateReel(id, { name: name.trim() })
    reel.value.name = name.trim()
  } catch (e) {
    window.alert(e.message)
  }
}

async function duplicateReel() {
  const name = window.prompt('Name for the copy', `${reel.value.name} (copy)`)
  if (name === null) return
  try {
    await saver.flushAll()
    const r = await api.duplicateReel(id, name.trim())
    router.push(`/reel/${r.id}`)
  } catch (e) {
    window.alert(e.message)
  }
}

async function removeReel() {
  if (!window.confirm(`Delete the reel "${reel.value.name}"? Your footage is not touched.`)) return
  await api.deleteReel(id)
  router.push('/')
}

async function doExport() {
  exporting.value = true
  try {
    await saver.flushAll()
    exportResult.value = await api.exportReel(id)
  } catch (e) {
    exportResult.value = { ok: false, path: '', dryRun: e.message, command: '' }
  } finally {
    exporting.value = false
  }
}

// ---------------------------------------------------------------- music & beats

const BEAT_CHOICES = [1, 2, 4, 8]
const shelf = ref({ tracks: [], dir: '', exists: true, beatDetection: false })
const beatData = ref(null)
const analyzing = ref(false)
const musicError = ref('')
const audioEl = ref(null)
const listening = ref(false)
const songClock = ref(0)
let songRaf

const shelfHas = (name) => shelf.value.tracks.some((t) => t.name === name)
const musicUrl = computed(() => (settings.music && shelfHas(settings.music) ? api.musicFile(settings.music) : null))
const synced = computed(() => !!(settings.music && settings.beatSync && beatData.value && grid.value))
const clocked = computed(() => !!musicUrl.value)   // play the reel against the song

// Same rule as the engine: time runs from the first beat at/after the song start.
const grid = computed(() => {
  const d = beatData.value
  if (!d || d.beats.length < 4) return null
  const start = Number(settings.musicStart) || 0
  const b = d.beats.filter((x) => x >= start - 0.02)
  if (b.length < 4) return null
  const first = b[0]
  const rel = b.map((x) => x - first)
  const steps = rel.slice(1).map((x, i) => x - rel[i]).sort((a, c) => a - c)
  const step = steps[Math.floor(steps.length / 2)]
  return { rel, step, songT0: first }
})
const period = computed(() => grid.value?.step || (beatData.value ? 60 / beatData.value.bpm : 0))
const beatAt = (i) => {
  const g = grid.value
  return i < g.rel.length ? g.rel[i] : g.rel[g.rel.length - 1] + (i - g.rel.length + 1) * g.step
}
const beatsOf = (p) => p.beats || Number(settings.beatsPerCut) || 4

// Where each kept part starts on the reel's timeline (plus the end).
const bounds = computed(() => {
  const out = [0]
  if (synced.value && grid.value) {
    let c = 0
    for (const p of kept.value) { c += beatsOf(p); out.push(beatAt(c)) }
  } else {
    for (const p of kept.value) out.push(out[out.length - 1] + p.length)
  }
  return out
})
// How long a part plays: whole beats when cutting on the beat, else its length.
function len(p) {
  if (!p) return 0
  if (p === topPart.value) return p.length
  if (!synced.value) return p.length
  const k = kept.value.indexOf(p)
  return k >= 0 ? bounds.value[k + 1] - bounds.value[k] : beatsOf(p) * period.value
}
const beatTicks = computed(() => {
  if (!synced.value || !reelLength.value) return []
  const out = []
  for (let i = 1; out.length < 400; i++) {
    const t = beatAt(i)
    if (t >= reelLength.value) break
    out.push((t / reelLength.value) * 100)
  }
  return out
})

function setBeats(p, n) {
  p.beats = n
  saver.queue(p.id, { beats: n })
}
function beatsAll(n) {
  for (const p of items.value) if (p.beats !== n) setBeats(p, n)
}
function setMusicStart(e) {
  const t = parseTime(e.target.value)
  if (!isNaN(t) && t >= 0) settings.musicStart = Math.round(t * 100) / 100
  e.target.value = fmtTime(settings.musicStart || 0)
}

async function loadShelf() {
  try { shelf.value = await api.music() } catch { /* server without music support */ }
}
async function loadBeats() {
  beatData.value = null
  musicError.value = ''
  if (!settings.music || !shelfHas(settings.music) || !shelf.value.beatDetection) return
  analyzing.value = true
  try {
    beatData.value = await api.musicBeats(settings.music)
  } catch (e) {
    musicError.value = e.message
  } finally {
    analyzing.value = false
  }
}
watch(() => settings.music, () => { stopListening(); loadBeats() })

// The song position (seconds into the file) where the reel begins.
const songT0 = computed(() => (synced.value && grid.value ? grid.value.songT0 : Number(settings.musicStart) || 0))

function startSong(at) {
  const a = audioEl.value
  if (!a) return
  a.volume = Math.min(1, Math.max(0, Number(settings.musicVolume ?? 0.8)))
  a.currentTime = songT0.value + at
  a.play().catch(() => {})
  cancelAnimationFrame(songRaf)
  const tick = () => {
    if (!reelOn.value) return
    const t = a.currentTime - songT0.value
    songClock.value = t
    const end = bounds.value[reelIdx.value + 1]
    if (end !== undefined && t >= end) startPart(reelIdx.value + 1)
    songRaf = requestAnimationFrame(tick)
  }
  songRaf = requestAnimationFrame(tick)
}
function onSongEnded() {
  if (reelOn.value) { stopReel(); restart = true }
  listening.value = false
}
function listen() {
  const a = audioEl.value
  if (!a) return
  if (listening.value) return stopListening()
  stopReel()
  a.volume = Math.min(1, Math.max(0, Number(settings.musicVolume ?? 0.8)))
  a.currentTime = songT0.value
  a.play().catch(() => {})
  listening.value = true
}
function stopListening() {
  if (listening.value) audioEl.value?.pause()
  listening.value = false
}
onBeforeUnmount(() => { cancelAnimationFrame(songRaf); audioEl.value?.pause() })

// ---------------------------------------------------------------- transitions

const TRANSITIONS = [
  { v: 'cut', label: 'Cut', icon: '│', hint: 'Straight cut' },
  { v: 'flash', label: 'Flash', icon: '⚡', hint: 'Quick white flash' },
  { v: 'whip', label: 'Whip', icon: '⇆', hint: 'Fast blurred slide' },
  { v: 'zoom', label: 'Zoom', icon: '⊕', hint: 'Cut, next shot punches in' },
  { v: 'dissolve', label: 'Dissolve', icon: '◐', hint: 'Soft crossfade' },
  { v: 'dip', label: 'Dip', icon: '●', hint: 'Through black' },
]
const QUICK = ['cut', 'flash', 'whip', 'zoom']   // what clicking the pill cycles through
const info = (v) => TRANSITIONS.find((t) => t.v === v) || TRANSITIONS[0]
const label = (v) => info(v).label
const icon = (v) => info(v).icon
const effective = (p) => p.transition || settings.transition || 'cut'
const hasNext = (p) => { const k = kept.value.indexOf(p); return k >= 0 && k < kept.value.length - 1 }

function setTransition(p, v) {
  p.transition = v
  saver.queue(p.id, { transition: v })
}
function cycle(p) {
  const i = QUICK.indexOf(effective(p))
  setTransition(p, QUICK[(i + 1) % QUICK.length])
}
function useDefaultEverywhere() {
  for (const p of items.value) if (p.transition) setTransition(p, '')
}

// ---------------------------------------------------------------- lighten

const LIGHTEN = [
  { v: 0, label: 'Off' }, { v: 0.33, label: 'Low' }, { v: 0.66, label: 'Medium' }, { v: 1, label: 'High' },
]
const lightenLabel = (v) => (LIGHTEN.find((l) => Math.abs(l.v - v) < 0.01) || { label: `${Math.round(v * 100)}%` }).label
function setLighten(p, v) {
  p.lighten = v
  saver.queue(p.id, { lighten: v })
}
function cycleLighten(p) {
  const i = LIGHTEN.findIndex((l) => Math.abs(l.v - p.lighten) < 0.01)
  setLighten(p, LIGHTEN[(i + 1) % LIGHTEN.length].v)
}
function lightenAll(v) {
  for (const p of items.value) if (p.lighten !== v) setLighten(p, v)
}

// ---------------------------------------------------------------- layout

// Per part: the reel's framing, or its own.
const LAYOUTS = [
  { v: '', label: 'Reel default', hint: 'Use the framing set in Settings' },
  { v: 'fill', label: 'Fill', hint: 'Crop to fit; drag the window to reframe' },
  { v: 'blur', label: 'Blur', hint: 'The whole frame, with a blurred copy above and below' },
]
const layoutOf = (p) => p.layout || settings.fit || 'fill'
const badge = (p) => (p.layout === 'blur' ? '  ◫' : '')
function setLayout(p, v) {
  p.layout = v
  saver.queue(p.id, { layout: v })
}

// ---------------------------------------------------------------- stack format

// A Stack reel: one clip (a timelapse, say) plays in the top pane for the whole
// reel; the kept parts play one after another underneath. The top clip is a
// normal part of the reel, pinned by the reel's topItemId.
const FORMATS = [
  { v: 'standard', label: 'Standard', hint: 'One clip at a time, full frame' },
  { v: 'stack', label: 'Stack', hint: 'A clip on top for the whole reel, the parts underneath' },
]
const isStack = computed(() => settings.format === 'stack')
const underLength = computed(() => bounds.value[bounds.value.length - 1] || 0)
const topRate = computed(() => (topPart.value && settings.fitTop
  ? topPart.value.length / (underLength.value || 1) : 1))
const topT = computed(() => (topPart.value ? topPart.value.start + (reelTime.value ?? 0) * topRate.value : 0))
// Fit off: the top clip at normal speed sets the length; the parts are cut
// where it ends, or the last one holds.
const spare = computed(() => (isStack.value && topPart.value && !settings.fitTop
  ? Math.max(topPart.value.length - underLength.value, 0) : 0))
const pastEnd = (p) => isStack.value && topPart.value && !settings.fitTop
  && offsetOf(kept.value.indexOf(p)) >= topPart.value.length
const readout = computed(() => {
  const top = topPart.value.length
  const under = underLength.value
  let line = `Top ${fmtTime(top)} · Underneath ${fmtTime(under)} · `
  if (settings.fitTop) line += `timelapse at ${(top / (under || 1)).toFixed(2)}×`
  else if (under > top + 0.05) line += `underneath cut at ${fmtTime(top)}`
  else if (under < top - 0.05) line += `last part holds ${(top - under).toFixed(1)}s`
  else line += 'same length'
  return line
})

// Standard → Stack picks a top clip: one called "timelapse", else the longest.
function defaultTop() {
  const videos = items.value.filter((p) => p.media.kind === 'video' && !p.media.missing)
  return videos.find((p) => /timelapse/i.test(p.media.file))
    || [...videos].sort((a, b) => b.media.duration - a.media.duration)[0] || null
}
async function setFormat(f) {
  if (f === (settings.format || 'standard')) return
  stopReel()
  if (f === 'stack') {
    const keep = items.value.find((p) => p.id === settings.topItemId && p.media.kind === 'video')
    settings.topItemId = (keep || defaultTop())?.id ?? null
    settings.format = 'stack'
    return
  }
  // Back to Standard: the top clip becomes the first part again.
  const top = topPart.value
  settings.format = 'standard'
  if (top) await moveItem(top, 0)
}
function makeTop(p) {
  stopReel()
  settings.topItemId = p.id
}
// The top clip back into the list, as a normal part, at `to` (default: first).
async function unTop(to = 0) {
  const top = topPart.value
  if (!top) return
  stopReel()
  settings.topItemId = null
  if (!top.keep) setKeep(top, true)
  await moveItem(top, to)
}
async function moveItem(p, to) {
  const cur = current.value
  const from = items.value.indexOf(p)
  items.value.splice(from, 1)
  items.value.splice(Math.min(to, items.value.length), 0, p)
  selected.value = items.value.indexOf(cur)
  await saveOrder()
}
function dropTop() {
  const from = dragFrom.value
  dragOver.value = null
  if (typeof from !== 'number') return
  const p = items.value[from]
  if (p.media.kind !== 'video') return
  makeTop(p)
}
const rowNumber = (p) => items.value.filter((q) => q !== topPart.value).indexOf(p) + 1

// What every ReelFrame showing the selected clip gets.
const frameProps = computed(() => ({
  media: current.value.media, fit: layoutOf(current.value), guides: !isStack.value && guides.value,
  muted: !settings.originalAudio, cropped: reelOn.value, effect: effect.value, lighten: current.value.lighten,
  focusX: current.value.focusX, focusY: current.value.focusY, zoom: current.value.zoom || 1,
  posterTime: current.value.start, bindVideo: (el) => { player.video.value = el },
}))
const frameOn = {
  loaded: (e) => onFrameLoaded(e), play: () => player.events.onPlay(), pause: () => player.events.onPause(),
  error: () => player.events.onError(), toggle: () => player.toggle(), focus: (f) => setFocus(f),
}

// ---------------------------------------------------------------- play the reel

// Plays every kept part in order, cropped to the reel, so you can see how the
// cuts flow. The part playing is selected (and highlighted) as it goes.
const reelOn = ref(false)
const reelIdx = ref(0)
const photoT = ref(0)
const effect = ref(null)   // the transition to preview into the part now playing
let photoTimer, photoTick, restart = false

const offsetOf = (k) => bounds.value[k] || 0
const reelTime = computed(() => {
  if (reelOn.value && clocked.value) return songClock.value
  const k = kept.value.indexOf(current.value)
  if (k < 0) return null
  const p = current.value
  const within = p.media.kind === 'video'
    ? Math.min(Math.max(player.playhead.value - p.start, 0), len(p))
    : (reelOn.value ? photoT.value : 0)
  return offsetOf(k) + within
})
const nextMedia = computed(() => {
  const list = kept.value
  for (let k = reelIdx.value + 1; k < list.length; k++) {
    const m = list[k].media
    if (m.kind === 'video' && m.id !== current.value?.mediaId) return m
  }
  return null
})

function clearPhoto() {
  clearTimeout(photoTimer)
  clearInterval(photoTick)
}

function startPart(k) {
  clearPhoto()
  const list = kept.value
  if (k >= list.length) {       // end of the reel
    stopReel()
    restart = true
    return
  }
  reelIdx.value = k
  const p = list[k]
  const into = k > 0 ? effective(list[k - 1]) : 'cut'
  effect.value = into === 'cut' ? null : { type: into, at: performance.now() }
  const sameClip = current.value?.mediaId === p.mediaId
  const v = player.video.value
  if (v && !sameClip) v.pause()
  select(items.value.indexOf(p), true)
  if (p.media.kind !== 'video' || p.media.missing) {
    if (clocked.value) return      // the song's clock moves us on
    photoT.value = 0
    const t0 = performance.now()
    photoTick = setInterval(() => { photoT.value = Math.min(len(p), (performance.now() - t0) / 1000) }, 50)
    photoTimer = setTimeout(() => startPart(k + 1), len(p) * 1000)
  } else if (sameClip && v && v.readyState > 0) {
    player.seek(p.start)
    v.play().catch(() => {})
  }                              // a different clip starts once it has loaded
}

function onFrameLoaded() {
  player.seek(current.value.start)
  if (reelOn.value) player.video.value?.play().catch(() => {})
}

// Move on when the playing part reaches its end.
watch(() => player.playhead.value, (t) => {
  if (!reelOn.value || clocked.value) return
  const p = kept.value[reelIdx.value]
  const v = player.video.value
  if (p && p === current.value && p.media.kind === 'video' && v && !v.paused && t >= p.start + len(p)) {
    startPart(reelIdx.value + 1)
  }
})

// A Stack reel with fit off ends when its top clip does.
watch(() => reelTime.value, (t) => {
  if (reelOn.value && topPart.value && !settings.fitTop && t >= reelLength.value) {
    stopReel()
    restart = true
  }
})

// Start from the cut you're on (or the next kept one if it's skipped); only
// go back to the top when the reel just finished and nothing was picked since.
function playReel() {
  let k = kept.value.indexOf(current.value)
  if (k < 0) {
    const after = items.value.slice(selected.value + 1).find((p) => kept.value.includes(p))
    k = after ? kept.value.indexOf(after) : 0
  }
  if (restart) k = 0
  restart = false
  reelOn.value = true
  stopListening()
  if (clocked.value) startSong(offsetOf(k))
  startPart(k)
}

function stopReel() {
  if (!reelOn.value) return
  reelOn.value = false
  clearPhoto()
  player.video.value?.pause()
  audioEl.value?.pause()
  cancelAnimationFrame(songRaf)
}

const toggleReel = () => (reelOn.value ? stopReel() : playReel())

// Shift+Space: back to the first part and play, even mid-play.
function playFromTop() {
  stopReel()
  restart = true
  playReel()
}

function jumpTo(p) {
  if (reelOn.value) {
    const k = kept.value.indexOf(p)
    if (clocked.value) startSong(offsetOf(k))
    startPart(k)
  } else select(items.value.indexOf(p))
}

function playThisPart() {
  stopReel()
  player.playPart()
}
onBeforeUnmount(clearPhoto)

// ---------------------------------------------------------------- render

const rendering = computed(() => job.value?.status === 'running')
const renderPct = computed(() => {
  const j = job.value
  if (!j) return 0
  if (j.stage === 'joining') return 92
  if (j.stage === 'mixing') return 97
  if (j.stage === 'done') return 100
  return j.total ? Math.round((j.done / j.total) * 90) : 0
})
const stageText = computed(() => ({
  starting: 'Starting…', cutting: `Cutting ${job.value.done} of ${job.value.total}`,
  joining: 'Joining cuts and transitions…', mixing: 'Mixing sound…',
}[job.value.stage] || job.value.stage))
const elapsed = computed(() => Math.max(0, Math.round(clock.value - job.value.startedAt)))

let poll
function watchJob() {
  clearInterval(poll)
  poll = setInterval(async () => {
    clock.value = Date.now() / 1000
    try {
      job.value = await api.renderStatus(job.value.id)
    } catch { /* server restarted: keep the last state */ }
    if (job.value.status !== 'running') clearInterval(poll)
  }, 700)
}
onBeforeUnmount(() => clearInterval(poll))

async function startRender() {
  try {
    await saver.flushAll()
    job.value = await api.render(id)
    watchJob()
  } catch (e) {
    exportResult.value = { ok: false, path: '', dryRun: e.message }
  }
}

// Pick up a render that's still going (or just finished) when the page opens.
onMounted(async () => {
  const last = await api.lastRender(id).catch(() => null)
  if (last && (last.status === 'running' || Date.now() / 1000 - last.finishedAt < 600)) {
    job.value = last
    if (last.status === 'running') watchJob()
  }
})

// ---------------------------------------------------------------- keyboard

function onKey(e) {
  if (e.target.closest('input, select, textarea') || e.metaKey || e.ctrlKey || e.altKey || !current.value) return
  const k = e.key
  const video = current.value.media.kind === 'video'
  if (k === ' ' && e.shiftKey) playFromTop()
  else if (k === ' ') toggleReel()
  else if (k === 'Enter') playThisPart()
  else if ((k === 'i' || k === 'I') && video) setIn()
  else if ((k === 'o' || k === 'O') && video) setOut()
  else if (k === 'x' || k === 'X') setKeep(current.value, !current.value.keep)
  else if (k === 'ArrowDown') select(selected.value + 1)
  else if (k === 'ArrowUp') select(selected.value - 1)
  else if (k === 'ArrowLeft' && video) { setRange({ ...current.value, start: current.value.start - (e.shiftKey ? 1 : 0.1) }); player.seek(current.value.start) }
  else if (k === 'ArrowRight' && video) { setRange({ ...current.value, start: current.value.start + (e.shiftKey ? 1 : 0.1) }); player.seek(current.value.start) }
  else if (k === 'Escape') exportResult.value = null
  else if (k === 'g' || k === 'G') guides.value = !guides.value
  else if ((k === 't' || k === 'T') && hasNext(current.value)) cycle(current.value)
  else if (k === 'l' || k === 'L') cycleLighten(current.value)
  else return
  e.preventDefault()
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<style scoped>
h1 { display: flex; align-items: center; gap: 10px; }
h1 .sw { width: 14px; height: 14px; border-radius: 50%; flex: none; }
.rename { cursor: text; border-bottom: 1px dashed transparent; }
.rename:hover { border-bottom-color: var(--sage); }
.total { color: var(--forest); }
.save { font-size: 12px; }
.settings { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 14px; }
.settings .wide { grid-column: span 2; }
.field.check span { display: flex; gap: 6px; align-items: center; color: var(--ink); font-size: 14px; }
.field.check small { font-size: 12px; }
.danger { color: var(--danger); }
.transport { display: flex; align-items: center; gap: 12px; margin: 16px 0 34px; }
.playreel { flex: none; min-width: 148px; }
.clock { flex: none; color: var(--forest); min-width: 116px; }
.strip { position: relative; flex: 1; display: flex; gap: 2px; height: 30px; }
.seg.playing { background: var(--forest); color: var(--cream); box-shadow: 0 0 0 2px var(--sage); }
.reelhead {
  position: absolute; top: -4px; bottom: -4px; width: 2px; margin-left: -1px;
  background: #c0703a; border-radius: 1px; pointer-events: none;
}
.row.playing :deep(.clip) { border-color: var(--forest); box-shadow: 0 0 0 2px var(--forest); }
.row.playing .num { color: var(--forest); font-size: 13px; }
.preload { display: none; }
.music { grid-column: 1 / -1; border-bottom: 1px solid var(--line); padding-bottom: 12px; }
.music h3 { margin: 0 0 8px; }
.musicrow { display: flex; gap: 16px; flex-wrap: wrap; align-items: flex-end; }
.musicrow .field { min-width: 160px; }
.musicrow .field select { min-width: 260px; }
.small { font-size: 12px; margin: 8px 0; }
.warn { color: var(--danger); }
.note { background: var(--sage-soft); padding: 6px 10px; border-radius: 6px; font-size: 13px; }
.songtag {
  flex: none; font-size: 12px; color: var(--forest); background: var(--sage-soft);
  border-radius: 999px; padding: 2px 10px; max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.tick { position: absolute; bottom: -6px; width: 1px; height: 4px; background: var(--muted); pointer-events: none; }
.tick.bar { height: 7px; bottom: -9px; background: var(--forest); }
.row { flex-wrap: wrap; }
.tpill {
  margin: 2px 0 4px 64px; padding: 1px 10px; font-size: 11px; font-weight: 600; cursor: pointer;
  border: 1px dashed var(--line); border-radius: 999px; background: transparent; color: var(--muted);
}
.tpill:hover { border-color: var(--forest); color: var(--forest); }
.tpill:not(.t-cut) { border-style: solid; border-color: var(--sage); background: var(--sage-soft); color: var(--forest); }
.tpick { display: flex; flex-direction: column; gap: 4px; font-size: 12px; }
.formats { display: inline-flex; gap: 2px; margin-left: 6px; padding: 2px; border-radius: 999px; background: rgb(128 128 128 / 16%); }
.formats .btn { border-radius: 999px; border-color: transparent; background: transparent; }
.formats .btn.active { background: var(--sage); color: var(--on-sage); }
.tracks { flex: 1; display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.tracks .strip { flex: none; }
.toptrack { height: 22px; }
.toptrack .topseg { flex: 1; text-align: left; padding-left: 10px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.toptrack-empty { font-size: 12px; padding: 4px 10px; }
.seg.spare { background: repeating-linear-gradient(45deg, transparent 0 6px, rgb(128 128 128 / 25%) 6px 12px); pointer-events: none; }
.seg[data-past] { opacity: 0.35; }
.readout { margin: -26px 0 14px; font-size: 12px; }
.slotlabel { font-size: 11px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted, inherit); opacity: 0.75; margin: 6px 0 4px; }
.topslot { border: 2px dashed transparent; border-radius: var(--radius); padding: 2px; margin-bottom: 6px; border-bottom: 3px solid var(--sage); }
.topslot.empty { border-color: var(--sage); padding: 14px; text-align: center; font-size: 12px; }
.topslot.over { border-style: dashed; border-color: var(--sage); background: rgb(138 163 124 / 15%); }
.maketop {
  border: 0; background: none; cursor: pointer; font-size: 15px; padding: 2px 6px; border-radius: 6px; color: inherit; opacity: 0.6;
}
.maketop:hover { opacity: 1; background: rgb(138 163 124 / 25%); }
.topnote { font-size: 12px; flex-basis: 100%; margin: 0; }
.underidle { position: absolute; inset: 0; display: grid; place-items: center; overflow: hidden; background: #111; }
.underidle img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: 0.35; }
.underidle span { position: relative; font-size: 12px; color: var(--on-media); padding: 6px 10px; border-radius: 999px; background: rgb(31 42 31 / 70%); }
.tpick div { display: flex; gap: 4px; flex-wrap: wrap; }
.seg {
  flex-basis: 0; min-width: 6px; border: 0; border-radius: 4px; cursor: pointer; padding: 0;
  background: var(--sage); color: var(--on-sage); font-size: 10px; font-weight: 700; overflow: hidden;
}
.seg.photo { background: var(--sage-soft); }
.seg.current { background: var(--forest); color: var(--cream); }
.empty { font-size: 15px; }
.row { display: flex; align-items: center; gap: 4px; border-top: 2px solid transparent; }
.row.over { border-top-color: var(--forest); }
.row > .clip { flex: 1 1 calc(100% - 30px); min-width: 0; }
.num { width: 18px; text-align: right; font-size: 11px; color: var(--muted); font-family: ui-monospace, monospace; }
.keep {
  width: 28px; height: 28px; border-radius: 50%; border: 2px solid var(--line);
  background: var(--paper); cursor: pointer; font-weight: 700; color: var(--muted);
}
.keep.on { background: var(--sage); border-color: var(--sage); color: var(--on-sage); }
.render .bar { height: 10px; background: var(--sage-soft); border-radius: 999px; overflow: hidden; }
.render .fill { height: 100%; background: var(--forest); transition: width 0.4s; }
.render p { margin: 8px 0 0; }
.result { display: flex; gap: 20px; align-items: flex-start; flex-wrap: wrap; }
.result video { height: 360px; aspect-ratio: 9 / 16; background: var(--stage); border-radius: 8px; }
.result .path { word-break: break-all; }
.log { background: var(--cream); padding: 12px; border-radius: 8px; font-size: 12px; max-height: 240px; overflow: auto; white-space: pre-wrap; }
.legend { font-size: 12px; display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; }
.lg { display: inline-flex; align-items: center; gap: 4px; }
.lg .sw { width: 10px; height: 10px; border-radius: 50%; }
</style>
