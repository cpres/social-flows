<template>
  <main v-if="error" class="screen-msg">{{ error }} · <RouterLink to="/">back</RouterLink></main>
  <main v-else-if="loading" class="screen-msg muted">Loading clips…</main>
  <main v-else class="screen">
    <section class="headbar">
      <RouterLink :to="backTo" class="back" :title="reelId ? 'Back to the reel (your draft is kept)' : 'Back to Reels & shoots (your draft is kept)'">←</RouterLink>
      <div class="title">
        <h1>{{ reelId ? `Edit weave · ${existingName}` : 'Weave a reel' }}</h1>
        <p class="muted">
          {{ folderTitle(folder) }} · {{ videos.length }} clip{{ videos.length === 1 ? '' : 's' }} →
          {{ partCount }} part{{ partCount === 1 ? '' : 's' }}<template v-if="photos.length"> + {{ photos.length }} photo{{ photos.length === 1 ? '' : 's' }}</template>
          · ≈ <b class="mono total">{{ fmtTime(total) }}</b>
          <span class="draftstate">{{ draftState }}</span>
          <template v-if="draftAt"> · <button class="link" @click="startOver">Start over</button></template>
        </p>
      </div>
      <nav class="steps" aria-label="Steps">
        <button
          v-for="(s, i) in STEPS" :key="s" class="stepchip" :class="{ on: i === step, done: i < step }"
          :disabled="i > 0 && !videos.length" @click="go(i)"
        ><span class="n">{{ i + 1 }}</span> {{ s }}</button>
      </nav>
      <button class="btn" @click="go(step - 1)" :disabled="step === 0">Back</button>
      <button class="btn primary" v-if="step < 3" @click="go(step + 1)" :disabled="!videos.length">Next</button>
    </section>
    <p v-if="resumedAt" class="notice">
      Picked up your draft from {{ savedAt(resumedAt) }}<template v-if="addedOnResume">, with the
        {{ addedOnResume }} file{{ addedOnResume === 1 ? '' : 's' }} you just imported added</template>.
      <button class="link" @click="startOver">Start over</button>
    </p>
    <p v-if="notice" class="notice">{{ notice }}</p>
    <p v-if="staleDraft" class="notice">
      You changed the reel after the weave edit you left at {{ savedAt(staleDraft.updatedAt) }}, so this starts
      from the reel as it is now. <button class="link" @click="useStaleDraft">Use that draft instead</button>
    </p>
    <p v-if="step === 2 && leftOut" class="notice">
      Left out {{ leftOut.clip.media.file }}.
      <button class="link" @click="putBack">Put it back</button>
    </p>

    <!-- 1. Order: what goes in, and in what order -->
    <section v-if="step === 0" class="panel">
      <h3>Pick the clips and photos, and put them in order</h3>
      <p class="muted lead">
        They're in the order they were shot. This is the order each round goes through them,
        so drag to change it. Click a tile to leave it out.
      </p>
      <p v-if="datesLookOff" class="warnnote">
        Several of these have almost the same time, which usually means it's when they were
        copied, not when they were filmed. Drag them into the order they happened.
      </p>
      <div class="selbar">
        <span><b>{{ videos.length }}</b> clip{{ videos.length === 1 ? '' : 's' }} · <b>{{ photos.length }}</b> photo{{ photos.length === 1 ? '' : 's' }} in</span>
        <span class="spacer"></span>
        <button class="btn small" @click="sortByTime">Sort by time</button>
        <button class="btn small" @click="setAll(true)">All</button>
        <button class="btn small" @click="setAll(false)">None</button>
      </div>
      <div class="tiles">
        <div
          v-for="(c, i) in clips" :key="c.mediaId" class="tile" :class="{ on: c.on, over: dragOver === i }"
          role="button" tabindex="0" draggable="true" :aria-pressed="c.on" :title="c.media.file"
          @click="c.on = !c.on" @keydown.enter.space.prevent="c.on = !c.on"
          @dragstart="dragFrom = i" @dragover.prevent="dragOver = i"
          @dragleave="dragOver = null" @drop="dropClip(i)" @dragend="dragOver = null"
        >
          <img :src="thumbOf(c)" loading="lazy" alt="" draggable="false" />
          <span class="check">{{ c.on ? '✓' : '' }}</span>
          <span class="tag" v-if="c.kind === 'video'">▶ {{ fmtTime(c.media.duration) }}</span>
          <span class="tag" v-else>photo</span>
          <span class="badge" v-if="c.on && c.kind === 'video' && c.parts.length > 1">{{ c.parts.length }} parts</span>
          <span class="badge" v-else-if="c.on && c.kind === 'photo' && smart" :title="STYLES[styleOf(c)].hint">
            {{ STYLES[styleOf(c)].icon }} {{ STYLES[styleOf(c)].label }}
          </span>
          <span class="time">{{ clockTime(c.media.capturedAt) }}</span>
        </div>
      </div>
    </section>

    <!-- 2. Pace: how long each part is, and the music it cuts to -->
    <section v-if="step === 1" class="panel pace">
      <div class="col">
        <h3>Music</h3>
        <div class="field">
          <label for="weave-song">Song</label>
          <SongPicker id="weave-song" v-model="pace.music" v-model:shelf="shelf">
            <button class="btn" :class="{ active: listening }" :disabled="!songUrl" title="Hear the song before you pick it" @click="listen">
              {{ listening ? '■ Stop' : '▶ Listen' }}
            </button>
          </SongPicker>
          <div class="songbar" v-if="listening">
            <input type="range" min="0" :max="songLength" step="0.1" :value="songAt" aria-label="Where in the song" @input="seekSong" />
            <span class="mono">{{ fmtTime(songAt) }} / {{ fmtTime(songLength) }}</span>
          </div>
          <small v-if="listening">Drag to hear another part of it. Pick another song and that one plays.</small>
          <small v-else-if="songError" class="warn">{{ songError }}</small>
        </div>
        <label class="field check" v-if="pace.music">
          <span><input type="checkbox" v-model="pace.beatSync" :disabled="!shelf.beatDetection" /> Cut on the beat</span>
          <small v-if="!shelf.beatDetection">Needs beat detection: start the studio with <code>./studio/run.sh --beat</code></small>
          <small v-else-if="analyzing">Finding the beat…</small>
          <small v-else-if="synced">{{ Math.round(60 / period) }} bpm · every part lasts whole beats.</small>
          <small v-else-if="musicError" class="warn">{{ musicError }}</small>
        </label>
        <p class="muted small" v-if="!shelf.tracks.length">Songs come from <code>{{ shelf.dir }}</code>.</p>

        <h3 class="gap">Pace</h3>
        <div class="field" v-if="synced">
          Beats per part
          <div class="chips">
            <button
              v-for="b in BEAT_CHOICES" :key="b" class="btn small" :class="{ active: pace.beatsPerCut === b }"
              @click="pace.beatsPerCut = b"
            >{{ b }} ≈ {{ (b * period).toFixed(1) }}s</button>
          </div>
        </div>
        <label class="field" v-else>
          Average part length <b class="mono">{{ pace.len.toFixed(1) }}s</b>
          <input type="range" min="1" max="4" step="0.1" v-model.number="pace.len" />
        </label>
        <div class="field">
          Or aim for a reel about
          <div class="chips">
            <button v-for="t in TARGETS" :key="t" class="btn small" @click="aimFor(t)">{{ t }}s</button>
          </div>
        </div>
        <p class="muted small">Reels that hold attention usually cut every 1.5–3 seconds.</p>
        <div class="field" v-if="photos.length">
          Photo hold
          <div class="chips">
            <button class="btn small" :class="{ active: smart }" @click="pace.hold = 'smart'" title="Each photo holds as long as what's in it needs">✦ Smart</button>
            <button class="btn small" :class="{ active: !smart }" @click="pace.hold = 'even'" title="Every photo holds the same">Even</button>
          </div>
          <table class="holds">
            <tr v-for="r in holdRows" :key="r.style">
              <td>{{ STYLES[r.style].icon }} <b>{{ STYLES[r.style].label }}</b></td>
              <td class="muted">{{ r.hint }}</td>
              <td class="mono">{{ sizeLabel(r.style) }}</td>
              <td class="muted">{{ r.count }}</td>
            </tr>
          </table>
          <small v-if="handHeld">
            {{ handHeld }} photo{{ handHeld === 1 ? ' holds' : 's hold' }} for a length set by hand.
            <button class="link" @click="allAutomatic">Hold {{ handHeld === 1 ? 'it' : 'them' }} by style instead</button>
          </small>
          <small v-if="smart && looking">Looking for people and animals… {{ photos.length - looking }} of {{ photos.length }}</small>
          <small v-else-if="smart && detects === false">
            This computer can't look for people and animals (it needs macOS's Vision framework, which
            <code>./studio/run.sh</code> sets up on a Mac), so photos hold Medium unless you pick. Bursts still work.
          </small>
          <small v-else-if="smart">
            Clips hold longest. Photos with people or animals in them hold Medium, ones without are Small,
            and look-alike shots taken together flick by as a Burst{{ synced ? ' on half or quarter beats, landing back on the beat' : '' }}.
            Change any photo under Moments.
          </small>
          <small v-else>Every photo holds Medium, a little shorter than a clip.</small>
        </div>
      </div>

      <div class="col">
        <h3>Splitting</h3>
        <label class="field">
          Split clips this long or longer
          <select v-model.number="pace.splitOver">
            <option v-for="o in SPLIT_CHOICES" :key="o.v" :value="o.v">{{ o.label }}</option>
          </select>
          <small>Longer clips get about one part per {{ SECONDS_PER_PART }}s of footage ({{ MIN_PARTS }}–{{ MAX_PARTS }}); you can change it per clip next.</small>
        </label>
        <div class="field">
          Between rounds
          <div class="chips">
            <button
              v-for="t in TRANSITIONS" :key="t.v" class="btn small" :class="{ active: pace.between === t.v }"
              :title="t.hint" @click="pace.between = t.v"
            >{{ t.icon }} {{ t.label }}</button>
          </div>
          <small>Inside a round the parts cut straight to each other; this marks time moving on.</small>
        </div>
        <div class="field">
          Where to cut
          <div class="chips">
            <button class="btn small" @click="suggestAll" :disabled="!!measuring">
              {{ measuring ? `Measuring ${measuring}…` : 'Suggest busy moments in every clip' }}
            </button>
            <button class="btn small" @click="spreadAll">Spread evenly</button>
          </div>
          <small>Busy moments start each part where the most is happening in its stretch of the clip.</small>
        </div>

        <div class="estimate">
          <b>{{ videos.length }} clip{{ videos.length === 1 ? '' : 's' }} → {{ partCount }} part{{ partCount === 1 ? '' : 's' }}<template
            v-if="photos.length"> + {{ photos.length }} photo{{ photos.length === 1 ? '' : 's' }}</template> ≈ {{ fmtTime(total) }}</b>
          <span class="muted">{{ rounds }} round{{ rounds === 1 ? '' : 's' }} · {{ lengthHint }}</span>
          <div class="mini">
            <span
              v-for="e in seq" :key="e.key" class="mseg" :class="{ photo: e.kind === 'photo' }"
              :style="{ flexGrow: lengthOf(e), background: e.kind === 'video' ? reelColor(e.number) : null }"
              :title="e.label"
            >{{ e.label }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- 3. Moments: where each part of each clip is -->
    <template v-if="step === 2 && moment">
      <div class="dots">
        <button
          v-for="(c, i) in included" :key="c.mediaId" class="dot" :class="{ on: i === cur }"
          :title="c.media.file" @click="pick(i)"
        >
          <img :src="thumbOf(c)" alt="" loading="lazy" />
          <span>{{ c.kind === 'video' ? videoNumber(c) : '▣' }}</span>
        </button>
      </div>
      <section class="editor moments">
        <div class="preview-col">
          <ReelFrame
            :key="moment.mediaId" :media="moment.media" fit="fill" muted
            :focus-x="moment.focusX" :focus-y="moment.focusY" :zoom="moment.zoom || 1"
            :poster-time="active ? active.start : 0" :bind-video="(el) => (player.video.value = el)"
            @loaded="onLoaded" @play="player.events.onPlay" @pause="player.events.onPause"
            @ended="player.events.onEnded" @error="player.events.onError" @toggle="player.toggle" @focus="setFocus"
          >
            <p v-if="player.failed.value" class="unplayable">
              This browser can't play this file's codec (HEVC often won't play in Chrome — try Safari).
              Thumbnails and the filmstrip still work.
            </p>
          </ReelFrame>
          <p class="muted small">Drag the window to frame this {{ moment.kind === 'video' ? 'clip; every part of it uses the same framing' : 'photo' }}.</p>
        </div>

        <div class="edit-col">
          <h2 class="mtitle">
            <span v-if="moment.kind === 'video'" class="num" :style="{ background: reelColor(videoNumber(moment)) }">{{ videoNumber(moment) }}</span>
            {{ moment.media.file }}
            <span class="muted mono">{{ cur + 1 }} of {{ included.length }}</span>
          </h2>

          <details class="musicbar" :open="musicOpen" @toggle="musicOpen = $event.target.open">
            <summary>
              <span class="songname">♪ {{ pace.music ? songTitle(shelf, pace.music) : 'No music yet' }}</span>
              <span class="muted small" v-if="hereAt !== null">{{ momentName }} starts at {{ fmtTime(hereAt) }} in the reel</span>
              <span class="muted small change">Change</span>
            </summary>
            <SongPicker id="moment-song" v-model="pace.music" v-model:shelf="shelf" />
            <div class="chips">
              <label class="check" v-if="pace.music">
                <input type="checkbox" v-model="withMusic" :disabled="!songUrl" /> Play with the music
              </label>
              <label class="check" v-if="pace.music">
                <input type="checkbox" v-model="pace.beatSync" :disabled="!shelf.beatDetection" /> Cut on the beat
              </label>
              <small class="muted" v-if="analyzing">Finding the beat…</small>
              <small class="warn" v-else-if="musicError">{{ musicError }}</small>
            </div>
          </details>

          <template v-if="moment.kind === 'video'">
            <SplitBar
              :duration="moment.media.duration" :starts="moment.parts.map((p) => p.start)" :length="lens(moment)"
              :selected="sel" :playhead="player.playhead.value" :activity="activityOf[moment.mediaId]"
              :thumb-at="(t) => api.thumb(moment.media.folder, moment.media.file, t, 160)"
              @update="(s) => setStarts(moment, s, true)" @select="selectWindow" @seek="player.seek"
            />
            <div class="controls">
              <button class="btn" :class="{ active: player.playingPart.value }" @click="player.playPart">▶ Play {{ letter(sel) }} <kbd>Space</kbd></button>
              <button class="btn" @click="player.toggle">{{ player.playing.value && !player.playingPart.value ? 'Pause' : 'Play clip' }}</button>
              <span class="muted mono">{{ fmtTime(player.playhead.value) }}</span>
              <span class="spacer"></span>
              <span class="muted">{{ moment.parts.length }} part{{ moment.parts.length === 1 ? '' : 's' }}</span>
              <button class="btn small" @click="removePart(moment)" :disabled="moment.parts.length <= 1" title="One part fewer (−)">−</button>
              <button class="btn small" @click="addPart(moment)" :disabled="!canAdd(moment)" title="One more part (+)">+</button>
            </div>
            <div class="controls">
              <button class="btn small" @click="suggest(moment)" :disabled="activityOf[moment.mediaId] === null">Suggest busy moments</button>
              <button class="btn small" @click="spread(moment)">Spread evenly</button>
              <span class="muted small" v-if="active">{{ letter(sel) }}: {{ fmtTime(active.start) }} → {{ fmtTime(active.start + partLen(active)) }}</span>
            </div>
            <div class="field" v-if="active">
              <span>{{ moment.parts.length > 1 ? `Length of ${letter(sel)}` : 'Length' }} <b class="mono" v-if="!synced">{{ partLen(active).toFixed(1) }}s</b></span>
              <div class="chips" v-if="synced">
                <button
                  v-for="b in BEAT_CHOICES" :key="b" class="btn small" :class="{ active: beatsOf(active) === b }"
                  :disabled="beatsOf(active) !== b && b * period > room(moment, sel) + 0.01"
                  :title="b * period > room(moment, sel) + 0.01 ? 'Longer than this clip has room for' : ''"
                  @click="sizePart(moment, sel, b)"
                >{{ b }}♩ ≈ {{ (b * period).toFixed(2) }}s<template v-if="b === pace.beatsPerCut"> · pace</template></button>
                <button v-if="moment.parts.length > 1" class="btn small" :disabled="!fitsAll(moment)" @click="sizeAll(moment)">Use on every part</button>
              </div>
              <div class="lenrow" v-else>
                <input
                  type="range" min="0.5" :max="longest(moment, sel)" step="0.1" :value="partLen(active)"
                  aria-label="Length of this part" @input="sizePart(moment, sel, Number($event.target.value))"
                />
                <button class="btn small" :disabled="!own(active)" @click="sizePart(moment, sel)">Pace · {{ pace.len.toFixed(1) }}s</button>
                <button v-if="moment.parts.length > 1" class="btn small" :disabled="!fitsAll(moment)" @click="sizeAll(moment)">Use on every part</button>
              </div>
            </div>
            <p class="muted small">
              Drag the windows along the filmstrip to pick each moment; they keep their order, so
              <b>a</b> always comes before <b>b</b>. The green lane under it shows where things move.
              Each part runs for the pace ({{ synced ? `${pace.beatsPerCut} beats, ` : '' }}{{ len.toFixed(1) }}s) unless you give it a length of its own.
            </p>
          </template>
          <template v-else>
            <div class="field">
              Hold
              <div class="chips" v-if="smart">
                <button
                  v-for="s in PHOTO_STYLES" :key="s" class="btn small" :class="{ active: !photoOwn(moment) && styleOf(moment) === s }"
                  :title="STYLES[s].hint" @click="choose(moment, s)"
                >{{ STYLES[s].icon }} {{ STYLES[s].label }} · {{ sizeLabel(s) }}</button>
              </div>
              <div class="chips" v-if="synced">
                <span class="muted exact">Exactly</span>
                <button
                  v-for="b in PHOTO_BEATS" :key="b" class="btn small" :class="{ active: photoOwn(moment) && moment.hold.beats === b }"
                  @click="holdFor(moment, b)"
                >{{ fmtBeats(b) }}♩</button>
              </div>
              <div class="lenrow" v-else>
                <span class="muted exact">Exactly</span>
                <input
                  type="range" min="0.2" max="4" step="0.1" :value="lengthOf({ key: String(moment.mediaId) })"
                  aria-label="How long this photo holds" @input="holdFor(moment, Number($event.target.value))"
                />
              </div>
              <small>
                {{ photoOwn(moment) ? 'Held for exactly this long, set by hand (here or in the reel).' : smart ? whyText(moment) : 'Every photo holds Medium.' }}
                <button v-if="photoOwn(moment) || chosen[moment.mediaId]" class="link" @click="automatic(moment)">Back to automatic</button>
              </small>
            </div>
            <div class="controls" v-if="songUrl && withMusic">
              <button class="btn" :class="{ active: photoPlaying }" @click="playPhoto">▶ Play it with the music <kbd>Space</kbd></button>
            </div>
            <p class="muted">
              This photo holds for {{ holdText(moment) }} between rounds. Drag the window on the left to frame it.
            </p>
          </template>

          <div class="controls">
            <button class="btn" @click="pick(cur - 1)" :disabled="cur === 0">↑ Previous</button>
            <button class="btn" @click="pick(cur + 1)" :disabled="cur >= included.length - 1">↓ Next</button>
            <span class="spacer"></span>
            <button
              class="btn" @click="leaveOut(moment)" :disabled="!canLeaveOut(moment)"
              :title="canLeaveOut(moment) ? `Take this ${moment.kind === 'video' ? 'clip' : 'photo'} out of the reel` : 'A weave needs at least one clip'"
            >Leave it out <kbd>X</kbd></button>
            <button class="btn primary" v-if="cur >= included.length - 1" @click="go(3)">Stitch them together →</button>
          </div>
          <p class="muted keys">
            <kbd>Space</kbd> play the part{{ songUrl && withMusic ? ' with the music' : '' }} · <kbd>1</kbd>–<kbd>6</kbd> pick a part · <kbd>←</kbd>/<kbd>→</kbd> nudge it 0.1s (<kbd>Shift</kbd> 1s) ·
            <kbd>[</kbd>/<kbd>]</kbd> shorter/longer · <kbd>+</kbd>/<kbd>−</kbd> more or fewer parts ·
            <kbd>X</kbd> leave it out · <kbd>↑</kbd>/<kbd>↓</kbd> previous/next clip
          </p>
        </div>
      </section>
    </template>

    <!-- the song: heard on Pace, and under the parts on Moments -->
    <audio
      ref="songEl" v-if="songUrl" :src="songUrl" preload="auto"
      @timeupdate="songAt = $event.target.currentTime" @loadedmetadata="songLength = $event.target.duration || 0"
      @ended="listening = false" @error="cantPlay"
    ></audio>

    <!-- 4. Stitch: the woven order, to drag around -->
    <section v-if="step === 3" class="panel">
      <h3>The weave</h3>
      <p class="muted lead">
        Each round shows a moment from every clip, then moves on in time. Drag tiles to change the order;
        click the marks between them to switch between a cut and {{ softLabel }}.
        <button v-if="order" class="link" @click="order = null">Back to the woven order</button>
      </p>
      <div class="seq">
        <template v-for="(e, i) in seq" :key="e.key">
          <div
            class="stile" :class="{ photo: e.kind === 'photo', burst: e.kind === 'photo' && smart && styleOf(e.clip) === 'burst', over: dragOver === i, newround: startsRound(i) }"
            draggable="true" @dragstart="dragFrom = i" @dragover.prevent="dragOver = i"
            @dragleave="dragOver = null" @drop="dropTile(i)" @dragend="dragOver = null"
            :title="`${e.clip.media.file}${e.part ? ` · ${fmtTime(e.part.start)}` : ''}`"
          >
            <img :src="e.kind === 'video' ? api.thumb(e.clip.media.folder, e.clip.media.file, e.part.start + partLen(e.part) / 2, 240) : thumbOf(e.clip)" alt="" draggable="false" />
            <span class="slabel" :style="{ background: e.kind === 'video' ? reelColor(e.number) : null }">{{ e.label }}</span>
            <span class="slen">{{ synced ? `${fmtBeats(timing.get(e.key).beats)}♩` : `${lengthOf(e).toFixed(1)}s` }}</span>
          </div>
          <button
            v-if="i < seq.length - 1" class="tmark" :class="{ soft: e.transition }"
            :title="`Into the next: ${tLabel(e.transition)}. Click to change.`" @click="toggleTransition(e)"
          >{{ tIcon(e.transition) }}</button>
        </template>
      </div>
      <div class="savebar">
        <label class="field grow" v-if="!reelId">
          Reel name
          <input v-model="newName" @keydown.enter="save" />
        </label>
        <span class="muted">≈ {{ fmtTime(total) }} · {{ seq.length }} cuts</span>
        <span class="spacer"></span>
        <span v-if="failure" class="warn">{{ failure }}</span>
        <button class="btn primary" @click="save" :disabled="saving || !seq.length || (!reelId && !newName.trim())">
          {{ saving ? 'Saving…' : reelId ? 'Save to the reel' : 'Create reel' }}
        </button>
      </div>
      <p class="muted small" v-if="reelId">
        Saving keeps the framing, lighten and zoom set on parts in the reel, and any length that isn't the pace.
      </p>
    </section>
  </main>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, debouncedSaver } from '../api'
import { usePlayer } from '../player'
import { clamp, clockTime, fmtBeats, fmtTime, folderTitle, reelColor, savedAt } from '../time'
import { PHOTO_STYLES, STYLES, holdLengths, photoStyles, timeline } from '../hold'
import {
  MAX_PARTS, MIN_PARTS, SECONDS_PER_PART, autoParts, busyStarts, fromReel, inOrder, letter,
  partKey, settle, spreadStarts, weave,
} from '../weave'
import ReelFrame from '../components/ReelFrame.vue'
import SongPicker from '../components/SongPicker.vue'
import { songTitle } from '../songs'
import SplitBar from '../components/SplitBar.vue'

const props = defineProps({ folder: { type: String, required: true } })
const route = useRoute()
const router = useRouter()
const reelId = route.query.reel ? Number(route.query.reel) : null
// A new weave's draft shows on Home; editing a reel's weave goes back to the reel.
const backTo = reelId ? `/reel/${reelId}` : '/'

const STEPS = ['Order', 'Pace', 'Moments', 'Stitch']
const BEAT_CHOICES = [1, 2, 4, 8]
const TARGETS = [15, 30, 45, 60]
const SPLIT_CHOICES = [
  { v: 15, label: '0:15' }, { v: 20, label: '0:20' }, { v: 30, label: '0:30' }, { v: 45, label: '0:45' }, { v: 60, label: '1:00' }, { v: 90, label: '1:30' },
  { v: 120, label: '2:00' }, { v: 1e9, label: 'Never split' },
]
const TRANSITIONS = [
  { v: 'cut', label: 'Cut', icon: '│', hint: 'Straight cut' },
  { v: 'flash', label: 'Flash', icon: '⚡', hint: 'Quick white flash' },
  { v: 'whip', label: 'Whip', icon: '⇆', hint: 'Fast blurred slide' },
  { v: 'zoom', label: 'Zoom', icon: '⊕', hint: 'Cut, next shot punches in' },
  { v: 'dissolve', label: 'Dissolve', icon: '◐', hint: 'Soft crossfade' },
  { v: 'dip', label: 'Dip', icon: '●', hint: 'Through black' },
]
const tInfo = (v) => TRANSITIONS.find((t) => t.v === (v || 'cut')) || TRANSITIONS[0]
const tLabel = (v) => tInfo(v).label
const tIcon = (v) => tInfo(v).icon

const loading = ref(true)
const error = ref('')
const notice = ref('')
const step = ref(0)
const clips = ref([])
const existingName = ref('')
const newName = ref(`${props.folder} weave`)
const PACE = { len: 2, splitOver: 15, between: 'dissolve', music: '', musicStart: 0, beatSync: false, beatsPerCut: 4,
               hold: 'smart' }   // hold: how photos hold, smart | even
const pace = reactive({ ...PACE })
const order = ref(null)          // the keys in the order dragged in Stitch; null = woven
const overrides = reactive({})   // key -> transition clicked in Stitch (or the reel's, re-weaving)
const activityOf = reactive({})  // mediaId -> movement points; null while measuring
const dragFrom = ref(null)
const dragOver = ref(null)

// ---------------------------------------------------------------- music & pace

const shelf = ref({ tracks: [], dir: '', beatDetection: false })
const beatData = ref(null)
const analyzing = ref(false)
const musicError = ref('')
const shelfHas = (name) => shelf.value.tracks.some((t) => t.name === name)

// Seconds per beat, measured the way the reel page does: from the first beat
// at or after where the song starts.
const period = computed(() => {
  const d = beatData.value
  if (!d?.beats?.length) return 0
  const b = d.beats.filter((x) => x >= (Number(pace.musicStart) || 0) - 0.02)
  if (b.length < 4) return 60 / d.bpm
  const steps = b.slice(1).map((x, i) => x - b[i]).sort((a, c) => a - c)
  return steps[Math.floor(steps.length / 2)]
})
const synced = computed(() => !!(pace.music && pace.beatSync && period.value))
const len = computed(() => (synced.value ? pace.beatsPerCut * period.value : pace.len))   // every part
// How long each style holds (see hold.js); a part of a clip is len, the longest.
const sizes = computed(() => holdLengths(pace.len, synced.value ? period.value : 0, pace.beatsPerCut))

async function loadBeats() {
  beatData.value = null
  musicError.value = ''
  if (!pace.music || !pace.beatSync || !shelfHas(pace.music) || !shelf.value.beatDetection) return
  analyzing.value = true
  try {
    beatData.value = await api.musicBeats(pace.music)
  } catch (e) {
    musicError.value = e.message
  } finally {
    analyzing.value = false
  }
}
watch(() => [pace.music, pace.beatSync], loadBeats)
// Picking a song turns cutting on the beat on, when the studio can find beats.
let ready = false
watch(() => pace.music, (m, was) => { if (ready && m && !was && shelf.value.beatDetection) pace.beatSync = true })

// Listening before picking: the song plays from where the reel would start
// it, and picking another one while it plays switches to that one.
const songEl = ref(null)
const listening = ref(false)
const songAt = ref(0)
const songLength = ref(0)
const songError = ref('')
const songUrl = computed(() => (pace.music && shelfHas(pace.music) ? api.musicFile(pace.music) : null))

function playSong() {
  const a = songEl.value
  if (!a) return
  a.currentTime = songAt.value = Number(pace.musicStart) || 0
  listening.value = true
  // Switching songs cuts the last one's play short: that's not a failure.
  a.play().catch((e) => { if (e.name !== 'AbortError') cantPlay() })
}
function stopListening() {
  songEl.value?.pause()
  listening.value = false
}
function listen() {
  if (listening.value) stopListening()
  else playSong()
}
function seekSong(e) {
  if (songEl.value) songEl.value.currentTime = Number(e.target.value)
}
function cantPlay() {
  listening.value = false
  songError.value = "This browser couldn't play this song."
}
watch(songUrl, async (url) => {
  songAt.value = 0
  songLength.value = shelf.value.tracks.find((t) => t.name === pace.music)?.duration || 0
  songError.value = ''
  if (!listening.value) return
  if (!url) return stopListening()
  await nextTick()   // the player has the new song
  playSong()
})
onBeforeUnmount(stopListening)

// Set the pace so the reel comes out about this long. Parts given a length
// of their own stay that long; the rest follow the pace.
function aimFor(seconds) {
  const parts = videos.value.flatMap((c) => c.parts)
  const v = parts.filter((q) => !own(q)).length
  const fixed = parts.filter(own).reduce((a, q) => a + partLen(q), 0)
  // The photos, counted in parts: how long they hold now, over a part's length.
  const p = seq.value.filter((e) => e.kind === 'photo').reduce((a, e) => a + lengthOf(e), 0) / len.value
  if (!v && !p) return
  const left = Math.max(0, seconds - fixed)
  if (synced.value) {
    const want = left / ((v + p) * period.value)
    pace.beatsPerCut = BEAT_CHOICES.reduce((a, b) => (Math.abs(b - want) < Math.abs(a - want) ? b : a))
  } else {
    pace.len = Math.round(clamp(left / (v + p), 1, 4) * 10) / 10
  }
}

// ---------------------------------------------------------------- clips & parts

const included = computed(() => clips.value.filter((c) => c.on))
const videos = computed(() => included.value.filter((c) => c.kind === 'video'))
const photos = computed(() => included.value.filter((c) => c.kind === 'photo'))
const partCount = computed(() => videos.value.reduce((a, c) => a + c.parts.length, 0))
const rounds = computed(() => Math.max(1, ...videos.value.map((c) => c.parts.length)))
const videoNumber = (c) => videos.value.indexOf(c) + 1
const thumbOf = (c) => api.thumb(c.media.folder, c.media.file, c.kind === 'video' ? c.media.duration * 0.3 : 0, 320)

function newClip(m, on) {
  const c = { mediaId: m.id, media: m, kind: m.kind, on, auto: true, placed: false, framed: false,
              parts: [], focusX: 0.5, focusY: 0.5, zoom: 1 }
  if (c.kind === 'video') c.parts = spreadStarts(m.duration, autoParts(m.duration, pace.splitOver, len.value), len.value).map((start) => ({ start }))
  return c
}

// New starts for a clip's windows; parts keep their ids (and lengths) by position.
function setStarts(c, starts, placed = c.placed) {
  c.parts = starts.map((start, j) => ({ ...(c.parts[j] || {}), start }))
  c.placed = placed
}

// How long a part plays: its own length if it was given one (beats on the
// beat, else seconds), else the pace.
const own = (p) => !!(synced.value ? p.beats : p.length)
const beatsOf = (p) => p.beats || pace.beatsPerCut
const partLen = (p) => (synced.value ? beatsOf(p) * period.value : p.length || pace.len)
// Each of a clip's n windows, as long as its part (parts still to come: the pace).
const lens = (c, n = c.parts.length) => Array.from({ length: n }, (_, j) => (c.parts[j] ? partLen(c.parts[j]) : len.value))
// How long part j can be before it runs into the clip's other parts.
const room = (c, j) => c.media.duration - lens(c).reduce((a, l, k) => (k === j ? a : a + l), 0)
const longest = (c, j) => Math.max(0.5, Math.floor(Math.min(8, room(c, j)) * 10) / 10)
const canAdd = (c) => lens(c).reduce((a, l) => a + l, 0) + len.value <= c.media.duration + 1e-6
const fitsAll = (c) => partLen(active.value) * c.parts.length <= c.media.duration + 0.01

// Give part j of a clip a length of its own: v beats on the beat, else v
// seconds. The pace's length (or none) puts it back on the pace. Beats keep
// their seconds too, so the part stays about as long off the beat.
function sizePart(c, j, v) {
  const p = c.parts[j]
  let mine = {}
  if (synced.value && v && v !== pace.beatsPerCut) mine = { beats: v, length: Math.round(v * period.value * 10) / 10 }
  else if (!synced.value && v && Math.abs(v - pace.len) >= 0.05) mine = { length: v }
  c.parts[j] = { id: p.id, start: p.start, ...mine }
  const d = c.media.duration
  if (!c.placed) setStarts(c, spreadStarts(d, c.parts.length, lens(c)), false)
  else setStarts(c, settle(c.parts.map((q) => q.start), lens(c), d))
}
function sizeAll(c) {
  const p = c.parts[sel.value]
  const v = synced.value ? p.beats : p.length
  for (let j = 0; j < c.parts.length; j++) sizePart(c, j, v)
}
// [ and ]: the next beat choice that fits, or half a second off the beat.
function stepLength(c, dir) {
  const j = sel.value
  const p = c.parts[j]
  if (!synced.value) return sizePart(c, j, Math.round(clamp(partLen(p) + dir * 0.5, 0.5, longest(c, j)) * 10) / 10)
  const now = beatsOf(p)
  const fit = BEAT_CHOICES.filter((b) => (dir > 0 ? b > now : b < now) && b * period.value <= room(c, j) + 0.01)
  const b = dir > 0 ? fit[0] : fit[fit.length - 1]
  if (b) sizePart(c, j, b)
}

// The pace or the split length changed: recount and respread the clips that
// are still automatic, keep the ones placed by hand where they are.
function refit(c) {
  const d = c.media.duration
  const n = c.auto ? autoParts(d, pace.splitOver, len.value) : c.parts.length
  if (!c.placed || n !== c.parts.length) setStarts(c, spreadStarts(d, n, lens(c, n)), false)
  else setStarts(c, settle(c.parts.map((p) => p.start), lens(c), d))
}
watch([len, () => pace.splitOver], () => {
  for (const c of clips.value) if (c.kind === 'video') refit(c)
})

function addPart(c) {
  const d = c.media.duration
  if (!canAdd(c)) return
  c.auto = false
  if (!c.placed) return setStarts(c, spreadStarts(d, c.parts.length + 1, lens(c, c.parts.length + 1)))
  // Placed by hand: the new part goes in the middle of the biggest gap.
  const s = c.parts.map((p) => p.start)
  const l = lens(c)
  const edges = [0, ...s.flatMap((t, j) => [t, t + l[j]]), d]
  let best = 0
  for (let i = 0; i < edges.length; i += 2) if (edges[i + 1] - edges[i] > edges[best + 1] - edges[best]) best = i
  const at = (edges[best] + edges[best + 1] - len.value) / 2
  const k = best / 2
  c.parts.splice(k, 0, { start: at })
  setStarts(c, settle(c.parts.map((p) => p.start), lens(c), d))
  sel.value = k
}
// The selected part goes; the rest of a clip not placed by hand respread.
function removePart(c) {
  if (c.parts.length <= 1) return
  c.auto = false
  c.parts.splice(sel.value, 1)
  if (!c.placed) setStarts(c, spreadStarts(c.media.duration, c.parts.length, lens(c)), false)
  sel.value = Math.min(sel.value, c.parts.length - 1)
}
function spread(c) {
  setStarts(c, spreadStarts(c.media.duration, c.parts.length, lens(c)), false)
}
function spreadAll() {
  for (const c of videos.value) spread(c)
}

// ---------------------------------------------------------------- movement

async function measure(c) {
  if (activityOf[c.mediaId] !== undefined) return activityOf[c.mediaId]
  activityOf[c.mediaId] = null
  try {
    activityOf[c.mediaId] = (await api.activity(c.media.folder, c.media.file)).points
  } catch {
    activityOf[c.mediaId] = []
  }
  return activityOf[c.mediaId]
}
async function suggest(c) {
  const points = await measure(c)
  const s = c.parts.map((p) => p.start)
  if (points?.length) setStarts(c, busyStarts(points, c.media.duration, s.length, lens(c), s), true)
}
const measuring = ref('')
async function suggestAll() {
  const list = videos.value
  for (let i = 0; i < list.length; i++) {
    measuring.value = `${i + 1} of ${list.length}`
    await suggest(list[i])
  }
  measuring.value = ''
}

// ---------------------------------------------------------------- photo holds

const looks = reactive({})    // mediaId -> what's in the photo (see hold.js); null while looking
const detects = ref(null)     // whether this computer can find people and animals at all
const chosen = reactive({})   // mediaId -> a photo's style, picked by hand
const smart = computed(() => pace.hold === 'smart')
const looking = computed(() => photos.value.filter((c) => !looks[c.mediaId]).length)

// A few photos at a time, so the count goes up as they come in.
async function lookAt(list) {
  const ids = list.filter((c) => c.kind === 'photo' && !(c.mediaId in looks)).map((c) => c.mediaId)
  for (const id of ids) looks[id] = null
  for (let i = 0; i < ids.length; i += 8) {
    const batch = ids.slice(i, i + 8)
    let found = {}
    try {
      const r = await api.looks(batch)
      detects.value = r.detects
      found = r.looks
    } catch { /* not known: it holds as Medium */ }
    for (const id of batch) looks[id] = found[id] || { look: null, people: null, animals: null }
  }
}
watch(() => [smart.value, photos.value.map((c) => c.mediaId).join()], () => { if (smart.value) lookAt(photos.value) })

const photoInfo = computed(() => photoStyles(photos.value, looks, smart.value ? chosen : {}))
const styleOf = (c) => (smart.value && photoInfo.value.get(c.mediaId)?.style) || 'medium'
// A style picked by hand stays picked, even if what's around the photo
// changes (or what's in it is still being looked at); Back to automatic
// lets it follow the rest again.
function choose(c, style) {
  chosen[c.mediaId] = style
  delete c.hold
}
// A photo can also hold for exactly some beats (or seconds off the beat),
// like a hold set in the reel.
const PHOTO_BEATS = [0.25, 0.5, 1, 2, 4]
const photoOwn = (c) => !!(c.hold && (synced.value ? c.hold.beats : c.hold.length))
const photoSize = (c) => (synced.value ? { beats: c.hold.beats, seconds: c.hold.beats * period.value }
  : { beats: 0, seconds: c.hold.length })
function holdFor(c, v) {
  c.hold = synced.value ? { beats: v, length: Math.round(v * period.value * 100) / 100 } : { length: v }
}
function automatic(c) {
  delete chosen[c.mediaId]
  delete c.hold
}
function allAutomatic() {
  for (const c of photos.value) delete c.hold
}

function sizeLabel(style) {
  const z = sizes.value[style]
  const each = style === 'burst' ? ' each' : ''
  return synced.value ? `${fmtBeats(z.beats)}♩ ≈ ${z.seconds.toFixed(2)}s${each}` : `${z.seconds.toFixed(1)}s${each}`
}
const holdRows = computed(() => {
  const n = (k, one, many) => `${k} ${k === 1 ? one : many}`
  const mine = videos.value.reduce((a, c) => a + c.parts.filter(own).length, 0)
  const rows = [{ style: 'clip', hint: STYLES.clip.hint,
                  count: n(partCount.value, 'part', 'parts') + (mine ? ` (${mine} with a length of ${mine === 1 ? 'its' : 'their'} own)` : '') }]
  for (const s of smart.value ? PHOTO_STYLES : ['medium']) {
    let count = n(photos.value.filter((c) => styleOf(c) === s).length, 'photo', 'photos')
    if (s === 'burst') {
      const bursts = new Set([...photoInfo.value.values()].filter((i) => i.style === 'burst').map((i) => i.group))
      if (bursts.size) count += ` in ${n(bursts.size, 'burst', 'bursts')}`
    }
    rows.push({ style: s, hint: smart.value ? STYLES[s].hint : 'every photo', count })
  }
  return rows
})
const handHeld = computed(() => photos.value.filter(photoOwn).length)

const WHY = {
  alike: 'It looks like the photo next to it, so they flick by together as a burst.',
  people: 'There are people in it, so it holds a little longer.',
  animals: "There's an animal in it, so it holds a little longer.",
  none: 'No people or animals in it, so it can go by quicker.',
  unknown: "This computer can't tell what's in it, so it holds as if someone's in it.",
}
function whyText(c) {
  const info = photoInfo.value.get(c.mediaId)
  if (!looks[c.mediaId] || !info) return 'Looking at it…'
  const why = WHY[info.why]
  if (!chosen[c.mediaId]) return why
  return `Picked by hand. On its own it would be ${STYLES[info.auto].label}: ${why[0].toLowerCase()}${why.slice(1)}`
}
function holdText(c) {
  const t = timing.value.get(String(c.mediaId))
  if (!t) return '…'
  return synced.value ? `${fmtBeats(t.beats)} beat${t.beats > 1 ? 's' : ''} (${t.seconds.toFixed(2)}s)` : `${t.seconds.toFixed(1)}s`
}

// ---------------------------------------------------------------- order

function dropClip(to) {
  const from = dragFrom.value
  dragOver.value = null
  if (from === null || from === to) return
  const [moved] = clips.value.splice(from, 1)
  clips.value.splice(to, 0, moved)
}
function sortByTime() {
  clips.value.sort((a, b) => a.media.capturedAt - b.media.capturedAt)
}
function setAll(on) {
  for (const c of clips.value) c.on = on
}

// Capture times that bunch up are usually when the files were copied.
const datesLookOff = computed(() => {
  const ts = included.value.map((c) => c.media.capturedAt).sort((a, b) => a - b)
  if (ts.length < 3) return false
  let run = 1
  let most = 1
  for (let i = 1; i < ts.length; i++) {
    run = ts[i] - ts[i - 1] < 3 ? run + 1 : 1
    most = Math.max(most, run)
  }
  return most >= 3 && most >= ts.length / 2
})

// ---------------------------------------------------------------- the weave

// A burst of look-alike photos stays together in one gap between rounds.
const woven = computed(() => weave(clips.value, pace.between,
                                   (c) => (smart.value && photoInfo.value.get(c.mediaId)?.group) || c.mediaId))
const seq = computed(() => inOrder(woven.value, order.value)
  .map((e) => ({ ...e, transition: e.key in overrides ? overrides[e.key] : e.transition })))
// How long each entry plays, in the order it plays: key -> { seconds, beats }.
// A part of a clip plays its own length (whole beats, so photos still land
// back on the beat).
const timing = computed(() => {
  const t = timeline(seq.value.map((e) => (e.kind === 'video' ? 'clip' : photoOwn(e.clip) ? photoSize(e.clip) : styleOf(e.clip))), sizes.value)
  return new Map(seq.value.map((e, i) => [e.key, e.kind === 'video'
    ? { seconds: partLen(e.part), beats: synced.value ? beatsOf(e.part) : 0 } : t[i]]))
})
const lengthOf = (e) => timing.value.get(e.key)?.seconds ?? len.value
const total = computed(() => seq.value.reduce((a, e) => a + lengthOf(e), 0))
const lengthHint = computed(() => {
  const t = total.value
  if (!t) return ''
  if (t < 15) return 'short: fine for a teaser'
  if (t <= 60) return 'a good length for a reel'
  if (t <= 90) return 'on the long side for a reel'
  return 'long for a reel: try splitting only longer clips, or a faster pace'
})
const startsRound = (i) => i > 0 && order.value === null && seq.value[i].round !== seq.value[i - 1].round

// Adding or removing parts (or clips) changes what there is to order.
watch(() => woven.value.map((e) => e.key).sort().join('|'), (keys) => {
  if (order.value && [...order.value].sort().join('|') !== keys) {
    order.value = null
    notice.value = 'The parts changed, so the stitch order is back to the woven one.'
    setTimeout(() => { notice.value = '' }, 5000)
  }
})
// Back to the woven order means its transitions too (re-weaving, the reel's
// own were attached to parts in their old places).
watch(order, (keys) => {
  if (keys === null) for (const k of Object.keys(overrides)) delete overrides[k]
})
// A new between-rounds transition replaces the old one wherever it was used.
watch(() => pace.between, (now, was) => {
  if (!ready) return   // loading a draft or a reel: its transitions are already right
  for (const k of Object.keys(overrides)) if (overrides[k] === was) overrides[k] = now
})

const soft = computed(() => (pace.between === 'cut' ? 'dissolve' : pace.between))
const softLabel = computed(() => tLabel(soft.value).toLowerCase())
function toggleTransition(e) {
  overrides[e.key] = e.transition ? '' : soft.value
}
function dropTile(to) {
  const from = dragFrom.value
  dragOver.value = null
  if (from === null || from === to) return
  const keys = seq.value.map((e) => e.key)
  const [k] = keys.splice(from, 1)
  keys.splice(to, 0, k)
  order.value = keys
}

// ---------------------------------------------------------------- moments

const cur = ref(0)
const sel = ref(0)
const moment = computed(() => included.value[Math.min(cur.value, included.value.length - 1)])
const active = computed(() => (moment.value?.kind === 'video' ? moment.value.parts[sel.value] : null))
const player = usePlayer(() => active.value && { start: active.value.start, length: partLen(active.value) })

// The song under a part as you watch it: from where that part lands in the
// reel, so you see and hear what the reel will do there.
const withMusic = ref(true)
const musicOpen = ref(false)   // the song picker on Moments; open to start with when there's no song
// Where the reel starts in the song: on the first beat at or after the start
// when cutting on the beat (the engine's rule), else at the start.
const songT0 = computed(() => {
  const s = Number(pace.musicStart) || 0
  return synced.value ? beatData.value.beats.find((b) => b >= s - 0.02) ?? s : s
})
// Where each entry starts in the reel: key -> seconds.
const startsAt = computed(() => {
  const out = new Map()
  let t = 0
  for (const e of seq.value) { out.set(e.key, t); t += lengthOf(e) }
  return out
})
const momentKey = computed(() => (moment.value?.kind === 'video' ? partKey(moment.value.mediaId, sel.value) : String(moment.value?.mediaId)))
const hereAt = computed(() => startsAt.value.get(momentKey.value) ?? null)
const momentName = computed(() => (moment.value?.kind === 'video' ? letter(sel.value) : 'This photo'))

function songUnder(key) {
  const a = songEl.value
  if (!a || !withMusic.value || !startsAt.value.has(key)) return false
  a.currentTime = songT0.value + startsAt.value.get(key)
  a.play().catch(() => {})
  return true
}
watch(() => player.playingPart.value, (on) => {
  if (on) songUnder(momentKey.value)
  else if (!photoPlaying.value) songEl.value?.pause()
})

// A photo has nothing to play, so it plays the song for as long as it holds.
const photoPlaying = ref(false)
let photoTimer
function playPhoto() {
  clearTimeout(photoTimer)
  if (photoPlaying.value) return stopPhoto()
  const t = timing.value.get(momentKey.value)
  if (!t || !songUnder(momentKey.value)) return
  photoPlaying.value = true
  photoTimer = setTimeout(stopPhoto, t.seconds * 1000)
}
function stopPhoto() {
  clearTimeout(photoTimer)
  if (photoPlaying.value) songEl.value?.pause()
  photoPlaying.value = false
}
watch(momentKey, stopPhoto)
onBeforeUnmount(stopPhoto)

function pick(i) {
  if (i < 0 || i >= included.value.length) return
  saveDraftNow()
  cur.value = i
  sel.value = 0
  player.reset()
  if (moment.value.kind === 'video') {
    player.playhead.value = moment.value.parts[0].start
    measure(moment.value)
  }
}
// Fewer parts (the pace changed, or one was removed): stay on one that exists.
watch(() => moment.value?.parts.length, (n) => { if (n && sel.value >= n) sel.value = n - 1 })
function selectWindow(j) {
  sel.value = j
  player.seek(moment.value.parts[j].start)
}
function onLoaded() {
  if (active.value) player.seek(active.value.start)
}
function nudge(by) {
  const c = moment.value
  const s = c.parts.map((p) => p.start)
  const l = lens(c)
  const j = sel.value
  const lo = j > 0 ? s[j - 1] + l[j - 1] : 0
  const hi = j < s.length - 1 ? s[j + 1] - l[j] : c.media.duration - l[j]
  s[j] = Math.round(clamp(s[j] + by, Math.min(lo, s[j]), Math.max(hi, s[j])) * 100) / 100
  setStarts(c, s, true)
  player.seek(s[j])
}
// Leave a clip or photo out right from its moment, with a way to put it back.
// An order dragged in Stitch keeps everything else where it was.
const leftOut = ref(null)   // { clip, order } the last one left out
const canLeaveOut = (c) => c.kind === 'photo' || videos.value.length > 1
const keysOf = (c) => (c.kind === 'video' ? c.parts.map((_, j) => partKey(c.mediaId, j)) : [String(c.mediaId)])
function leaveOut(c) {
  if (!canLeaveOut(c)) return
  leftOut.value = { clip: c, order: order.value }
  if (order.value) order.value = order.value.filter((k) => !keysOf(c).includes(k))
  c.on = false
  pick(Math.min(cur.value, included.value.length - 1))
}
function putBack() {
  const { clip, order: was } = leftOut.value
  clip.on = true
  order.value = was
  leftOut.value = null
  pick(included.value.indexOf(clip))
}

function setFocus({ x, y, zoom }) {
  const c = moment.value
  c.focusX = x
  c.focusY = y
  if (zoom !== undefined) c.zoom = zoom
  c.framed = true
}

function go(i) {
  if (i < 0 || i > 3 || (i > 0 && !videos.value.length)) return
  player.video.value?.pause()
  stopListening()
  leftOut.value = null
  saveDraftNow()
  step.value = i
  if (i === 2) {
    musicOpen.value = !pace.music
    pick(Math.min(cur.value, included.value.length - 1))
  }
}

function onKey(e) {
  if (step.value !== 2 || !moment.value) return
  if (e.target.closest('input, select, textarea') || e.metaKey || e.ctrlKey || e.altKey) return
  const k = e.key
  const video = moment.value.kind === 'video'
  if (k === ' ' && video) player.playPart()
  else if (k === ' ' && songUrl.value && withMusic.value) playPhoto()
  else if (k === 'ArrowDown') pick(cur.value + 1)
  else if (k === 'ArrowUp') pick(cur.value - 1)
  else if (k === 'ArrowLeft' && video) nudge(e.shiftKey ? -1 : -0.1)
  else if (k === 'ArrowRight' && video) nudge(e.shiftKey ? 1 : 0.1)
  else if ((k === '+' || k === '=') && video) addPart(moment.value)
  else if ((k === '-' || k === '_') && video) removePart(moment.value)
  else if (k === '[' && video) stepLength(moment.value, -1)
  else if (k === ']' && video) stepLength(moment.value, 1)
  else if (k === 'x' || k === 'X') leaveOut(moment.value)
  else if (/^[1-9]$/.test(k) && video && Number(k) <= moment.value.parts.length) selectWindow(Number(k) - 1)
  else return
  e.preventDefault()
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

// ---------------------------------------------------------------- load & save

const draftQuery = reelId ? { reel: reelId } : { folder: props.folder }
let folderMedia = []   // the shoot's files
let reelData = null    // re-weaving: the reel as it was loaded
let untouched = []     // re-weaving: parts the wizard leaves as they are

// A Stack reel's top clip, and parts whose file is missing for now, aren't the
// wizard's to change: they're saved back as they are.
const managed = (it) => !it.media.missing
  && !(reelData.settings.format === 'stack' && it.id === reelData.settings.topItemId)

// Every file the wizard can use: the shoot's, plus (re-weaving) the reel's.
function mediaById() {
  const out = new Map(folderMedia.map((m) => [m.id, m]))
  for (const it of reelData?.items || []) if (managed(it) && !out.has(it.mediaId)) out.set(it.mediaId, it.media)
  return out
}

// From scratch: what was just imported (else the whole shoot), or the reel as it is.
function startFresh(imported) {
  Object.assign(pace, PACE)
  for (const k of Object.keys(overrides)) delete overrides[k]
  for (const k of Object.keys(chosen)) delete chosen[k]
  order.value = null
  step.value = 0
  cur.value = 0
  newName.value = `${props.folder} weave`
  if (!reelData) {
    clips.value = folderMedia.map((m) => newClip(m, imported.length ? imported.includes(m.file) : true))
    return
  }
  const s = reelData.settings
  const w = s.weave || {}
  Object.assign(pace, {
    len: Number(w.pace || s.defaultLength) || 2, splitOver: w.splitOver ?? 60, between: w.between || 'dissolve',
    music: s.music || '', musicStart: Number(s.musicStart) || 0, beatSync: !!s.beatSync,
    beatsPerCut: Number(s.beatsPerCut) || 4, hold: w.hold || 'smart',
  })
  Object.assign(chosen, w.styles || {})
  const back = fromReel(reelData.items.filter(managed), w,
                        { beatSync: !!(pace.music && pace.beatSync), beatsPerCut: pace.beatsPerCut, len: pace.len })
  const inReel = new Set(back.clips.map((c) => c.mediaId))
  clips.value = [...back.clips, ...folderMedia.filter((m) => !inReel.has(m.id)).map((m) => newClip(m, false))]
  order.value = back.keys
  Object.assign(overrides, back.transitions)
  step.value = 1
}

// ---------------------------------------------------------------- drafts
// Everything chosen so far is saved as a draft as you go, so leaving the
// wizard (or closing the page) loses nothing; it picks up where you were.

const draftAt = ref(null)        // when the draft was last saved
const resumedAt = ref(null)      // this visit picked up a draft saved then
const addedOnResume = ref(0)     // files imported since the draft, added to it
const draftSaving = ref(false)
const draftError = ref('')
let stopDraft = false            // finishing or starting over: save nothing more
let lastSaved = ''
let inflight = Promise.resolve()

const draftState = computed(() => {
  if (draftError.value) return ` · draft not saved: ${draftError.value}`
  if (draftSaving.value) return ' · saving draft…'
  return draftAt.value ? ` · draft saved ${savedAt(draftAt.value)}` : ''
})

function snapshot() {
  return {
    v: 1, step: step.value, cur: cur.value, newName: newName.value,
    pace: { ...pace }, order: order.value, overrides: { ...overrides }, chosen: { ...chosen },
    clips: clips.value.map((c) => ({
      mediaId: c.mediaId, kind: c.kind, on: c.on, auto: c.auto, placed: c.placed, framed: c.framed,
      focusX: c.focusX, focusY: c.focusY, zoom: c.zoom, id: c.id, hold: c.hold,
      parts: c.parts.map((p) => ({ id: p.id, start: p.start, beats: p.beats, length: p.length })),
    })),
  }
}

// Back to a saved draft. Files gone since are dropped; files added since go
// at the end, switched on if they were just imported.
function restore(state, media, imported) {
  Object.assign(pace, PACE, state.pace || {})
  const seen = new Set()
  const out = []
  for (const c of state.clips || []) {
    const m = media.get(c.mediaId)
    if (!m) continue
    seen.add(m.id)
    const clip = newClip(m, !!c.on)
    Object.assign(clip, { auto: !!c.auto, placed: !!c.placed, framed: !!c.framed, focusX: c.focusX ?? 0.5,
                          focusY: c.focusY ?? 0.5, zoom: c.zoom || 1, id: c.id })
    if (c.hold) clip.hold = { ...c.hold }
    if (m.kind === 'video' && c.parts?.length) clip.parts = c.parts.map((p) => ({ ...p }))
    out.push(clip)
  }
  const added = [...media.values()].filter((m) => !seen.has(m.id))
  addedOnResume.value = added.filter((m) => imported.includes(m.file)).length
  clips.value = [...out, ...added.map((m) => newClip(m, imported.includes(m.file)))]
  order.value = state.order || null
  for (const k of Object.keys(overrides)) delete overrides[k]
  Object.assign(overrides, state.overrides || {})
  for (const k of Object.keys(chosen)) delete chosen[k]
  Object.assign(chosen, state.chosen || {})
  newName.value = state.newName || newName.value
  step.value = state.step || 0
  cur.value = state.cur || 0
}

// Saves go one after another, so an older one can never land last.
const draftSaver = debouncedSaver(async (_, state) => {
  if (stopDraft) return
  draftSaving.value = true
  const send = inflight.catch(() => {}).then(() => (stopDraft ? null : api.saveWeaveDraft({ folder: props.folder, reelId, state })))
  inflight = send
  try {
    const r = await send
    if (r) draftAt.value = r.updatedAt
    draftError.value = ''
  } catch (e) {
    draftError.value = e.message
  } finally {
    draftSaving.value = false
  }
}, 250)
function queueDraft() {
  const text = JSON.stringify(snapshot())
  if (!ready || stopDraft || text === lastSaved) return false
  lastSaved = text
  draftSaver.queue('draft', JSON.parse(text))
  return true
}
watch(() => JSON.stringify(snapshot()), queueDraft)
// Every click saves straight away; so do Next, Back and moving between moments.
function saveDraftNow() {
  queueDraft()
  draftSaver.flushAll()
}
const onClick = () => setTimeout(saveDraftNow)   // after the click has changed things
onMounted(() => window.addEventListener('click', onClick, true))
onBeforeUnmount(() => window.removeEventListener('click', onClick, true))
const flushDraft = () => draftSaver.flushAll()
onMounted(() => window.addEventListener('pagehide', flushDraft))
onBeforeUnmount(() => {
  window.removeEventListener('pagehide', flushDraft)
  flushDraft()
})

// Stop saving, and make sure nothing still on its way brings the draft back.
async function dropDraft() {
  stopDraft = true
  await draftSaver.flushAll()
  await inflight.catch(() => {})
  await api.deleteWeaveDraft(draftQuery).catch(() => {})
  draftAt.value = null
}

async function startOver() {
  const ask = reelId ? 'Throw away this draft and start again from the reel as it is?'
    : 'Throw away this draft and start over?'
  if (!window.confirm(ask)) return
  await dropDraft()
  ready = false
  resumedAt.value = null
  notice.value = ''
  startFresh(window.history.state?.imported || [])
  setTimeout(() => {
    lastSaved = JSON.stringify(snapshot())
    ready = true
    stopDraft = false
  })
}

onMounted(async () => {
  try {
    const [data, music, draft] = await Promise.all([
      api.folder(props.folder), api.music().catch(() => null), api.weaveDraft(draftQuery).catch(() => null),
    ])
    if (music) shelf.value = music
    folderMedia = data.media.filter((m) => !m.missing)
    if (reelId) {
      reelData = await api.reel(reelId)
      existingName.value = reelData.name
      untouched = reelData.items.filter((it) => !managed(it))
    }
    const imported = window.history.state?.imported || []
    // A draft older than the reel's last change would undo what was changed
    // in the reel since: start from the reel, and offer the draft instead.
    if (draft?.state?.clips && reelData && reelData.updatedAt > draft.updatedAt + 1) {
      staleDraft.value = draft
      startFresh(imported)
    } else if (draft?.state?.clips) {
      restore(draft.state, mediaById(), imported)
      draftAt.value = resumedAt.value = draft.updatedAt
    } else {
      startFresh(imported)
    }
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
    setTimeout(() => {
      lastSaved = JSON.stringify(snapshot())
      ready = true
    })
  }
})

const staleDraft = ref(null)   // editing a weave: a draft from before the reel last changed
function useStaleDraft() {
  const d = staleDraft.value
  staleDraft.value = null
  restore(d.state, mediaById(), [])
  draftAt.value = resumedAt.value = d.updatedAt
}

const saving = ref(false)
const failure = ref('')

async function save() {
  if (saving.value || !seq.value.length) return
  saving.value = true
  failure.value = ''
  const settings = {
    music: pace.music, musicStart: pace.musicStart, beatSync: !!(pace.music && pace.beatSync),
    beatsPerCut: pace.beatsPerCut, defaultLength: pace.len, defaultHold: holdLengths(pace.len).medium.seconds,
    weave: { folder: props.folder, clips: included.value.map((c) => c.mediaId), splitOver: pace.splitOver,
             between: pace.between, pace: pace.len, hold: pace.hold,
             styles: Object.fromEntries(photos.value.filter((c) => chosen[c.mediaId]).map((c) => [c.mediaId, chosen[c.mediaId]])),
             // what each photo holding by style was saved at, to tell holds changed in
             // the reel later; one held exactly isn't listed, so it stays exact
             holds: Object.fromEntries(photos.value.filter((c) => !photoOwn(c)).map((c) => {
               const t = timing.value.get(String(c.mediaId))
               return [c.mediaId, synced.value ? t.beats : Math.round(t.seconds * 100) / 100]
             })) },
  }
  const items = seq.value.map((e) => {
    const c = e.clip
    const id = e.kind === 'video' ? e.part.id : c.id
    const t = timing.value.get(e.key)
    const item = { mediaId: c.mediaId, transition: e.transition, length: Math.round(t.seconds * 100) / 100 }
    if (id) item.id = id
    if (e.kind === 'video') {
      item.start = e.part.start
      item.beats = synced.value && e.part.beats ? e.part.beats : 0   // 0: the reel's beats per part
    } else {
      item.beats = synced.value ? t.beats : 0
    }
    // Framing set here goes on every part; parts framed in the reel keep theirs.
    if (!id || c.framed) Object.assign(item, { focusX: c.focusX, focusY: c.focusY, zoom: c.zoom || 1 })
    return item
  })
  for (const it of untouched) {
    items.push({ id: it.id, mediaId: it.mediaId, start: it.start, length: it.length,
                 beats: it.beats, transition: it.transition })
  }
  try {
    let target = reelId
    if (!target) target = (await api.createReel(newName.value.trim())).id
    await api.updateReel(target, { settings })
    await api.saveItems(target, items)
    await dropDraft()                    // it's a reel now
    router.push(`/reel/${target}`)
  } catch (e) {
    failure.value = e.message
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.total { color: var(--forest); }
.steps { display: flex; gap: 4px; padding: 3px; border-radius: 999px; background: rgb(128 128 128 / 14%); }
.stepchip {
  display: inline-flex; align-items: center; gap: 6px; border: 0; background: transparent; cursor: pointer;
  padding: 4px 12px 4px 4px; border-radius: 999px; font-size: 14px; color: var(--muted);
}
.stepchip .n {
  display: grid; place-items: center; width: 22px; height: 22px; border-radius: 50%;
  background: var(--paper); font-size: 12px; font-weight: 700;
}
.stepchip.done { color: var(--ink); }
.stepchip.done .n { background: var(--sage); color: var(--on-sage); }
.stepchip.on { background: var(--forest); color: var(--cream); font-weight: 600; }
.stepchip.on .n { background: var(--cream); color: var(--forest); }
.stepchip:disabled { cursor: default; opacity: 0.5; }
.draftstate { font-size: 13px; }
.notice { margin: 12px 0 0; padding: 8px 12px; border-radius: 8px; background: var(--sage-soft); font-size: 14px; }
.lead { margin: -4px 0 12px; font-size: 14px; }
.warnnote { margin: 0 0 12px; padding: 8px 12px; border-radius: 8px; border-left: 4px solid var(--warn); background: var(--cream); font-size: 13px; }
.selbar { display: flex; align-items: center; gap: 8px; font-size: 13px; margin-bottom: 10px; }
.small { font-size: 12px; }
.warn { color: var(--danger); }
.link {
  border: 0; background: none; padding: 0; color: var(--forest); font-weight: 600; cursor: pointer;
  text-decoration: underline; text-underline-offset: 2px; font-size: inherit;
}

/* 1. order */
.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(124px, 1fr)); gap: 10px; }
.tile {
  position: relative; aspect-ratio: 3 / 4; border: 0; padding: 0; border-radius: 10px; overflow: hidden;
  background: var(--stage); cursor: grab; outline: 3px solid transparent; outline-offset: -3px;
  border-left: 3px solid transparent;
}
.tile img { width: 100%; height: 100%; object-fit: cover; display: block; opacity: 0.4; pointer-events: none; }
.tile.on { outline-color: var(--sage); }
.tile.on img { opacity: 1; }
.tile.over { border-left-color: var(--forest); box-shadow: -4px 0 0 var(--forest); }
.tile .check {
  position: absolute; top: 6px; right: 6px; width: 22px; height: 22px; border-radius: 50%;
  display: grid; place-items: center; font-size: 13px; font-weight: 700;
  border: 2px solid var(--on-media); background: rgb(0 0 0 / 25%); color: var(--on-sage);
}
.tile.on .check { background: var(--sage); border-color: var(--sage); }
.tag, .time, .badge {
  position: absolute; font-size: 11px; font-weight: 600; color: var(--on-media);
  background: rgb(20 28 20 / 70%); padding: 1px 6px; border-radius: 999px;
}
.tag { top: 6px; left: 6px; }
.time { bottom: 6px; right: 6px; }
.badge { bottom: 6px; left: 6px; background: var(--sage); color: var(--on-sage); }

/* 2. pace */
.pace { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; }
.pace .col { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.pace h3 { margin: 0; }
.pace h3.gap { margin-top: 10px; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 2px; }
.field b { color: var(--ink); }
.field small { font-size: 12px; }
.field.check span { display: flex; gap: 6px; align-items: center; color: var(--ink); font-size: 14px; }
.field input[type='range'] { padding: 0; accent-color: var(--forest); }
.songbar { display: flex; gap: 10px; align-items: center; }
.songbar input { flex: 1; }
.songbar .mono { color: var(--ink); white-space: nowrap; }
.estimate {
  display: flex; flex-direction: column; gap: 6px; padding: 12px 14px; border-radius: 10px;
  background: var(--sage-soft); font-size: 14px;
}
.mini { display: flex; gap: 2px; height: 22px; margin-top: 4px; }
.mseg {
  flex-basis: 0; min-width: 8px; border-radius: 3px; font-size: 10px; font-weight: 700; color: #fff;
  display: grid; place-items: center; overflow: hidden; white-space: nowrap;
}
.mseg.photo { background: var(--paper); color: var(--muted); }
.holds { border-collapse: collapse; font-size: 13px; margin-top: 4px; }
.lenrow { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.exact { font-size: 12px; align-self: center; margin-right: 2px; }
.lenrow input[type='range'] { flex: 1; min-width: 160px; padding: 0; accent-color: var(--forest); }
.holds td { padding: 2px 10px 2px 0; white-space: nowrap; }
.holds td:nth-child(2) { white-space: normal; }

/* 3. moments */
.dots { display: flex; gap: 6px; overflow-x: auto; margin-top: 14px; padding: 2px; }
.dot {
  position: relative; flex: none; width: 48px; height: 64px; padding: 0; border: 0; border-radius: 8px;
  overflow: hidden; cursor: pointer; background: var(--stage); outline: 2px solid transparent; outline-offset: -2px;
}
.dot img { width: 100%; height: 100%; object-fit: cover; opacity: 0.6; }
.dot span {
  position: absolute; left: 4px; bottom: 4px; font-size: 11px; font-weight: 700; color: var(--on-media);
  background: rgb(20 28 20 / 70%); padding: 0 5px; border-radius: 999px;
}
.dot.on { outline-color: var(--forest); }
.dot.on img { opacity: 1; }
.moments { margin-top: 14px; }
.musicbar { margin: 10px 0; padding: 8px 12px; border-radius: 10px; background: var(--sage-soft); font-size: 14px; }
.musicbar summary { display: flex; gap: 10px; align-items: baseline; cursor: pointer; list-style: none; }
.musicbar summary::-webkit-details-marker { display: none; }
.musicbar .songname { font-weight: 600; color: var(--forest); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.musicbar .change { margin-left: auto; text-decoration: underline; }
.musicbar[open] .change { visibility: hidden; }
.musicbar[open] > :not(summary) { margin-top: 8px; }
.musicbar .check { display: flex; gap: 6px; align-items: center; font-size: 13px; }
.musicbar input[type='checkbox'] { accent-color: var(--forest); }
.mtitle { display: flex; align-items: center; gap: 10px; margin: 0; font-size: 17px; word-break: break-all; }
.mtitle .num {
  display: grid; place-items: center; min-width: 26px; height: 26px; border-radius: 50%;
  color: #fff; font-size: 13px; flex: none;
}
.mtitle .mono { margin-left: auto; white-space: nowrap; }

/* 4. stitch */
.seq { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 2px; }
.stile {
  position: relative; width: 72px; height: 96px; border-radius: 8px; overflow: hidden; cursor: grab;
  background: var(--stage); flex: none; border-left: 3px solid transparent;
}
.stile.newround { margin-left: 14px; }
.stile.over { box-shadow: -5px 0 0 var(--forest); }
.stile img { width: 100%; height: 100%; object-fit: cover; pointer-events: none; }
.stile.photo { outline: 2px dashed var(--sage); outline-offset: -2px; }
.stile.burst { outline-style: dotted; outline-color: var(--forest); }
.slabel {
  position: absolute; top: 4px; left: 4px; padding: 0 6px; border-radius: 999px; font-size: 12px;
  font-weight: 700; color: #fff; background: rgb(20 28 20 / 70%);
}
.slen {
  position: absolute; bottom: 4px; right: 4px; font-size: 10px; font-weight: 600; color: var(--on-media);
  background: rgb(20 28 20 / 70%); padding: 0 5px; border-radius: 999px;
}
.tmark {
  width: 20px; height: 20px; padding: 0; border: 1px dashed var(--line); border-radius: 50%;
  background: transparent; color: var(--muted); font-size: 12px; line-height: 1; cursor: pointer; flex: none;
}
.tmark:hover { border-color: var(--forest); color: var(--forest); }
.tmark.soft { border-style: solid; border-color: var(--sage); background: var(--sage-soft); color: var(--forest); }
.savebar { display: flex; align-items: flex-end; gap: 14px; margin-top: 18px; flex-wrap: wrap; }
.savebar .grow { flex: 0 1 360px; }

@media (max-width: 860px) {
  .pace { grid-template-columns: 1fr; }
}
</style>
