"""Relay v2: auto-stitching. A pure planner, no database, UI or ffmpeg.

    plan_relay(items, opts) -> {lanes, scenes, timeline, stats}

The one rule: when one of the two items on screen runs out of time, it
leaves and the other takes the full frame. Videos can hold the screen a long
time; photos can't, so a photo always runs out first.

Every input (in shot order) is one of:

    LONG   a video of LONG_THRESHOLD seconds or more: plays its stretch (to
           the long-clip cap, quiet moments out); can host cameos
    SHORT  a shorter video: plays its own part's length
    PHOTO  a still: on screen for photo_seconds in all, full frame and
           split together

Two ways in, both a newcomer coming in under the item playing:

    handoff  near X's end, Y comes in underneath for o seconds; X ends and Y
             takes the full frame
    cameo    a PHOTO or SHORT guest comes in under a LONG host, spends its
             whole life there, and goes; the host grows back to full

items: [{kind: "video" | "photo", duration (the file's), start (where its
part starts), length (its part), avail (a long clip's stretch from start,
before the cap), shot_at (seconds, the file's capture time; a video's is
when it started), keep (optional, a long clip's stretch with its quiet
moments out: [(start, length)] in the file, already within the cap),
clip (optional: stretches of one clip share it; they hand on to each other
like any two long clips, the later moment coming in under the earlier, so
the split skips ahead in the clip), match (optional, (from, to) file seconds: the
moments a stretch claims for photos shot while its clip recorded), hold
(optional, a photo's own time on screen instead of photo_seconds)}].
A capped long clip is several items, one per stretch (see stretches).

opts: {dial: 1..10, photo_seconds, cap (seconds or None)}.

Returns
    lanes     {"A": [], "B": [{item, start, length}]}: the parts, in order.
              A relay has no lane A: its top slot is the shot from the
              scene before carrying on (scenes.py `relay`).
    scenes    [{layout: soloB | stack, into, parts: [indices into lanes.B],
                relay?, grow?}] on the reel's scene model: a stack is a
              relay (the item that was on screen first carries on on top,
              the newcomer is below); a Solo B after one is a take over,
              by the newcomer (grow absent) or back to the host on top
              (grow: "A", the end of a cameo).
    timeline  [{at, len, top, bottom}]: who's on screen when (item
              indices; bottom None: top alone, full frame).
    stats     {totalSeconds, splitSeconds, splitPct, longCount, shortCount,
               photoCount, cameoCount, limitedBy: "photos" | None}

The same inputs always give the same plan.
"""
import math

# ---------------------------------------------------------------- constants (tune here)

# Nothing on screen for less than 3s: shorter is frantic. A full-frame moment,
# a split, a host alone between cameos: each at least this long, or not at all.
MIN_SCENE = 3.0        # no scene shorter
MIN_SOLO = 3.0         # a host's full-frame time before, between and after cameos
MIN_OVERLAP = 3.0      # a split shorter than this is a straight cut instead
TRANSITION = 0.4       # the slide in / out (the engine draws its own moves)
LONG_THRESHOLD = 10.0  # a video this long or longer is LONG
CAMEO_GAP = (6.0, 1.5)  # host alone between cameos: lerp(dial 1, dial 10)
PHOTO_SECONDS = 4.0    # default photo life
DIAL_DEFAULT = 5
DIAL_MIN, DIAL_MAX = 1, 10

# From which dial each pairing is allowed.
PAIR_LONG_LONG = 2
PAIR_LONG_GUEST = 3    # a long clip with a photo or short clip (cameo or handoff)
PAIR_SHORTS = 5        # short + short, short + photo
PAIR_PHOTOS = 7        # photo + photo
CAMEO_MATCH = 3        # photos shot while a long clip was recording, at that moment
CAMEO_LOOK_AHEAD = 6   # the photos after a long clip pulled into its spare time
HANDOFF_ROOM = 6.0     # cameos keep this far (at dial 10; 1s at 2) from a host's ends next to a long clip

MIX_TO_DIAL = {"single": 3, "even": 5, "split": 8}   # the old Single or split choice

# A long clip with a cap ("Up to 20s") plays as several stretches of up to the
# cap, spread evenly through it: at most `most` of them (MOST_DEFAULT), all of
# them for a clip of FULL_AT seconds or more and fewer for a shorter one, so
# no clip takes over the reel. Each sits in the middle of its share of the
# clip, with at least BREATH left at each end (its fumbly start and end).
BREATH = 2.0
MOST_DEFAULT = 4
MOST_MAX = 12
FULL_AT = 120.0
MIN_STRETCH = 4.0   # shortest stretch a target length can ask of a long clip

LONG, SHORT, PHOTO = "LONG", "SHORT", "PHOTO"


def lerp(a, b, t):
    return a + (b - a) * t


def dial_of(value, mix=None):
    """A dial setting from what was asked (or an old mix), 1..10."""
    if value is None and mix in MIX_TO_DIAL:
        return MIX_TO_DIAL[mix]
    try:
        return int(min(max(round(float(value)), DIAL_MIN), DIAL_MAX))
    except (TypeError, ValueError):
        return DIAL_DEFAULT


def stretch_count(length, most=MOST_DEFAULT):
    """How many stretches a clip this long gets: `most` from FULL_AT seconds
    (two minutes) up, fewer in proportion below (a minute: half), at least one."""
    most = max(1, int(most or MOST_DEFAULT))
    return max(1, min(most, round(most * length / FULL_AT)))


def stretches(start, length, cap=None, breath=BREATH, most=MOST_DEFAULT):
    """The stretches of a long clip a relay plays: [(start, length)] in the
    file. With a cap: stretch_count of them (as many as fit) of up to `cap`
    seconds, the clip less `breath` at each end shared out evenly, each in
    the middle of its share. Without one: all of it, less `breath` at each
    end. Never less than half of what's there."""
    inner = max(length - 2 * breath, length / 2)
    pad = (length - inner) / 2
    if not cap or inner <= cap:
        one = min(inner, cap or inner)
        return [(round(start + (length - one) / 2, 3), round(one, 3))]
    n = max(1, min(stretch_count(length, most), int(inner // cap)))
    share = inner / n
    return [(round(start + pad + i * share + (share - cap) / 2, 3), round(float(cap), 3)) for i in range(n)]


# ---------------------------------------------------------------- highlights
# Moments marked on a clip in its shoot (or, until any are, ones suggested
# from how much moves). With a cap, a long clip's stretches sit on them
# instead of being spread evenly: each stretch centred on one.

AMOUNT_MOST = {-1: 0.5, 0: 1.0, 1: 2.0}   # Less / Normal / More of a clip: its share of stretches
SUGGEST_EVERY = 30.0   # a suggested moment per 30s of clip…
SUGGEST_RANGE = (2, 5)  # …between 2 and 5 (Less: one fewer, More: two more)
STILL = 0.05           # a share of the clip moving less than this: no peak, its middle


def most_for(most, amount=0):
    """Stretches a clip may have, given how much of it is wanted."""
    return int(min(max(round(max(1, int(most or MOST_DEFAULT)) * AMOUNT_MOST.get(amount, 1.0)), 1), MOST_MAX))


def suggest_count(duration, amount=0):
    """How many moments to suggest in a clip this long."""
    lo, hi = SUGGEST_RANGE
    n = min(max(round(duration / SUGGEST_EVERY), lo), hi)
    return max(1, n - 1) if amount < 0 else n + 2 if amount > 0 else n


def suggest_moments(points, duration, n, breath=BREATH):
    """n moments worth showing: the clip less `breath` at each end in n equal
    shares, the busiest point of each (points: [(seconds, 0..1)], movement),
    or its middle where nothing much moves. Seconds, in order."""
    lo, hi = min(breath, duration / 4), max(min(breath, duration / 4), duration - breath)
    share = (hi - lo) / max(1, n)
    out = []
    for k in range(max(1, n)):
        a, b = lo + k * share, lo + (k + 1) * share
        inside = [(t, v) for t, v in points or [] if a <= t <= b]
        best = max(inside, key=lambda p: p[1], default=None)
        out.append(round(best[0] if best and best[1] > STILL else (a + b) / 2, 2))
    return out


AROUND_DEFAULT = 10.0   # seconds of a long clip played around each highlight
# A highlight moment comes in under the one before it for longer: each may
# give up to this share of itself to the handoff after it (others: half),
# and the dial leans further toward that (dial 5 is two thirds of the way).
PINNED_SHARE = 0.75
PINNED_LEAN = 0.5   # the dial's share s becomes s ** PINNED_LEAN for these


def pinned_stretches(start, length, pins, cap, most=MOST_DEFAULT, around=AROUND_DEFAULT, every=False):
    """A long clip with highlights (pins, file seconds, within
    start..start+length) plays only the moments around them, never all of
    itself: a stretch `around` seconds long (shorter if the cap is, or the
    clip) centred on each pin as far as the clip allows. every: all of the
    pins (ones marked by hand); else (suggested ones) as many as
    stretch_count allows, the pin nearest where each evenly spread stretch
    would sit (one stretch: the pin nearest the middle). Stretches that would
    overlap become one, so nothing plays twice. [(start, length)] in file
    order, or None with no pins."""
    pins = sorted(t for t in pins if start <= t <= start + length)
    if not pins:
        return None
    one = min(float(around or AROUND_DEFAULT), float(cap) if cap else math.inf, length)
    n = len(pins) if every else min(len(pins), max(1, stretch_count(length, most)))
    if n >= len(pins):
        chosen = pins
    else:
        targets = [s + ln / 2 for s, ln in stretches(start, length, one, most=n)]
        if len(targets) < n:   # stretches() fits fewer: spread the rest evenly
            targets = [start + length * (k + 0.5) / n for k in range(n)]
        left, chosen = list(pins), []
        for c in targets[:n]:
            best = min(left, key=lambda t: abs(t - c))
            chosen.append(best)
            left.remove(best)
        chosen.sort()
    end = start + length
    wins = [[min(max(t - one / 2, start), end - one)] for t in chosen]
    for w in wins:
        w.append(w[0] + one)
    merged = []
    for a, b in wins:
        if merged and a < merged[-1][1] - 0.01:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(round(a, 3), round(b - a, 3)) for a, b in merged]


def fit_target(make_items, opts, target, longest):
    """The stretch length (cap) whose reel comes out closest to `target`
    seconds: make_items(cap) -> the items with long clips in stretches of
    that (None: their full length). Tries whole and half seconds from
    MIN_STRETCH up to the longest clip, coarsely then finely, since a
    longer stretch can mean fewer of them. If even the full length is
    under the target, that's it; if the shortest is still over (lots of
    photos, say), that. -> (items, plan, cap)."""
    seen = {}

    def run(cap):
        cap = None if cap is None else round(cap * 2) / 2
        if cap not in seen:
            items = make_items(cap)
            seen[cap] = (items, plan_relay(items, {**opts, "cap": cap}), cap)
        return seen[cap]

    total = lambda r: r[1]["stats"]["totalSeconds"]   # noqa: E731
    full = run(None)
    if total(full) <= target or longest <= MIN_STRETCH:
        return full
    steps = 24
    grid = [run(MIN_STRETCH * (longest / MIN_STRETCH) ** (k / (steps - 1))) for k in range(steps)]
    # refine around where it crosses the target
    for a, b in zip(grid, grid[1:]):
        if (total(a) - target) * (total(b) - target) <= 0:
            lo, hi = a[2], b[2]
            for _ in range(8):
                if hi - lo <= 0.5:
                    break
                mid = run((lo + hi) / 2)
                if (total(mid) - target) * (total(a) - target) > 0:
                    lo = mid[2]
                else:
                    hi = mid[2]
    return min(seen.values(), key=lambda r: (abs(total(r) - target), total(r)))


def allowed(a, b, dial):
    """Whether two kinds of item may share the frame at this dial."""
    kinds = {a, b}
    if kinds == {LONG}:
        return dial >= PAIR_LONG_LONG
    if LONG in kinds:
        return dial >= PAIR_LONG_GUEST
    if kinds == {PHOTO}:
        return dial >= PAIR_PHOTOS
    return dial >= PAIR_SHORTS


# ---------------------------------------------------------------- items

class Entry:
    """One input item as the planner sees it."""

    def __init__(self, idx, it, opts):
        self.idx = idx
        self.pinned = bool(it.get("pinned"))   # a moment around a highlight (pinned_stretches)
        self.shot_at = float(it.get("shot_at") or 0)
        photo_s = float(opts.get("photo_seconds") or PHOTO_SECONDS)
        cap = opts.get("cap") or None
        if it.get("kind") == "photo":
            self.kind = PHOTO
            life = float(it.get("hold") or photo_s)   # its own, once it's been trimmed in the reel
            self.ranges = [(0.0, life)]
            self.split_tol = life
        elif float(it.get("duration") or 0) >= LONG_THRESHOLD:
            self.kind = LONG
            start = float(it.get("start") or 0)
            window = float(it.get("avail") if it.get("avail") is not None else it.get("duration") or 0)
            if cap:
                window = min(window, float(cap))
            keep = [(float(s), float(l)) for s, l in (it.get("keep") or [])]
            keep = [(max(s, start), min(s + l, start + window) - max(s, start)) for s, l in keep]
            keep = [(s, l) for s, l in keep if l > 0.04]
            self.ranges = keep or [(start, window)]
            self.split_tol = math.inf
        else:
            self.kind = SHORT
            self.ranges = [(float(it.get("start") or 0), float(it.get("length") or it.get("duration") or 0))]
            self.split_tol = self.ranges[0][1]
        self.life = sum(l for _, l in self.ranges)
        self.file_start = self.shot_at   # second 0 of the file, in shot time
        # What a long clip claims of its file for photos shot while it was
        # recording (a stretch of one: its share, up to halfway to the next).
        match = it.get("match") or (0.0, float(it.get("duration") or 0) if self.kind != PHOTO else 0.0)
        self.match_from, self.shot_end = self.shot_at + float(match[0]), self.shot_at + float(match[1])
        self.clip = it.get("clip")       # stretches of the same clip share this
        self.cameos = []                 # [(guest Entry, start, end)] in the host's play time
        self.in_o = 0.0                  # under the item before
        self.out_o = 0.0                 # on top of the item after
        self.failed = False              # a match that didn't fit

    def play_at(self, src):
        """Where in this clip's play time its file's second `src` comes:
        the nearest kept moment when that one was cut."""
        p, best, best_d = 0.0, 0.0, math.inf
        for s, l in self.ranges:
            if s <= src <= s + l:
                return p + (src - s)
            for edge, at in ((s, p), (s + l, p + l)):
                if abs(src - edge) < best_d:
                    best, best_d = at, abs(src - edge)
            p += l
        return best


# ---------------------------------------------------------------- cameos

def place_matched(host, guest, at, gap):
    """Put a guest in its host at play time `at` (or as soon after as the
    spacing allows). False if it doesn't fit."""
    first = not host.cameos
    start = max(at, host.head if first else host.cameos[-1][2] + gap)
    if start + guest.life > host.life - host.tail + 1e-9:
        return False
    host.cameos.append((guest, start, start + guest.life))
    return True


def place_look_ahead(host, cands, s, gap):
    """Pull the items after a host into its back half, evenly, in order.
    Returns those placed."""
    if not cands:
        return []
    guest_life = sum(c.life for c in cands) / len(cands)
    max_guests = math.floor(s * host.life / (guest_life + gap)) - len(host.cameos)
    lo = max(host.life / 2, host.cameos[-1][2] + gap if host.cameos else host.head)
    hi = host.life - host.tail
    for k in range(min(max_guests, len(cands)), 0, -1):
        lives = [c.life for c in cands[:k]]
        space = (hi - lo - sum(lives)) / (k + 1)
        if space >= gap - 1e-9:
            t = lo + space
            for c in cands[:k]:
                host.cameos.append((c, t, t + c.life))
                t += c.life + space
            return cands[:k]
    return []


def plan_cameos(entries, dial, s):
    """Attach guests to long hosts. Returns the set of guest indices."""
    gap = max(lerp(*CAMEO_GAP, s), MIN_SOLO)
    guests = set()
    hosts = [e for e in entries if e.kind == LONG]
    # Room at a host's ends for handing on with a long clip beside it (its
    # own next stretch, often): cameos keep out of it.
    room = lerp(MIN_OVERLAP, HANDOFF_ROOM, s) if dial >= PAIR_LONG_LONG else 0.0
    for h in hosts:
        before = entries[h.idx - 1] if h.idx else None
        after = entries[h.idx + 1] if h.idx + 1 < len(entries) else None
        h.head = MIN_SOLO + (room if before is not None and before.kind == LONG else 0.0)
        h.tail = MIN_SOLO + (room if after is not None and after.kind == LONG else 0.0)
    can_guest = lambda e: e.kind in (PHOTO, SHORT) and e.life >= MIN_SCENE   # noqa: E731
    if dial >= CAMEO_MATCH and hosts:
        last_host = -1
        for g in entries:
            if not can_guest(g):
                continue
            covering = [h for h in hosts if h.match_from <= g.shot_at <= h.shot_end and h.idx >= last_host]
            if not covering:
                continue
            h = max(covering, key=lambda h: (h.shot_at, h.idx))   # the clip that started last
            if place_matched(h, g, h.play_at(g.shot_at - h.file_start), gap):
                guests.add(g.idx)
                last_host = h.idx
            else:
                g.failed = True
    if dial >= CAMEO_LOOK_AHEAD:
        for h in hosts:
            cands = []
            for e in entries[h.idx + 1:]:
                if e.kind == LONG:
                    break
                if e.idx in guests:
                    continue
                if not can_guest(e) or e.failed:
                    break
                cands.append(e)
            for c in place_look_ahead(h, cands, s, gap):
                guests.add(c.idx)
    # Guests keep their order: any that would show before one shot earlier go back.
    order = sorted(((h.idx, st, g) for h in hosts for g, st, _ in h.cameos), key=lambda x: (x[0], x[1]))
    last = None
    for hidx, st, g in order:
        if last is not None and (g.shot_at, g.idx) < last:
            entries[hidx].cameos = [c for c in entries[hidx].cameos if c[0] is not g]
            guests.discard(g.idx)
            continue
        last = (g.shot_at, g.idx)
    return guests


# ---------------------------------------------------------------- the plan

def plan_relay(items, opts=None):
    """The plan (see the top of this file). The dial is a preference: at
    the edges, a pairing turning on can squeeze a neighbour's split by more
    than it adds, so a setting that would split less than the one below it
    keeps that one's plan instead. Turning the dial up never splits less."""
    opts = dict(opts or {})
    dial = dial_of(opts.get("dial", DIAL_DEFAULT))
    best = None
    for d in range(DIAL_MIN, dial + 1):
        plan = _plan(items, opts, d)
        if best is None or plan["stats"]["splitSeconds"] / max(plan["stats"]["totalSeconds"], 1e-9) >= \
                best["stats"]["splitSeconds"] / max(best["stats"]["totalSeconds"], 1e-9) - 1e-9:
            best = plan
    best["stats"]["dial"] = dial
    return best


def _plan(items, opts, dial):
    s = (dial - 1) / 9
    entries = [Entry(i, it, opts) for i, it in enumerate(items)]

    # 1. cameos
    guests = plan_cameos(entries, dial, s)

    # 2. sequence: the handoff overlap between each top-level pair
    top = [e for e in entries if e.idx not in guests]
    for j in range(len(top) - 1):
        x, y = top[j], top[j + 1]
        if not allowed(x.kind, y.kind, dial):
            continue
        if x.cameos:
            x_room = x.life - x.cameos[-1][2] - MIN_SOLO
        else:
            x_room = x.life - x.in_o - MIN_SCENE
        moments = x.pinned or y.pinned   # highlights handing on: split for longer
        share = PINNED_SHARE if moments else 0.5
        if y.cameos:
            y_room = y.cameos[0][1] - MIN_SOLO
        else:
            y_room = y.life - MIN_SCENE
            if j + 2 < len(top) and y_room * share >= MIN_OVERLAP:
                y_room *= share   # leave it room to hand on to the next (whatever the dial, so turning it up never squeezes this one)
        max_o = min(x.split_tol, y.split_tol, x_room, y_room)
        lean = s ** PINNED_LEAN if moments else s
        o = lerp(MIN_OVERLAP, max_o, lean) if max_o >= MIN_OVERLAP else 0.0
        if o >= MIN_OVERLAP - 1e-9:
            x.out_o = y.in_o = round(o, 3)

    # 3 and 4. who's on screen when, then the parts and scenes
    timeline = []   # [at, len, top, bottom]
    t = 0.0
    for j, y in enumerate(top):
        x = top[j - 1] if j else None
        if y.in_o:
            timeline.append([t, y.in_o, x, y])
        p = y.in_o
        for g, st, en in y.cameos:
            timeline.append([t + p, st - p, y, None])
            timeline.append([t + st, en - st, y, g])
            p = en
        end_solo = y.life - y.out_o
        timeline.append([t + p, end_solo - p, y, None])
        t += end_solo   # its out-overlap is the next item's in-overlap
    timeline = [seg for seg in timeline if seg[1] > 1e-6]

    lanes_b, scenes = emit(timeline)
    out_timeline = [{"at": round(a, 3), "len": round(l, 3), "top": tp.idx, "bottom": b.idx if b else None}
                    for a, l, tp, b in timeline]
    total = sum(seg["len"] for seg in out_timeline)
    split = sum(seg["len"] for seg in out_timeline if seg["bottom"] is not None)
    kinds = [e.kind for e in entries]
    split_pct = round(100 * split / total) if total else 0
    photos = kinds.count(PHOTO)
    # mostly photos, and split well under what the dial asked for
    limited = photos * 2 > len(entries) and dial > 1 and split_pct < 100 * s - 15
    stats = {"totalSeconds": round(total, 3), "splitSeconds": round(split, 3), "splitPct": split_pct,
             "longCount": len({e.clip if e.clip is not None else ("i", e.idx) for e in entries if e.kind == LONG}),
             "longPieces": kinds.count(LONG), "shortCount": kinds.count(SHORT), "photoCount": photos,
             "cameoCount": len(guests), "limitedBy": "photos" if limited else None, "dial": dial, "planDial": dial,
             # items that can't be on screen for MIN_SCENE however it's planned (a 1.7s clip)
             "tooShort": [e.idx for e in entries if e.life < MIN_SCENE - 1e-9]}
    return {"lanes": {"A": [], "B": lanes_b}, "scenes": scenes, "timeline": out_timeline, "stats": stats}


def emit(timeline):
    """Parts and scenes from who's on screen when. Each item plays on from
    where it was: the bottom slot and full frame are its parts (lane B, in
    its kept stretches); on top it's the shot before carrying on, straight
    through its file (so a cameo over a cut quiet moment just shows it, and
    the clip ends that much earlier in its stretch)."""
    cursor = {}   # entry idx -> (range index, seconds into it) for kept walks; or a file second
    parts, scenes = [], []

    def take(e, seconds):
        """Seconds of e's kept stretches from where it is: [(start, length)]."""
        ri, src = cursor.get(e.idx, (0, e.ranges[0][0]))
        out = []
        need = seconds
        while need > 1e-6 and ri < len(e.ranges):
            s, l = e.ranges[ri]
            src = max(src, s)
            room = s + l - src
            if room <= 1e-6:
                ri += 1
                continue
            got = min(room, need)
            out.append((src, got))
            src += got
            need -= got
        if need > 1e-6:   # ran out (it never should): hold where it is
            out.append((src, need))
        cursor[e.idx] = (ri, src)
        return out

    def carry(e, seconds):
        ri, src = cursor.get(e.idx, (0, e.ranges[0][0]))
        if e.kind != PHOTO:
            src += seconds
        while ri < len(e.ranges) and src >= e.ranges[ri][0] + e.ranges[ri][1] - 1e-6:
            ri += 1
        cursor[e.idx] = (ri, src)

    def add_parts(e, seconds):
        ids = []
        for st, ln in take(e, seconds):
            if e.kind == PHOTO:
                st = 0.0
            if ids and e.kind == PHOTO:
                parts[ids[-1]]["length"] = round(parts[ids[-1]]["length"] + ln, 3)
                continue
            parts.append({"item": e.idx, "start": round(st, 3), "length": round(ln, 3)})
            ids.append(len(parts) - 1)
        return ids

    prev = None   # the segment before
    for at, ln, tp, bottom in timeline:
        if bottom is None:
            ids = add_parts(tp, ln)
            if prev is not None and prev[3] is None:
                scenes[-1]["parts"] += ids   # straight on: the same Solo B scene
            else:
                sc = {"layout": "soloB", "into": "takeover" if prev else "cut", "parts": ids}
                if prev and prev[2] is tp:
                    sc["grow"] = "A"   # a cameo over: the host grows back to the full frame
                scenes.append(sc)
        else:
            carry(tp, ln)
            scenes.append({"layout": "stack", "into": "handoff", "relay": True, "parts": add_parts(bottom, ln)})
        prev = (at, ln, tp, bottom)
    return parts, scenes


# ---------------------------------------------------------------- checks

def check(plan, items, opts):
    """The invariants a plan keeps (a list of what's broken; empty: none)."""
    errors = []
    opts = dict(opts or {})
    entries = [Entry(i, it, opts) for i, it in enumerate(items)]
    on = {}
    for seg in plan["timeline"]:
        for k in (seg["top"], seg["bottom"]):
            if k is not None:
                on[k] = on.get(k, 0) + seg["len"]
    for e in entries:
        if on.get(e.idx, 0) > e.life + 0.01:
            errors.append(f"item {e.idx} on screen {on[e.idx]:.2f}s, life {e.life:.2f}s")
        if e.kind == PHOTO and on.get(e.idx, 0) > e.life + 0.01:
            errors.append(f"photo {e.idx} on screen {on[e.idx]:.2f}s")
        if abs(on.get(e.idx, 0) - e.life) > 0.01:
            errors.append(f"item {e.idx} on screen {on.get(e.idx, 0):.2f}s, not its life {e.life:.2f}s")
    tl = plan["timeline"]
    for a, b in zip(tl, tl[1:]):
        if abs(a["at"] + a["len"] - b["at"]) > 0.01:
            errors.append(f"gap or overlap at {b['at']}")
        # a newcomer comes in below; whoever was there first stays on top
        if b["bottom"] is not None and b["top"] not in (a["top"], a["bottom"]):
            errors.append(f"split at {b['at']}: its top wasn't on screen before")
        if b["bottom"] is not None and b["bottom"] in (a["top"], a["bottom"]) and b["top"] != a["top"]:
            errors.append(f"split at {b['at']}: the newcomer isn't below")
        if b["bottom"] is not None and a["bottom"] is not None:
            errors.append(f"split at {b['at']} straight after another")
    # scene lengths
    lens = scene_lengths(plan)
    tiny = [i for i, l in enumerate(lens) if l < MIN_SCENE - 0.01]
    if tiny and not (len(lens) == 1):
        if any(entries[plan["lanes"]["B"][p]["item"]].life >= MIN_SCENE for i in tiny for p in plan["scenes"][i]["parts"]):
            errors.append(f"scenes shorter than {MIN_SCENE}s: {tiny}")
    # top-level items in shot order; guests in order
    firsts, seen = [], set()
    for seg in tl:
        for k in (seg["top"], seg["bottom"]):
            if k is not None and k not in seen:
                seen.add(k)
                firsts.append(k)
    guests = {seg["bottom"] for seg in tl if seg["bottom"] is not None and seg["bottom"] not in
              {s2["top"] for s2 in tl}}
    top_order = [k for k in firsts if k not in guests]
    if top_order != sorted(top_order):
        errors.append(f"top-level items out of order: {top_order}")
    g_order = [k for k in firsts if k in guests]
    if g_order != sorted(g_order, key=lambda k: (entries[k].shot_at, k)):
        errors.append(f"cameos out of order: {g_order}")
    if plan["stats"]["dial"] == 1 and plan["stats"]["splitPct"]:
        errors.append("dial 1 but split")
    return errors


def scene_lengths(plan):
    return [sum(plan["lanes"]["B"][p]["length"] for p in sc["parts"]) for sc in plan["scenes"]]


def bar(plan):
    """The plan as a strip for the dialog: [[seconds, split?]], runs merged."""
    out = []
    for seg in plan["timeline"]:
        sp = seg["bottom"] is not None
        if out and out[-1][1] == sp:
            out[-1][0] = round(out[-1][0] + seg["len"], 3)
        else:
            out.append([seg["len"], sp])
    return out
