# Claude Code brief: Garden Steward montage tool

## What exists already

This folder contains a working command-line montage builder:

- `montage.py` — the engine. Tested and working, except where noted below.
- `montage.yaml` — config for the "interleaved rounds" style.
- `daylog.yaml` — config for the "day in the life" style.
- `README.md` — setup and tuning notes.

**Tested:** cut planning, beat sync via librosa, transitions, audio mixing,
the three framing modes, photo push-in, dry-run output, full renders.

**Untested — written but never executed:** the `folder:` source expansion in
`expand_folders()`, the `soft_every` transition rule, and the
`videotoolbox` encoder path. Verify these before trusting them.

Setup: `brew install ffmpeg`, `pip install pyyaml librosa`.

## What I want to build

A local tool — service plus simple UI — that replaces hand-editing YAML.
The engine stays; this is a front end for **choosing moments**.

The problem it solves: I shoot a lot of footage on smart glasses. Individual
files run several minutes. I may shoot four takes of the same action and
want only the best one. Deciding what to keep, and *where inside each clip*
to cut, is currently blind guesswork in a text file.

### Core interaction

For each source clip:

1. A **filmstrip of thumbnails** extracted along the clip's length, so I can
   see what happens where without scrubbing in a player. Roughly one frame
   every 15–30 seconds of footage, tuned so a long clip still fits on screen.
   Extract once, cache to disk, keyed on file path plus mtime.
2. A **scrubber with draggable start and end handles** over that filmstrip.
   Dragging updates a preview frame live. The filmstrip is the visual helper:
   if the point I picked turns out to be dull, I can see a better one nearby.
3. A **keep / skip toggle** per clip, so rejected takes stay on disk but out
   of the cut.
4. Clips listed in the order they were shot (there is already a
   `capture_time()` helper that reads creation time with an mtime fallback).

### Output

The tool writes the config the engine already reads. Round-trip, not
one-way: I should be able to open a previous session, see my selections as
I left them, adjust, and re-render. Selections live in a sidecar file, not
in my head.

A **render button** that shells out to `montage.py` and shows progress and
the dry-run cut list before committing.

## Things to decide together before writing code

- **Shape.** Local web app (FastAPI plus a small front end) versus native
  versus a TUI. I want something I can run on a MacBook Pro with one
  command. Argue for a choice rather than offering a menu.
- **State.** Does the sidecar file replace `daylog.yaml`, or generate it?
  I'd lean toward generate, so the engine stays independently runnable.
- **Preview.** Frame-accurate seeking versus cheap thumbnail scrubbing.
  Probably start cheap.
- **Scope discipline.** This is a personal tool, not a product. No accounts,
  no cloud, no database if a JSON file will do.

## Context on the design decisions in the engine

- **Two styles.** "Rounds" interleaves a few clips so several actions appear
  to progress in parallel — the viewer watches three things at once rather
  than one thing end to end. "Daylog" is one cut per clip, many clips, in
  shooting order — a snapshot of a day.
- **Beat sync.** Cuts land on detected beats so the montage feels intentional
  rather than arbitrary. `beats_per_cut` is the pace dial.
- **Ambient audio bed.** The glasses audio stays under the music at low
  volume. It keeps the footage feeling like a real place rather than a
  stock-music reel.
- **No captions.** Deliberate, for now. Sound and cutting first.
- **Vertical 1080x1920** output for social.
- Brand palette, if any chrome needs colouring: sage `#8aa37c`, forest
  `#344a34`, cream `#f7f1e3`.

## How I like to work

Talk through the plan with me before building. Push back if a piece of this
is a bad idea or if there is a materially simpler path — I would rather be
argued with than agreed with. Take your best shot at decisions rather than
asking me a list of clarifying questions, and state the assumptions you made.
