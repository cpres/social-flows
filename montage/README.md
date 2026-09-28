# Steward Montage

Cuts several long clips together in interleaved rounds, so viewers watch a few actions progress side by side. Cuts land on the music's beats. Rounds are separated by soft dissolves, photos get a slow push-in, and the glasses audio sits quietly under the music.

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
- **Softness:** set `within_round: dissolve` for a dreamier piece, or `between_rounds: dip` for a breath through black.
- **Ambience:** `original_volume` controls how much bird, water, and tool sound comes through. Set it to 0.5 or higher for a raw feel.
- **No music:** remove the `music:` line. Timing then uses `clip_length` / `length` / `hold` in seconds, and the glasses audio carries the piece.

If a cut would run past the end of a clip, the script slides it earlier so it stays on the beat. The dry run tells you when that happens.

Output is 1080×1920 at 30fps. Photos should be JPG or PNG; convert HEIC files first.
