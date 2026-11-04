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
- **Stack:** `top: {file: footage/timelapse.mp4, start: 0, length: 60, focus: [0.5, 0.5]}` plays that clip in the top pane for the entire piece while the cuts play underneath. `stack: {split: 0.5, divider: 4, divider_color: "#f7f1e3", fit: true}` sets the top pane's share, the line between the panes, and whether the top clip is sped up or slowed down to end with the cuts (`fit: false`: the piece runs as long as the top clip at normal speed; the cuts are cut short or the last one holds); `speed: 2` plays it at that speed when fit is off). `fit_by: quiet` fits it by cutting out its quiet stretches instead (it needs `activity: [[seconds, 0..1], ...]` on `top:`, the studio's movement measure). In a frame wider than tall the panes are side by side.
- **Stack layouts:** a cut with `pane: solo` fills the frame on its own, and a source `{gap: true, beats: 4}` (or `length:` in seconds) is the top clip on its own. The panes slide between layouts over half a second, a pane on its own sits in the middle over a blurred copy of itself, and the top clip pauses while it's off screen. The dry run prints the layout and the top clip's pieces.
- **Scenes:** `scenes:` (a list) says what's on screen, one scene after another: `{layout: soloA | stack | soloB | swap, split: 0.58 | square, into: cut | slide | push | dissolve | handoff (after a Solo B scene: its last frame moves into A's slot as B comes in, stays `handoff:` seconds, default 3, then dissolves into A) | takeover (into Solo B after a split: B grows to the full frame as A slides out). A split after Solo B with `relay: true, carry: {file, kind, start, focus, zoom}` plays that shot on in A's slot instead of lane A, fill: fill | blur, a: {file, start, end, in, out, timing: fit | quiet | hold | range, speed, focus, zoom}}`. Each source has a `scene:` (its index), and a Solo A scene is a `gap:` source with `length:` (whole beats nearest it when cutting on the beat). Each scene's lanes are framed to their slots and stacked (side by side in a wide frame) with `stack: {divider, divider_color}`. Then the scenes are joined, each coming in over the last frame of the one before for 0.4s. An A that doesn't say `in`/`out` carries on from the last scene on that clip, and fitted scenes share what's left. The dry run lists the scenes and A's speed in each.
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
  logos: [../brand/oufp.png]
  lines: ["Oakland Urban Farming Project", "3rd Sundays · Next: Sun Nov 16"]
  presented_by: ../brand/garden-steward.png   # small, under "presented by"
  beats: 4                    # the last part holds this much longer (hold: 2 without beat sync)
  dim: 0.62
```

The title fades in just after the start. The end card comes in with the last part, which holds `beats` (or `hold` seconds) longer for it, so the piece runs that much longer; a clip too short for that holds its last frame. The end card's first line is set large; the others are smaller. Text stays inside the area Reels and TikTok don't cover. The cards use Playfair Display and Roboto when they're installed or in `brand/` (`fonts: {display: ..., body: ...}` picks other files), otherwise Georgia and Helvetica. They need Pillow (`pip install pillow`).

## Voice and captions

A reading laid over the footage: pieces of one or more takes (audio files, or videos for their sound), each placed on the piece's clock, with the song kept low under it. Its lines can show as captions.

```yaml
voice:
  pieces:
    - {file: "takes/reading take 2.m4a", start: 0.5, end: 11.0, at: 0.5}   # start/end in the take, at = on the piece
    - file: "takes/reading take 4.m4a"
      start: 12.1
      end: 22.1
      at: 11.6
      fx:                # optional: phrases (in the take) through an effect
        - {start: 14.4, end: 16.6, effect: echo, amount: 1}   # echo | hall | waver | pulse | doubled; 0.6 / 1 / 1.4
  fit: true          # the last part holds until the voice ends (+0.8s), then the end card
  clean: true        # highpass and denoise; every piece is loudness-normalised either way
  song_under: 0.15   # the song's volume while the voice speaks
  song_between: 0.3  # ... and around it (replaces music_volume)

captions:
  style: stanza      # stanza | unfold | breath | page
  font: playfair     # playfair, playfair-italic, garamond-italic, cormorant-italic, courier, roboto, caveat
  background: band   # scrim | band | paper | blur | shadow
  size: 1            # 0.85 small, 1.18 large
  title: ""          # page: a small title over the words
  lines:             # on the piece's clock; stanza: true starts a new stanza
    - {start: 0.6, end: 2.6, text: "We push the cloves in, point up,", stanza: true}
    - start: 3.6
      end: 5.6
      text: "two knuckles deep in the cold bed."
      fx:              # optional: words 2-6 show an effect from 3.9s
        - {effect: echo, amount: 1, start: 3.9, end: 5.6, words: [2, 6]}
```

An effect plays its words in place of the plain voice: *echo* repeats them three times, fading; *hall* puts them in a big room that rings on after; *waver* makes the pitch tremble; *pulse* makes the voice throb; *doubled* adds two drifting voices just behind. An echo or hall carries on past its words, and `fit` waits for it.

A caption line's `fx` shows a voice effect on its words while it plays (copies under them, like CSS text-shadows): echo, three ghosts stepping down and away, one per repeat; hall, a warm glow that lingers; waver, a trembling copy; pulse, a throbbing glow; doubled, two copies drifting either side.

*stanza* shows the whole stanza with the line being said bright and the rest dim; *unfold* fades lines in as they're said, keeping them until the stanza ends; *breath* shows one line at a time, centred, drifting up as it comes in; *page* sets the lines left on a cream panel under the title. The fonts are the files in `brand/fonts/` (Footage Studio's preview uses the same ones). The captions go over the picture before the title and end card.

If a cut would run past the end of a clip, the script slides it earlier so it stays on the beat. The dry run tells you when that happens.

Output is 1080×1920 at 30fps (`width:` and `height:` change it, e.g. 1920 and 1080 for YouTube or 1080 and 1080 for a square; `focus: [0.5, 1]` then keeps the bottom of a 3:4 clip at full width). Photos should be JPG or PNG; convert HEIC files first.
