# Footage Studio

A local app for picking moments out of long clips. Browse the folders in
`~/Footage`, preview each clip, and set **where each cut starts and how long
it runs**. It writes the config `montage/montage.py` already reads.

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

- **Home** lists every folder in `~/Footage` (one per shoot, e.g. `2026-09-24`),
  newest first, with a cover frame, clip count and total footage length.
- **A folder** lists its clips in the order they were shot. Pick one to preview it.
  Under the video, a filmstrip shows what happens where; drag the handles to set
  the start and end, or drag the highlighted selection to slide it.
  Type exact values in *Start* / *Length*, or use the quick-length buttons.
- **Keep / skip** each clip (✓ or `X`). Skipped takes stay on disk, out of the cut.
- The bar under the header shows the montage: one block per kept cut, sized by length.
- Everything autosaves to `<folder>/.studio.json`, so reopening a folder
  picks up where you left off.
- **Export & preview cut list** writes `<folder>/montage.yaml` and shows
  `montage.py --dry-run`'s output. Render with the command it prints; the
  video lands in `<folder>/renders/`.

Keys: `Space` play · `Enter` loop selection · `I`/`O` start/end at playhead ·
`←`/`→` nudge start (Shift = 1s) · `↑`/`↓` previous/next clip · `X` keep/skip.

**Lengths and beat sync.** With no music, or beat sync off (the default), your
lengths are used exactly. Turn beat sync on in *Settings* and the engine
snaps each cut to `beats_per_cut` beats instead, ignoring per-clip lengths.

**Playback.** Chrome can't play HEVC; if smart-glasses `.mov` files don't
preview, use Safari. Thumbnails and trimming work either way.

Thumbnails are cached in `~/.cache/footage-studio/`.

UI development: run the server, then `npm run dev` in `studio/web` (proxies `/api`).
