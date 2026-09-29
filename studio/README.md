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
can be framed differently in different reels. Press `G` to see where Instagram's
caption and buttons will cover the picture. Files stored sideways with a
rotation flag (common from phones) are handled.

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

Keys in a reel: `Space` play/pause the whole reel · `Enter` play just this part ·
`I`/`O`, `←`/`→`, `↑`/`↓` as above · `X` keep/skip · `G` Instagram overlays.

**Lengths and beat sync.** With no music, or beat sync off (the default), your
lengths are used exactly. Turn beat sync on in *Settings* and the engine
snaps each cut to `beats_per_cut` beats instead, ignoring per-clip lengths.

**Playback.** If a clip won't preview in Chrome it's probably HEVC; Safari
plays it. Thumbnails, trimming and rendering work either way.

Thumbnails are cached in `~/.cache/footage-studio/`.

UI development: run the server, then `npm run dev` in `studio/web` (proxies `/api`).
