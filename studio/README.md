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
and everything else works the same.

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
- **Open a shoot** to go through its clips in the order they were shot. Under the
  video, a filmstrip shows what happens where; drag the handles to pick a part,
  or type exact start and length. Then click a reel (or press `1`–`9`) to add
  that part to it. Move the selection and add again to use another part of the
  same clip, in the same reel or a different one. Photos toggle in and out of
  reels with one click.
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
- **Duplicate** (reel header) makes a full copy of a reel (parts, trims,
  framing, transitions, music) so you can try a different cut without losing
  the one you have.
- **Music:** drop songs (MP3, M4A, WAV…) into `~/Music/Reels/` (or set
  `MUSIC_DIR`), then pick one under the reel's *Settings → Music*. Set where the
  song starts, and *Listen* to check it. Play reel plays the song and moves
  through the parts in time with it.
- **Cut on the beat:** the studio finds the song's beats once (cached), then each
  part lasts a whole number of beats: 1, 2, 4 or 8 (default 4, set per reel).
  Change a part's beats in its editor, or drag its end, which snaps to whole beats. The
  strip shows beat ticks, with a longer one every 4 beats. The render uses
  the same beats, so it cuts exactly where the preview does.
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

**Portrait & framing.** Reels are 1080×1920 (9:16). The preview shows each clip
as it will appear in the reel. When a clip isn't exactly 9:16 (glasses footage
is often 3:4), the part the reel keeps is outlined and the rest dimmed. Drag
that window to keep the subject in frame; it's saved per part, so the same clip
can be framed differently in different reels. Drag a corner of the window to zoom in (up to 3×; also works on clips that are already 9:16), then drag the window to place it; double-click it to zoom back out. Press `G` to see where Instagram's
caption and buttons will cover the picture. Files stored sideways with a
rotation flag (common from phones) are handled.

**Layout per part** (for landscape footage like mural timelapses): each part
can override the reel's framing, chosen under *Layout* on the shoot page
(before adding the part) or in the reel's part editor. *Fill* crops to 9:16 as above; *Blur* shows
the whole frame with a blurred copy filling the top and bottom; *Stack* puts
the whole clip across the top at full width and photos underneath (glasses
photos fit the space well). Pick the photos with *+ Add photos* (from the
clip's shoot, or any other); several take equal turns across the part, in the
order shown. Stacked parts get ▤ in the list, blurred ones ◫.

Everything is stored in one SQLite file, `~/Footage/.studio/studio.db`
(no database server to run). Files are never copied or moved. If you rename a
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
