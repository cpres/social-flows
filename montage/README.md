# Steward Montage

Cuts several long clips together in interleaved rounds, so viewers watch a few actions progress side by side. Cuts land on the music's beats. Rounds are separated by soft dissolves and photos get a slow push-in. The glasses audio is off by default; set `original_audio: true` to keep it quietly under the music.

## Setup (once)

```
brew install ffmpeg
pip install pyyaml librosa
```

librosa detects the beat automatically. If you skip it, set `bpm:` in the config.

## Use

1. Make a folder per montage with `montage.py`, a copy of `montage.yaml`, and `footage/`, `photos/`, `music/` subfolders.
2. Edit `montage.yaml`: list your clips in the order they should appear within each round.
3. Preview the cut list: `python3 montage.py montage.yaml --dry-run`
4. Render: `python3 montage.py montage.yaml`

## Tuning the feel

- **Pace:** `beats_per_cut` (1 = frantic, 2 = lively, 4 = calm). Give single clips `beats: 4` to let them breathe.
- **Per-cut transitions:** give any source `transition: flash | whip | zoom | dissolve | dip | cut` to choose how it leads into the next one. Flash is a 0.16s white flash, whip a 0.22s blurred slide, zoom a cut where the next shot punches in from 118%.
- **Softness:** set `within_round: dissolve` for a dreamier piece, or `between_rounds: dip` for a breath through black.
- **Ambience:** with `original_audio: true`, `original_volume` controls how much bird, water, and tool sound comes through. Set it to 0.5 or higher for a raw feel.
- **No music:** remove the `music:` line. Timing then uses `clip_length` / `length` / `hold` in seconds, and the piece is silent unless you set `original_audio: true` to let the glasses audio carry it.

If a cut would run past the end of a clip, the script slides it earlier so it stays on the beat. The dry run tells you when that happens.

Output is 1080×1920 at 30fps. Photos should be JPG or PNG; convert HEIC files first.
