# Footage Studio

A local app for building reels out of parts of your clips and photos. Your
footage stays in shoot folders under `~/Footage`; you tag parts of it into
reels (one per concept), and the same clip or photo can be used in as many
reels as you like, with different start and length in each. It writes the
config `montage/montage.py` already reads.

## Run

```
brew install ffmpeg node python@3.12   # once
./studio/run.sh                        # opens http://localhost:3009
```

Beat detection (for *Cut on the beat*) is optional and fairly large:
`./studio/run.sh --beat` installs it once. Plain `./studio/run.sh` skips it,
and everything else works the same. Transcribing voice takes (for captions)
is optional in the same way: `./studio/run.sh --voice` installs it once, and
the speech model (about 1.6 GB) downloads the first time you transcribe.

Needs Python 3.9 or newer; `run.sh` looks for `python3.13` … `python3.9`
before plain `python3`, so an old default `python3` (e.g. 3.7) is fine as long
as a newer one is installed. The first run creates a Python environment in `studio/.venv`, installs the
packages and builds the web app; later runs start straight away.
`./studio/run.sh --port 9000` picks another port, and
`FOOTAGE_DIR=/some/other/dir ./studio/run.sh` points it at another folder.

Manual alternative (delete any `.venv` made with an older Python first):

```
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r studio/requirements.txt
(cd studio/web && npm install && npm run build)
python3 studio/server.py --open
```

## How it works

- **Home** shows your **Reels** (concepts) above your **Shoots** (the date
  folders in `~/Footage`, newest first).
- **Import from Downloads** (next to *Shoots*) brings in what you AirDropped
  from your phone. It lists the photos and videos that landed in `~/Downloads`
  over the last month, grouped by the day they arrived, starting on today (the
  button shows how many new ones are waiting). Everything new from that day is
  selected; click thumbnails to leave some out. Then either make a **new shoot
  folder** (the date plus an optional "what was it", e.g.
  `2026-10-06 garden build`) or **add them to an existing folder** (a folder
  already named for that day is picked for you). Files are moved, so there's
  only ever one of each. iPhone HEIC photos are converted to JPEG on the way in.
  A file that's already in a shoot folder (matched on content, so AirDrop's
  renamed copies like `IMG_1234 2.MOV` count), or that's a repeat of another
  file in Downloads, isn't copied again: importing just deletes it from
  Downloads. `DOWNLOADS_DIR` points it somewhere else. If what came in is two
  or more videos (or one of 15s or more), the shoot page offers to **weave** them
  (below).
- **Imported into the wrong folder?** The shoot page says what just came in,
  with *Move them* next to it. Any time, *↪ Move files* in a shoot's header
  puts checkboxes on the clip list (*All* / *None*, `Esc` to stop); pick some
  and move them to another shoot folder or a new one. Their parts in reels
  come along, a name clash gets ` (2)` added, and a folder left empty is
  removed (you're taken to where everything went).
- **Open a shoot** to go through its clips in the order they were shot. Under the
  video, a filmstrip shows what happens where; drag the handles to pick a part,
  or type exact start and length. Then click a reel (or press `1`–`9`) to add
  that part to it. Move the selection and add again to use another part of the
  same clip, in the same reel or a different one. Photos toggle in and out of
  reels with one click.
- **Picks are kept.** The part you pick of a file (start, length, framing,
  zoom, layout) is saved as you go, even before it's in any reel: it's there
  when you open the shoot again (marked *picked* in the list), and it's where
  the file starts out when it's added to a reel, made into one with *Make a
  reel from this folder*, or woven (as one part, which you can add to).
  *Reset* under the lengths forgets it.
- Coloured marks under the filmstrip show every part of that clip already in a
  reel; click one (or *Edit* in the list below) to adjust it.
- **Play reel** (`Space` in a reel) plays every kept part in order, cropped
  exactly as the reel will be, so you can judge how the cuts flow. The part
  that's playing is highlighted in the list and on the strip; click a block on
  the strip to jump there. `Enter` plays just the selected part.
- **Transitions:** under each part in a reel, a small pill shows how it leads
  into the next. Click it (or press `T`) to cycle **Cut → Flash → Whip → Zoom**;
  the part's editor also offers Dissolve and Dip. *Flash* is a quick white flash,
  *Whip* a fast blurred slide, *Zoom* a cut where the next shot punches in and
  settles. Set a reel-wide default under *Settings*. Playing the reel shows a
  rough preview of each one; the render does the real thing.
- **Lighten:** each part can be lightened (Off / Low / Medium / High, or `L`),
  with *Use on every part* to match the rest. It lifts shadows and midtones
  rather than flat brightness, so shade opens up without blowing out the sky.
  The preview shows it live; parts with it on get a ☀ in the list.
- **Title & end card** (*Settings*): a title (with an optional line under it,
  like "October Edition") over the opening shots, and an end card over the
  last part, which holds 2, 4 or 8 beats longer for it, so the reel runs that
  much longer. The end card has a logo, a few lines (the first one big) and a
  small "presented by" logo underneath. Both are a dark, see-through layer
  over the footage with cream text, fading in. Grey text in the boxes is a
  suggestion: `Tab` takes it. *Preview title* / *Preview end card* draw the
  card over a frame of the first or last part, as the render will. Logos
  come from `brand/` (`oufp.png`, `garden-steward.png`, both cream). Play
  reel doesn't show the cards or the longer last part; the render does.
- **Duplicate this reel** (under *Settings*) makes a full copy of a reel (parts, trims,
  framing, transitions, music) so you can try a different cut without losing
  the one you have.
- **Archive** a reel you're done with: hover its card on the home page and
  click *Archive* (or *Archive this reel* under *Settings*). It leaves the
  home page and the shoot page's tag chips but is kept as it is;
  *Archived reels (n)* under the reels shows them, with *Unarchive*.
- **Music:** drop songs (MP3, M4A, WAV…) into `~/Music/Reels/` (or set
  `MUSIC_DIR`), then pick one under the reel's *Settings → Music*. Set where the
  song starts, and *Listen* to check it. Play reel plays the song and moves
  through the parts in time with it.
- **Make a beat for this reel** (✨ under *Settings → Music*) opens the
  **beat studio**, a full-screen page (`Esc` or ← goes back to the reel)
  for AI music made to the reel's exact length.
  - Across the top, a picture of the music: the planned sections (Intro,
    Build, Peak…), your energy curve, the hits on your scene changes, and
    bars pulsing at the beat's tempo. While takes are made it shows each one
    arriving; playing a take shows its waveform, a playhead (click to jump)
    and live frequencies.
  - Under it, the plan: *Start from* a song category, a song or scratch (the
    song sets the groove and sound, measured here: tempo, key, tone; needs
    `--beat`; never copied or sent; ▶ on a card plays
    30 seconds from the middle of its song, ■ stops); *Energy over the reel* (*Follow my
    scenes*, *Arc*, *Slow build*, *Two peaks*, *Steady*, or drag the points;
    *Hits on scene changes*, *End on the last frame*); ten *vibe levers*
    with four presets; the tempo and key they point to (or yours); and the
    prompt, which you can edit.
  - *Generate 3 takes* makes three, each leaning a different way (tighter
    drums / more bass, warmer / sparser, more space). *What's happening*
    says what's going on as it goes: the sections laid out, the song
    listened to, each take composing, its audio arriving (how much of it),
    and how it was landed on the last frame.
  - **ElevenLabs** (the default) gets a composition plan: a section per
    stretch of the curve, cut at your scene changes, each exactly as long as
    asked, so the take is the reel's length and the hits land on the cuts.
    It needs `ELEVENLABS_API_KEY` in `.env` (next to `studio/`) and a paid
    ElevenLabs plan (the free plan can't use Music). **Lyria** (through
    OpenRouter, `OPENROUTER_API_KEY`, about $0.08 a take) is the other
    engine: it follows the timing loosely.
  - Every take is cut or padded to exactly the reel's length (the last bar
    resolving on the last frame, or a fade if you'd rather) and kept in
    `~/Footage/.studio/beats/<reel>/` with what it was asked for and its
    seed. ☆ stars a take you like (*★ Starred only* to see just those).
    *Adapt…* makes a new take from one: pick how to change it (more or
    fewer drums, more bass, calmer, more energy, brighter, grittier,
    simpler) and/or say it in your own words; it keeps the take's seed and
    tempo, so it stays close and still fits the cut, and shows *from Take n*.
    Takes are numbered on across runs. *Use in reel* puts it on the music shelf (category *AI*) as the
    reel's song. If the cut changes after, the take in the reel offers
    *Rebuild to* the new length (same seed), which replaces it in the reel.
- **Song names and categories:** songs show by name and artist, read from the
  file's tags or, for Pixabay downloads (`artist-title-words-123456.mp3`), from
  the file name. ✎ next to the song gives it your own name and categories (a
  genre tag starts it off); the category chips above the list narrow it down.
  These live in the library, so the files themselves are never changed.
- **Cut on the beat:** the studio finds the song's beats once (cached), then each
  part lasts a whole number of beats: by default the number nearest its own
  length, so a 30s clip stays about 30s (*Beats per part: Nearest to each
  part's length*), or a fixed 1, 2, 4 or 8 for every part. A photo can also
  be ½ or ¼ of a beat, for quick ones. A part given beats of its own keeps
  them; *↺ nearest to its length* in its editor goes back. Change a part's beats in
  its editor, or drag its end, which snaps to whole beats (or ½ and ¼ for a
  photo). The strip shows beat ticks, with a longer one every 4 beats. The render
  uses the same beats, so it cuts exactly where the preview does.
- **Smart photo holds** (reel *Settings*): each kept photo holds for as long as
  what's in it needs, next to the reel's cut length; clips keep theirs. See
  *Smart hold* below.
- **Put the song in the video** (on by default). Turn it off to render the cuts
  timed to the song but without it, then add the same song in Instagram, which
  licenses it. The render tells you where in the song to start.
- **Open a reel** to see its parts from every shoot. Drag to reorder (or *Sort by
  shot time*), fine-tune each part's start and length, skip parts without
  removing them, and set music, beat sync and framing under *Settings*.
- **Render video** runs the montage engine for you, with a progress bar, then
  plays the result in the page. *Show in Finder* jumps to the file. Videos go to
  `~/Movies/Footage Studio/` (set `RENDER_DIR` to change). *Preview cut list*
  shows the engine's dry run first if you want to check timings.

**Shape & framing.** Pick the reel's *Shape* under *Settings → Look & timing*
(or in Weave's Moments, under the preview). The two main ones are *Reels 9:16*
(1080×1920, Instagram Reels, TikTok, Shorts; the default) and *YouTube 16:9*
(1920×1080); there's also *4:5* (1080×1350, the Instagram feed) and *Square*
(1080×1080). The preview switches as you click, so you can see how a reel
reads in each; *Duplicate this reel* first to keep one of each. A 16:9 frame
keeps a strip of tall footage (*Blurred background* shows all of it with
blurred sides), and captions keep to a centred column so they stay the size
they'd be on a square. Glasses footage is 3:4, so a square keeps its whole
width; *Square, framed to the bottom* there (also in Weave's Moments) picks
square and frames every part on the bottom of its shot, where the hands are,
at full width. In 16:9, split scenes put the lanes side by side. The preview shows each clip
as it will appear in the reel. When a clip isn't exactly the reel's shape,
the part the reel keeps is outlined and the rest dimmed. *Framing* in the part
editor puts the window at the *Top*, *Middle* or *Bottom* at full width, and
*Use on every part* frames every part like the one you're on (*Length → Use on
every part* does the same for its length). Drag
that window to keep the subject in frame; it's saved per part, so the same clip
can be framed differently in different reels. Drag a corner of the window to zoom in (up to 3×; also works on clips that are already 9:16), then drag the window to place it; double-click it to zoom back out. Press `G` to see where Instagram's
caption and buttons will cover the picture. Files stored sideways with a
rotation flag (common from phones) are handled.

**Layout per part** (for landscape footage like a day's timelapse): each part
can override the reel's framing, chosen under *Layout* on the shoot page
(before adding the part) or in the reel's part editor. *Fill* crops as above;
*Blur* shows the whole frame with a blurred copy filling the top and bottom
(marked ◫ in the list).

**Clip sheet: A and B side by side.** On a reel with two lanes, the list on
the left is a clip sheet with one row per scene. Lane A's card (its stretch of
the A clip, or the shot a relay carries on) sits on the left, and lane B's
parts on the right, each with where it starts on the reel, its length, and a
bar that fills as it plays. Green is always lane A and amber always lane B:
on the timeline, in the sheet, on the preview's slot borders, in the Now
playing rows and in the inspector's band. Other highlights on the page are
neutral so the two colours only ever mean a lane.

- **Following the playhead:** the scene under it is outlined in red with a
  *playing* chip, and the A and B cards under it glow. *Follow playhead*
  (on) keeps that row in view, and pauses for 3s after you scroll the sheet
  yourself. A lane that isn't on screen in a scene shows a hatched *waits ·
  off-screen* cell: it pauses there and picks up where it left off.
- **One selection:** clicking a timeline block, a sheet card, a preview slot
  or a *Now playing* row selects the same part everywhere, outlined in all of
  them. The playhead moves to the part's start unless it's already inside it.
  Clicking a scene's header moves the playhead to its start. `Tab` jumps
  between the A and B on screen. *◀ Part* / *Part ▶* move the playhead to the
  previous or next place a part starts, in either lane.
- **The inspector's header** shows the lane in its colour, *B lane · part 3
  of 12* (or *A lane · part 2 of 3*: the scenes that show A), the scene and
  where it sits on the reel, and in plain words where it shows: *in the
  BOTTOM slot*, *FULL FRAME*, or *Not visible: lane B waits*.
- **Lane toggle:** moving a B part to lane A makes it its scene's A clip from
  where the part starts, and lane B closes up (a scene left with no B becomes
  Solo A, showing it). Moving an A card to lane B makes that stretch a B part
  at the start of its scene, which then shows B on its own.
- Parts that aren't in the reel right now (skipped parts, and lane A clips
  no scene shows) wait at the bottom of the sheet.

**Making a reel, in a style.** *New reel* (Home) and *Make a reel from this
folder* (a shoot) ask for a name and a style:

- **Standard:** one part after another, full frame.
- **Weave:** opens the Weave wizard (below).
- **Stack:** the longest clip goes in lane A, on top the whole way at real
  speed, with the others underneath.
- **Relay:** single, split, single, split… for long-form reels. Each clip
  plays alone, then moves up into A's slot and carries on (3s by default)
  while the next clip comes in underneath. The next clip then takes over the
  full frame as the first one finishes, and so on, in the order the clips
  were shot. **Long clips** (10s or more) get their own length: all of the
  clip, or the long stretch you picked on the shoot page, or up to 20, 30 or
  60s if you cap them. *Skip quiet moments in long clips* cuts out where
  nothing much happens, at real speed. **Photos and short clips** play alone
  for a set few seconds (3s by default), like clips between the long pieces.
  The dialog shows about how long the reel will run. Every move is seamless:
  the shot moving up is exactly what was on screen, and B grows from its
  slot to the full frame. In the reel it's ordinary scenes (Solo B, then a
  split with *Relay* ticked that comes in with *Hand off*, then Solo B coming
  in with *Take over*), so you can trim, reorder and change any of it.
  Ticking *Relay* on any split after a Solo B scene does the same by hand.

**Lanes and scenes.** A reel has two lanes of footage and a row of scenes
over them. Lanes say what's playing; scenes say what's on screen.

- **Lane A** is the main, continuous footage: usually one long glasses POV
  clip, or a few. ⤒ on a part, or dragging it onto the *A lane* slot in the
  list or the *A lane* row of the timeline, puts it there. *Move to lane B*,
  or dragging its block down onto the *B lane* row, puts it back. While you
  drag a B video (from the list or the timeline), the whole timeline becomes
  a *Move to A lane* drop zone (reorder the cut list in the list below). Its
  start and length
  pick the stretch the scenes can use.
- **Lane B** is the cut list: every other kept part, one after another, as
  before.
- **Scenes** follow one another along the *Layout* row: **Solo A**, **A over
  B** (A in the primary slot), **Solo B** and **B over A**. The output shape
  (next to the reel's name) decides which way a split reads: *9:16 · A top*
  stacks them, *16:9 · A left* puts them side by side. A reel with nothing in
  lane A is all Solo B, which is just a normal reel.
- **Who sets the length:** when B is on screen, the scene runs as long as its
  parts, so trimming a part moves the scene's edge and A re-fits (a note says
  "A now 1.81×" when A's speed depends on it). In Solo A, A plays alone for the scene's length (or its
  range), and B waits. A lane that's off screen is hatched, and it pauses: it
  picks up where it left off.
- **Click a scene** to edit it on the right: its layout (or `1`–`4`), the
  split (50/50, 58/42, a square second slot, or drag the divider in the
  preview; `[` `]` nudge it 2%), how A plays in it, how it comes in (Cut,
  Slide, Push or Dissolve, 0.8s, with both scenes playing through it;
  Hand off and Take over take 1s; into or out of Solo A, Slide keeps A on
  screen: it shrinks from the full frame into its slot as B comes in, or grows
  back as B goes out, playing on all the while), and how a lane alone fills the frame (16:9
  defaults to a blurred fill). *Use this split on every stacked scene* and
  *Merge into previous scene* are at the bottom.
- **How A plays in a scene:** at **real speed**, always, unless you pick a
  speed. A plays 1× for as long as the scene lasts, carrying on from the
  scene before. So lane A works out how much footage it needs: its *Start*
  is where it begins, and it runs on into the clip as far as the scenes need
  (the A clip's editor says how far, e.g. "0:54 → 2:12 of the clip"). If the
  clip runs out first, its last frame holds, and you're told by how much.
  *Real speed, skip quiet moments* is still 1×, but it jumps over stretches
  where nothing much happens (the same movement measure as Weave's), so more
  of A gets in. Only two choices change speed, and they say so: *Pick a
  speed* (½× to 4×) and *Speed up to fit its range* (A's start → end
  squeezed into the scene, a timelapse; a chip warns over 4×). *A starts at*
  sets where A begins in any scene.
- **Starting a split:** `S` (*Split scene at playhead*) starts a new scene at
  the nearest cut with the last split you used, and A carries on from the
  same point. In a part's editor, *On its own (full frame)* gives that part a
  Solo B scene of its own, and what comes after it carries on in the layout
  it had. That's how a reel opens on a single photo before the split: the
  split scene then comes in with **Hand off**. The photo moves into A's slot
  (top, or left) as B comes in from the other side, stays there 3s (1, 2, 3
  or 5 in the scene's inspector), then dissolves into A, which only starts
  then. Hand off is offered for any split scene that follows a Solo B one.
  *Split from here* starts a split scene at that part.
  `W` swaps A and B. Drag the edge between two scenes to move where it
  changes (it snaps to a cut). Under 1s, the two scenes merge.
- **Framing per slot:** a part keeps a framing for each slot shape: full
  frame, half, square. So reframing it for the bottom half doesn't touch its
  full-frame crop. Drag the window in its slot to reframe. In a slot, new B
  parts start framed low (hands are low in glasses footage) and A a little
  above the middle. `Tab` jumps between the A clip and the B part on screen.
- **Transitions:** inside a scene, parts keep their own *Into next part*.
  Where a scene starts, the scene's transition wins, and the part's picker
  says so.
- **Sound:** *Glasses audio* (under the audio tracks, or in *Settings*) is
  *Follows primary slot* (the lane top or left, or the one alone; a swap
  moves the sound with it), *A only* (lane A whenever it's on screen, never
  B) or *Off*. Reels that had *Keep glasses audio* on start on *Follows
  primary slot*. A sped-up A is silent. Where a scene's sound comes from
  somewhere else, it switches over 80ms (out 40ms, in 40ms) so it never
  clicks; where the same A clip carries straight on, it doesn't dip.
  *Duck music under glasses + voice* (on) drops the song about 9dB (in
  0.15s, back over 0.4s) wherever the kept glasses audio is loud, as well
  as under the voice; off, the song stays at its level throughout.
- **Audio strip:** under the lanes, *Audio* shows what you'll actually
  hear, on the same clock: the glasses audio that's kept, the song at its
  level (lower under the voice, fading at the end) and the voice, added up
  in bars about 0.4s apart, each coloured by where most of it comes from
  (A green, B orange, song blue, voice cream). Orange bands mark where a
  scene comes in (or, in a reel of one scene, where a part leads into the
  next with anything but a cut). Each file's loudness is measured once
  (`audio.py`, cached in `~/.cache/footage-studio`); the first look at a
  reel says *measuring…* while that happens. The strip follows the
  render's own levels, to within about half a dB. *Show tracks* opens a row
  each for A glasses, B glasses, the music and the voice, at their own
  level: bright where it's heard, dim where it isn't (the lane whose sound
  isn't kept, a sped-up A, the song where it ducks).
- **Volume:** *Tracks & volume* opens the rows, each with its own volume
  (0–150%, 100% as it comes): A glasses, B glasses, the music and the
  voice. Turn the clips' sound down under a song or a beat, or the song
  down under them. Click the % to mute (again to bring it back),
  double-click the slider for 100%. The audio strip, the render and Play
  reel all follow it (the preview can't play a clip above 100%). With the
  tracks hidden, *volumes set* says some aren't at 100%.
- **Quiet moments:** a ◆ on the audio strip by each scene edge marks the
  quietest moment of what you hear within 1s of it, where a change of
  scene goes by least noticed. Dragging the edge within 0.3s of its ◆
  snaps it there (the edge turns orange); clicking the ◆ moves it there.
  After a Solo A the edge can go anywhere; between B scenes it only goes
  on a cut, so there the ◆ is the quietest cut nearby. A dim ◆ means the
  edge is already as quiet as anywhere near it (nothing is 3dB quieter).
- **Reels from before:** a Standard reel becomes one Solo B scene. A Stack
  reel's top clip becomes lane A, with one *A over B* scene at real speed.
  The top-alone and on-its-own parts from the first moving-stack version
  become Solo A and Solo B scenes. Nothing changes until you edit it.

**Take out quiet moments.** A long video part (8s or more) with boring
stretches in it has *✂ Take out quiet moments* in its editor. It cuts the
part where nothing much happens (a lull of 1.5s or more) into parts one
after another, each 3s or longer, which you can trim, move or skip like
any other, the way you edit a weave.

**Voice & captions.** *🎙 Voice* (in a reel's header) lays a reading over the
footage, a poem or an idea, with its words on screen as they're said.

- **Takes** are recordings in a shoot folder: voice memos (M4A, MP3, WAV…) or
  the sound of a video. AirDropped memos waiting in Downloads are listed under
  the folder picker; *Move to this folder* brings one in.
- **Transcribe** a take once (it runs in the background; transcripts are kept
  in `~/Footage/.studio/voice/`) and its words come back as lines, broken at
  your pauses and punctuation, with a gap between stanzas. Click the first line
  you want and shift-click the last, then *Add lines … as a piece*: the piece is
  trimmed to exactly those words. *Use the whole take* works without
  transcribing. Add more pieces, from the same take or others, to build the
  reading from your best lines.
- **Pieces** play one after another, each after its *breath* (the pause
  before it; the first one's is the lead-in). Reorder them with ↑ ↓; *Lines*
  opens a piece's trim (*From*/*To* in the take) and its caption lines: edit the
  words, `Enter` splits a line at the cursor, *join ↓* joins two, ¶ starts a new
  stanza, ✕ leaves a line uncaptioned. *Paste the written text* times your own
  text (a line per caption line, a blank line between stanzas) to what's said,
  keeping your exact words and breaks.
- **Effects on a phrase:** ✦ beside a caption line lifts some of its words
  out with an effect. Click the first word and shift-click the last (all of
  the line to start with), then pick *Echo* (the phrase repeats three times,
  fading), *Hall* (a huge stone room that rings on after), *Waver* (the pitch
  trembles), *Pulse* (the voice throbs) or *Doubled* (two more voices just
  behind, drifting), and *Light*, *Medium* or *Strong*. The plain voice steps
  aside for those words; an echo or hall rings on over what follows, and *Fit
  to the voice* waits for it. *Hear it* plays the phrase with its effect;
  the line shows the effect's name, and the voice lane marks where it is.
  *Play reel* plays a rough version; the render does the real thing.
  With *Show effects in the words* (under Captions, on), the words show it
  too while it plays: an echo leaves three ghosts stepping down and away, one
  per repeat; a hall glows warm and lingers while the room rings; waver
  trembles; pulse throbs; doubled drifts two copies either side.
- **Sound:** the song sits at *Song under the voice* (15%) while it speaks and
  rises to *Song in the breaths* (30%) around it; *Clean up the voice* cuts low
  rumble and hiss, and each piece is evened out to the same loudness. Adding the
  first piece turns glasses audio off. *Fit to the voice* (on) holds the last
  part until the reading ends, then the end card plays; the strip shows the hold
  as a striped block.
- **Captions** come in four styles, each with a font and background you can
  change: *Stanza* (the whole stanza shows, the line being said bright, the rest
  dim), *Unfold* (lines fade in as they're said and stay until the stanza ends),
  *Breath* (one line at a time, centred, drifting up) and *Page* (set left on a
  cream panel under a small title). Backgrounds: a see-through layer over the
  whole frame, a band, a paper panel, blur behind the words, or just a shadow.
  The fonts are in `brand/fonts/`. The preview beside them shows the captions
  over the part playing at that point (*← line* / *line →* step through);
  *Show as rendered* draws that frame exactly as the render will. Captions stay
  clear of Instagram's caption and buttons.
- Under the strip, the voice lane shows the pieces and the caption lane the
  lines, on the reel's clock. *Play reel* plays the voice with the song lowered
  under it and shows the captions over the frame.

**Weave.** Long clips are dull watched end to end. The *Weave* style (in *Make
a reel from this folder* on a shoot's page, or offered right after an import;
a weave left part way is picked up with *Continue weave draft*) cuts each clip
into a few parts and
interleaves them: a bit of clip 1, an early bit of clip 2, of clip 3, then back
for later bits (`1a 2a 3a ▣ 1b 2b ▣ 1c 2c ▣`), so several things seem to happen
at once. It's a four-step wizard that makes a normal reel:

1. **Order**: the shoot's clips and photos in the order they were shot (what you
   just imported is picked). Drag to reorder, click to leave one out. Each round
   goes through the clips in this order.
2. **Pace**: the length of every part (1–8s, or *Aim for* 15/30/45/60s), and a
   song: *Listen* plays it (drag along it to hear more, or pick another song and
   that one plays). With a song and beat detection, every part is a whole
   number of beats (1, 2, 4 or 8). *Photo hold* is *Smart* (below) or *Even*,
   every photo a bit shorter than a part. Clips at least *Split clips this long
   or longer* (0:15) get about one part per 15s of footage (2–6), so a 30s clip
   gives its first and second 15 seconds; shorter ones get one. *Between rounds* picks the transition that marks time moving on.
3. **Moments**: one clip at a time. Its parts are windows on the filmstrip
   (a, b, c…) that slide but never cross, so a always comes before b; `+`/`−`
   changes how many. The lane under the filmstrip shows how much is moving where
   (measured once from the keyframes, cached), and *Suggest busy moments* starts
   each part on the liveliest stretch of its share of the clip. Framing set here
   applies to every part of the clip; under the preview, pick the reel's *Shape*
   (Reels 9:16, YouTube 16:9, 4:5, Square), put the window at the *Top*, *Middle* or *Bottom*, and
   *Use on every clip* to frame them all alike. Each part runs for the pace unless you give
   it a **length** of its own: on the beat, 1, 2, 4 or 8 beats (the pace's is
   marked), else a length in seconds; `[`/`]` makes it shorter or longer.
   *All of a–f* gives that length to every part of this clip; *Every clip* makes
   it the pace, so every part of every clip runs that long. For a
   photo, pick its hold (Medium, Small or Burst); it says why it got the one it
   has. **Leave it out** (`X`) takes the clip or photo out of the reel right
   there, and *Put it back* undoes it. The song is here too (♪, *Change* to
   pick another or cut on the beat), and playing a part (`Space`) plays the song
   under it from where that part lands in the reel; a photo plays the song for
   as long as it holds. *Play with the music* off plays them silent.
4. **Stitch**: the woven order as tiles. Every clip shows up in the first round
   and ends in the last; a clip with more parts than the others is spread across
   the rounds, and photos go between rounds, the last one closing the reel (a
   burst stays together). Drag
   tiles to change it, and click the marks between them to switch a cut to the
   between-rounds transition. *Create reel* opens it as a normal reel to play,
   fine-tune and render.

A reel made this way has **Edit weave** in its header, which reopens the wizard
on that reel, with its settings, parts and order, and saves back into the same
reel (it never makes a new one; *Duplicate* is for that). Parts keep the framing, lighten and zoom set on
them in the reel, and any length that isn't the pace; the rest follow the pace.
A photo whose hold you changed in the reel comes back held for exactly that
long; a style picked by hand stays picked. In Moments a photo can also hold
for *Exactly* ¼–4 beats (or a length off the beat); *Back to automatic* undoes
either.

**Drafts.** The wizard saves what you've chosen as you go: on every click, on
Next and Back, moving between moments, and a moment after a drag or key (the
header says "draft saved 10:42"), so leaving it loses nothing. If you change
the reel after leaving a weave edit, *Edit weave* starts from the reel as it is
now and offers the older draft instead. ← takes you Home, where the
draft waits at the front of *Reels*; click it, or *Continue weave draft* on the
shoot's page, to pick up on the step and clip you left. There's one draft per
shoot. An unsaved weave edit isn't a card of its own: the reel's card says
*Editing weave*, and its *Edit weave (unsaved)* button picks it up. Files
imported since are added to a draft.
*Start over* throws a draft away; making the reel (or saving it) clears it.

**Smart hold.** Clips hold longest; a photo holds for as long as what's in it
needs:

| Style | What | Off the beat (2s parts) | On the beat (4-beat parts) |
|---|---|---|---|
| ▶ Clip | a part of a clip | the pace: 2s | 4 beats |
| ◉ Medium | a photo with people or animals in it | ≈ 0.7 × (1.4s) | 2 beats |
| ○ Small | a photo with neither | ≈ 0.45 × (0.9s) | 1 beat |
| ⁂ Burst | near-repeats shot within 2 minutes | 0.4–0.7s each | ½ beat each, at least 0.4s (usually 1) |

In a reel with two lanes on screen (lane A, or a relay), there's more to take
in at once, so no photo flicks by: Burst holds 2s, Small 3s and Medium 4s,
and on the beat each is the whole beats that last at least that long.

On the beat, each is half the one above it, but never too quick to see (it
goes up to the next division, so at 160 bpm a burst is one beat), and a run of
photos that would end between beats holds its last one to the next beat, so the
clips after it still cut on the beat. Photos next to each other that look
almost exactly alike (the same light, dark and colours, allowing a small
reframe) and were taken within 2 minutes are a burst, so most photos hold
Medium or Small; in Weave a burst stays together in one gap
between rounds. People and animals are found by macOS's own Vision framework
(faces, people, cats and dogs, and scene labels like *bird* or *insect*), which
`run.sh` installs on a Mac (PyObjC, small); without it, photos hold Medium
unless you pick, and bursts still work. What it finds is cached per photo.

Everything is stored in one SQLite file, `~/Footage/.studio/studio.db`
(no database server to run). Files are never copied, and only moved when you
say so (Import, *Move files*). If you rename a
file or move it to another shoot folder, it relinks automatically (matched on
size and capture time).

**Per-concept folders you already have:** open the folder and click *Make a
reel from this folder*. Files that are copies of originals in another shoot
folder are pointed at the original, so the copies can be deleted afterwards.
Trims made with the first version of the studio (`.studio.json`) are carried
over the same way.

Keys in a shoot: `Space` play the selection (stops at its end) · `Enter` play/pause
the whole clip · `I`/`O` start/end at playhead · `←`/`→` nudge start (Shift = 1s) ·
`↑`/`↓` previous/next · `1`–`9` add to reel · `G` Instagram overlays.

Keys in a reel: `Space` play/pause the whole reel · `Shift`+`Space` play from the start · `Enter` play just this part ·
`I`/`O`, `←`/`→`, `↑`/`↓` as above · `X` keep/skip · `T` transition · `L` lighten · `G` Instagram overlays.

**Lengths and beat sync.** With no music, or beat sync off (the default), your
lengths are used exactly. Turn beat sync on in *Settings* and the engine
snaps each cut to `beats_per_cut` beats instead, ignoring per-clip lengths.

**Playback.** If a clip won't preview in Chrome it's probably HEVC; Safari
plays it. Thumbnails, trimming and rendering work either way.

**Renders & Send to phone:** the *Renders* page (top bar) lists every
finished video in `~/Movies/Footage Studio/`, newest first, even after a
restart. Play it again, show it in Finder, or **Send to phone**: scan the QR
code with your phone (on the same Wi-Fi) and it downloads the video, ready to
post from the Instagram app with its music library. Only that one video is
shared, over a private link that expires after an hour, on port 3010
(`SHARE_PORT`); the rest of the studio stays on this Mac. The first time,
macOS may ask whether Python may accept incoming connections: allow it.

**Themes:** Light (cream), Grey (cool grey) or Dark, from the switch in the top bar. It's remembered, and until you pick one it follows your Mac's dark mode.

Thumbnails are cached in `~/.cache/footage-studio/`.

UI development: run the server, then `npm run dev` in `studio/web` (proxies `/api`).
