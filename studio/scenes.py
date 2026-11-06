"""A reel in lanes and scenes.

Lanes say what's playing: lane A is the main, continuous footage (one long
clip, or a few: the reel's `laneA`, a list of its parts' ids); lane B is the
reel's other kept parts, the cut list, one after another. Scenes say what's
visible, one after another (the reel's `scenes`):

    {id, layout: soloA | stack | soloB | swap,
     from: the first B part in it (B scenes),
     len: seconds (soloA: how long A plays alone),
     split: 0.5 | 0.58 | ... | "square" (the primary slot's share; square:
            the other slot is square),
     relay: true (a split after Solo B: A's slot is that shot carrying on,
            instead of lane A),
     into: cut | slide | push | dissolve | handoff | takeover (how it comes in;
           takeover, into Solo B after a split: B grows to the full frame
           as A slides out;
           handoff, after a Solo B scene: its last frame moves into A's
           slot as B comes in, stays `handoff` seconds, then dissolves
           into A, which starts then),
     fill: "" | fill | blur (a lane alone in a wide frame),
     a: {item, in, out (null: carry on / share what's left),
         timing: real | quiet | hold | fit, speed}}

A plays at real speed unless a speed is asked for: `real` takes as much of
its clip as the scene lasts (carrying on from the scene before, up to the
clip's end, then holding its last frame), `quiet` does the same skipping
lulls, `hold` plays at the speed picked, and only `fit` speeds it up or
slows it down to fit its range into the scene.

A B scene holds the kept B parts from its `from` up to the next B scene's;
its length is theirs. A soloA scene holds none (B waits). The same rules
are in web/src/scenes.js.
"""
import json
import uuid

LAYOUTS = ("soloA", "stack", "soloB", "swap")
INTOS = ("cut", "slide", "push", "dissolve", "handoff", "takeover")
HANDOFF_DEFAULT = 3.0   # seconds a Solo B scene's last frame stays in A's slot, handing off
TIMINGS = ("real", "quiet", "hold", "fit", "range")   # range: real, from before
SOLO_A_DEFAULT = 4.0   # seconds a new Solo A scene runs
SOLO_A_MIN = 1.0


def new_id():
    return uuid.uuid4().hex[:8]


def lane_a(s):
    """The ids of the parts in lane A, in order."""
    if s.get("laneA") is not None:
        return [int(i) for i in s["laneA"]]
    if s.get("format") == "stack" and s.get("topItemId"):
        return [int(s["topItemId"])]   # a Stack reel from before scenes: its top clip
    return []


def migrated(s, rows):
    """Scenes for a reel saved before scenes existed. Standard: one Solo B
    scene, lane A empty. Stack: its top clip is lane A; one A-over-B scene
    (or, from the first version of moving stacks, the top clip alone at the
    start, parts on their own, and the top clip alone after a part)."""
    a_ids = lane_a(s)
    kept = [r for r in rows if r["keep"] and not r["missing"] and r["id"] not in a_ids]
    if not a_ids:
        return [{"id": new_id(), "layout": "soloB", "from": kept[0]["id"] if kept else None, "into": "cut"}]
    if not s.get("fitTop", True) and abs(float(s.get("topSpeed") or 1) - 1) > 0.001:
        timing, speed = "hold", float(s.get("topSpeed"))   # a speed that was picked
    else:
        timing, speed = ("quiet" if s.get("fitTopBy") == "quiet" else "real"), 1.0
    split = float(s.get("stackSplit") or 0.5)

    def a(solo=False):
        return {"item": a_ids[0], "in": None, "out": None, "timing": "hold" if solo else timing,
                "speed": 1.0 if solo else speed}

    scenes = []
    if s.get("stackIntro"):
        scenes.append({"id": new_id(), "layout": "soloA", "len": float(s["stackIntro"]) * 0.5, "into": "cut", "a": a(True)})
    for r in kept:
        layout = "soloB" if r["pane"] == "solo" else "stack"
        if not scenes or scenes[-1]["layout"] == "soloA" or scenes[-1]["layout"] != layout:
            scenes.append({"id": new_id(), "layout": layout, "from": r["id"], "split": split,
                           "into": "slide" if scenes else "cut", **({"a": a()} if layout != "soloB" else {})})
        if r["top_after"]:
            scenes.append({"id": new_id(), "layout": "soloA", "len": float(r["top_after"]) * 0.5,
                           "into": "slide", "a": a(True)})
    return scenes or [{"id": new_id(), "layout": "stack", "from": None, "split": split, "into": "cut", "a": a()}]


def normalized(scenes, kept_ids, a_ids):
    """The scenes as they play: each B scene with its parts ([ids]), in
    order. Scenes that lost their parts (removed, skipped, out of order) or
    their A clip are dropped or become Solo B; parts before the first B
    scene join it."""
    out = []
    last = -1
    order = {pid: i for i, pid in enumerate(kept_ids)}
    for sc in scenes or []:
        sc = dict(sc)
        if sc.get("layout") not in LAYOUTS:
            continue
        if sc["layout"] != "soloB":
            a = dict(sc.get("a") or {})
            if not a_ids:
                if sc["layout"] == "soloA":
                    continue
                if not sc.get("relay"):   # a relay's A slot is the shot before, not lane A
                    sc["layout"] = "soloB"
            else:
                if a.get("item") not in a_ids:
                    a["item"] = a_ids[0]
                sc["a"] = a
        if sc["layout"] == "soloA":
            sc["parts"] = []
            out.append(sc)
            continue
        at = order.get(sc.get("from"))
        if not any(o["layout"] != "soloA" for o in out):
            at = 0 if kept_ids else None   # the first B scene starts with the first part
        if at is None or at <= last:
            continue
        sc["_at"] = at
        last = at
        out.append(sc)
    bs = [sc for sc in out if sc["layout"] != "soloA"]
    for i, sc in enumerate(bs):
        end = bs[i + 1]["_at"] if i + 1 < len(bs) else len(kept_ids)
        sc["parts"] = kept_ids[sc.pop("_at"):end]
        sc["from"] = sc["parts"][0]
    if kept_ids and not bs:
        out.append({"id": new_id(), "layout": "soloB", "from": kept_ids[0], "parts": list(kept_ids), "into": "cut"})
    return [sc for sc in out if sc["layout"] == "soloA" or sc["parts"]]


def slot_shape(scene, lane):
    """Which framing a lane uses in a scene: full (alone), square (the
    square slot of a square split) or half (any other split slot)."""
    if scene["layout"] in ("soloA", "soloB"):
        return "full"
    secondary = "B" if scene["layout"] == "stack" else "A"
    return "square" if scene.get("split") == "square" and lane == secondary else "half"


def frame_for(row, shape, lane):
    """A part's framing (focus x, y, zoom) in a slot shape. The full frame
    is the part's own framing; a half or square slot remembers its own, and
    until it's framed there shows the bottom of the shot (in glasses
    footage, where the hands are). A part from before slots that was framed
    keeps that framing everywhere."""
    legacy = (row["focus_x"], row["focus_y"], row["zoom"] or 1)
    if shape == "full":
        return legacy
    if row["frames"] is None and (legacy[0], legacy[1], legacy[2]) != (0.5, 0.5, 1):
        return legacy
    try:
        f = json.loads(row["frames"] or "{}").get(shape)
    except ValueError:
        f = None
    if f:
        return (float(f.get("x", 0.5)), float(f.get("y", 0.5)), float(f.get("zoom", 1) or 1))
    return (legacy[0], 1.0, 1.0)


def band_of(row):
    """Which band of a part's full frame a half slot shows when the part
    moves into one (or grows out of one): its half framing, x and y."""
    fx, fy, _ = frame_for(row, "half", "B")
    return [round(fx, 3), round(fy, 3)]


def clean(scenes, s):
    """Keep a reel's scenes in range."""
    out = []
    for sc in scenes if isinstance(scenes, list) else []:
        if not isinstance(sc, dict) or sc.get("layout") not in LAYOUTS:
            continue
        c = {"id": str(sc.get("id") or new_id())[:16], "layout": sc["layout"],
             "into": sc.get("into") if sc.get("into") in INTOS else "cut"}
        if sc.get("from") is not None:
            c["from"] = int(sc["from"])
        if sc["layout"] == "soloA":
            c["len"] = round(max(float(sc.get("len") or SOLO_A_DEFAULT), SOLO_A_MIN), 3)
        split = sc.get("split", s.get("stackSplit") or 0.5)
        c["split"] = "square" if split == "square" else round(min(max(float(split or 0.5), 0.3), 0.7), 3)
        if c["into"] == "handoff":
            c["handoff"] = round(min(max(float(sc.get("handoff") or HANDOFF_DEFAULT), 0.5), 10.0), 2)
        if sc.get("relay") and sc["layout"] in ("stack", "swap"):
            c["relay"] = True
        if sc.get("fill") in ("fill", "blur"):
            c["fill"] = sc["fill"]
        a = sc.get("a")
        if isinstance(a, dict):
            c["a"] = {"item": int(a["item"]) if a.get("item") is not None else None,
                      "in": None if a.get("in") is None else round(float(a["in"]), 3),
                      "out": None if a.get("out") is None else round(float(a["out"]), 3),
                      "timing": {"range": "real"}.get(a.get("timing"), a.get("timing")) if a.get("timing") in TIMINGS else "real",
                      "speed": round(min(max(float(a.get("speed") or 1), 0.25), 16.0), 3)}
        out.append(c)
    return out


LONG_CLIP = 10.0   # a relay plays videos this long or longer in full (or up to its cap)


RELAY_MIX = {"single": None, "even": 0.5, "split": 0.8}   # about how much of the reel is split
ALONE_MIN = 1.0   # every clip is alone at least this long


def relay_overlaps(clips, overlap, solo, cap, mix):
    """How long each pair of neighbours shares the frame (the split between
    clip i and i+1). Mostly single: `overlap` each. Even or mostly split:
    about that share of the reel is split. A long clip gives q = 2f/(1+f)
    of its time to splits (a split shows two clips at once), shared between
    its sides, and keeps at least ALONE_MIN alone; a photo stays up as long
    as the splits beside it need; a short video as long as its footage
    lasts. Also returns each clip's time alone."""
    f = RELAY_MIX.get(mix)
    n = len(clips)
    if f is None:
        return [overlap] * max(n - 1, 0), [None] * n
    q = 2 * f / (1 + f)
    times = [relay_time(c, solo, cap) for c in clips]
    sides = [(i > 0) + (i < n - 1) for i in range(n)]
    want = [q * times[i] / sides[i] if clips[i]["long"] and sides[i] else None for i in range(n)]
    out = []
    for i in range(n - 1):
        w = [x for x in (want[i], want[i + 1]) if x is not None]
        out.append(sum(w) / len(w) if w else q * solo)
    short_alone = max(ALONE_MIN, solo * (1 - q))
    for _ in range(3):   # keep each clip's time alone, and short videos within their footage
        for i, c in enumerate(clips):
            left = out[i - 1] if i else 0
            right = out[i] if i < n - 1 else 0
            if c["long"]:
                room = times[i] - ALONE_MIN
            elif c["row"]["kind"] == "video":
                room = max(c["row"]["duration"] - short_alone, 1.0)
            else:
                continue
            if left + right > room:
                k = max(room, 1.0) / (left + right)
                if i:
                    out[i - 1] *= k
                if i < n - 1:
                    out[i] *= k
    out = [round(max(o, 0.5), 3) for o in out]
    # A long clip's time alone is held to the mix: at most (1-f)/f of its time
    # split. The first and last share with only one neighbour, so this is
    # what keeps them split too; such a clip plays less of itself (it ends
    # sooner, no jump).
    alone = []
    for i, c in enumerate(clips):
        if c["long"]:
            split = (out[i - 1] if i else 0) + (out[i] if i < n - 1 else 0)
            alone.append(max(ALONE_MIN, min(times[i] - split, split * (1 - f) / f)))
        else:
            alone.append(short_alone)
    return out, alone


def relay_time(c, solo, cap):
    """A long clip's own time on screen in a relay: its length, to its cap."""
    if c["long"]:
        return c["avail"] if cap is None else min(c["avail"], cap)
    return solo


def relay_plan(clips, overlap=3.0, solo=4.0, cap=None, quiet=None, mix="single"):
    """A relay reel from clips in order: each plays alone, then moves into
    A's slot and carries on while the next comes in underneath, which then
    takes over the full frame.

    clips: [{row, start, avail, long}]: where each starts and how much of it
    there is to play from there. A long clip (a video of LONG_CLIP seconds or
    more) gets its own length: all of `avail` (up to `cap`), less what it
    plays underneath the clip before and carries on over the next. mix sets
    how much is split: single (photos and short clips alone for `solo`, an
    `overlap` between clips), even (about half of each clip's time split) or
    split (mostly split, short moments alone). quiet(row, start, length),
    when given, splits a long clip's time alone into pieces with its lulls
    taken out.

    Returns ([(row, start, length, kind)]: the parts: under (beneath the
    clip before), alone, and more (the rest of a quiet-cut stretch alone)),
    and a function making the scenes from their new ids."""
    parts = []
    n = len(clips)
    shared, alones = relay_overlaps(clips, overlap, solo, cap, mix)
    for i, c in enumerate(clips):
        r, start = c["row"], float(c["start"])
        under = shared[i - 1] if i else 0.0
        after = shared[i] if i + 1 < n else 0.0
        if alones[i] is not None:
            alone = alones[i]
        elif c["long"]:
            alone = max(solo, relay_time(c, solo, cap) - under - after)
        else:
            alone = solo
        if not c["long"] and r["kind"] == "video":   # room for all of it before the clip ends, if it can
            start = min(start, max(0.0, r["duration"] - under - alone - after))
        if i:
            parts.append((r, round(start, 3), under, "under"))
            start += under
        pieces = quiet(r, start, alone) if quiet and c["long"] else [(start, alone)]
        for j, (ps, pl) in enumerate(pieces):
            parts.append((r, round(ps, 3), round(pl, 3), "alone" if j == 0 else "more"))

    def scenes(ids):
        out = []
        for (r, _, _, kind), pid in zip(parts, ids):
            if kind == "more":
                continue   # more of the same clip alone, in the same scene
            if kind == "alone":
                out.append({"id": new_id(), "layout": "soloB", "from": pid,
                            "into": "takeover" if out else "cut"})
            else:
                out.append({"id": new_id(), "layout": "stack", "from": pid, "split": 0.5,
                            "relay": True, "into": "handoff"})
        return out
    return parts, scenes
