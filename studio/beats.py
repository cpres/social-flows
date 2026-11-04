"""The beat builder: AI music made to a reel's exact length, building up and
cooling down with an energy curve over the reel (see web/src/beat.js for the
levers, presets and the prompt).

A reel's `beat` setting holds what it was asked for:

    {from: {kind: song|scratch, name?, category?},
     curve: [[t 0..1, energy 0..1], ...], preset: follow|arc|slow|peaks|steady|custom,
     hits: bool (a fill, riser or drop on each scene change),
     end: bool (resolve on the last frame, else fade out),
     levers: {funky..earthy: 0..5}, vibe: the preset the levers came from,
     tempo: bpm or null (derived from the levers), key: "F major" or null (derived),
     prompt: the edited prompt, or null (built from the above)}
"""

LEVERS = ("funky", "happy", "chill", "upbeat", "grungy", "futuristic", "ecstatic", "drummy", "bass", "earthy")
PRESETS = ("follow", "arc", "slow", "peaks", "steady", "custom")
TEMPO_RANGE = (60, 180)


def _num(v, lo, hi, default):
    try:
        return min(max(float(v), lo), hi)
    except (TypeError, ValueError):
        return default


def clean(beat):
    """A reel's `beat` setting, kept in range (None if it isn't one)."""
    if not isinstance(beat, dict):
        return None
    src = beat.get("from") if isinstance(beat.get("from"), dict) else {}
    kind = "song" if src.get("kind") == "song" and src.get("name") else "scratch"
    out = {"from": {"kind": kind, **({"name": str(src["name"])[:300],
                                      "category": str(src.get("category") or "")[:60]} if kind == "song" else {})}}
    points = []
    for p in beat.get("curve") or []:
        if isinstance(p, (list, tuple)) and len(p) == 2:
            points.append([round(_num(p[0], 0, 1, 0), 4), round(_num(p[1], 0, 1, 0.5), 3)])
    points.sort(key=lambda p: p[0])
    if len(points) < 2:
        points = [[0, 0.5], [1, 0.5]]
    points[0][0], points[-1][0] = 0, 1
    out["curve"] = points[:40]
    out["preset"] = beat.get("preset") if beat.get("preset") in PRESETS else "custom"
    out["hits"] = bool(beat.get("hits", True))
    out["end"] = bool(beat.get("end", True))
    levers = beat.get("levers") if isinstance(beat.get("levers"), dict) else {}
    out["levers"] = {k: int(_num(levers.get(k), 0, 5, 0)) for k in LEVERS}
    out["vibe"] = str(beat.get("vibe") or "")[:40]
    tempo = beat.get("tempo")
    out["tempo"] = None if tempo in (None, "") else round(_num(tempo, *TEMPO_RANGE, 100))
    key = " ".join(str(beat.get("key") or "").split())[:20]
    out["key"] = key or None
    prompt = beat.get("prompt")
    out["prompt"] = str(prompt)[:4000] if isinstance(prompt, str) and prompt.strip() else None
    return out
