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
          <span class="formats" role="group" aria-label="Output shape">
            <span class="muted small">Output</span>
            <button
              v-for="sh in SHAPES" :key="sh.v" class="btn small" :class="{ active: (settings.shape || 'tall') === sh.v }"
              @click="settings.shape = sh.v" :title="sh.hint"
            >{{ sh.v === 'tall' ? '9:16 · A top' : sh.v === 'wide' ? '16:9 · A left' : sh.short }}</button>
          </span>
        </h1>
        <p class="muted">
          {{ kept.length + aParts.length }} of {{ items.length }} parts · {{ sceneList.length }} scene{{ sceneList.length === 1 ? '' : 's' }} ·
          reel <b class="mono total">{{ fmtTime(reelLength) }}</b>
          <span class="save">{{ saveState }}</span>
          <template v-if="reel.archivedAt">
            · <b>archived</b>
          </template>
        </p>
      </div>
      <button class="btn" @click="sortByShotTime" :disabled="items.length < 2">Sort by shot time</button>
      <button
        class="btn" v-if="settings.weave?.folder" @click="reweave"
        :title="draftAt ? 'Pick up the weave edit you started (not saved yet)' : 'Edit this reel in the Weave wizard; saving updates this reel'"
      >⧉ Edit weave{{ draftAt ? ' (unsaved)' : '' }}</button>
      <button class="btn" :class="{ active: showVoice }" @click="showVoice = !showVoice" title="A reading over the footage, and its captions">
        🎙 Voice{{ voiceTl.pieces.length ? ` · ${voiceTl.pieces.length}` : '' }}
      </button>
      <button
        class="btn" @click="setArchived(!reel.archivedAt)"
        :title="reel.archivedAt ? 'Back on the home page' : 'Off the home page and the shoot tags; kept as it is'"
      >{{ reel.archivedAt ? 'Unarchive' : 'Archive' }}</button>
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
        <p class="muted">{{ stageText }} · {{ elapsed }}s
          <span class="small">· the title and end card can still change: they're laid over near the end</span></p>
        <ol v-if="steps.length" class="steps" ref="stepsEl">
          <li v-for="(st, i) in steps" :key="i" :class="{ now: st.now, slow: st.slow }">
            <span class="mono dur">{{ st.secs.toFixed(1) }}s</span> {{ st.label }}
          </li>
        </ol>
      </template>
      <div v-else-if="job.status === 'done'" class="result">
        <video :src="`${api.renderVideo(job.id)}?t=${job.finishedAt}`" controls playsinline></video>
        <div>
          <h3>Rendered</h3>
          <p class="mono path">{{ job.output }}</p>
          <p class="muted">Took {{ Math.round(job.finishedAt - job.startedAt) }}s.</p>
          <details v-if="steps.length" class="stepsbox">
            <summary class="muted small">What took the time</summary>
            <ol class="steps">
              <li v-for="(st, i) in slowest" :key="i" :class="{ slow: st.slow }"><span class="mono dur">{{ st.secs.toFixed(1) }}s</span> {{ st.label }}</li>
            </ol>
          </details>
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
      <div class="sgroup music" :class="{ flash: musicFlash }">
        <div class="musichead">
          <h3>Music</h3>
          <div class="beatbtns">
            <RouterLink
              v-if="songTake" class="btn small primary beatbtn" :to="`/reel/${id}/beat?take=${songTake}`" @click="saver.flushAll()"
              title="Open this beat in the beat studio with its settings, to change it a bit more"
            >✨ Edit this beat</RouterLink>
            <RouterLink
              v-else-if="settings.music" class="btn small primary beatbtn" :to="`/reel/${id}/beat?from=${encodeURIComponent(settings.music)}`" @click="saver.flushAll()"
              title="Make a beat for this reel starting from this song: its groove, tempo and key"
            >✨ Make a beat from this song</RouterLink>
            <RouterLink
              class="btn small beatbtn" :class="{ primary: !settings.music }" :to="`/reel/${id}/beat`" @click="saver.flushAll()"
              title="Make a beat for this reel: its exact length, building up and cooling down with your scenes"
            >{{ settings.music ? 'Beat studio' : '✨ Make a beat for this reel' }}</RouterLink>
          </div>
        </div>
        <div class="musicrow">
          <div class="field song">
            <label for="reel-song">Song</label>
            <SongPicker id="reel-song" v-model="settings.music" v-model:shelf="shelf" />
          </div>
          <label class="field" v-if="settings.music">
            Song starts at
            <input :value="fmtTime(settings.musicStart || 0)" @change="setMusicStart($event)" />
          </label>
          <div class="field" v-if="settings.music && musicUrl">
            &nbsp;
            <button class="btn small" @click="listen">{{ listening ? '■ Stop' : '▶ Listen' }}</button>
          </div>
        </div>
        <p class="muted small">
          Songs come from <code>{{ shelf.dir }}</code><template v-if="!shelf.exists"> (make that folder and drop MP3s in)</template>.
          <template v-if="analyzing"> Finding the beat…</template>
          <template v-else-if="beatData"> {{ Math.round(beatData.bpm) }} bpm · one beat = {{ (60 / beatData.bpm).toFixed(2) }}s.</template>
          <span v-if="musicError" class="warn"> {{ musicError }}</span>
        </p>
        <p v-if="settings.beat?.inUse && settings.music && settings.music.startsWith('Beat ')" class="small">
          ♪ A beat from the <RouterLink :to="`/reel/${id}/beat`">beat studio</RouterLink> is this reel's song.
        </p>
        <div class="musicrow" v-if="settings.music">
          <label class="field check">
            <span><input type="checkbox" v-model="settings.beatSync" :disabled="!shelf.beatDetection" /> Cut on the beat</span>
            <small v-if="!shelf.beatDetection">Needs beat detection: start the studio with <code>./studio/run.sh --beat</code></small>
            <small v-else-if="settings.beatSync">Each part lasts whole beats (a photo can be ½ or ¼); drag or pick beats per part.</small>
            <small v-else>Your lengths are used exactly; the song plays underneath.</small>
          </label>
          <label class="field" v-if="settings.beatSync">
            Beats per part
            <select :value="settings.beatsFit === 'fixed' ? settings.beatsPerCut : 'nearest'" @change="setBeatsFit($event.target.value)">
              <option value="nearest">Nearest to each part's length</option>
              <option v-for="b in BEAT_CHOICES" :key="b" :value="b">{{ b }} each{{ period ? ` ≈ ${(b * period).toFixed(1)}s` : '' }}</option>
            </select>
            <small class="muted">{{ settings.beatsFit === 'fixed' ? 'Parts without beats of their own get this many.' : 'Each part keeps about its length, rounded to whole beats.' }}</small>
          </label>
          <label class="field check">
            <span><input type="checkbox" v-model="settings.musicInVideo" /> Put the song in the video</span>
            <small v-if="settings.musicInVideo">The render includes the music.</small>
            <small v-else>Cut to the song, but leave it out, to add the same song in Instagram (which licenses it).</small>
          </label>
        </div>
      </div>
      <div class="sgroup cards">
        <h3>Title &amp; end card</h3>
        <p class="muted small">Laid over your footage on a dim, see-through layer with cream text. Grey text is a suggestion: <kbd>Tab</kbd> takes it.</p>
        <div class="cardgrid">
          <div class="cardbox" :class="{ off: !titleOn }">
            <header>
              <label class="check"><input type="checkbox" :checked="titleOn" @change="settings.titleCard = $event.target.checked" /> <strong>Title</strong></label>
              <small class="muted">over the opening shots</small>
              <button v-if="titleOn" class="btn small" @click="previewCard('title')" :disabled="!settings.titleText">Preview</button>
            </header>
            <div class="cardfields" v-if="titleOn">
              <label class="field span2">
                Title
                <input v-model="settings.titleText" placeholder="3rd Sundays" @keydown.tab="takeHint($event, 'titleText')" />
              </label>
              <label class="field">
                Under the title
                <input v-model="settings.titleSub" :placeholder="`${MONTH} Edition`" @keydown.tab="takeHint($event, 'titleSub')" />
              </label>
              <label class="field">
                Logo
                <select v-model="settings.titleLogo">
                  <option v-for="l in LOGO_CHOICES" :key="l.v" :value="l.v">{{ l.label }}</option>
                </select>
              </label>
            </div>
            <CardShot v-if="titleOn && cardShot.kind === 'title'" />
          </div>
          <div class="cardbox" :class="{ off: !settings.endCard }">
            <header>
              <label class="check"><input type="checkbox" v-model="settings.endCard" /> <strong>End card</strong></label>
              <small class="muted">over the last part</small>
              <button v-if="settings.endCard" class="btn small" @click="previewCard('end_card')">Preview</button>
            </header>
            <div class="cardfields" v-if="settings.endCard">
              <label class="field span2">
                <span>Lines <small>(the first is big)</small></span>
                <textarea rows="2" v-model="settings.endLines" :placeholder="endHint" @keydown.tab="takeHint($event, 'endLines', endHint)"></textarea>
              </label>
              <label class="field">
                Logo
                <select v-model="settings.endLogo">
                  <option v-for="l in LOGO_CHOICES" :key="l.v" :value="l.v">{{ l.label }}</option>
                </select>
              </label>
              <label class="field">
                Presented by
                <select v-model="settings.endPresentedBy">
                  <option v-for="l in LOGO_CHOICES.filter((c) => c.v !== 'both')" :key="l.v" :value="l.v">{{ l.label }}</option>
                </select>
              </label>
              <label class="field span2">
                Holds the last part longer by
                <select v-model.number="settings.endBeats">
                  <option v-for="b in [2, 4, 8]" :key="b" :value="b">{{ b }} beats{{ synced ? ` ≈ ${(b * period).toFixed(1)}s` : ` ≈ ${b / 2}s` }}</option>
                </select>
              </label>
            </div>
            <CardShot v-if="settings.endCard && cardShot.kind === 'end_card'" />
          </div>
        </div>
      </div>

      <div class="sgroup">
        <h3>Look &amp; timing</h3>
        <div class="sgrid">
          <label class="field">
            Divider between the slots (px at 1080)
            <input type="number" min="0" max="20" step="2" v-model.number="settings.dividerPx" />
          </label>
          <label class="field">
            Divider colour
            <input type="color" v-model="settings.dividerColor" />
          </label>
          <div class="field">
            Shape
            <div class="shapes">
              <button
                v-for="sh in SHAPES" :key="sh.v" class="btn small" :class="{ active: (settings.shape || 'tall') === sh.v }"
                :title="sh.hint" @click="settings.shape = sh.v"
              >{{ sh.label }}</button>
            </div>
            <button class="link" @click="squareBottom" title="Square, with every part framed to the bottom of its shot, where the hands are">Square, framed to the bottom</button>
          </div>
          <div class="field">
            Look
            <div class="shapes">
              <button
                v-for="l in LOOKS" :key="l.v" class="btn small" :class="{ active: (settings.look || '') === l.v }"
                :title="l.hint" @click="settings.look = l.v"
              >{{ l.label }}</button>
            </div>
            <small class="muted">{{ LOOKS.find((l) => l.v === (settings.look || '')).hint }} The preview shows it; titles, cards and captions keep their colours.</small>
          </div>
          <label class="field">
            Framing on its own
            <select v-model="settings.fit">
              <option value="fill">Fill (crop to {{ shapeOf(settings.shape).short }})</option>
              <option value="blur">Blurred background</option>
              <option value="pad">Brand colour bars</option>
            </select>
          </label>
          <div class="field">
            <label for="reel-transition">Default transition</label>
            <select id="reel-transition" v-model="settings.transition">
              <option v-for="t in TRANSITIONS" :key="t.v" :value="t.v">{{ t.label }}</option>
            </select>
            <button class="link" @click="useDefaultEverywhere">Use between every part</button>
          </div>
          <div class="field">
            <label for="reel-length">Default cut length (s)</label>
            <input id="reel-length" type="number" min="0.2" step="0.1" v-model.number="settings.defaultLength" />
            <button class="link" @click="applyLengthToAll">Set every kept cut to {{ settings.defaultLength }}s</button>
          </div>
          <div class="field">
            <label for="reel-hold">Default photo hold (s)</label>
            <input id="reel-hold" type="number" min="0.2" step="0.1" v-model.number="settings.defaultHold" />
            <button
              v-if="kept.some((p) => p.media.kind === 'photo')" class="link" @click="smartHolds" :disabled="timingPhotos"
              :title="anyA ? 'Photos with people or animals hold Medium (4s), the rest Small (3s), and look-alike shots taken together go by as a Burst (2s): with two lanes on screen, nothing shorter. Clips keep their lengths.' : 'Photos with people or animals hold Medium, the rest Small, and look-alike shots taken together flick by as a Burst. Clips keep their lengths.'"
            >{{ timingPhotos ? 'Looking at the photos…' : '✦ Smart photo holds' }}</button>
            <small v-if="smartNote">{{ smartNote }}</small>
          </div>
          <div class="field">
            Glasses audio
            <div class="tbtns">
              <button v-for="g in GLASSES" :key="g.v" class="btn small" :class="{ primary: glasses === g.v }" :title="g.hint" @click="glasses = g.v">{{ g.label }}</button>
            </div>
            <small>{{ GLASSES.find((g) => g.v === glasses).hint }}</small>
          </div>
          <label class="field check" v-if="settings.music">
            <span><input type="checkbox" :checked="settings.duckMusic !== false" @change="settings.duckMusic = $event.target.checked" /> Duck music under glasses + voice</span>
            <small>The song drops about {{ DUCK_DB }}dB while the glasses audio is loud or the voice speaks.</small>
          </label>
          <label class="field" v-if="glasses !== 'off'">
            Glasses audio volume
            <input type="number" min="0" max="1" step="0.05" v-model.number="settings.originalVolume" />
          </label>
        </div>
      </div>

      <div class="sgroup reelactions">
        <button class="btn small" @click="duplicateReel" title="Make a copy of this reel to experiment on">Duplicate this reel</button>
        <button
          class="btn small" @click="setArchived(!reel.archivedAt)"
          :title="reel.archivedAt ? 'Back on the home page' : 'Off the home page and the shoot tags; kept as it is'"
        >{{ reel.archivedAt ? 'Unarchive this reel' : 'Archive this reel' }}</button>
        <button class="btn small danger" @click="removeReel">Delete this reel</button>
      </div>
    </section>

    <VoicePanel
      v-if="showVoice" :reel-id="id" :settings="settings" :reel-length="reelLength" :part-at="partAt"
      :flush="() => saver.flushAll()" :reel-name="reel.name"
    />

    <!-- the reel at a glance: one block per kept part, sized by its length -->
    <section class="transport" v-if="kept.length">
      <button class="btn primary playreel" @click="toggleReel" :title="reelOn ? 'Pause (Space) · Shift+Space: from the start' : 'Play the reel (Space) · Shift+Space: from the start'">
        {{ reelOn ? '❚❚ Pause' : '▶ Play reel' }} <kbd>Space</kbd>
      </button>
      <span class="mono clock">{{ fmtTime(reelTime ?? 0) }} / {{ fmtTime(reelLength) }}</span>
      <button class="btn small" @click="jumpPart(-1)" title="The playhead back to where the last part starts, in either lane">◀ Part</button>
      <button class="btn small" @click="jumpPart(1)" title="The playhead on to where the next part starts, in either lane">Part ▶</button>
      <button
        v-if="settings.music" class="songtag" @click="editSong"
        :title="songTake ? 'Edit this beat in the beat studio' : `${settings.music}: change the song (Settings › Music)`"
      >
        <span class="songname">♪ {{ songTitle(shelf, settings.music) }}{{ beatData ? ` · ${Math.round(beatData.bpm)} bpm` : '' }}</span>
        <span class="songedit">{{ songTake ? '✨ edit' : '✎' }}</span>
      </button>
      <button v-else class="songtag add" @click="editSong" title="Pick a song, or make a beat for this reel">♪ Add music</button>
      <span class="spacer"></span>
      <span v-if="toast" class="toast">{{ toast }}</span>
      <button class="btn small" @click="splitAtPlayhead" title="A new scene starts at the playhead (the nearest cut), with the last split used">Split scene at playhead <kbd>S</kbd></button>
      <button class="btn small" @click="swapScene()" :disabled="!['stack', 'swap'].includes(shownSc?.layout)" title="Swap which lane has the primary slot">Swap A ⇄ B <kbd>W</kbd></button>
      <RouterLink class="btn small" to="/" title="Open a shoot and add parts to this reel: they join lane B">Add clip to B lane…</RouterLink>
      <div class="tracks">
      <!-- dragging a B video: the whole timeline is a drop zone for lane A -->
      <div
        v-if="draggingB" class="tozone" :class="{ hot: dragOver === 'zone' }"
        @dragover.prevent="dragOver = 'zone'" @dragleave.self="dragOver = null" @drop.prevent="dropA(); endDrag()"
      ><span>⤒ Move to A lane</span><small>the main, continuous footage</small></div>
      <div class="ruler">
        <span v-for="t in rulerTicks" :key="t" class="rt mono" :style="{ left: `${(t / (reelLength || 1)) * 100}%` }">{{ fmtTime(t).replace(/\.\d$/, '') }}</span>
      </div>
      <div class="lanerow">
        <div class="lanename"><b>Layout</b><small>scenes</small></div>
        <div class="lanebody scenes" @pointermove="edgeMove" @pointerup="edgeUp">
          <button
            v-for="(sc, k) in sceneList" :key="sc.id" class="scene" :class="[`l-${sc.layout}`, { sel: sc.id === selScene, now: k === shownScene, playing: reelTime !== null && reelTime >= sceneTimes[k].start - 1e-6 && reelTime < sceneTimes[k].end }]"
            :style="laneStyle(sceneTimes[k].start, sceneTimes[k].end - sceneTimes[k].start)" @click="selectScene(k)"
            :title="`Scene ${k + 1}: ${layoutLabel(sc.layout, wide)} · ${fmtTime(sceneTimes[k].start)} → ${fmtTime(sceneTimes[k].end)}`"
          >
            <span class="glyph" :class="`g-${sc.layout}`"><i></i><i></i></span>
            <span class="sname">{{ layoutLabel(sc.layout, wide) }}</span>
            <small class="mono">{{ fmtTime(sceneTimes[k].start) }} → {{ fmtTime(sceneTimes[k].end) }}</small>
          </button>
          <span
            v-for="k in sceneList.length - 1" :key="`e${k}`" class="edge" :class="{ snapped: dragEdge?.k === k && dragEdge.snapped }"
            :style="{ left: `${((dragEdge?.k === k ? dragEdge.t : sceneTimes[k].start) / (reelLength || 1)) * 100}%` }"
            @pointerdown.stop="edgeDown($event, k)" title="Drag to move where the scene changes"
          ></span>
          <div class="reelhead" v-if="reelTime !== null" :style="{ left: `${(reelTime / (reelLength || 1)) * 100}%` }"></div>
        </div>
      </div>
      <div class="lanerow">
        <div class="lanename"><b>A lane</b><small>{{ wide ? 'left' : 'top' }} / main</small></div>
        <div
          class="lanebody" :class="{ over: dragOver === 'A' }"
          @dragover.prevent="dragOver = 'A'" @dragleave="dragOver = null" @drop="dropA"
          title="Drop a B part here to put it in lane A"
        >
          <template v-for="(sc, k) in sceneList" :key="sc.id">
            <button
              v-if="aPlans[k]" draggable="true" @dragstart="dragFrom = `A${sc.a.item}`" @dragend="dragOver = null" class="aseg" :class="{ picked: pickedA === k, warn: aPlans[k].rate > 4.001 }"
              :style="laneStyle(sceneTimes[k].start, sceneTimes[k].end - sceneTimes[k].start)"
              @click="selectA(k)"
              :title="`${byId.get(sc.a.item)?.media.file}: ${fmtTime(aRanges[k][0])} → ${fmtTime(aRanges[k][1])} of the clip`"
            >{{ byId.get(sc.a.item)?.media.file }} · {{ aPlans[k].pieces.length > 1 ? `${aPlans[k].pieces.length} pieces · ` : '' }}{{ rateText(k) }}{{ aTiming(sc) === 'fit' ? ' sped to fit' : '' }}<span v-if="aPlans[k].rate > 4.001" class="warnchip">over 4×</span></button>
            <div
              v-else-if="carryOf(k)" class="aseg relay" :class="{ picked: pickedA === k }" :style="laneStyle(sceneTimes[k].start, sceneTimes[k].end - sceneTimes[k].start)" @click="selectA(k)"
              :title="`Relay: ${carryOf(k).media.file} carries on in A's slot`"
            >↪ {{ carryOf(k).media.file }} carries on</div>
            <div v-else class="off" :style="laneStyle(sceneTimes[k].start, sceneTimes[k].end - sceneTimes[k].start)">{{ aIds.length || sceneList.some((x, i) => carryOf(i)) ? 'A off-screen' : '' }}</div>
          </template>
          <span v-if="!aIds.length && !sceneList.some((x, i) => carryOf(i))" class="muted laneempty">No clip in lane A: ⤒ on a part puts it here</span>
          <div class="reelhead" v-if="reelTime !== null" :style="{ left: `${(reelTime / (reelLength || 1)) * 100}%` }"></div>
        </div>
      </div>
      <div class="lanerow">
        <div class="lanename"><b>B lane</b><small>{{ wide ? 'right' : 'bottom' }} / cut list</small></div>
      <div
        class="strip lanebody" :class="{ over: dragOver === 'B' }"
        @dragover.prevent="dragOver = typeof dragFrom === 'string' ? 'B' : dragOver" @dragleave.self="dragOver = null" @drop="dropB"
      >
        <template v-for="st in stretches" :key="st.key">
          <div
            v-if="st.kind === 'gap'" class="seg gap abs" :style="laneStyle(st.start, st.end - st.start)"
            title="B isn't on screen in this scene"
          >B off-screen</div>
          <button
            v-else class="seg abs" draggable="true"
            @dragstart="startDragB(items.indexOf(st.part))" @dragend="endDrag"
            @dragover.prevent.stop="dragOver = items.indexOf(st.part)" @drop.stop="drop(items.indexOf(st.part))"
            :class="{ picked: pickedB === st.part.id, playing: reelOn && st.part === current, photo: st.part.media.kind === 'photo', over: dragOver === items.indexOf(st.part) }"
            :style="laneStyle(st.start, st.end - st.start)" :title="`${st.part.media.file} · ${len(st.part).toFixed(1)}s`"
            @click="pickB(st.part)"
          >{{ synced ? `${fmtBeats(beatsOf(st.part))}♩` : len(st.part).toFixed(1) }}</button>
        </template>
        <div
          v-for="(x, i) in beatTicks" :key="i" class="tick" :class="{ bar: i % 4 === 0 }"
          :style="{ left: `${x}%` }"
        ></div>
        <div v-if="voiceHold > 0" class="seg spare abs" :style="laneStyle(partsEnd, voiceHold)" :title="`The last part holds ${voiceHold.toFixed(1)}s longer, until the voice ends`"></div>
        <div class="reelhead" v-if="reelTime !== null" :style="{ left: `${(reelTime / (reelLength || 1)) * 100}%` }"></div>
      </div>
      </div>
      <!-- what will be heard: the mix of glasses audio, song and voice (audioMix.js) -->
      <div class="lanerow audiorow">
        <div class="lanename">
          <b>Audio</b><small>{{ envWaiting ? 'measuring…' : 'what you hear' }}</small>
          <button class="tracksbtn" @click="showTracks = !showTracks" :aria-expanded="showTracks" title="A row for each sound, with its volume">{{ showTracks ? 'Hide tracks' : 'Tracks & volume' }}</button>
          <small v-if="faded && !showTracks" class="fadednote">volumes set</small>
        </div>
        <div class="lanebody mixstrip" :title="mixHeard ? '' : 'Nothing is heard yet: glasses audio is off and there\'s no song or voice'">
          <div v-for="(b, i) in bands" :key="`band${i}`" class="band" :style="laneStyle(b.start, b.end - b.start)"></div>
          <button
            v-for="m in quietMarks" :key="`q${m.k}`" class="quiet" :class="{ at: Math.abs(m.t - sceneTimes[m.k].start) < 0.02, hot: dragEdge?.k === m.k }"
            :style="{ left: `${(m.t / (reelLength || 1)) * 100}%` }" :title="markTitle(m)" :aria-label="markTitle(m)" @click="toQuiet(m)"
          >◆</button>
          <svg class="bars" :viewBox="`0 0 ${mix.length || 1} 1`" preserveAspectRatio="none" aria-hidden="true">
            <rect
              v-for="(b, i) in mix" :key="i" :class="`s-${b.src}`" :x="i + 0.14" :width="0.72"
              :y="(1 - Math.max(b.h, 0.02)) / 2" :height="Math.max(b.h, 0.02)"
            ><title>{{ barTitle(b) }}</title></rect>
          </svg>
          <span v-if="!mixHeard && !envWaiting" class="muted laneempty">Silent: glasses audio is off, and no song or voice</span>
          <div class="reelhead" v-if="reelTime !== null" :style="{ left: `${(reelTime / (reelLength || 1)) * 100}%` }"></div>
        </div>
      </div>
      <template v-if="showTracks">
        <div v-for="tr in tracks" :key="tr.id" class="lanerow audiorow trackrow">
          <div class="lanename">
            <b :class="`t-${tr.id}`">{{ tr.name }}</b><small>{{ tr.sub }}</small>
            <div class="fader" :title="`${tr.name}: ${faderPct(tr.id)}%. Drag to turn it up or down; double-click for 100%`">
              <input
                type="range" min="0" max="150" step="5" :value="faderPct(tr.id)" :aria-label="`${tr.name} volume`"
                @input="setFader(tr.id, $event.target.value)" @dblclick="setFader(tr.id, 100)"
              />
              <button class="pct mono" :class="{ muted0: faderPct(tr.id) === 0 }" @click="toggleMute(tr.id)" :aria-label="faderPct(tr.id) === 0 ? `Unmute ${tr.name}` : `Mute ${tr.name}`">{{ faderPct(tr.id) === 0 ? 'off' : `${faderPct(tr.id)}%` }}</button>
            </div>
          </div>
          <div class="lanebody track">
            <div v-for="(b, i) in bands" :key="`band${i}`" class="band" :style="laneStyle(b.start, b.end - b.start)"></div>
            <svg class="bars" :viewBox="`0 0 ${tr.bars.length || 1} 1`" preserveAspectRatio="none" aria-hidden="true">
              <rect
                v-for="(b, i) in tr.bars" :key="i" :class="[`s-${tr.id}`, { dim: !b.on }]" :x="i + 0.14" :width="0.72"
                :y="(1 - Math.max(b.h, 0.02)) / 2" :height="Math.max(b.h, 0.02)"
              />
            </svg>
            <div class="reelhead" v-if="reelTime !== null" :style="{ left: `${(reelTime / (reelLength || 1)) * 100}%` }"></div>
          </div>
        </div>
        <div class="lanerow audiorow">
          <div class="lanename"></div>
          <div class="trackctl">
            <span class="muted small">Glasses audio</span>
            <button v-for="g in GLASSES" :key="g.v" class="btn small" :class="{ primary: glasses === g.v }" :title="g.hint" @click="glasses = g.v">{{ g.label }}</button>
            <label v-if="settings.music" class="small duckbox" :title="`The song drops about ${DUCK_DB}dB while the glasses audio is loud or the voice speaks`">
              <input type="checkbox" :checked="settings.duckMusic !== false" @change="settings.duckMusic = $event.target.checked" /> Duck music under glasses + voice
            </label>
          </div>
        </div>
      </template>
      <!-- the voice track and its captions, on the same clock -->
      <VoiceLanes
        :pieces="voiceTl.pieces" :fx="voiceTl.fx" :lines="settings.captions ? voiceTl.lines : []"
        :length="reelLength" :active="activeLine" @seek="seekAt"
      />
      </div>
    </section>
    <p class="readout muted small">Hatched = that lane isn't on screen in the scene. Click a scene to edit its layout; drag a scene edge to move where it changes. Orange bands = scene transitions. The audio strip shows what you'll actually hear, coloured by where it comes from.</p>

    <p v-if="!items.length" class="panel empty">
      This reel is empty. Open a shoot from the <RouterLink to="/">home page</RouterLink>,
      pick a clip, set a selection and add it to <b>{{ reel.name }}</b>.
    </p>

    <div class="workspace" v-else>
      <aside class="cliplist" ref="listEl">
        <!-- the clip sheet: one row per scene, lane A beside lane B -->
        <ClipSheet
          :rows="sheetRows" :wide="wide" :reel-time="reelTime" :reel-on="reelOn"
          :picked-a="pickedA" :picked-b="pickedB" :picked-clip="pickedClip" :spare-a="spareA" :skipped="skippedParts"
          @seek="seekReel" @pick-a="selectA" @pick-b="(x) => pickB(x)" @pick-clip="(x) => select(items.indexOf(x))"
          @keep="(x, on) => setKeep(x, on)" @cycle="cycle" @drag-b="(x) => startDragB(items.indexOf(x))"
          @drop-on="(x) => drop(items.indexOf(x))" @drop-a="dropA"
        />
      </aside>

      <section class="editor" v-if="current">
        <div class="preview-col" :class="settings.look ? `look-${settings.look}` : ''">
          <div v-if="current.media.missing" class="frame-missing">
            <p class="unplayable">
              This file is missing from <code>{{ current.media.folder }}/{{ current.media.file }}</code>.
              Put it back (or in any shoot folder) and it will relink.
            </p>
          </div>
          <!-- lanes in their slots, as the scene on show has them -->
          <SceneFrame
            v-else-if="(aIds.length || hasRelay) && slots" :frame-w="frameW" :frame-h="frameH" :slots="slots"
            :divider-color="settings.dividerColor" :picked="pickedLane" :captions="slotCaptions" @pick="pickLane" :into="intoNow"
            :a-t="aNow?.t ?? 0" :a-rate="aNow?.rate ?? 1" :a-playing="reelOn && aNow?.playing !== false" :guides="tall && guides"
            @split="(v) => setSplit(shownScene, v)"
          >
            <template #A="{ maxH, out, bindA }">
              <img v-if="handoffShot" class="handoffshot" :src="handoffShot.url" alt="" :style="{ opacity: 1 - handoffShot.fade, objectPosition: handoffShot.pos }" />
              <ReelFrame
                v-if="isA(current) && aNow?.part === current" :key="`edit-${current.mediaId}`" v-bind="frameProps" v-on="frameOn"
                :out="out" :max-h="maxH" muted
              />
              <ReelFrame
                v-else-if="aNow" :key="`a-${aNow.part.id}`" :media="aNow.part.media" :fit="slotFit('A')" :out="out" :max-h="maxH"
                cropped muted :lighten="aNow.part.lighten" v-bind="focusProps(aNow.part, 'A')" :band="carryBand"
                :poster-time="aNow.t" :bind-video="bindA"
              />
            </template>
            <template #B="{ maxH, out }">
              <ReelFrame
                v-if="!isA(current) && (selAK < 0 || reelOn)" :key="`edit-${current.mediaId}`" v-bind="frameProps" v-on="frameOn"
                :out="out" :max-h="maxH"
              />
              <ReelFrame
                v-else-if="shownPart" :key="`b-${shownPart.id}`" :media="shownPart.media" fit="fill" :out="out" :max-h="maxH"
                cropped muted :lighten="shownPart.lighten" v-bind="focusProps(shownPart, 'B')" :band="bBand" :poster-time="shownPart.start"
              />
              <div v-else class="underidle">
                <img v-if="shownPart" :src="api.thumb(shownPart.media.folder, shownPart.media.file, shownPart.start, 480)" alt="" />
                <span>Lane B plays here</span>
              </div>
            </template>
            <p v-if="player.failed.value" class="unplayable">
              This browser can't play this file's codec (HEVC often won't play in Chrome — try Safari).
              Thumbnails and trimming still work.
            </p>
            <template #overlay><CaptionLayer v-if="showCaptions" v-bind="captionProps" /></template>
          </SceneFrame>
          <ReelFrame v-else :key="current.mediaId" v-bind="frameProps" v-on="frameOn" :guides="tall && guides">
            <p v-if="player.failed.value" class="unplayable">
              This browser can't play this file's codec (HEVC often won't play in Chrome — try Safari).
              Thumbnails and trimming still work.
            </p>
            <template #overlay><CaptionLayer v-if="showCaptions" v-bind="captionProps" /></template>
          </ReelFrame>
          <div v-if="anyA" class="nowplaying">
            <button
              v-for="r in nowLanes" :key="r.lane" class="nowrow" :class="[`lane-${r.lane}`, { hidden: r.hidden, picked: !r.hidden && pickedLane === r.lane }]"
              :disabled="r.hidden" @click="pickLane(r.lane)"
            >
              <i></i><b>{{ r.lane }} · {{ r.hidden ? 'hidden' : r.where }}</b>
              <span v-if="r.hidden" class="muted">{{ r.note }}</span>
              <span v-else class="mono">{{ short(r.name) }} — {{ fmtTime(r.t) }} in clip</span>
            </button>
          </div>
          <label class="guides-toggle muted" v-if="tall"><input type="checkbox" v-model="guides" /> Show Instagram overlays <kbd>G</kbd></label>
          <div v-if="restitchAsk" class="flowask">
            <span>
              <b>Stitch the relay back together?</b>
              <small class="muted">Plans the splits and full-frame moments again around what you took out, each clip's stretches as you have them.</small>
            </span>
            <button class="flowok" :disabled="restitching" @click="restitch" title="Stitch it back together">
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" /></svg>
            </button>
            <button class="btn small" @click="restitchAsk = false" title="Leave it as it is">Leave</button>
          </div>
          <div v-else-if="flowAsk" class="flowask">
            <span>
              <b>Move {{ flowPending.length }} later part{{ flowPending.length === 1 ? '' : 's' }} to keep the clips flowing?</b>
              <small class="muted">{{ flowSummary }}</small>
            </span>
            <button class="flowok" @click="applyFlow" title="Do it: move the later parts on">
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" /></svg>
            </button>
            <button class="btn small" @click="leaveFlow" title="Leave the later parts as they are">Leave</button>
          </div>
          <label class="guides-toggle muted" title="Plays small copies of the videos here so the preview keeps up. The render always uses the originals.">
            <input type="checkbox" v-model="lowQuality" /> Display low quality
            <small v-if="lowQuality && lowProgress && lowProgress.ready < lowProgress.total">(making small copies: {{ lowProgress.ready }} of {{ lowProgress.total }}; the originals play until each is ready)</small>
          </label>
          <audio ref="audioEl" v-if="musicUrl" :src="musicUrl" preload="auto" @ended="onSongEnded"></audio>
          <video
            v-if="reelOn && nextMedia" class="preload" muted preload="auto"
            :src="api.media(nextMedia.folder, nextMedia.file)"
          ></video>
        </div>

        <div class="edit-col">

        <!-- the scene inspector -->
        <div v-if="selSc" class="inspector">
          <div class="ihead">
            <div>
              <small class="muted caps">Scene {{ selK + 1 }} of {{ sceneList.length }}</small>
              <h3>{{ layoutLabel(selSc.layout, wide) }}</h3>
              <small class="mono muted">{{ fmtTime(sceneTimes[selK].start) }} → {{ fmtTime(sceneTimes[selK].end) }} · {{ sceneSecs[selK].toFixed(1) }}s</small>
            </div>
            <button class="btn small" @click="selScene = null" title="Back to the part editor">Close</button>
          </div>
          <span class="muted">Layout</span>
          <div class="layouts">
            <button
              v-for="l in SCENE_LAYOUTS" :key="l.v" class="lay" :class="{ active: selSc.layout === l.v }"
              @click="setSceneLayout(selK, l.v)" :title="`${l.label} (${l.key})`"
            ><span class="glyph big" :class="[`g-${l.v}`, { side: wide }]"><i></i><i></i></span>{{ wide && l.wide ? l.wide : l.label }}</button>
          </div>
          <template v-if="['stack', 'swap'].includes(selSc.layout)">
            <span class="muted">Split · or drag the divider in the preview</span>
            <div class="tbtns">
              <button class="btn small" :class="{ active: selSc.split === 0.5 }" @click="setSplit(selK, 0.5)">50 / 50</button>
              <button class="btn small" :class="{ active: selSc.split === 0.58 }" @click="setSplit(selK, 0.58)">58 / 42</button>
              <button class="btn small" :class="{ active: selSc.split === 'square' }" @click="setSplit(selK, 'square')">Square {{ wide ? 'right' : 'bottom' }}</button>
              <span v-if="typeof selSc.split === 'number' && ![0.5, 0.58].includes(selSc.split)" class="mono muted">{{ Math.round(selSc.split * 100) }} / {{ 100 - Math.round(selSc.split * 100) }}</span>
            </div>
          </template>
          <template v-if="['stack', 'swap'].includes(selSc.layout) && sceneList[selK - 1]?.layout === 'soloB'">
            <label class="field check">
              <span><input type="checkbox" :checked="!!selSc.relay" @change="editScene(selK, $event.target.checked ? { relay: true, into: 'handoff' } : { relay: false })" />
                Relay: the shot before carries on in A's slot</span>
              <small class="muted">{{ selSc.relay ? `${carryOf(selK)?.media.file || 'The shot before'} moves into A's slot and keeps playing while B comes in. End the scene with a Solo B that comes in with Take over, and B grows to the full frame.`
                : 'Off: A\'s slot plays lane A.' }}</small>
            </label>
          </template>
          <template v-if="selSc.layout !== 'soloB' && aIds.length && !isRelay(sceneList, selK)">
            <span class="muted">A lane {{ selSc.layout === 'soloA' ? 'in this scene' : 'timing in this scene' }}</span>
            <div class="tbtns" v-if="aParts.length > 1">
              <button
                v-for="ap in aParts" :key="ap.id" class="btn small" :class="{ active: selSc.a.item === ap.id }"
                @click="editA(selK, { item: ap.id, in: null, out: null })"
              >{{ ap.media.file }}</button>
            </div>
            <template v-if="selSc.layout === 'soloA'">
              <label class="field">
                How long A plays alone (s)
                <input type="number" min="1" step="0.5" :value="soloSeconds(selSc).toFixed(1)" @change="editScene(selK, { len: Math.max(1, Number($event.target.value) || 4) }); editA(selK, { out: null })" />
              </label>
            </template>
            <div v-else class="timings">
              <button
                v-for="tm in TIMINGS" :key="tm.v" class="timing" :class="{ active: aTiming(selSc) === tm.v, speedy: tm.speed }"
                @click="editA(selK, { timing: tm.v, ...(tm.v === 'fit' ? {} : { out: null }) })"
              >
                <b>{{ tm.label }}{{ aTiming(selSc) === tm.v && aPlans[selK] && tm.speed ? ` · ${rateText(selK)}` : '' }}</b>
                <small>{{ tm.hint }}</small>
              </button>
            </div>
            <div class="tbtns" v-if="aTiming(selSc) === 'hold'">
              <span class="muted">Speed</span>
              <button
                v-for="r in [0.5, 1, 1.5, 2, 4]" :key="r" class="btn small" :class="{ active: (selSc.a.speed || 1) === r }"
                @click="editA(selK, { speed: r })"
              >{{ r }}×</button>
            </div>
            <label class="field" v-if="aRanges[selK]">
              A starts at (in its clip)
              <span class="tbtns">
                <input class="mono" :value="fmtTime(aRanges[selK][0])" @change="setAIn(selK, $event)" />
                <button v-if="selSc.a.in != null" class="link" @click="editA(selK, { in: null })">carry on from the last scene</button>
              </span>
              <small class="muted">Plays {{ fmtTime(aRanges[selK][0]) }} → {{ fmtTime(aRanges[selK][1]) }} of {{ byId.get(selSc.a.item)?.media.file }}{{ aPlans[selK].pieces.length > 1 ? `, in ${aPlans[selK].pieces.length} pieces` : '' }}{{ aPlans[selK].rate !== 1 ? ` at ${rateText(selK)}` : ' at real speed' }}.
                <b v-if="aShort(aPlans[selK], aSecs[selK]) > 0.05" class="warn">The clip runs out: its last frame holds {{ aShort(aPlans[selK], aSecs[selK]).toFixed(1) }}s.</b>
                <b v-if="aPlans[selK].rate > 4.001" class="warn">Over 4×: think about a shorter stretch of A, or Cut quiet moments.</b></small>
            </label>
          </template>
          <template v-if="selSc.layout === 'soloA' || selSc.layout === 'soloB'">
            <span class="muted">On its own</span>
            <div class="tbtns">
              <button class="btn small" :class="{ active: soloFitOf(selSc) === 'fill' }" @click="editScene(selK, { fill: 'fill' })">Fill</button>
              <button class="btn small" :class="{ active: soloFitOf(selSc) === 'blur' }" @click="editScene(selK, { fill: 'blur' })">Blur fill</button>
            </div>
          </template>
          <template v-if="selK > 0">
            <span class="muted">Into this scene</span>
            <div class="tbtns">
              <button
                v-for="t in INTOS.filter((x) => !x.when || x.when(sceneList[selK - 1], selSc))"
                :key="t.v" class="btn small" :class="{ active: (selSc.into || 'cut') === t.v }"
                @click="editScene(selK, { into: t.v, ...(t.v === 'handoff' && selSc.handoff == null ? { handoff: HANDOFF_DEFAULT } : {}) })"
              >{{ t.v === 'slide' ? (wide ? 'Slide in' : 'Slide up') : t.label }}</button>
            </div>
            <small class="muted">{{ INTOS.find((t) => t.v === (selSc.into || 'cut'))?.hint }}</small>
            <div class="tbtns" v-if="handoffs[selK]">
              <span class="muted">The shot stays in A's slot for</span>
              <button
                v-for="x in [1, 2, 3, 5]" :key="x" class="btn small" :class="{ active: (selSc.handoff ?? HANDOFF_DEFAULT) === x }"
                @click="editScene(selK, { handoff: x })"
              >{{ x }}s</button>
            </div>
          </template>
          <div class="ilinks">
            <button v-if="['stack', 'swap'].includes(selSc.layout)" class="link" @click="splitEverywhere(selK)">Use this split on every stacked scene</button>
            <button v-if="selK > 0" class="link danger" @click="mergeIntoPrevious(selK)">Merge into previous scene</button>
          </div>
        </div>

        <PartHeader v-if="!selSc && headerInfo && anyA" :info="headerInfo" :wide="wide" @lane="moveLane" />
        <template v-if="!selSc && current.media.kind === 'video' && !current.media.missing">
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
          v-if="!selSc" :kind="current.media.kind" :start="current.start" :length="len(current)"
          :duration="current.media.duration" @update="setRange"
        >
          <p v-if="isA(current)" class="topnote muted">
            <template v-for="n in aNeeds.filter((x) => x.part === current)" :key="n.part.id">
              <template v-if="n.used">
                Lane A starts at {{ fmtTime(current.start) }} and plays at real speed for as long as its scenes need:
                <b>{{ fmtTime(n.from) }} → {{ fmtTime(n.to) }}</b> of the clip ({{ (n.to - n.from).toFixed(1) }}s).
                <b v-if="n.short > 0.05" class="warn">The clip runs out {{ n.short.toFixed(1) }}s early: its last frame holds. Start it earlier, or skip quiet moments less.</b>
              </template>
              <template v-else>No scene shows this clip yet: pick it under a split scene's A lane.</template>
            </template>
            Start sets where A begins (the length only matters for <i>Speed up to fit its range</i>). Drag the window above to reframe it
            {{ editShape === 'full' ? 'full frame' : `in its ${editShape} slot` }}.
          </p>
          <label class="field check" v-if="!isA(current)">
            <span><input type="checkbox" :checked="current.keep" @change="setKeep(current, $event.target.checked)" /> In the cut <kbd>X</kbd></span>
          </label>
          <div class="tpick" v-if="synced && !isA(current)">
            <span class="muted">Beats (one beat = {{ period.toFixed(2) }}s)</span>
            <div>
              <button
                v-for="b in beatChoices(current)" :key="b" class="btn small" :class="{ active: beatsOf(current) === b }"
                @click="setBeats(current, b)"
              >{{ fmtBeats(b) }}</button>
              <button class="btn small" @click="beatsAll(beatsOf(current))" :title="`Make every part ${fmtBeats(beatsOf(current))} beats`">Use on every part</button>
            </div>
            <small class="muted">
              {{ fmtBeats(beatsOf(current)) }} beat{{ beatsOf(current) === 1 ? '' : 's' }} ≈ {{ (beatsOf(current) * period).toFixed(1) }}s<template v-if="!current.beats && fitsNearest"> · the nearest to its {{ current.length.toFixed(1) }}s</template>
              <button v-if="current.beats && fitsNearest" class="link" @click="setBeats(current, 0)" :title="`Back to the whole beats nearest its length (${fmtBeats(nearestBeats(current))})`">↺ nearest to its length ({{ fmtBeats(nearestBeats(current)) }})</button>
            </small>
          </div>
          <div class="tpick" v-if="!synced && !isA(current) && current.media.kind === 'video'">
            <span class="muted">Length {{ len(current).toFixed(1) }}s</span>
            <div>
              <button class="btn small" @click="lengthAll(len(current))" :title="`Make every kept clip part ${len(current).toFixed(1)}s (as far as each clip runs)`">Use on every part</button>
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
          <div class="tpick" v-if="!isA(current) && layoutOf(current) === 'fill'">
            <span class="muted">Framing</span>
            <div>
              <button
                v-for="f in FRAMINGS" :key="f.v" class="btn small" :class="{ active: Math.abs(current.focusY - f.v) < 0.01 && (current.zoom || 1) <= 1.001 }"
                @click="setFocus({ x: current.focusX, y: f.v, zoom: 1 })" :title="f.hint"
              >{{ f.label }}</button>
              <button class="btn small" @click="framingAll(current)" title="Frame every part the way this one is">Use on every part</button>
            </div>
          </div>
          <div class="tpick" v-if="!isA(current) && current.keep && aIds.length">
            <span class="muted">This part is in scene {{ sceneOfPart(current) + 1 }} ({{ layoutLabel(sceneList[sceneOfPart(current)]?.layout, wide) }})</span>
            <div>
              <button
                class="btn small" :class="{ active: aloneInScene(current) }" @click="soloThis(current)"
                title="Give this part a scene of its own, full frame (Solo B); what comes after it carries on in the layout it had"
              >On its own (full frame)</button>
              <button
                class="btn small" @click="showAAbove(current)"
                :title="`Start a new scene at this part with A ${wide ? 'beside' : 'above'} it`"
              >Split from here (A {{ wide ? 'beside' : 'above' }})</button>
              <button class="btn small" @click="selectScene(sceneOfPart(current))">Edit the scene</button>
            </div>
          </div>
          <div class="tpick" v-if="!isA(current)">
            <span class="muted">Layout</span>
            <div>
              <button
                v-for="l in LAYOUTS" :key="l.v" class="btn small" :class="{ active: (current.layout || '') === l.v }"
                @click="setLayout(current, l.v)" :title="l.hint"
              >{{ l.label }}</button>
            </div>
          </div>
          <div class="tpick" v-if="hasNext(current)" :class="{ overruled: sceneEdgeAfter(current) }">
            <span class="muted">Into next part <kbd>T</kbd></span>
            <div>
              <button
                v-for="t in TRANSITIONS" :key="t.v" class="btn small" :class="{ active: effective(current) === t.v }"
                @click="setTransition(current, t.v)" :title="t.hint" :disabled="!!sceneEdgeAfter(current)"
              >{{ t.icon }} {{ t.label }}</button>
            </div>
            <small v-if="sceneEdgeAfter(current)" class="muted">A new scene starts after this part: its transition ({{ INTOS.find((t) => t.v === (sceneEdgeAfter(current).into || 'cut')).label }}) is used here.</small>
          </div>
          <button class="btn small" @click="duplicate(current)" v-if="current.media.kind === 'video' && !isA(current)">Use another part of this clip</button>
          <button
            class="btn small" v-if="current.media.kind === 'video' && !isA(current) && current.length >= 8" :disabled="splitting"
            @click="splitQuiet(current)" title="Cut this part where nothing much happens, into parts you can trim like a weave"
          >{{ splitting ? 'Looking for quiet moments…' : '✂ Take out quiet moments' }}</button>
          <small v-if="splitNote" class="muted">{{ splitNote }}</small>
          <button class="btn small" @click="toB(current)" v-if="isA(current)">Move to lane B</button>
          <button class="btn small" @click="remove(current)">Remove from reel</button>
        </TimingFields>

        <p class="muted legend" v-if="segments.length && !selSc">
          Coloured marks under the filmstrip are other parts of this clip:
          <span v-for="s in segments" :key="s.id" class="lg"><span class="sw" :style="{ background: s.color }"></span>{{ s.label }}</span>
        </p>
        <p class="muted keys">
          <kbd>S</kbd> split scene at playhead · <kbd>W</kbd> swap A ⇄ B · <kbd>1</kbd>–<kbd>4</kbd> layout: Solo A · A over B · Solo B · B over A ·
          <kbd>[</kbd>/<kbd>]</kbd> nudge the split 2% · <kbd>Tab</kbd> between lane A and B ·
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
import { computed, h, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { lowQuality, noteLowMade } from '../quality'
import { useRoute, useRouter } from 'vue-router'
import { api, debouncedSaver } from '../api'
import { usePlayer } from '../player'
import { fitRange, fmtBeats, fmtTime, folderTitle, parseTime, reelColor, snapBeats } from '../time'
import { TWO_LANE_FLOOR, holdLengths, photoStyles, timeline } from '../hold'
import { songTitle } from '../songs'
import { fxInfo, songLevel, VOICE_DUCK, VOICE_TAIL, voiceTimeline } from '../captions'
import { useVoicePlayer } from '../voicePlayer'
import CaptionLayer from '../components/CaptionLayer.vue'
import VoiceLanes from '../components/VoiceLanes.vue'
import VoicePanel from '../components/VoicePanel.vue'
import ClipCard from '../components/ClipCard.vue'
import ClipSheet from '../components/ClipSheet.vue'
import PartHeader from '../components/PartHeader.vue'
import SendToPhone from '../components/SendToPhone.vue'
import SongPicker from '../components/SongPicker.vue'
import ReelFrame from '../components/ReelFrame.vue'
import { SHAPES, shapeOf, shapeRatio } from '../shapes'
import { quietCut, topSource } from '../stack'
import { HANDOFF_DEFAULT, INTOS, isRelay, LAYOUTS as SCENE_LAYOUTS, SCENE_IN, SCENE_MOVE, SOLO_A_MIN, TIMINGS, aShort, aTiming, fitted, handoffSecs, frameFor, layoutLabel, newId, normalize,
  resolveA, sceneAPlan, sceneSlots, showsA, showsB, slotShape, soloSeconds } from '../scenes'
import SceneFrame from '../components/SceneFrame.vue'
import { DUCK_DB, GLASSES, MIX, QUIET_SNAP, audioSegments, mixLevel, glassesMode, mixBars, musicBars, quietMarker, trackBars, transitionBands, withDucking } from '../audioMix'
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
const showVoice = ref(false)
const LOGO_CHOICES = [{ v: '', label: 'None' }, { v: 'oufp', label: 'OUFP' },
  { v: 'garden-steward', label: 'Garden Steward' }, { v: 'both', label: 'Both' }]
const MONTH = new Date().toLocaleString('en-US', { month: 'long' })
// The next third Sunday after today, for the end card's suggested line.
function nextThirdSunday(from = new Date()) {
  for (let m = 0; m < 3; m++) {
    const first = new Date(from.getFullYear(), from.getMonth() + m, 1)
    const day = new Date(first.getFullYear(), first.getMonth(), 1 + ((7 - first.getDay()) % 7) + 14)
    if (day > from) return day.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
  }
}
const endHint = `Oakland Urban Farming Project\n3rd Sundays · Next: ${nextThirdSunday()}`
// Tab in an empty box takes its grey suggestion.
function takeHint(e, key, hint = e.target.placeholder) {
  if (!settings[key] && hint) settings[key] = hint
}
const cardShot = reactive({ kind: '', url: '', error: '' })
// The preview under a card's fields: the picture, or why there isn't one.
const CardShot = {
  setup: () => () => h('div', { class: 'cardpreview' }, cardShot.error
    ? [h('p', { class: 'warn small' }, cardShot.error), h('button', { class: 'link', onClick: closeCard }, 'Close')]
    : cardShot.url && [
      h('img', { src: cardShot.url, alt: 'Preview' }),
      h('div', { class: 'cardpreview-actions' }, [
        h('button', { class: 'link', onClick: () => previewCard(cardShot.kind) }, 'Refresh'),
        h('button', { class: 'link', onClick: closeCard }, 'Close'),
      ]),
    ]),
}
async function previewCard(kind) {
  await saver.flushAll()
  try {
    const url = await api.cardPreview(id, kind)
    if (cardShot.url) URL.revokeObjectURL(cardShot.url)
    Object.assign(cardShot, { kind, url, error: '' })
  } catch (err) {
    Object.assign(cardShot, { kind, url: '', error: err.message })
  }
}
// Turning the end card on starts it with the suggested lines, to edit.
// The reel's song, if it's a take made in the beat studio for this reel: its id (in the file name).
const songTake = computed(() => {
  const m = /(\d{8}-\d{6}-[0-9a-f]{4})\.mp3$/.exec(settings.music || '')
  return m && String(settings.music).startsWith('Beat ') ? m[1] : null
})
// The song tag by Play reel: a beat from the studio opens there; any other
// song (or none) opens Settings at Music, the song picker ready.
const musicFlash = ref(false)
async function editSong() {
  stopReel()
  if (songTake.value) {
    await saver.flushAll()
    router.push(`/reel/${id}/beat?take=${songTake.value}`)
    return
  }
  showSettings.value = true
  await nextTick()
  const box = document.querySelector('.sgroup.music')
  box?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  document.getElementById('reel-song')?.focus({ preventScroll: true })
  musicFlash.value = true
  setTimeout(() => { musicFlash.value = false }, 1600)
}
// The title is on when ticked (reels from before: when it has text).
const titleOn = computed(() => settings.titleCard ?? !!(settings.titleText || '').trim())
watch(() => settings.endCard, (on) => { if (on && ready && !settings.endLines) settings.endLines = endHint })
function closeCard() {
  if (cardShot.url) URL.revokeObjectURL(cardShot.url)
  Object.assign(cardShot, { kind: '', url: '', error: '' })
}
const exporting = ref(false)
const exportResult = ref(null)
const listEl = ref(null)
const dragFrom = ref(null)
const dragOver = ref(null)
const guides = ref(false)
const job = ref(null)
const sending = ref(null)   // render file name being sent to the phone
const draftAt = ref(null)   // an unsaved weave edit of this reel, saved then
const clock = ref(Date.now() / 1000)

const current = computed(() => items.value[selected.value])
// Lane A: the main, continuous footage (settings.laneA); lane B: the other
// kept parts, one after another (see scenes.js).
const aIds = computed(() => (settings.laneA || []).filter((i) => items.value.some((p) => p.id === i && p.media.kind === 'video')))
const aParts = computed(() => aIds.value.map((i) => items.value.find((p) => p.id === i)))
const isA = (p) => !!p && aIds.value.includes(p.id)
const kept = computed(() => items.value.filter((p) => p.keep && !p.media.missing && !isA(p)))
const reelLength = computed(() => partsEnd.value + voiceHold.value)
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
    else if (key === 'reading') await api.saveReading(patch.id, { pieces: patch.pieces })
    else await api.updateItem(key, patch)
    saveState.value = '· saved'
  } catch (e) {
    saveState.value = `· not saved: ${e.message}`
  }
})

let ready = false
async function loadReel() {
  const data = await api.reel(id)
  items.value = data.items
  otherItems.value = data.otherItems
  Object.assign(settings, data.settings)
  return data
}
onMounted(async () => {
  try {
    const data = await api.reel(id)
    reel.value = { name: data.name, archivedAt: data.archivedAt || null }
    items.value = data.items
    otherItems.value = data.otherItems
    draftAt.value = data.draftAt || null
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
// The voice track is saved to its reading (which other reels may share), not the reel.
watch(() => settings.voice, (pieces) => {
  if (ready && settings.readingId) saver.queue('reading', { id: settings.readingId, pieces })
}, { deep: true })

// ---------------------------------------------------------------- selection

function select(i, fromReel = false) {
  if (i < 0 || i >= items.value.length) return
  if (!fromReel) {
    stopReel()
    restart = false   // picking a cut means "play from here"
    selScene.value = null
    selA.value = null
    parkT.value = null
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
    setBeats(p, snapBeats(length / period.value, p.media.kind === 'photo'))
    length = len(p)
  }
  const r = p.media.kind === 'video'
    ? fitRange(start, length, p.media.duration)
    : { start: 0, length: Math.max(0.2, Math.round(length * 100) / 100) }
  if (Math.abs(r.start - p.start) < 0.005 && Math.abs(r.length - p.length) < 0.005) return   // nothing changed (a field losing focus)
  const moved = Math.abs(r.start - p.start) > 0.005
  const delta = (r.start + r.length) - (p.start + p.length)
  Object.assign(p, r)
  saver.queue(p.id, r)
  flowEdit.value = { id: p.id, delta: Math.max(0, delta), moved }
}

// A relay is one clip carrying on through several parts: full frame, then
// on top while something comes in under it (the shot carrying on is the
// part before, played on), then full frame again. So each part of a clip
// starts where its last one left off, plus the time it carried on in A's
// slot; and a newcomer's part full frame starts where its part underneath
// ended. These links, in order: [{ from, to, gap }] (to.start = from's end + gap).
const flowLinks = computed(() => {
  const scs = sceneList.value
  const out = []
  scs.forEach((sc, k) => {
    if (!isRelay(scs, k)) return
    const next = scs[k + 1]
    if (!next || next.layout !== 'soloB' || next.into !== 'takeover') return
    const top = byId.value.get(scs[k - 1].parts[scs[k - 1].parts.length - 1])
    const under = sc.parts.map((id) => byId.value.get(id)).filter(Boolean)
    const after = byId.value.get(next.parts[0])
    if (!top || !after || !under.length || after.media.kind !== 'video') return
    const last = under[under.length - 1]
    if ((next.grow === 'A' || after.mediaId !== last.mediaId) && after.mediaId === top.mediaId) {
      out.push({ from: top, to: after, under })   // the host carried on over the split
    } else if (after.mediaId === last.mediaId) {
      out.push({ from: last, to: after, under: [] })   // the newcomer, now full frame
    }
  })
  return out
})
// After an edit, what the rest of a relay would need to keep flowing, as a
// plan to look at before it's done (the ✓ under the preview), so trying
// things out never moves parts further down the reel by itself:
// - links: each later part of a clip starts where its last left off (plus
//   the time it carried on on top); a part whose start was moved moves the
//   end of the part before it instead
// - stretches of one clip never overlap (counting the time one plays on on
//   top as the next comes in under it): one pushed into the next pushes it
//   on by as much as the edit added, and that one the next, and so on
// The last edit: { id, delta (seconds added to its end), moved (its start changed) }.
const flowEdit = ref(null)
const flowDismissed = ref('')
function flowPlan(edit) {
  const links = flowLinks.value
  if (!hasRelay.value) return []
  const sim = new Map(kept.value.map((p) => [p.id, { start: p.start, length: p.length }]))
  const S = (q) => sim.get(q.id) || { start: q.start, length: q.length }
  const L = (q) => (synced.value ? len(q) : S(q).length)
  const set = (q, r) => sim.set(q.id, { ...S(q), ...r })
  const r2 = (v) => Math.round(v * 100) / 100
  const gapOf = (l) => l.under.reduce((s, q) => s + L(q), 0)
  const clampTo = (q, start) => {
    const dur = q.media.duration || Infinity
    const st = r2(Math.min(start, Math.max(0, dur - 0.2)))
    return { start: st, length: r2(Math.max(0.2, Math.min(S(q).length, dur - st))) }
  }
  const edited = edit && byId.value.get(edit.id)
  const back = edit?.moved && edited && links.find((l) => l.to === edited)
  if (back && back.from.media.kind === 'video') {
    const length = r2(S(edited).start - gapOf(back) - S(back.from).start)
    if (length >= 0.2) set(back.from, { length })
  }
  const linked = new Set(links.map((l) => l.to.id))
  // how long a part plays on past its end, on top while the next comes in under it
  const carried = new Map()
  sceneList.value.forEach((sc, k) => {
    if (!isRelay(sceneList.value, k)) return
    const prev = sceneList.value[k - 1]
    carried.set(prev.parts[prev.parts.length - 1], sc.parts.map((id) => byId.value.get(id)).filter(Boolean))
  })
  const carriedFor = (q) => (carried.get(q.id) || []).reduce((s, u) => s + L(u), 0)
  for (let pass = 0; pass < 8; pass++) {
    let changed = false
    for (const l of links) {
      const want = r2(S(l.from).start + L(l.from) + gapOf(l))
      if (Math.abs(want - S(l.to).start) < 0.01) continue
      set(l.to, clampTo(l.to, want))
      changed = true
    }
    // where each clip's footage has got to (a part on top carries on past its own end)
    const reach = new Map()
    for (const q of kept.value) {
      if (q.media.kind !== 'video') continue
      const was = reach.get(q.mediaId)
      if (was !== undefined && !linked.has(q.id) && q.id !== edit?.id && S(q).start < was - 0.01) {
        set(q, clampTo(q, S(q).start + Math.max(edit?.delta || 0, was - S(q).start)))
        changed = true
      }
      const end = S(q).start + L(q) + carriedFor(q)
      reach.set(q.mediaId, Math.max(was ?? -Infinity, end))
    }
    if (!changed) break
  }
  return kept.value
    .filter((q) => Math.abs(S(q).start - q.start) >= 0.01 || Math.abs(S(q).length - q.length) >= 0.01)
    .map((q) => ({ part: q, patch: { start: S(q).start, length: S(q).length } }))
}
const flowPending = computed(() => flowPlan(flowEdit.value))
const flowSig = computed(() => flowPending.value.map((c) => `${c.part.id}:${c.patch.start}:${c.patch.length}`).join('|'))
const flowAsk = computed(() => flowPending.value.length && flowSig.value !== flowDismissed.value)
// e.g. "d_long.mp4 2:20.0 → 2:45.0, and 2 more"
const flowSummary = computed(() => {
  const ch = flowPending.value
  const say = (c) => {
    const s = Math.abs(c.patch.start - c.part.start) >= 0.01
    return s ? `${c.part.media.file} ${fmtTime(c.part.start)} → ${fmtTime(c.patch.start)}`
      : `${c.part.media.file} ${c.part.length.toFixed(1)}s → ${c.patch.length.toFixed(1)}s`
  }
  return ch.slice(0, 2).map(say).join(' · ') + (ch.length > 2 ? `, and ${ch.length - 2} more` : '')
})
function applyFlow() {
  for (const { part, patch } of flowPending.value) {
    Object.assign(part, patch)
    saver.queue(part.id, patch)
  }
  flowEdit.value = null
  flowDismissed.value = ''
}
function leaveFlow() {
  flowDismissed.value = flowSig.value
  flowEdit.value = null
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

// The selected part's framing is kept per slot shape: the full frame is its
// own (focusX/Y, zoom), a half or square slot remembers its own.
function setFocus({ x, y, zoom }) {
  const p = current.value
  const shape = editShape.value
  if (shape === 'full') {
    const patch = { focusX: x, focusY: y }
    if (zoom !== undefined) patch.zoom = zoom
    Object.assign(p, patch)
    saver.queue(p.id, patch)
    return
  }
  const was = frameFor(p, shape, isA(p) ? 'A' : 'B')
  const frames = { ...(p.frames || {}), [shape]: { x, y, zoom: zoom ?? was.zoom } }
  p.frames = frames
  saver.queue(p.id, { frames })
}

// Quick framings: the whole width (zoom 1), at the top, middle or bottom.
const FRAMINGS = [
  { v: 0, label: 'Top', hint: 'Keep the top of the shot' },
  { v: 0.5, label: 'Middle', hint: 'Keep the middle of the shot' },
  { v: 1, label: 'Bottom', hint: 'Keep the bottom of the shot, where the hands are' },
]
function frame(p, patch) {
  Object.assign(p, patch)
  saver.queue(p.id, patch)
}
// Every B part framed like this one, in the slot shape being edited.
function framingAll(from) {
  const shape = editShape.value
  const f = frameFor(from, shape, 'B')
  for (const p of kept.value) {
    if (p === from) continue
    if (shape === 'full') frame(p, { focusX: f.x, focusY: f.y, zoom: f.zoom })
    else frame(p, { frames: { ...(p.frames || {}), [shape]: { ...f } } })
  }
}
// Square, every part showing the bottom of its shot at full width.
function squareBottom() {
  settings.shape = 'square'
  for (const p of kept.value) frame(p, { focusY: 1, zoom: 1 })
}

function setKeep(p, keep) {
  p.keep = keep
  saver.queue(p.id, { keep })
  if (hasRelay.value) restitchAsk.value = true
}

// A part taken out of a relay (or put back) leaves a hole in it: the split
// it was in loses a side and the clip around it jumps. Stitching it back
// together plans the relay again from what's left (server.py restitch),
// each stretch as you have it, after a ✓ under the preview.
const restitchAsk = ref(false)
const restitching = ref(false)
async function restitch() {
  restitching.value = true
  try {
    await saver.flushAll()
    ready = false
    await api.restitch(id)
    await loadReel()
    restitchAsk.value = false
    flowEdit.value = null
    selScene.value = null
    selected.value = Math.min(selected.value, items.value.length - 1)
    saveState.value = '· stitched back together'
  } catch (e) {
    saveState.value = `· not stitched: ${e.message}`
  } finally {
    restitching.value = false
    setTimeout(() => { ready = true })
  }
}

function applyLengthToAll() {
  lengthAll(Number(settings.defaultLength))
}
function lengthAll(len) {
  if (!(len > 0)) return
  for (const p of items.value) {
    if (!p.keep || p.media.kind !== 'video' || isA(p)) continue
    const r = fitRange(p.start, len, p.media.duration)
    Object.assign(p, r)
    saver.queue(p.id, r)
  }
}

async function remove(p) {
  if (hasRelay.value) restitchAsk.value = true
  await api.deleteItem(p.id)
  const i = items.value.indexOf(p)
  items.value.splice(i, 1)
  select(Math.min(i, items.value.length - 1))
}

// A second part of the same clip, starting just after this one.
async function duplicate(p) {
  const r = fitRange(p.start + len(p), p.length, p.media.duration)
  const item = await api.addItem(id, { mediaId: p.mediaId, ...r, focusX: p.focusX, focusY: p.focusY, zoom: p.zoom,
                                       lighten: p.lighten, layout: p.layout, frames: p.frames || {} })
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
  if (typeof from === 'string' && from.startsWith('A')) return toB(byId.value.get(Number(from.slice(1))), to)   // from lane A
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

// A reel made with Weave: back into the wizard, which saves into this reel.
async function reweave() {
  stopReel()
  await saver.flushAll()
  router.push({ path: `/weave/${encodeURIComponent(settings.weave.folder)}`, query: { reel: id } })
}

// Archive: off the home page (and back there); unarchiving stays here.
async function setArchived(archived) {
  try {
    await saver.flushAll()
    await api.updateReel(id, { archived })
    if (archived) router.push('/')
    else reel.value.archivedAt = null
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
const beatChoices = (p) => (p.media.kind === 'photo' ? [0.25, 0.5, ...BEAT_CHOICES] : BEAT_CHOICES)   // quick photos: ¼, ½
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
// Where beat i falls; a fraction (½, ¼) is that share of the way to the next.
const beatAt = (i) => {
  const g = grid.value
  const at = (k) => (k < g.rel.length ? g.rel[k] : g.rel[g.rel.length - 1] + (k - g.rel.length + 1) * g.step)
  const k = Math.floor(i)
  return i === k ? at(k) : at(k) + (i - k) * (at(k + 1) - at(k))
}
// A part's beats when cutting on the beat: its own; else the whole beats
// nearest its length (a photo can be ½ or ¼), or the reel's fixed count.
// The same as nearest_beats in server.py.
function nearestBeats(p) {
  const v = period.value ? p.length / period.value : 0
  if (p.media.kind === 'photo' && v < 0.375) return 0.25
  if (p.media.kind === 'photo' && v < 0.75) return 0.5
  return Math.min(Math.max(Math.round(v), 1), 2048)
}
const fitsNearest = computed(() => settings.beatsFit !== 'fixed' && period.value > 0)
const beatsOf = (p) => p.beats || (fitsNearest.value ? nearestBeats(p) : Number(settings.beatsPerCut) || 4)

// The reel's stretches, in order: each scene's parts, and for a Solo A
// scene the time A plays alone (whole beats when cutting on the beat). Each
// gets its start and end on the reel's timeline, and its scene.
const sceneList = computed(() => normalize(settings.scenes, kept.value.map((p) => p.id), aIds.value))
const byId = computed(() => new Map(items.value.map((p) => [p.id, p])))
const stretches = computed(() => {
  const out = []
  sceneList.value.forEach((sc, k) => {
    if (sc.layout === 'soloA') {
      const secs = soloSeconds(sc)
      out.push({ kind: 'gap', key: `solo${sc.id}`, scene: k, secs, beats: synced.value && period.value ? Math.max(1, Math.round(secs / period.value)) : 0 })
    } else {
      for (const pid of sc.parts) {
        const p = byId.value.get(pid)
        out.push({ kind: 'part', key: p.id, part: p, scene: k, beats: beatsOf(p), secs: p.length })
      }
    }
  })
  let c = 0
  let t = 0
  for (const st of out) {
    st.start = t
    if (synced.value && grid.value) { c += st.beats; t = beatAt(c) } else t += st.secs
    st.end = t
  }
  return out
})
// Where each scene starts and ends on the reel's clock (the last runs on
// while the voice finishes).
const sceneTimes = computed(() => sceneList.value.map((sc, k) => {
  const own = stretches.value.filter((st) => st.scene === k)
  const start = own[0]?.start ?? 0
  const end = k === sceneList.value.length - 1 ? reelLength.value : (own[own.length - 1]?.end ?? start)
  return { start, end }
}))
const spans = computed(() => stretches.value.filter((st) => st.kind === 'part'))
const partsEnd = computed(() => stretches.value[stretches.value.length - 1]?.end || 0)
const partStart = (k) => spans.value[k]?.start ?? partsEnd.value
const partEnd = (k) => spans.value[k]?.end ?? partsEnd.value
// How long a part plays: its beats when cutting on the beat, else its length.
function len(p) {
  if (!p) return 0
  if (isA(p)) return p.length
  if (!synced.value) return p.length
  const k = kept.value.indexOf(p)
  return k >= 0 ? partEnd(k) - partStart(k) : beatsOf(p) * period.value
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

function setBeatsFit(v) {
  if (v === 'nearest') settings.beatsFit = 'nearest'
  else { settings.beatsFit = 'fixed'; settings.beatsPerCut = Number(v) }
}
function setBeats(p, n) {
  p.beats = n
  saver.queue(p.id, { beats: n })
}
function beatsAll(n) {
  for (const p of items.value) if (p.beats !== n) setBeats(p, n)
}

// Smart photo holds (see hold.js): each kept photo holds as long as what's
// in it needs, against the reel's cut length (or beats per part). Clips keep
// their own lengths.
const timingPhotos = ref(false)
const smartNote = ref('')
async function smartHolds() {
  const photos = kept.value.filter((p) => p.media.kind === 'photo')
  if (!photos.length || timingPhotos.value) return
  timingPhotos.value = true
  smartNote.value = ''
  try {
    const { looks, detects } = await api.looks([...new Set(photos.map((p) => p.mediaId))])
    const entries = kept.value.map((p) => ({ mediaId: p.mediaId, kind: p.media.kind, media: p.media }))
    const styles = photoStyles(entries, looks)
    // Two lanes on screen: no photo flicks by in under TWO_LANE_FLOOR seconds.
    const sizes = holdLengths(Number(settings.defaultLength) || 2, synced.value ? period.value : 0,
                              Number(settings.beatsPerCut) || 4, anyA.value ? TWO_LANE_FLOOR : 0)
    const t = timeline(entries.map((e) => (e.kind === 'photo' ? styles.get(e.mediaId).style : 'clip')), sizes)
    kept.value.forEach((p, i) => {
      if (p.media.kind !== 'photo') return
      const r = { length: Math.round(t[i].seconds * 100) / 100 }
      if (synced.value) r.beats = t[i].beats
      Object.assign(p, r)
      saver.queue(p.id, r)
    })
    const count = (s) => photos.filter((p) => styles.get(p.mediaId).style === s).length
    smartNote.value = `${count('medium')} Medium · ${count('small')} Small · ${count('burst')} in bursts`
      + (anyA.value ? ` · two lanes, so none under ${TWO_LANE_FLOOR}s` : '')
      + (detects ? '' : " (this computer can't look for people and animals, so Medium stands in for Small)")
  } catch (e) {
    smartNote.value = `Couldn't look at the photos: ${e.message}`
  } finally {
    timingPhotos.value = false
  }
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

// The song ran out before the reel: the clock carries on from there without it.
let songOver = null   // {t, at}: where the song ended on the reel's clock, and when
function startSong(at) {
  const a = audioEl.value
  if (!a) return
  songOver = null
  a.volume = songOut(at)
  a.currentTime = songT0.value + at
  if (a.duration && songT0.value + at >= a.duration - 0.05) songOver = { t: at, at: performance.now() }   // past the song's end
  else a.play().catch(() => {})
  cancelAnimationFrame(songRaf)
  const tick = () => {
    if (!reelOn.value) return
    const t = songOver ? songOver.t + (performance.now() - songOver.at) / 1000 : a.currentTime - songT0.value
    songClock.value = t
    a.volume = songOut(t)   // its level under the voice, and the music fader as it moves
    const k = reelIdx.value
    if (gapFrom.value !== null) { if (t >= partStart(k + 1)) startPart(k + 1) } else if (k < kept.value.length && t >= partEnd(k)) afterPart(k)
    songRaf = requestAnimationFrame(tick)
  }
  songRaf = requestAnimationFrame(tick)
}
function onSongEnded() {
  listening.value = false
  if (!reelOn.value) return
  // More reel than song: keep playing to the end of the reel, on the clock alone.
  const t = (audioEl.value?.duration || 0) - songT0.value
  if (t < reelLength.value - 0.05) songOver = { t, at: performance.now() }
  else { stopReel(); restart = true }
}
function listen() {
  const a = audioEl.value
  if (!a) return
  if (listening.value) return stopListening()
  stopReel()
  a.volume = Math.min(1, Math.max(0, Number(settings.musicVolume ?? 0.8) * mixLevel(settings, 'music')))
  a.currentTime = songT0.value
  a.play().catch(() => {})
  listening.value = true
}
function stopListening() {
  if (listening.value) audioEl.value?.pause()
  listening.value = false
}
onBeforeUnmount(() => { cancelAnimationFrame(songRaf); audioEl.value?.pause() })

// ---------------------------------------------------------------- voice & captions

// The reading over the footage: its pieces and caption lines on the reel's
// clock. With Fit to voice, the last part holds until the voice is done.
const voiceTl = computed(() => voiceTimeline(settings.voice))
const voiceHold = computed(() => {
  const end = voiceTl.value.end
  if (!end || settings.voiceFit === false) return 0
  return Math.max(0, end + VOICE_TAIL - partsEnd.value)
})
const voicePlayer = useVoicePlayer()
watch(() => voiceTl.value.pieces.map((p) => `${p.folder}/${p.file}`).join('|'), (keys) => {
  if (keys) voicePlayer.prepare(voiceTl.value.pieces)
})
const showCaptions = computed(() => reelOn.value && settings.captions !== false && voiceTl.value.lines.length > 0)
const captionProps = computed(() => ({
  lines: voiceTl.value.lines, variant: settings.captionStyle, font: settings.captionFont, bg: settings.captionBg,
  size: Number(settings.captionSize) || 1, title: settings.captionTitle || '', clock: captionClock,
  fx: settings.captionFx !== false, ratio: shapeRatio(settings.shape),
}))
// The captions read the reel's time themselves (CaptionLayer), so the page
// playing doesn't hand them a new time, and redraw them, every frame.
const captionClock = () => reelTime.value ?? 0
// The caption line being said: changes once a line, not once a frame.
const activeLine = computed(() => {
  const t = reelTime.value
  return t === null ? -1 : voiceTl.value.lines.findIndex((l) => t >= l.start && t < l.end)
})
const laneStyle = (at, length) => ({
  left: `${(at / (reelLength.value || 1)) * 100}%`, width: `${(length / (reelLength.value || 1)) * 100}%`,
})
// The part on screen at reel time t, and where in its clip: for the captions preview.
function partAt(t) {
  const list = kept.value
  if (!list.length) return null
  let k = list.length - 1
  for (let i = 0; i < list.length; i++) if (t < partEnd(i)) { k = i; break }
  const p = list[k]
  const within = Math.max(0, Math.min(t, partEnd(k)) - partStart(k))
  const src = p.media.kind === 'video'
    ? Math.floor(Math.max(0, Math.min(p.start + within, (p.media.duration || Infinity) - 0.2)) * 2) / 2 : 0
  return { item: p.id, src, thumb: api.thumb(p.media.folder, p.media.file, src, 480) }
}
// Clicking the voice or caption lane: play (or select) the part under that point.
function seekAt(t) {
  const k = kept.value.findIndex((p, i) => t < partEnd(i))
  jumpTo(kept.value[k < 0 ? kept.value.length - 1 : k])
}
// The song while a voice plays: it dips under the voice (the Music fader
// sets how loud it is overall).
const songVolume = (t) => {
  const base = Number(settings.musicVolume ?? 0.8)
  return voiceTl.value.pieces.length ? songLevel(voiceTl.value.pieces, base * VOICE_DUCK, base, t) : base
}

// What the song plays at here: its level (under the voice) through the music fader.
const songOut = (t) => Math.min(1, Math.max(0, songVolume(t) * mixLevel(settings, 'music')))
// The faders reach Play reel too: the voice as it plays, B's own sound in the
// preview (a browser can't play a video above 100%; the render goes to 150%).
watch(() => mixLevel(settings, 'voice'), (v) => voicePlayer.setVolume(v), { immediate: true })
watch(() => [mixLevel(settings, 'B'), player.video.value], ([v, el]) => { if (el) el.volume = Math.min(1, v) }, { immediate: true })
watch(() => mixLevel(settings, 'music'), () => {
  const a = audioEl.value
  if (a && listening.value) a.volume = Math.min(1, Math.max(0, Number(settings.musicVolume ?? 0.8) * mixLevel(settings, 'music')))
})

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

// The reel's look, on every clip (montage.py LOOKS); the preview copies it with CSS.
const LOOKS = [
  { v: '', label: 'As shot', hint: 'The clips as they are.' },
  { v: 'vivid', label: 'Vivid', hint: 'More colour, a touch more contrast and depth in the shadows.' },
  { v: 'rich', label: 'Rich', hint: 'Stronger still: deep colour and contrast.' },
]

// ---------------------------------------------------------------- lanes & scenes

// Scenes say what's on screen (scenes.js): Solo A, A over B, Solo B, B over
// A. A B scene runs as long as its parts; a Solo A scene as long as A plays
// alone. The output shape decides whether a split reads top/bottom or
// left/right.
const tall = computed(() => (settings.shape || 'tall') === 'tall')   // Instagram's overlays only cover a tall reel
const frameW = computed(() => shapeOf(settings.shape).w)
const frameH = computed(() => shapeOf(settings.shape).h)
const wide = computed(() => frameW.value > frameH.value)
const selScene = ref(null)   // the scene in the inspector (its id), or null: the part editor
const sceneSecs = computed(() => sceneTimes.value.map((t) => Math.max(t.end - t.start, 0.04)))
const sceneIndexAt = (t) => {
  const k = sceneTimes.value.findIndex((x) => t < x.end - 1e-6)
  return k < 0 ? sceneList.value.length - 1 : k
}
const sceneOfPart = (p) => sceneList.value.findIndex((sc) => sc.parts.includes(p?.id))
// The scene in the preview: on the reel's clock while it plays; else the one
// in the inspector; else the selected part's.
const shownScene = computed(() => {
  if (reelOn.value && reelTime.value !== null) return sceneIndexAt(reelTime.value)
  const sel = sceneList.value.findIndex((sc) => sc.id === selScene.value)
  if (sel >= 0) return sel
  if (selAK.value >= 0) return selAK.value
  if (current.value && !isA(current.value)) {
    const k = sceneOfPart(current.value)
    if (k >= 0) return k
  }
  if (isA(current.value)) {
    const k = sceneList.value.findIndex((sc) => showsA(sc) && sc.a?.item === current.value.id)
    if (k >= 0) return k
  }
  return 0
})
const shownSc = computed(() => sceneList.value[shownScene.value] || null)
const slots = computed(() => shownSc.value && sceneSlots(shownSc.value, frameW.value, frameH.value, Number(settings.dividerPx) || 0))
// Which framing the selected part is edited in: the slot shape it has in the scene shown.
const editShape = computed(() => {
  const sc = shownSc.value
  const lane = isA(current.value) ? 'A' : 'B'
  if (!sc || (lane === 'A' && !showsA(sc)) || (lane === 'B' && !showsB(sc))) return 'full'
  return slotShape(sc, lane)
})

// Lane A in each scene: its stretch of the clip, and how fast it plays.
const aPoints = ref({})   // movement measures, for scenes that cut A's quiet moments
watch(() => sceneList.value.filter((sc) => showsA(sc) && aTiming(sc) === 'quiet').map((sc) => sc.a.item).join(','), async (ids) => {
  for (const i of new Set(ids ? ids.split(',').map(Number) : [])) {
    const p = byId.value.get(i)
    if (!p || aPoints.value[i]) continue
    try { aPoints.value = { ...aPoints.value, [i]: (await api.activity(p.media.folder, p.media.file)).points } } catch { /* measured at render */ }
  }
}, { immediate: true })
// A hand off (a Solo B shot held in A's slot) comes off the front of A's time in its scene.
const handoffs = computed(() => sceneList.value.map((sc, k) => handoffSecs(sceneList.value, k, sceneSecs.value)))
const aSecs = computed(() => sceneSecs.value.map((x, k) => Math.max(x - handoffs.value[k], 0.04)))
const aRanges = computed(() => resolveA(sceneList.value, aSecs.value, byId.value, (i) => aPoints.value[i]))
const aPlans = computed(() => sceneList.value.map((sc, k) => (aRanges.value[k]
  ? sceneAPlan(sc, aRanges.value[k], aSecs.value[k], aPoints.value[sc.a.item], byId.value.get(sc.a.item)?.media.duration) : null)))
// How much footage lane A needs, clip by clip: from where it starts to where the last scene on it stops.
const aNeeds = computed(() => aParts.value.map((p) => {
  const used = sceneList.value.map((sc, k) => (sc.a?.item === p.id ? aRanges.value[k] : null)).filter(Boolean)
  if (!used.length) return { part: p, used: false }
  const from = Math.min(...used.map((r) => r[0]))
  const to = Math.max(...used.map((r) => r[1]))
  const short = sceneList.value.reduce((t, sc, k) => t + (sc.a?.item === p.id && aPlans.value[k] ? aShort(aPlans.value[k], aSecs.value[k]) : 0), 0)
  return { part: p, used: true, from, to, short }
}))
// What the A slot shows now: which clip, where in it and how fast.
// ---------------------------------------------------------------- clip sheet & one selection

// The A cards: each scene with A on screen (its stretch of a lane A clip, or
// the shot a relay carries on), and where that sits on the reel.
const aCards = computed(() => {
  const out = []
  sceneList.value.forEach((sc, k) => {
    const t = sceneTimes.value[k]
    const carry = carryOf(k)
    if (carry) {
      out.push({ k, part: carry, carry: true, start: t.start, len: t.end - t.start,
                 inClip: carry.media.kind === 'video' ? carry.start + carry.length : 0 })
    } else if (aPlans.value[k]) {
      out.push({ k, part: byId.value.get(sc.a.item), carry: false, start: t.start + handoffs.value[k],
                 len: Math.max(aSecs.value[k], 0.04), inClip: aRanges.value[k][0], outClip: aRanges.value[k][1],
                 rate: aPlans.value[k].rate })
    }
  })
  return out
})
const anyA = computed(() => aIds.value.length > 0 || hasRelay.value)
// One row per scene for the clip sheet: its A card beside its B parts.
const sheetRows = computed(() => sceneList.value.map((sc, k) => ({
  k, sc, start: sceneTimes.value[k].start, end: sceneTimes.value[k].end,
  a: aCards.value.find((c) => c.k === k) || null,
  aOff: anyA.value ? 'A waits · off-screen' : 'nothing on lane A',
  b: stretches.value.filter((st) => st.scene === k && st.kind === 'part').map((st) => ({
    part: st.part, start: st.start, len: st.end - st.start, edge: !!sceneEdgeAfter(st.part),
    next: hasNext(st.part) ? { label: label(effective(st.part)), icon: icon(effective(st.part)) } : null,
  })),
  bOff: 'B waits · off-screen',
})))
const spareA = computed(() => aParts.value.filter((ap) => !aCards.value.some((c) => !c.carry && c.part === ap)))
const skippedParts = computed(() => items.value.filter((it) => !it.keep && !isA(it)))

// One selection, shown on the timeline, in the sheet and in the preview: a B
// part (selected), or a scene's A stretch (selA, its scene's id). parkT holds
// the playhead where a selection put it when that isn't a B part's start.
const selA = ref(null)
const parkT = ref(null)
const selAK = computed(() => sceneList.value.findIndex((sc) => sc.id === selA.value))
const pickedA = computed(() => (selAK.value >= 0 ? selAK.value : null))
const pickedB = computed(() => (selAK.value < 0 && current.value && !isA(current.value) ? current.value.id : null))
const pickedClip = computed(() => (selAK.value < 0 && isA(current.value) ? current.value.id : null))
function selectA(k) {
  const card = aCards.value.find((c) => c.k === k)
  if (!card) return
  select(items.value.indexOf(card.part))
  selA.value = sceneList.value[k].id
  parkT.value = card.start
  player.seek(card.inClip)
}
// A B part: the playhead stays where it is if it's inside the part, else goes to its start.
function pickB(p, at = reelTime.value) {
  if (reelOn.value && p.keep) return jumpTo(p)
  select(items.value.indexOf(p))
  const k = kept.value.indexOf(p)
  if (k >= 0 && at !== null && at >= partStart(k) && at < partEnd(k) && p.media.kind === 'video') {
    player.seek(p.start + (at - partStart(k)))
  }
}
// Move the playhead to t (a scene's start, the next part…), selecting what's there.
function seekReel(t) {
  const st = stretches.value.find((x) => t >= x.start - 1e-6 && t < x.end) || stretches.value[stretches.value.length - 1]
  if (!st) return
  if (st.kind === 'part') {
    if (reelOn.value) return jumpTo(st.part)
    return pickB(st.part, t)
  }
  stopReel()
  const card = aCards.value.find((c) => c.k === st.scene)
  if (card) selectA(card.k)
  parkT.value = t
}
// ◀ Part / Part ▶: the previous or next place a part starts, in either lane.
const boundaries = computed(() => [...new Set([0, ...stretches.value.map((x) => +x.start.toFixed(3)),
  ...aCards.value.map((c) => +c.start.toFixed(3))])].sort((x, y) => x - y))
function jumpPart(dir) {
  const t = reelTime.value ?? 0
  const b = boundaries.value
  const to = dir > 0 ? b.find((x) => x > t + 0.02) : [...b].reverse().find((x) => x < t - 0.02)
  if (to !== undefined) seekReel(to)
}

// What's on screen now, lane by lane: for the preview's slot captions and the
// Now playing rows under it.
const short = (name) => (name.length > 20 ? `${name.slice(0, 18)}…` : name)
const slotWhere = (lane) => {
  const sl = slots.value
  if (!sl?.[lane]) return null
  if (!(sl.A && sl.B)) return 'full frame'
  const first = sl[lane].x === 0 && sl[lane].y === 0
  return wide.value ? (first ? 'left' : 'right') : (first ? 'top' : 'bottom')
}
const nowLanes = computed(() => {
  const rows = []
  const a = slotWhere('A') && aNow.value
  if (a) rows.push({ lane: 'A', where: slotWhere('A'), name: a.part.media.file, t: a.t, part: a.part })
  else rows.push({ lane: 'A', hidden: true, note: anyA.value ? 'waits · off-screen' : 'nothing on this lane' })
  if (slotWhere('B')) {
    const bp = !isA(current.value) && selAK.value < 0 ? current.value : shownPart.value
    const t = bp === current.value && bp.media.kind === 'video' ? player.playhead.value : (bp?.start ?? 0)
    if (bp) rows.push({ lane: 'B', where: slotWhere('B'), name: bp.media.file, t, part: bp })
  } else rows.push({ lane: 'B', hidden: true, note: 'waits · off-screen' })
  return rows
})
const slotCaptions = computed(() => Object.fromEntries(nowLanes.value.filter((r) => !r.hidden)
  .map((r) => [r.lane, { name: short(r.name), t: fmtTime(r.t) }])))
// Which slot holds the selected part, to outline it.
const pickedLane = computed(() => {
  if (selAK.value >= 0) return selAK.value === shownScene.value ? 'A' : ''
  if (isA(current.value)) return aNow.value?.part === current.value ? 'A' : ''
  return slotWhere('B') ? 'B' : ''
})
// Clicking a slot (or a Now playing row) selects what's in it.
function pickLane(lane) {
  const row = nowLanes.value.find((r) => r.lane === lane && !r.hidden)
  if (!row) return
  if (lane === 'A') {
    const k = shownScene.value
    if (aCards.value.some((c) => c.k === k)) return selectA(k)
    return select(items.value.indexOf(row.part))
  }
  pickB(row.part)
}

// The inspector's header: lane, where the part sits, whether it's seen.
const headerInfo = computed(() => {
  const w = wide.value
  const word = (sc, lane) => {
    if (!sc || (lane === 'A' ? !showsA(sc) : !showsB(sc))) return null
    if (sc.layout === 'soloA' || sc.layout === 'soloB') return 'FULL FRAME'
    const primary = (sc.layout === 'stack') === (lane === 'A')
    return w ? (primary ? 'LEFT' : 'RIGHT') : (primary ? 'TOP' : 'BOTTOM')
  }
  const seen = (sc, lane) => {
    const x = word(sc, lane)
    if (!x) return { shows: `Not visible: this scene is ${layoutLabel(sc?.layout, w)}. Lane ${lane} waits until it's on screen again.`, hidden: true }
    return { shows: x === 'FULL FRAME' ? 'Shows <b>FULL FRAME</b>' : `Shows in the <b>${x}</b> ${w ? 'side' : 'slot'}`, hidden: false }
  }
  const at = (a, b) => `on the reel ${fmtTime(a)} → ${fmtTime(b)}`
  if (selAK.value >= 0) {
    const card = aCards.value.find((c) => c.k === selAK.value)
    if (!card) return null
    const sc = sceneList.value[card.k]
    return {
      lane: 'A', title: card.carry ? `A slot · ${card.part.media.file} carries on` : `A lane · part ${aCards.value.indexOf(card) + 1} of ${aCards.value.length}`,
      scene: `Scene ${card.k + 1} · ${layoutLabel(sc.layout, w)} · ${at(card.start, card.start + card.len)}`, ...seen(sc, 'A'),
      canMove: !card.carry,
      moveHint: 'Moving this stretch to lane B makes it a B part at the start of the scene, which then shows B on its own.',
    }
  }
  const p = current.value
  if (!p) return null
  if (isA(p)) {
    const n = aCards.value.filter((c) => !c.carry && c.part === p).length
    return { lane: 'A', title: 'A lane clip', scene: n ? `Shown in ${n} scene${n === 1 ? '' : 's'}` : 'No scene shows it yet',
             shows: 'Pick its card in a scene to see where it sits and set where it starts there.', hidden: !n,
             canMove: true, moveHint: 'Moving it to lane B makes it a part at the end of the cut list.' }
  }
  if (!p.keep) return { lane: 'B', title: 'B lane · skipped', shows: 'Skipped: not in the reel. Tick it to bring it back.', hidden: true, canMove: false }
  const kk = kept.value.indexOf(p)
  const k = sceneOfPart(p)
  const sc = sceneList.value[k]
  return {
    lane: 'B', title: `B lane · part ${kk + 1} of ${kept.value.length}`,
    scene: sc ? `Scene ${k + 1} · ${layoutLabel(sc.layout, w)} · ${at(partStart(kk), partEnd(kk))}` : '', ...seen(sc, 'B'),
    canMove: p.media.kind === 'video',
    moveHint: 'Moving it to lane A makes it this scene\'s A clip from where the part starts, and lane B closes up. The scene layout decides if it\'s seen.',
  }
})
async function moveLane(to) {
  const p = current.value
  if (!p) return
  if (to === 'A' && !isA(p) && selAK.value < 0) return moveBtoA(p)
  if (to === 'B' && selAK.value >= 0) return moveAtoB(selAK.value)
  if (to === 'B' && isA(p)) return toB(p, items.value.length)
}
// B → A: the part becomes its scene's A clip from where it starts; lane B closes
// up. A scene left with no B parts becomes Solo A, so it still shows it.
function moveBtoA(p) {
  stopReel()
  const k = sceneOfPart(p)
  const list = sceneCopy()
  const sc = list[k]
  if (sc) {
    const rest = sc.parts.filter((id) => id !== p.id)
    sc.a = { item: p.id, in: null, out: null, timing: 'real', speed: 1 }
    if (!rest.length) { sc.layout = 'soloA'; sc.len = Math.max(SOLO_A_MIN, len(p)) } else if (sc.from === p.id) sc.from = rest[0]
  }
  settings.laneA = [...aIds.value.filter((i) => i !== p.id), p.id]
  commit(list)
  say(`${short(p.media.file)} is in lane A now`)
}
// A → B: the scene's A stretch becomes a B part at the start of the scene, and
// the scene shows B on its own.
async function moveAtoB(k) {
  const card = aCards.value.find((c) => c.k === k)
  if (!card || card.carry) return
  stopReel()
  await saver.flushAll()
  const a = card.part
  const sc = sceneList.value[k]
  // where it goes: before this scene's first part, else after the parts before it
  const before = sc.parts.length ? byId.value.get(sc.parts[0])
    : kept.value.find((x, i) => partStart(i) >= sceneTimes.value[k].end - 1e-6)
  const pos = before ? items.value.indexOf(before) : items.value.length
  const item = await api.addItem(id, { mediaId: a.mediaId, start: card.inClip, length: Math.round(card.len * 100) / 100,
                                       focusX: a.focusX, focusY: a.focusY, zoom: a.zoom, lighten: a.lighten, frames: a.frames || {} })
  items.value.splice(pos, 0, { ...item, media: a.media })
  await saveOrder()
  const list = sceneCopy()
  list[k].layout = 'soloB'
  list[k].from = item.id
  commit(list)
  if (!aCards.value.some((c) => !c.carry && c.part === a && c.k !== k)) settings.laneA = aIds.value.filter((i) => i !== a.id)
  selA.value = null
  select(items.value.findIndex((x) => x.id === item.id))
  say('That stretch of A is a B part now')
}

// A reel with a relay in it has splits even with nothing in lane A.
const hasRelay = computed(() => sceneList.value.some((sc, k) => isRelay(sceneList.value, k)))
// A relay's A slot: the shot from the scene before, carrying on from where its part ended.
const carryOf = (k) => {
  if (!isRelay(sceneList.value, k)) return null
  const prev = sceneList.value[k - 1]
  return byId.value.get(prev.parts[prev.parts.length - 1]) || null
}
const aNow = computed(() => {
  const k = shownScene.value
  const within = reelOn.value && reelTime.value !== null ? reelTime.value - sceneTimes.value[k].start : 0
  // A going (a scene without it coming in): the scene before's A, playing on as it slides out.
  if (k > 0 && intoNow.value?.type === 'morph' && intoNow.value.from?.A && !showsA(sceneList.value[k]) && !isRelay(sceneList.value, k)) {
    if (sceneList.value[k].grow === 'A' && isRelay(sceneList.value, k - 1)) {
      // a cameo over: the guest slides out as the host grows back
      const prev = sceneList.value[k - 1]
      const g = byId.value.get(prev.parts[prev.parts.length - 1])
      if (g) return { part: g, t: g.media.kind === 'video' ? g.start + g.length : 0, rate: 1, playing: true, band: true }
    }
    const prevCarry = carryOf(k - 1)
    const run = sceneSecs.value[k - 1] + within
    if (prevCarry) return { part: prevCarry, t: prevCarry.media.kind === 'video' ? prevCarry.start + prevCarry.length + run : 0, rate: 1, playing: true, band: true }
    const prevPlan = aPlans.value[k - 1]
    if (prevPlan) return { part: byId.value.get(sceneList.value[k - 1].a.item), t: topSource(prevPlan, run - handoffs.value[k - 1]), rate: prevPlan.rate, playing: true }
  }
  const carry = carryOf(k)
  if (carry) return { part: carry, t: carry.media.kind === 'video' ? carry.start + carry.length + within : 0, rate: 1, playing: true, carry: true, band: true }
  const plan = aPlans.value[k]
  if (!plan) return null
  const hand = handoffs.value[k]
  return { part: byId.value.get(sceneList.value[k].a.item), t: topSource(plan, Math.max(0, within - hand)), rate: plan.rate,
           playing: within >= hand }
})
// A relay's shots keep the framing they have full frame: a half slot shows
// a band of it (the bottom, unless the part is framed in a half slot), as
// the engine draws them (montage.py render_carry, band_offset; server.py
// frames relay parts full). That's the shot carrying on in A's slot, the
// one coming in under it, and each through the moves in and out. Not over
// a blur, where the full frame is the whole picture.
function bandOf(p, k) {
  const sc = sceneList.value[k]
  if (!p || !sc) return null
  const solo = sc.layout === 'soloB' ? sc : sceneList.value[k - 1]
  const fit = ['fill', 'blur'].includes(p.layout) ? p.layout : soloFitOf(solo || sc)
  if (fit !== 'fill') return null
  const f = frameFor(p, 'full', 'B')
  const b = frameFor(p, 'half', 'B')
  const y = !wide.value
  return { focusX: f.x, focusY: f.y, zoom: f.zoom, out: frameW.value / frameH.value, axis: y ? 'y' : 'x', at: y ? b.y : b.x }
}
const carryBand = computed(() => (aNow.value?.band ? bandOf(aNow.value.part, shownScene.value) : null))
// B: in a relay split, and in the Solo B just after one (growing out of its slot).
const bBand = computed(() => {
  const k = shownScene.value
  if (isRelay(sceneList.value, k) || (k && isRelay(sceneList.value, k - 1) && sceneList.value[k].layout === 'soloB')) {
    return bandOf(shownPart.value, k)
  }
  return null
})
// While a scene is handed off: the Solo B shot before it, held in A's slot.
const handoffShot = computed(() => {
  const k = shownScene.value
  if (!handoffs.value[k]) return null
  const within = reelOn.value && reelTime.value !== null ? reelTime.value - sceneTimes.value[k].start : 0
  if (within > handoffs.value[k] + 0.4) return null
  const prev = sceneList.value[k - 1]
  const p = byId.value.get(prev.parts[prev.parts.length - 1])
  if (!p) return null
  const t = p.media.kind === 'video' ? p.start + p.length : 0
  const f = frameFor(p, 'half', 'B')   // the band of it A's slot shows: the bottom, unless framed
  return { url: api.thumb(p.media.folder, p.media.file, t, 640), fade: Math.min(1, Math.max(0, (within - handoffs.value[k]) / 0.4)),
           pos: `${f.x * 100}% ${f.y * 100}%` }
})
// The scene coming in, while it does: {type, p}.
const intoNow = computed(() => {
  if (!reelOn.value || reelTime.value === null) return null
  const k = shownScene.value
  const sc = sceneList.value[k]
  if (!k || !sc || (sc.into || 'cut') === 'cut') return null
  const moves = ['handoff', 'takeover'].includes(sc.into)
  const p = (reelTime.value - sceneTimes.value[k].start) / (moves ? SCENE_MOVE : SCENE_IN)
  if (p >= 1) return null
  // A new layout: the lanes lock into their new slots rather than a picture
  // sliding in over black. A lane on screen before moves from where it was
  // (in a hand off the Solo B shot moves into A's slot); one arriving comes
  // in from its side.
  const prev = sceneList.value[k - 1]
  if (sc.into !== 'dissolve' && prev.layout !== sc.layout) {
    const before = sceneSlots(prev, frameW.value, frameH.value, Number(settings.dividerPx) || 0)
    const from = { ...before }
    if (sc.into === 'handoff' && before.B) { from.A = before.B; delete from.B }
    if (sc.into === 'takeover' && sc.grow === 'A' && before.A && before.B) { from.B = before.A; from.A = before.B }
    // A shown both sides but a different clip (or a relay's carried shot): it comes in fresh, from its side.
    if (sc.into !== 'handoff' && showsA(sc) && !(showsA(prev) && prev.a?.item === sc.a?.item && !isRelay(sceneList.value, k - 1))) delete from.A
    return { type: 'morph', p, from }
  }
  return { type: sc.into === 'handoff' || sc.into === 'takeover' ? 'slide' : sc.into, p }
})
// ---------------------------------------------------------------- audio rows

// How loud each file is along its length (audio.py), fetched once a file
// and kept: { mediaId | 'music' | 'folder/file': { step, db, hasAudio } }.
const envs = ref({})
const envWaiting = ref(0)   // files still being measured
const envAsked = new Set()
async function fetchEnvs(want) {
  const fresh = want.filter((k) => !envAsked.has(k.key))
  if (!fresh.length) return
  fresh.forEach((k) => envAsked.add(k.key))
  envWaiting.value += fresh.length
  const media = fresh.filter((k) => k.mediaId)
  const others = fresh.filter((k) => !k.mediaId)
  const jobs = others.map(async (k) => {
    try { envs.value = { ...envs.value, [k.key]: await k.load() } } catch { envAsked.delete(k.key) } finally { envWaiting.value-- }
  })
  // Videos in batches, so the strip fills in as they're measured.
  for (let i = 0; i < media.length; i += 6) {
    const batch = media.slice(i, i + 6)
    jobs.push(api.envelopes(batch.map((k) => k.mediaId)).then((got) => {
      envs.value = { ...envs.value, ...got }
    }).catch(() => batch.forEach((k) => envAsked.delete(k.key))).finally(() => { envWaiting.value -= batch.length }))
  }
  await Promise.all(jobs)
}
const envWanted = computed(() => {
  const want = []
  const seen = new Set()
  for (const p of [...kept.value, ...aParts.value]) {
    if (p?.media?.kind !== 'video' || seen.has(p.media.id)) continue
    seen.add(p.media.id)
    want.push({ key: p.media.id, mediaId: p.media.id })
  }
  if (settings.music) want.push({ key: `music:${settings.music}`, load: () => api.musicEnvelope(settings.music) })
  for (const v of voiceTl.value.pieces) {
    want.push({ key: `${v.folder}/${v.file}`, load: () => api.voiceEnvelope(v.folder, v.file) })
  }
  return want
})
watch(() => envWanted.value.map((k) => k.key).join('|'), () => fetchEnvs(envWanted.value), { immediate: true })
// The song's envelope is kept under its name; the mix reads it as 'music'.
const envsForMix = computed(() => ({ ...envs.value, music: envs.value[`music:${settings.music}`] }))
const audioSegs = computed(() => withDucking(audioSegments({
  sceneList: sceneList.value, sceneTimes: sceneTimes.value, stretches: stretches.value, aPlans: aPlans.value,
  aSecs: aSecs.value, handoffs: handoffs.value, byId: byId.value, reelLength: reelLength.value, settings,
  voicePieces: voiceTl.value.pieces, songVolume, carryOf, songStart: songT0.value,
}), envsForMix.value, reelLength.value, settings))
// The rows per source (Show tracks): each at its own level, dim where it isn't heard.
const TRACKS_KEY = 'footage-studio-audio-tracks'
const showTracks = ref((() => { try { return localStorage.getItem(TRACKS_KEY) === '1' } catch { return false } })())
watch(showTracks, (v) => { try { localStorage.setItem(TRACKS_KEY, v ? '1' : '0') } catch { /* storage unavailable */ } })
const tracks = computed(() => {
  if (!showTracks.value) return []
  const segs = audioSegs.value
  const env = envsForMix.value
  const L = reelLength.value
  const rows = [
    { id: 'A', name: 'A glasses', sub: 'mic', bars: trackBars(segs.A, env, L), show: aIds.value.length > 0 },
    { id: 'B', name: 'B glasses', sub: 'mic', bars: trackBars(segs.B, env, L), show: true },
    { id: 'music', name: 'Music', sub: segs.duck.length ? 'ducked under glasses' : 'the song', bars: musicBars(segs, env, L), show: !!settings.music },
    { id: 'voice', name: 'Voice', sub: 'voiceover', bars: trackBars(segs.voice, env, L), show: segs.voice.length > 0 },
  ]
  return rows.filter((r) => r.show)
})
// The faders: each layer's volume, 0..150% (stored 0..1.5 as mixA, mixB, mixMusic, mixVoice).
const faderKey = (layer) => MIX.find((m) => m.v === layer).key
const faderPct = (layer) => Math.round(mixLevel(settings, layer) * 100)
const unmuted = {}   // what a muted fader goes back to
function setFader(layer, pct) {
  settings[faderKey(layer)] = Math.round(Math.min(150, Math.max(0, Number(pct) || 0))) / 100
}
function toggleMute(layer) {
  if (faderPct(layer) === 0) return setFader(layer, unmuted[layer] || 100)
  unmuted[layer] = faderPct(layer)
  setFader(layer, 0)
}
const faded = computed(() => MIX.some((m) => mixLevel(settings, m.v) !== 1))
// Glasses audio: follows the primary slot, lane A only, or off (older reels: Keep glasses audio).
const glasses = computed({
  get: () => glassesMode(settings),
  set: (v) => { settings.glassesAudio = v; settings.originalAudio = v !== 'off' },
})
const mix = computed(() => mixBars(audioSegs.value, envsForMix.value, reelLength.value))
const mixHeard = computed(() => mix.value.some((b) => b.h > 0))
const bands = computed(() => transitionBands({
  sceneList: sceneList.value, sceneTimes: sceneTimes.value, stretches: stretches.value, handoffs: handoffs.value,
  settings, sceneIn: SCENE_IN,
}))
const SRC_LABEL = { A: 'A glasses', B: 'B glasses', music: 'music', voice: 'voice' }
const barTitle = (b) => `${fmtTime(b.t)}${b.src ? ` · mostly ${SRC_LABEL[b.src]}` : ' · silent'}`

const rateText = (k) => (aPlans.value[k] ? `${aPlans.value[k].rate.toFixed(2)}×` : '')
// Trimming parts moves scene edges and A re-fits: say so.
const toast = ref('')
let toastTimer
function say(text) {
  toast.value = text
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 2200)
}
let trimmedAt = 0   // when a part's length last changed, so only that says "A now…"
watch(() => stretches.value.map((st) => st.end.toFixed(2)).join(), () => { trimmedAt = Date.now() })
watch(() => aPlans.value.map((x) => (x ? x.rate.toFixed(2) : '')), (now, was) => {
  if (!ready || !was || reelOn.value || now.length !== was.length || Date.now() - trimmedAt > 1500) return
  const k = now.findIndex((r, i) => r && was[i] && r !== was[i])
  if (k >= 0) say(`A now ${now[k]}× in scene ${k + 1}`)
})

// Editing scenes: settings.scenes is saved as the normalized list.
function commit(list) {
  settings.scenes = list.map(({ parts, ...sc }) => sc)   // eslint-disable-line no-unused-vars
}
const sceneCopy = () => sceneList.value.map((sc) => ({ ...sc, a: sc.a ? { ...sc.a } : sc.a, parts: [...sc.parts] }))
const lastSplit = () => [...sceneList.value].reverse().find((sc) => sc.layout === 'stack' || sc.layout === 'swap')
function newA(itemFrom) {
  return { item: itemFrom ?? aIds.value[0], in: null, out: null, timing: 'real', speed: 1 }
}
function selectScene(k) {
  const sc = sceneList.value[k]
  if (!sc) return
  stopReel()
  selScene.value = sc.id
  const first = sc.parts[0] && byId.value.get(sc.parts[0])
  if (first) selected.value = items.value.indexOf(first)
}
function editScene(k, patch) {
  const list = sceneCopy()
  Object.assign(list[k], patch)
  commit(list)
}
function editA(k, patch) {
  const list = sceneCopy()
  list[k].a = { ...(list[k].a || newA()), ...patch }
  commit(list)
}
// A new layout for scene k. A scene that loses B (Solo A) hands its parts to
// the scene before (or after) and keeps its length; one that gains B takes
// the first part of the next scene with B.
function setSceneLayout(k, layout) {
  const list = sceneCopy()
  const sc = list[k]
  if (!sc || sc.layout === layout) return
  if (layout !== 'soloB' && !aIds.value.length) return say('Put a clip in lane A first: ⤒ on a part')
  if (layout === 'soloA' && sc.layout !== 'soloA') {
    const others = list.filter((x) => x.layout !== 'soloA' && x !== sc)
    if (!others.length) return say('Keep one scene with B in it')
    sc.len = Math.max(SOLO_A_MIN, sceneSecs.value[k])
  }
  if (sc.layout === 'soloA' && layout !== 'soloA') {
    const next = list.slice(k + 1).find((x) => x.layout !== 'soloA')
    if (!next) return say('No parts after this scene to show with A')
    sc.from = next.parts[0]
    if (next.parts.length > 1) next.from = next.parts[1]
  }
  sc.layout = layout
  if (layout !== 'soloB') sc.a = sc.a || newA(lastA(k))
  if ((layout === 'stack' || layout === 'swap') && sc.split == null) sc.split = lastSplit()?.split ?? 0.5
  commit(list)
}
const lastA = (k) => [...sceneList.value.slice(0, k)].reverse().find((x) => x.a)?.a.item
// S: a new scene starts at the playhead (at the nearest cut in a B scene),
// with the last split used. A carries on from the same point in its clip.
function splitAtPlayhead() {
  const t = reelTime.value ?? sceneTimes.value[shownScene.value]?.start ?? 0
  const k = sceneIndexAt(t)
  const list = sceneCopy()
  const sc = list[k]
  if (!sc) return
  const start = sceneTimes.value[k].start
  if (sc.layout === 'soloA') {
    if (t - start < SOLO_A_MIN) return say('Too near the start of the scene')
    const a = aRanges.value[k]
    sc.len = t - start
    if (a && sc.a?.in != null) sc.a.out = sc.a.in + (t - start) * (sc.a.speed || 1)
    commit(list)
    return say('Solo A ends here')
  }
  const own = stretches.value.filter((st) => st.scene === k)
  const cut = own.slice(1).reduce((best, st) => (!best || Math.abs(st.start - t) < Math.abs(best.start - t) ? st : best), null)
  if (!cut) return say('A scene needs two parts to split: this one has one')
  const like = lastSplit()
  const fresh = {
    id: newId(), from: cut.part.id, into: 'slide',
    layout: sc.layout === 'soloB' ? (aIds.value.length ? like?.layout || 'stack' : 'soloB') : sc.layout,
    split: like?.split ?? sc.split ?? 0.5,
  }
  if (showsA(fresh)) {
    const range = aRanges.value[k]
    const plan = aPlans.value[k]
    if (sc.a && range && plan) {   // A splits where the cut is
      const at = topSource(plan, cut.start - start)
      fresh.a = { ...sc.a, in: Math.round(at * 1000) / 1000, out: sc.a.out }
      if (fitted(sc)) sc.a.out = Math.round(at * 1000) / 1000
    } else fresh.a = newA(lastA(k + 1))
  }
  list.splice(k + 1, 0, fresh)
  commit(list)
  selScene.value = fresh.id
  say(`Scene ${k + 2} starts at ${fmtTime(cut.start)}`)
}
// W: swap which lane has the primary slot (top, or left).
function swapScene(k = shownScene.value) {
  const sc = sceneList.value[k]
  if (sc?.layout === 'stack') setSceneLayout(k, 'swap')
  else if (sc?.layout === 'swap') setSceneLayout(k, 'stack')
}
function setSplit(k, split) {
  editScene(k, { split })
}
function nudgeSplit(d) {
  const k = shownScene.value
  const sc = sceneList.value[k]
  if (!sc || !['stack', 'swap'].includes(sc.layout)) return
  const now = sc.split === 'square' ? 0.5 : Number(sc.split) || 0.5
  setSplit(k, Math.round(Math.min(0.7, Math.max(0.3, now + d)) * 100) / 100)
}
function splitEverywhere(k) {
  const split = sceneList.value[k].split
  commit(sceneCopy().map((sc) => (['stack', 'swap'].includes(sc.layout) ? { ...sc, split } : sc)))
  say('Every split scene uses this split')
}
function mergeIntoPrevious(k) {
  if (k < 1) return
  const list = sceneCopy()
  list.splice(k, 1)
  commit(list)
  selScene.value = list[k - 1].id
}
// Quiet markers (◆ on the audio strip): the quietest moment of what you hear
// within 1s of each scene edge, where a change of scene (and of sound) is
// least jarring. After a Solo A the edge can go anywhere; between B scenes
// only on a cut, so there the marker is the quietest cut nearby.
function edgeCuts(k) {
  const list = sceneList.value
  if (!k || !list[k]) return undefined
  if (list[k - 1].layout === 'soloA') return null           // anywhere
  if (list[k].layout === 'soloA') return undefined          // not draggable here
  const pStart = sceneTimes.value[k - 1].start
  const end = sceneTimes.value[k].end
  return stretches.value
    .filter((st) => (st.scene === k - 1 || st.scene === k) && st.kind === 'part')
    .map((st) => st.start).filter((t) => t - pStart >= SOLO_A_MIN && end - t >= SOLO_A_MIN)
}
const quietMarks = computed(() => {
  if (envWaiting.value) return []
  const out = []
  for (let k = 1; k < sceneList.value.length; k++) {
    const cuts = edgeCuts(k)
    if (cuts === undefined) continue
    const m = quietMarker(audioSegs.value, envsForMix.value, sceneTimes.value[k].start, reelLength.value, cuts)
    if (m) out.push({ ...m, k })
  }
  return out
})
const markTitle = (m) => (Math.abs(m.t - sceneTimes.value[m.k].start) < 0.02
  ? `Scene ${m.k + 1} already starts at the quietest moment nearby`
  : `Quietest moment near scene ${m.k + 1}'s start: ${fmtTime(m.t)}, ${Math.max(0, m.edgeDb - m.db).toFixed(0)}dB quieter than where it is. Click to move the edge here, or drag the edge near it.`)

// Scene edges: drag the start of scene k. Between two B scenes it snaps to a
// cut; the end of a Solo A scene sets its length. Under 1s, the scenes merge.
// Near the edge's quiet marker, it snaps to that.
const dragEdge = ref(null)
function edgeDown(e, k) {
  e.currentTarget.setPointerCapture(e.pointerId)
  dragEdge.value = { k, row: e.currentTarget.parentElement.getBoundingClientRect(), t: sceneTimes.value[k].start, snapped: false }
}
function edgeMove(e) {
  const d = dragEdge.value
  if (!d) return
  d.t = Math.max(0, Math.min(reelLength.value, ((e.clientX - d.row.left) / d.row.width) * reelLength.value))
  const m = quietMarks.value.find((x) => x.k === d.k)
  d.snapped = !!m && Math.abs(d.t - m.t) < QUIET_SNAP
  if (d.snapped) d.t = m.t
}
function edgeUp() {
  const d = dragEdge.value
  dragEdge.value = null
  if (!d) return
  setEdge(d.k, d.t)
}
function toQuiet(m) {
  stopReel()
  setEdge(m.k, m.t)
  say(`Scene ${m.k + 1} starts at ${fmtTime(m.t)}, the quiet moment`)
}
function setEdge(k, t) {
  const list = sceneCopy()
  const prev = list[k - 1]
  const sc = list[k]
  const pStart = sceneTimes.value[k - 1].start
  if (prev.layout === 'soloA') {
    if (t - pStart < SOLO_A_MIN) { list.splice(k - 1, 1); commit(list); return say('Merged: under 1s') }
    prev.len = t - pStart
    if (prev.a?.in != null && prev.a?.out != null) prev.a.out = prev.a.in + prev.len * (prev.a.speed || 1)
    return commit(list)
  }
  if (sc.layout === 'soloA') return say('Drag the other edge of a Solo A scene, or split with S')
  const cuts = stretches.value.filter((st) => (st.scene === k - 1 || st.scene === k) && st.kind === 'part')
  const best = cuts.reduce((b, st) => (!b || Math.abs(st.start - t) < Math.abs(b.start - t) ? st : b), null)
  if (!best) return
  if (best.start - pStart < SOLO_A_MIN || best.part.id === prev.from) { list.splice(k, 1); commit(list); return say('Merged: under 1s') }
  const end = sceneTimes.value[k].end
  if (end - best.start < SOLO_A_MIN && best.scene === k && best.part.id !== sc.from) { list.splice(k, 1); commit(list); return say('Merged: under 1s') }
  sc.from = best.part.id
  commit(list)
}
// "Show A above this": a split scene starting at this part.
// "On its own": this part gets a scene of its own, full frame (Solo B). The
// parts before it stay in their scene; the ones after it start a new scene
// in the layout they had, sliding in. A opening photo before a split, say.
const aloneInScene = (p) => {
  const sc = sceneList.value[sceneOfPart(p)]
  return !!sc && sc.layout === 'soloB' && sc.parts.length === 1
}
function soloThis(p) {
  const k = sceneOfPart(p)
  if (k < 0) return
  const list = sceneCopy()
  const sc = list[k]
  if (sc.layout === 'soloB' && sc.parts.length === 1) return say('This part is already on its own')
  const at = sc.parts.indexOf(p.id)
  const next = sc.parts[at + 1]
  const solo = { id: newId(), layout: 'soloB', from: p.id, split: sc.split, into: at > 0 ? 'slide' : (sc.into || 'cut') }
  const split = ['stack', 'swap'].includes(sc.layout)
  const rest = next && { ...sc, id: newId(), from: next, into: split ? 'handoff' : sc.layout === 'soloB' ? 'cut' : 'slide',
                         ...(split ? { handoff: HANDOFF_DEFAULT } : {}), a: sc.a ? { ...sc.a, in: null, out: null } : sc.a }
  list.splice(k, 1, ...(at > 0 ? [sc] : []), solo, ...(rest ? [rest] : []))
  commit(list)
  selScene.value = null
  say(rest ? (split ? `On its own, then it hands off to ${layoutLabel(rest.layout, wide.value)} (${HANDOFF_DEFAULT}s)` : `On its own, then ${layoutLabel(rest.layout, wide.value)}`) : 'On its own')
}
function showAAbove(p) {
  if (!aIds.value.length) return say('Put a clip in lane A first: ⤒ on a part')
  const k = sceneOfPart(p)
  const list = sceneCopy()
  const sc = list[k]
  const like = lastSplit()
  if (sc.from === p.id) {
    if (sc.layout === 'soloB') { setSceneLayout(k, like?.layout || 'stack'); return }
    return say('A is already on screen here')
  }
  list.splice(k + 1, 0, { id: newId(), from: p.id, layout: like?.layout || 'stack', split: like?.split ?? 0.5,
                          into: 'slide', a: newA(lastA(k + 1)) })
  commit(list)
}

// Lane A: ⤒ puts a part there; it leaves lane B.
function addToA(p) {
  if (p.media.kind !== 'video') return
  stopReel()
  settings.laneA = [...aIds.value.filter((i) => i !== p.id), p.id]
  if (!sceneList.value.some(showsA)) {
    const list = sceneCopy()
    if (list[0]) { list[0].layout = 'stack'; list[0].split = list[0].split ?? 0.5; list[0].a = newA(p.id) }
    commit(list)
  }
  if (!p.keep) setKeep(p, true)
}
// Back into lane B, as a normal part at `to` (default: first).
async function toB(p, to = 0) {
  stopReel()
  settings.laneA = aIds.value.filter((i) => i !== p.id)
  if (!p.keep) setKeep(p, true)
  await moveItem(p, to)
}
async function moveItem(p, to) {
  const cur = current.value
  const from = items.value.indexOf(p)
  items.value.splice(from, 1)
  items.value.splice(Math.min(to, items.value.length), 0, p)
  selected.value = items.value.indexOf(cur)
  await saveOrder()
}
// An A clip dropped on the B lane row (not on a part): back into lane B, at the end.
function dropB() {
  const from = dragFrom.value
  dragOver.value = null
  if (typeof from === 'string' && from.startsWith('A')) toB(byId.value.get(Number(from.slice(1))), items.value.length)
}
// While a B video is dragged, the timeline turns into a "Move to A lane"
// drop zone (shown a moment later: changing the page as a drag starts can
// cancel it).
const draggingB = ref(false)
function startDragB(i) {
  dragFrom.value = i
  if (items.value[i]?.media.kind === 'video') setTimeout(() => { draggingB.value = true })
}
function endDrag() {
  draggingB.value = false
  dragOver.value = null
}
onMounted(() => { window.addEventListener('dragend', endDrag); window.addEventListener('drop', endDrag) })
onBeforeUnmount(() => { window.removeEventListener('dragend', endDrag); window.removeEventListener('drop', endDrag) })
function dropA() {
  const from = dragFrom.value
  dragOver.value = null
  if (typeof from !== 'number') return
  addToA(items.value[from])
}
const rowNumber = (p) => kept.value.indexOf(p) + 1
// The scene in the inspector.
const selK = computed(() => sceneList.value.findIndex((sc) => sc.id === selScene.value))
const selSc = computed(() => (selK.value >= 0 ? sceneList.value[selK.value] : null))
// A lane on its own: blur fill by default in a wide frame.
const soloFitOf = (sc) => sc.fill || (wide.value ? 'blur' : (settings.fit === 'blur' ? 'blur' : 'fill'))
const slotFit = (lane) => (shownSc.value && slotShape(shownSc.value, lane) === 'full' ? soloFitOf(shownSc.value) : 'fill')
const focusProps = (p, lane) => {
  const f = frameFor(p, shownSc.value ? slotShape(shownSc.value, lane) : 'full', lane)
  return { focusX: f.x, focusY: f.y, zoom: f.zoom }
}
// The B part to show while lane A's clip is being edited.
const shownPart = computed(() => byId.value.get(shownSc.value?.parts[0]) || kept.value[0] || null)
function setAIn(k, e) {
  const t = parseTime(e.target.value)
  if (!isNaN(t) && t >= 0) editA(k, { in: Math.round(t * 100) / 100, ...(fitted(sceneList.value[k]) ? { out: null } : {}) })
  e.target.value = fmtTime(aRanges.value[k]?.[0] ?? 0)
}
// Display low quality: get the reel's small copies made, and say how far that's got.
const lowProgress = ref(null)
let lowTimer = null
async function checkLowCopies() {
  clearTimeout(lowTimer)
  if (!lowQuality.value || !props.id) { lowProgress.value = null; return }
  try { lowProgress.value = await api.lowCopies(props.id) } catch { lowProgress.value = null; return }
  noteLowMade(lowProgress.value.made)
  if (lowProgress.value.ready < lowProgress.value.total) lowTimer = setTimeout(checkLowCopies, 3000)
}
watch([lowQuality, () => props.id], checkLowCopies, { immediate: true })
onBeforeUnmount(() => clearTimeout(lowTimer))
// The ruler over the lanes: a mark every 5, 15 or 30 seconds (or minute).
const rulerTicks = computed(() => {
  const L = reelLength.value || 0
  const step = [5, 15, 30, 60, 120].find((x) => L / x <= 8) || 300
  const out = []
  for (let t = 0; t < L; t += step) out.push(t)
  return out
})
// Where a part's "Into next part" is overruled by the scene coming in after it.
const sceneEdgeAfter = (p) => {
  const k = sceneOfPart(p)
  const sc = sceneList.value[k]
  return k >= 0 && sc.parts[sc.parts.length - 1] === p.id && k + 1 < sceneList.value.length ? sceneList.value[k + 1] : null
}

// A long part with boring stretches in it: cut where nothing much happens
// (the same measure and rule as the top clip's quiet cuts), into parts one
// after another that can each be trimmed, moved or skipped like any other.
const splitting = ref(false)
const splitNote = ref('')
async function splitQuiet(p) {
  if (splitting.value) return
  splitting.value = true
  splitNote.value = ''
  try {
    const { points } = await api.activity(p.media.folder, p.media.file)
    const pieces = quietCut(points || [], p.start, p.length)
    if (pieces.length < 2) {
      splitNote.value = 'Nothing quiet enough to take out of this part.'
      return
    }
    await saver.flushAll()
    const cut = p.length - pieces.reduce((a, [, l]) => a + l, 0)
    const fields = { focusX: p.focusX, focusY: p.focusY, zoom: p.zoom, lighten: p.lighten, layout: p.layout,
                     transition: p.transition, frames: p.frames || {} }
    const beatsFor = (l) => (synced.value ? snapBeats(l / period.value, false) : 0)
    const [first, ...rest] = pieces
    const r = { start: first[0], length: first[1], ...(synced.value ? { beats: beatsFor(first[1]) } : {}) }
    Object.assign(p, r)
    saver.queue(p.id, r)
    let at = items.value.indexOf(p)
    for (const [start, length] of rest) {
      const item = await api.addItem(id, { mediaId: p.mediaId, start, length, ...fields,
                                           ...(synced.value ? { beats: beatsFor(length) } : {}) })
      items.value.splice(++at, 0, { ...item, media: p.media })
    }
    await saveOrder()
    splitNote.value = `${pieces.length} parts, ${cut.toFixed(1)}s of quiet taken out.`
  } catch (e) {
    splitNote.value = `Couldn't split it: ${e.message}`
  } finally {
    splitting.value = false
  }
}

// What every ReelFrame showing the selected clip gets.
const frameProps = computed(() => {
  const f = frameFor(current.value, editShape.value, isA(current.value) ? 'A' : 'B')
  return {
    media: current.value.media,
    fit: editShape.value !== 'full' ? 'fill' : (!isA(current.value) && current.value.layout) || (aIds.value.length ? soloFitOf(shownSc.value || {}) : layoutOf(current.value)),
    guides: !aIds.value.length && tall.value && guides.value, out: shapeRatio(settings.shape),
    muted: glassesMode(settings) !== 'primary', cropped: reelOn.value, effect: effect.value, lighten: current.value.lighten,
    focusX: f.x, focusY: f.y, zoom: f.zoom,
    posterTime: current.value.start, bindVideo: (el) => { player.video.value = el },
  }
})
const frameOn = {
  loaded: (e) => onFrameLoaded(e), play: () => player.events.onPlay(), pause: () => player.events.onPause(),
  ended: () => onFrameEnded(),
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
// After the last part, the reel holds on it while the voice finishes.
const holdT = ref(null)
let holdTimer, holdTick
function startHold() {
  const t0 = performance.now()
  holdT.value = 0
  holdTick = setInterval(() => { holdT.value = (performance.now() - t0) / 1000 }, 40)
  holdTimer = setTimeout(() => { stopReel(); restart = true }, voiceHold.value * 1000)
}
function clearHold() {
  clearTimeout(holdTimer)
  clearInterval(holdTick)
  holdT.value = null
}
// A Stack's "top alone" after part k (or before the first, k = -1): the part
// underneath carries on out of sight until the next one comes in. gapFrom
// is where it started on the reel's clock.
const gapFrom = ref(null)
const gapT = ref(0)
let gapTimer, gapTick
function clearGap() {
  clearTimeout(gapTimer)
  clearInterval(gapTick)
  gapFrom.value = null
  gapT.value = 0
}
function enterGap(k, from) {
  clearGap()
  reelIdx.value = k
  gapFrom.value = from
  if (clocked.value) return       // the song's clock moves us on
  const t0 = performance.now()
  gapTick = setInterval(() => { gapT.value = (performance.now() - t0) / 1000 }, 40)
  gapTimer = setTimeout(() => startPart(k + 1), Math.max(0, partStart(k + 1) - from) * 1000)
}
// Part k has played: on to the next, through the top clip alone if it's there.
function afterPart(k) {
  if (partStart(k + 1) > partEnd(k) + 0.01) enterGap(k, partEnd(k))
  else startPart(k + 1)
}

const offsetOf = (k) => partStart(k)
const reelTime = computed(() => {
  if (reelOn.value && clocked.value) return songClock.value
  if (reelOn.value && holdT.value !== null) return partsEnd.value + holdT.value
  if (reelOn.value && gapFrom.value !== null) return gapFrom.value + gapT.value
  if (!reelOn.value && parkT.value !== null) return parkT.value
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
  clearGap()
  const list = kept.value
  if (k >= list.length) {       // end of the reel (or of its parts, while the voice finishes)
    if (holdT.value !== null) return
    if (voiceHold.value > 0.05) return startHold()
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
    photoTimer = setTimeout(() => afterPart(k), len(p) * 1000)
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
  if (!reelOn.value || clocked.value || gapFrom.value !== null) return
  const p = kept.value[reelIdx.value]
  const v = player.video.value
  if (p && p === current.value && p.media.kind === 'video' && v && !v.paused && t >= p.start + len(p)) {
    afterPart(reelIdx.value)
  }
})

// The clip ran out before the part's end (the file is a touch shorter than
// its measured duration): move on rather than freeze on the last frame.
function onFrameEnded() {
  player.events.onEnded()
  if (!reelOn.value || clocked.value || gapFrom.value !== null) return
  const p = kept.value[reelIdx.value]
  if (p && p === current.value && p.media.kind === 'video') afterPart(reelIdx.value)
}

// Start from the cut you're on (or the next kept one if it's skipped); only
// go back to the top when the reel just finished and nothing was picked since.
function playReel() {
  selA.value = null   // playing: the selection follows the part playing
  let k = kept.value.indexOf(current.value)
  if (parkT.value !== null) {   // from where the playhead was put: the first part ending after it
    k = kept.value.findIndex((x, i) => partEnd(i) > parkT.value + 0.01)
    if (k < 0) k = 0
    parkT.value = null
  }
  if (k < 0) {
    const after = items.value.slice(selected.value + 1).find((p) => kept.value.includes(p))
    k = after ? kept.value.indexOf(after) : 0
  }
  if (restart) k = 0
  restart = false
  reelOn.value = true
  stopListening()
  clearHold()
  // From the top of a Stack that opens on its top clip alone: that first.
  const from = k === 0 ? 0 : offsetOf(k)
  if (voiceTl.value.pieces.length) voicePlayer.play(voiceTl.value.pieces, from)
  if (clocked.value) startSong(from)
  if (partStart(k) > from + 0.01) {
    select(items.value.indexOf(kept.value[k]), true)
    enterGap(k - 1, from)
  } else startPart(k)
}

function stopReel() {
  if (!reelOn.value) return
  reelOn.value = false
  clearPhoto()
  clearHold()
  clearGap()
  voicePlayer.stop()
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
    clearHold()
    if (voiceTl.value.pieces.length) voicePlayer.play(voiceTl.value.pieces, offsetOf(k))
    if (clocked.value) startSong(offsetOf(k))
    startPart(k)
  } else select(items.value.indexOf(p))
}

function playThisPart() {
  stopReel()
  player.playPart()
}
onBeforeUnmount(() => { clearPhoto(); clearHold(); clearGap(); voicePlayer.stop() })

// ---------------------------------------------------------------- render

const rendering = computed(() => job.value?.status === 'running')
const renderPct = computed(() => {
  const j = job.value
  if (!j) return 0
  if (j.stage === 'joining') return 90
  if (j.stage === 'captions') return 94
  if (j.stage === 'mixing') return 97
  if (j.stage === 'done') return 100
  return j.total ? Math.round((j.done / j.total) * 90) : 0
})
const stageText = computed(() => ({
  starting: 'Starting…', cutting: `Cutting ${job.value.done} of ${job.value.total}`,
  joining: 'Joining cuts and transitions…', captions: 'Laying the captions over…', mixing: 'Mixing sound…',
  scenes: 'Putting the scenes together…', cards: 'Laying the title and end card over…',
}[job.value.stage] || job.value.stage))
const elapsed = computed(() => Math.max(0, Math.round(clock.value - job.value.startedAt)))
// The render's steps, each with how long it took (the one under way, so far).
const steps = computed(() => {
  const list = job.value?.steps || []
  const out = list.filter((st) => st.label !== 'finished').map((st, i) => {
    const next = list[i + 1]
    const end = next ? next.at : (job.value.status === 'running' ? clock.value : job.value.finishedAt || st.at)
    return { label: st.label, secs: Math.max(0, end - st.at), now: !next && job.value.status === 'running' }
  })
  const total = out.reduce((a, st) => a + st.secs, 0) || 1
  out.forEach((st) => { st.slow = st.secs > Math.max(5, total * 0.08) })
  return out
})
const slowest = computed(() => [...steps.value].sort((a, b) => b.secs - a.secs).slice(0, 12))
const stepsEl = ref(null)
watch(() => steps.value.length, async () => {
  await nextTick()
  if (stepsEl.value) stepsEl.value.scrollTop = stepsEl.value.scrollHeight
})

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
  else if (k === 's' || k === 'S') splitAtPlayhead()
  else if (k === 'w' || k === 'W') swapScene()
  else if (['1', '2', '3', '4'].includes(k)) setSceneLayout(shownScene.value, SCENE_LAYOUTS[Number(k) - 1].v)
  else if (k === '[') nudgeSplit(-0.02)
  else if (k === ']') nudgeSplit(0.02)
  else if (k === 'Tab') tabLane()
  else return
  e.preventDefault()
}
// Tab: from a B part to the A clip on screen, and back.
function tabLane() {
  pickLane(pickedLane.value === 'A' ? 'B' : 'A')
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
.settings { display: block; }
.musichead { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; }
.musichead h3 { margin: 0; }
.beatbtn { text-decoration: none; }
.beatbtns { display: flex; flex-wrap: wrap; gap: 6px; }
.settings .wide { grid-column: span 2; }
.field.check span { display: flex; gap: 6px; align-items: center; color: var(--ink); font-size: 14px; }
.field.check small { font-size: 12px; }
.danger { color: var(--danger); }
.transport { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 12px; margin: 16px 0 34px; }
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
.sgroup { padding: 4px 0 16px; border-bottom: 1px solid var(--line); margin-bottom: 14px; }
.sgroup:last-child { border-bottom: 0; margin-bottom: 0; padding-bottom: 0; }
.sgroup h3 { margin: 0 0 8px; }
.sgroup > p.small { margin: 0 0 12px; }
.sgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 16px 20px; align-items: start; }
.cardgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 16px; align-items: start; }
.cardbox { border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px 14px; background: var(--cream); }
.cardbox.off { background: transparent; padding-bottom: 12px; }
.cardbox.off header { margin-bottom: 0; }
.cardbox header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.cardbox header strong { color: var(--ink); font-size: 15px; }
.cardbox header .btn { margin-left: auto; }
.cardbox header .check { display: flex; align-items: center; gap: 6px; cursor: pointer; }
.cardbox p.small { margin: 0; }
.cardfields { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 14px; }
.cardfields .span2 { grid-column: 1 / -1; }
.cardfields small { font-size: 11px; }
.cardfields textarea {
  border: 1px solid var(--line); border-radius: 8px; padding: 6px 8px; resize: vertical;
  background: var(--paper); font: inherit; font-size: 15px; color: var(--ink); width: 100%; box-sizing: border-box;
}
.cards input::placeholder, .cards textarea::placeholder { color: var(--muted); opacity: 0.55; font-style: italic; }
.cardbox :deep(.cardpreview) { display: flex; gap: 12px; align-items: flex-end; margin-top: 14px; }
.cardbox :deep(.cardpreview img) { width: 180px; height: 320px; border-radius: 8px; border: 1px solid var(--line); display: block; }
.cardbox :deep(.cardpreview-actions) { display: flex; flex-direction: column; gap: 6px; }
.link, .cardbox :deep(.link) { background: none; border: 0; padding: 2px 0; color: var(--forest); font: inherit; font-size: 13px; text-align: left; cursor: pointer; text-decoration: underline; text-underline-offset: 2px; }
.link:hover, .cardbox :deep(.link:hover) { color: var(--forest-2); }
.link:disabled { opacity: 0.5; cursor: default; }
.reelactions { display: flex; gap: 10px; }
.reelactions .danger { margin-left: auto; }
.musicrow { display: flex; gap: 16px; flex-wrap: wrap; align-items: flex-end; }
.musicrow .field { min-width: 160px; }
.musicrow .field select { min-width: 260px; }
.musicrow .field.song { flex: 1 1 480px; align-self: flex-start; }
.small { font-size: 12px; margin: 8px 0; }
.warn { color: var(--danger); }
.note { background: var(--sage-soft); padding: 6px 10px; border-radius: 6px; font-size: 13px; }
.songtag {
  flex: none; display: inline-flex; align-items: center; gap: 6px; font: inherit; font-size: 12px; color: var(--forest); background: var(--sage-soft);
  border: 1px solid transparent; border-radius: 999px; padding: 2px 10px; max-width: 280px; cursor: pointer;
}
.songtag:hover, .songtag:focus-visible { border-color: var(--sage); outline: none; }
.songtag .songname { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.songtag .songedit { flex: none; font-size: 11px; opacity: 0.75; }
.songtag:hover .songedit { opacity: 1; }
.songtag.add { background: transparent; border: 1px dashed var(--sage); }
.sgroup.music.flash { animation: musicflash 1.6s ease-out; border-radius: 10px; }
@keyframes musicflash { 0%, 30% { box-shadow: 0 0 0 3px var(--sage); } 100% { box-shadow: 0 0 0 3px transparent; } }
@media (prefers-reduced-motion: reduce) { .sgroup.music.flash { animation: none; } }
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
.tracks { flex: 1 1 100%; display: flex; flex-direction: column; gap: 3px; min-width: 0; position: relative; }
.tozone {
  position: absolute; inset: -6px; z-index: 20; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 2px; border-radius: var(--radius); border: 2px dashed var(--sage); background: var(--paper); color: var(--ink);
  box-shadow: var(--shadow);
}
.tozone span { font-size: 20px; font-weight: 700; color: var(--forest); pointer-events: none; }
.tozone small { color: var(--muted); pointer-events: none; }
.tozone.hot { background: var(--sage-soft); border-style: solid; }
.tracks .strip { flex: none; }
.toptrack { height: 22px; }
.toptrack .topseg { flex: 1; text-align: left; padding-left: 10px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.toptrack-empty { font-size: 12px; padding: 4px 10px; }
.seg.gap { background: repeating-linear-gradient(45deg, var(--panel-2, #0002) 0 6px, transparent 6px 12px); color: var(--muted); display: grid; place-items: center; font-size: 11px; }
.seg.solo { box-shadow: inset 0 -3px 0 var(--sage); }
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
.result video { height: 360px; max-width: 100%; background: var(--stage); border-radius: 8px; }
.result .path { word-break: break-all; }
.log { background: var(--cream); padding: 12px; border-radius: 8px; font-size: 12px; max-height: 240px; overflow: auto; white-space: pre-wrap; }
.legend { font-size: 12px; display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; }
.lg { display: inline-flex; align-items: center; gap: 4px; }
.lg .sw { width: 10px; height: 10px; border-radius: 50%; }
.shapes { display: flex; flex-wrap: wrap; gap: 6px; }

/* the ✓ for keeping a relay flowing after an edit */
.flowask { display: flex; align-items: center; gap: 10px; margin-top: 8px; padding: 8px 10px; border-radius: 10px;
  border: 1px solid var(--sage); background: var(--sage-soft, rgb(184 207 168 / 18%)); }
.flowask > span { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
.flowok { display: grid; place-items: center; width: 34px; height: 34px; flex: none; border-radius: 50%; border: 0;
  background: var(--sage); color: var(--on-lane, #fff); cursor: pointer; }
.flowok:hover { filter: brightness(1.08); }
/* the audio rows: the mix strip, coloured by where the sound comes from */
.audiorow { --au-a: #8fae7c; --au-b: #d9954f; --au-music: #6f93c4; --au-voice: #b59a62; }
:root[data-theme='dark'] .audiorow { --au-a: #b8cfa8; --au-b: #e9b27a; --au-music: #8fb0dc; --au-voice: #efe6cf; }
.mixstrip { min-height: 44px; border-radius: 6px; background: rgb(128 128 128 / 7%); }
.mixstrip .bars { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
.bars rect { fill: rgb(128 128 128 / 35%); }
.bars rect.s-A { fill: var(--au-a); }
.bars rect.s-B { fill: var(--au-b); }
.bars rect.s-music { fill: var(--au-music); }
.bars rect.s-voice { fill: var(--au-voice); }
.lanename .tracksbtn {
  align-self: flex-start; margin-top: 3px; padding: 1px 7px; border-radius: 6px; font: inherit; font-size: 10px; cursor: pointer;
  border: 1px solid var(--line); background: transparent; color: var(--muted);
}
.fader { display: flex; align-items: center; gap: 3px; margin-top: 3px; }
.fader input[type='range'] { width: 58px; height: 14px; margin: 0; accent-color: var(--sage); }
.fader .pct { border: 0; background: none; padding: 0; color: var(--ink); font-size: 10px; min-width: 30px; text-align: left; cursor: pointer; }
.fader .pct.muted0 { color: var(--danger); }
.fadednote { color: var(--forest) !important; }
.trackrow .track { min-height: 52px; }
.lanename .tracksbtn:hover { color: var(--ink); border-color: var(--sage); }
.track { min-height: 36px; border-radius: 6px; background: rgb(128 128 128 / 5%); }
.track .bars { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
.bars rect.dim { opacity: 0.22; }
.trackrow .lanename b.t-A { color: var(--au-a); } .trackrow .lanename b.t-B { color: var(--au-b); }
.trackrow .lanename b.t-music { color: var(--au-music); } .trackrow .lanename b.t-voice { color: var(--au-voice); }
.trackctl { flex: 1; display: flex; flex-wrap: wrap; align-items: center; gap: 6px; padding: 4px 0; }
.duckbox { display: inline-flex; align-items: center; gap: 4px; margin-left: 8px; }
.quiet {
  position: absolute; top: -7px; z-index: 2; transform: translateX(-50%); padding: 0 2px; border: 0; background: none;
  font-size: 11px; line-height: 1; color: var(--ink); opacity: 0.75; cursor: pointer;
}
.quiet:hover, .quiet.hot { opacity: 1; color: #e08038; }
.quiet.at { opacity: 0.4; }
.edge.snapped::after { opacity: 1; background: #e08038; width: 3px; left: 3.5px; }
.band { position: absolute; top: 0; bottom: 0; min-width: 3px; background: rgb(224 128 56 / 28%); border-left: 1px solid rgb(224 128 56 / 55%); border-right: 1px solid rgb(224 128 56 / 55%); pointer-events: none; }

/* lanes & scenes */
.strip.lanebody { display: block; flex: 1; height: 30px; }
.lanebody.over { outline: 2px dashed var(--sage); outline-offset: 2px; border-radius: 8px; }
.seg.abs.over { box-shadow: inset 3px 0 0 var(--sage); }
.seg.abs[draggable='true'], .aseg[draggable='true'] { cursor: grab; }
.seg.abs { position: absolute; top: 0; bottom: 0; margin-right: 2px; box-sizing: border-box; border-right: 2px solid var(--bg, transparent); }
.toast { font-size: 12px; padding: 3px 10px; border-radius: 12px; background: var(--sage); color: #1d2a1d; }
.ruler { position: relative; height: 16px; margin-left: 110px; }
.rt { position: absolute; font-size: 10px; color: var(--muted); transform: translateX(-2px); }
.lanerow { display: flex; align-items: stretch; gap: 8px; }
.lanename { width: 102px; flex: none; display: flex; flex-direction: column; justify-content: center; font-size: 12px; line-height: 1.2; }
.lanename small { color: var(--muted); font-size: 10px; }
.lanebody { position: relative; flex: 1; min-height: 34px; }
.lanebody.scenes { min-height: 44px; }
.scene {
  position: absolute; top: 2px; bottom: 2px; display: flex; flex-direction: column; align-items: flex-start; justify-content: center;
  gap: 1px; padding: 2px 8px 2px 26px; overflow: hidden; white-space: nowrap; text-align: left;
  border: 1px solid var(--line, rgb(128 128 128 / 30%)); border-radius: 8px; background: var(--panel-2, rgb(128 128 128 / 10%));
  color: inherit; font: inherit; font-size: 12px; cursor: pointer;
}
.scene .sname { font-weight: 600; }
.scene small { font-size: 10px; color: var(--muted); }
.scene.sel { border-color: var(--sage); box-shadow: inset 0 0 0 1px var(--sage); }
.scene .glyph { position: absolute; left: 8px; top: 50%; transform: translateY(-50%); }
.edge { position: absolute; top: 0; bottom: 0; width: 10px; margin-left: -5px; cursor: ew-resize; z-index: 3; touch-action: none; }
.edge::after { content: ''; position: absolute; left: 4px; top: 8px; bottom: 8px; width: 2px; border-radius: 1px; background: var(--muted); opacity: 0.5; }
.edge:hover::after { opacity: 1; background: var(--sage); }
.glyph { display: inline-flex; flex-direction: column; gap: 2px; width: 10px; height: 16px; }
.glyph i { flex: 1; border-radius: 2px; }
.glyph.g-soloA i:first-child { background: #b8cfa8; } .glyph.g-soloA i:last-child { display: none; }
.glyph.g-soloB i:first-child { background: #e9b27a; } .glyph.g-soloB i:last-child { display: none; }
.glyph.g-stack i:first-child { background: #b8cfa8; } .glyph.g-stack i:last-child { background: #e9b27a; }
.glyph.g-swap i:first-child { background: #e9b27a; } .glyph.g-swap i:last-child { background: #b8cfa8; }
.glyph.big { width: 20px; height: 32px; margin-bottom: 4px; }
.glyph.big.side { flex-direction: row; width: 32px; height: 20px; }
.aseg, .lanebody .off {
  position: absolute; top: 2px; bottom: 2px; display: flex; align-items: center; justify-content: center; overflow: hidden;
  white-space: nowrap; font-size: 11px; border-radius: 6px; padding: 0 6px;
}
.aseg { border: 0; background: #b8cfa8; color: #1d2a1d; cursor: pointer; font-family: var(--mono, monospace); }
.aseg.current { box-shadow: inset 0 0 0 2px #344a34; }
.aseg.warn { background: #e8c27a; }
.warnchip { margin-left: 6px; padding: 0 5px; border-radius: 4px; background: #b3412f; color: #fff; font-size: 10px; }
.lanebody .off, .seg.gap { background: repeating-linear-gradient(45deg, rgb(128 128 128 / 16%) 0 6px, transparent 6px 12px); color: var(--muted); font-size: 11px; }
.seg.gap { display: grid; place-items: center; overflow: hidden; white-space: nowrap; }
.laneempty { position: absolute; left: 8px; top: 50%; transform: translateY(-50%); font-size: 12px; }
.inspector { display: flex; flex-direction: column; gap: 10px; padding: 16px; border-radius: var(--radius); background: var(--panel); }
.inspector h3 { margin: 2px 0; }
.ihead { display: flex; justify-content: space-between; align-items: flex-start; }
.caps { text-transform: uppercase; letter-spacing: 0.06em; font-size: 11px; }
.layouts { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.lay {
  display: flex; flex-direction: column; align-items: center; padding: 10px 4px; border-radius: 10px; font: inherit; font-size: 12px;
  border: 1px solid var(--line, rgb(128 128 128 / 30%)); background: transparent; color: inherit; cursor: pointer;
}
.lay.active { border-color: var(--sage); background: rgb(138 163 124 / 18%); }
.tbtns { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.timings { display: flex; flex-direction: column; gap: 6px; }
.timing {
  display: flex; flex-direction: column; align-items: flex-start; gap: 2px; padding: 8px 12px; border-radius: 8px; text-align: left;
  border: 1px solid var(--line, rgb(128 128 128 / 30%)); background: transparent; color: inherit; font: inherit; cursor: pointer;
}
.timing small { color: var(--muted); font-size: 11px; }
.timing.active { border-color: var(--sage); background: rgb(138 163 124 / 18%); }
.ilinks { display: flex; gap: 16px; flex-wrap: wrap; padding-top: 8px; border-top: 1px solid var(--line, rgb(128 128 128 / 20%)); }
.link.danger { color: #c0583f; }
.warn { color: #b3412f; }
.overruled .btn { opacity: 0.45; }
.aseg.relay { background: repeating-linear-gradient(45deg, #b8cfa8 0 8px, #a9c398 8px 16px); cursor: default; }
.handoffshot { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; z-index: 3; pointer-events: none; }
.timing.speedy b::after { content: ' · changes speed'; font-weight: 400; font-size: 11px; color: var(--muted); }

/* Lanes: green is A, amber is B (style.css tokens) on the timeline, the clip
   sheet, the preview and the inspector band. The page's other accents stay
   neutral so those two colours only ever mean a lane. */
.aseg { background: var(--lane-a); color: var(--on-lane); }
.aseg.relay { background: repeating-linear-gradient(45deg, var(--lane-a) 0 10px, color-mix(in srgb, var(--lane-a) 70%, var(--paper)) 10px 20px); color: var(--on-lane); font-weight: 600; }
.aseg.warn { background: var(--lane-a); box-shadow: inset 0 -3px 0 var(--danger); }
.seg.abs:not(.gap):not(.spare) { background: var(--lane-b-soft); color: var(--ink); box-shadow: inset 0 0 0 1px var(--lane-b); }
.seg.abs.playing:not(.gap) { background: var(--lane-b); color: var(--on-lane); box-shadow: none; }
.seg.abs.picked, .aseg.picked { outline: 2px solid var(--picked); outline-offset: 1px; z-index: 3; }
.scene.playing { border-color: var(--playing); box-shadow: inset 0 0 0 1px var(--playing); }
.scene.sel { border-color: var(--ink); box-shadow: inset 0 0 0 1px var(--ink); }
.scene .glyph.g-soloA i:first-child, .scene .glyph.g-stack i:first-child, .scene .glyph.g-swap i:last-child { background: var(--lane-a); }
.scene .glyph.g-soloB i:first-child, .scene .glyph.g-stack i:last-child, .scene .glyph.g-swap i:first-child { background: var(--lane-b); }
.lay .glyph.g-soloA i:first-child, .lay .glyph.g-stack i:first-child, .lay .glyph.g-swap i:last-child { background: var(--lane-a); }
.lay .glyph.g-soloB i:first-child, .lay .glyph.g-stack i:last-child, .lay .glyph.g-swap i:first-child { background: var(--lane-b); }
.formats .btn.active, .lay.active, .timing.active { background: transparent; border-color: var(--ink); color: var(--ink); box-shadow: inset 0 0 0 1px var(--ink); }
.toast { background: var(--ink); color: var(--paper); }
.editor :deep(.btn.active) { background: transparent; border-color: var(--ink); box-shadow: inset 0 0 0 1px var(--ink); }
.cliplist { padding-right: 4px; }
.workspace { grid-template-columns: minmax(380px, 440px) 1fr; }
@media (max-width: 1100px) { .workspace { grid-template-columns: 1fr; } }
.nowplaying { display: flex; flex-direction: column; gap: 6px; margin-top: 10px; }
.nowrow {
  display: flex; align-items: center; gap: 8px; padding: 6px 10px; border-radius: 8px; text-align: left; font: inherit; font-size: 12px;
  border: 1px solid var(--line); background: var(--paper); color: inherit; cursor: pointer; min-width: 0;
}
.nowrow i { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.nowrow.lane-A i { background: var(--lane-a); }
.nowrow.lane-B i { background: var(--lane-b); }
.nowrow.lane-A:not(.hidden) { border-color: var(--lane-a); }
.nowrow.lane-B:not(.hidden) { border-color: var(--lane-b); }
.nowrow.hidden { opacity: 0.55; cursor: default; }
.nowrow.picked { outline: 2px solid var(--picked); outline-offset: 1px; }
.nowrow span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.steps { list-style: none; margin: 8px 0 0; padding: 6px 10px; max-height: 190px; overflow-y: auto; font-size: 12px; border-radius: 8px; background: var(--cream); }
.steps li { padding: 1px 0; color: var(--muted); }
.steps li.slow { color: var(--ink); font-weight: 600; }
.steps li.now { color: var(--ink); }
.steps li.now::after { content: ' …'; }
.steps .dur { display: inline-block; width: 52px; text-align: right; margin-right: 8px; }
.stepsbox summary { cursor: pointer; }

/* the reel's Look, as near as CSS gets to the render's eq */
.preview-col.look-vivid :deep(.media video), .preview-col.look-vivid :deep(.media img) { filter: contrast(1.08) saturate(1.28) brightness(0.985); }
.preview-col.look-rich :deep(.media video), .preview-col.look-rich :deep(.media img) { filter: contrast(1.15) saturate(1.45) brightness(0.97); }
</style>
