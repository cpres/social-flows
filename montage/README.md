# Steward Montage

Cuts several long clips together in interleaved rounds, so viewers watch a few actions progress side by side. Cuts land on the music's beats. Rounds are separated by soft dissolves and photos get a slow push-in. The glasses audio is off by default; set `original_audio: true` to keep it quietly under the music.

## Setup (once)

```
brew install ffmpeg
pip install pyyaml librosa pillow
```

librosa detects the beat automatically. If you skip it, set `bpm:` in the config.

## Use

1. Make a folder per montage with `montage.py`, a copy of `montage.yaml`, and `footage/`, `photos/`, `music/` subfolders.
2. Edit `montage.yaml`: list your clips in the order they should appear within each round.
3. Preview the cut list: `python3 montage.py montage.yaml --dry-run`
4. Render: `python3 montage.py montage.yaml`

## Tuning the feel

- **Pace:** `beats_per_cut` (1 = frantic, 2 = lively, 4 = calm). Give single clips `beats: 4` to let them breathe. A photo's `hold_beats` (and a clip's `beats`) can be `0.5` or `0.25` too, to flick through photos on half or quarter beats.
- **Framing:** `focus: [x, y]` (0–1) picks which part of the frame a fill crop keeps; `zoom: 1.5` (1–3) crops tighter.
- **Layout per source:** `fit: fill | blur | pad` overrides the config's `fit` for one source.
- **Stack:** `top: {file: footage/timelapse.mp4, start: 0, length: 60, focus: [0.5, 0.5]}` plays that clip in the top pane for the entire piece while the cuts play underneath. `stack: {split: 0.5, divider: 4, divider_color: "#f7f1e3", fit: true}` sets the top pane's share, the line between the panes, and whether the top clip is sped up or slowed down to end with the cuts (`fit: false`: the piece runs as long as the top clip at normal speed; the cuts are cut short or the last one holds).
- **Lighten:** give a source `lighten: 0.5` (0–1) to lift shadows and midtones for footage shot in shade.
- **Per-cut transitions:** give any source `transition: flash | whip | zoom | dissolve | dip | cut` to choose how it leads into the next one. Flash is a 0.16s white flash, whip a 0.22s blurred slide, zoom a cut where the next shot punches in from 118%.
- **Softness:** set `within_round: dissolve` for a dreamier piece, or `between_rounds: dip` for a breath through black.
- **Ambience:** with `original_audio: true`, `original_volume` controls how much bird, water, and tool sound comes through. Set it to 0.5 or higher for a raw feel.
- **No music:** remove the `music:` line. Timing then uses `clip_length` / `length` / `hold` in seconds, and the piece is silent unless you set `original_audio: true` to let the glasses audio carry it.

## Title and end card

Both are overlays on your footage: a dark, see-through forest layer with cream text, fading in and out. Neither is a solid black or white card.

```yaml
title:
  text: "3rd Sundays"
  sub: "October Edition"
  logo: ../brand/oufp.png     # optional; or logos: [a.png, b.png]
  hold: 2.5                   # seconds fully shown (default 2.5)
  dim: 0.45                   # how dark the layer is, 0-1

end_card:
  logos: [../brand/oufp.png, ../brand/garden-steward.png]
  lines: ["Oakland Urban Farming Project", "3rd Sundays · Next: Sun Nov 16"]
  hold: 3.5                   # roughly how long it's on; it starts on the nearest cut
  dim: 0.62
```

The title fades in just after the start. The end card starts on the cut nearest `hold` seconds from the end, so it lands with a new shot (and with the beat when cuts are on the beat), and stays to the end. The end card's first line is set large; the others are smaller. Text stays inside the area Reels and TikTok don't cover. The cards use Playfair Display and Roboto when they're installed or in `brand/` (`fonts: {display: ..., body: ...}` picks other files), otherwise Georgia and Helvetica. They need Pillow (`pip install pillow`).

If a cut would run past the end of a clip, the script slides it earlier so it stays on the beat. The dry run tells you when that happens.

Output is 1080×1920 at 30fps. Photos should be JPG or PNG; convert HEIC files first.
