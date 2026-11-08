"""Relay v2 planner tests: python3 -m unittest discover studio/tests"""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import relay  # noqa: E402

T0 = 1_760_000_000.0   # some afternoon; times below are minutes:seconds after it


def at(m, s=0.0):
    return T0 + m * 60 + s


def photo(t):
    return {"kind": "photo", "duration": 0, "start": 0, "length": 4, "shot_at": t}


def video(t, dur, start=0.0, length=None, keep=None):
    it = {"kind": "video", "duration": dur, "start": start, "length": length if length is not None else dur,
          "avail": dur - start, "shot_at": t}
    if keep is not None:
        it["keep"] = keep
    return it


# lemon-prune: 9 long clips, a short one and 5 photos, in shot order.
LEMON = [
    photo(at(4, 5)), photo(at(4, 19)),
    video(at(4, 24), 121.7),          # 4:24 → 6:25.7
    video(at(4, 32), 6.6),
    video(at(4, 34), 14.1),
    video(at(4, 38), 180.4),          # 4:38 → 7:38.4
    photo(at(4, 51)),                 # while 4:38 was recording
    photo(at(5, 40)),                 # while 4:38 was recording
    video(at(8, 2), 42.0),
    video(at(9, 10), 25.5),
    photo(at(9, 20)),                 # while 9:10 was recording
    video(at(10, 0), 63.0),
    video(at(11, 30), 18.2),
    video(at(12, 5), 31.0),
    video(at(13, 0), 12.4),
]
ALL_PHOTOS = [photo(at(1, i * 20)) for i in range(10)]
ONE_LONG_SIX_PHOTOS = [video(at(1), 180.0)] + [photo(at(5, i * 15)) for i in range(6)]
TWO_LONG = [video(at(1), 40.0), video(at(2), 25.0)]
# A 70s clip whose 20..40 was cut as quiet; a photo shot at 30s into it.
QUIET = [video(at(1), 70.0, keep=[(0, 20), (40, 30)]), photo(at(1, 30))]

FIXTURES = {"lemon": LEMON, "photos": ALL_PHOTOS, "long+6": ONE_LONG_SIX_PHOTOS, "two-long": TWO_LONG, "quiet": QUIET}


def random_items(seed):
    rnd = random.Random(seed)
    t, out = at(0), []
    for _ in range(rnd.randint(1, 18)):
        t += rnd.uniform(1, 40)
        r = rnd.random()
        if r < 0.4:
            out.append(photo(t))
        elif r < 0.7:
            d = rnd.uniform(1.2, 9.9)
            out.append(video(t, d, length=rnd.uniform(1.0, d)))
        else:
            d = rnd.uniform(10, 200)
            out.append(video(t, d))
    return out


def splits(plan):
    return [s for s in plan["timeline"] if s["bottom"] is not None]


def cameos(plan):
    tops = {s["top"] for s in plan["timeline"]}
    return [s for s in splits(plan) if s["bottom"] not in tops]


class Invariants(unittest.TestCase):
    def each(self):
        cases = list(FIXTURES.items()) + [(f"random {k}", random_items(k)) for k in range(60)]
        for name, items in cases:
            for photo_s in (2, 3, 4, 6):
                for cap in (None, 20):
                    yield name, items, {"photo_seconds": photo_s, "cap": cap}

    def test_invariants_every_dial(self):
        for name, items, opts in self.each():
            for dial in range(1, 11):
                o = {**opts, "dial": dial}
                plan = relay.plan_relay(items, o)
                with self.subTest(fixture=name, dial=dial, **opts):
                    self.assertEqual(relay.check(plan, items, o), [])
                    # 4. never more than two on screen: each segment has a top and at most one bottom
                    for seg in plan["timeline"]:
                        self.assertNotEqual(seg["top"], seg["bottom"])
                    self.assertEqual(len(plan["lanes"]["A"]), 0)

    def test_dial_one_is_all_full_frame(self):
        for name, items, opts in self.each():
            plan = relay.plan_relay(items, {**opts, "dial": 1})
            self.assertEqual(plan["stats"]["splitPct"], 0, name)
            self.assertEqual(plan["stats"]["cameoCount"], 0, name)
            self.assertTrue(all(sc["layout"] == "soloB" for sc in plan["scenes"]), name)

    def test_split_never_drops_as_the_dial_rises(self):
        for name, items, opts in self.each():
            pcts = [relay.plan_relay(items, {**opts, "dial": d})["stats"]["splitPct"] for d in range(1, 11)]
            with self.subTest(fixture=name, **opts):
                self.assertEqual(pcts, sorted(pcts), pcts)

    def test_same_inputs_same_plan(self):
        for name, items, opts in self.each():
            o = {**opts, "dial": 7}
            self.assertEqual(relay.plan_relay(items, o), relay.plan_relay([dict(i) for i in items], o), name)

    def test_scenes_match_the_timeline(self):
        """Every split is a relay after a Solo B whose last part is the top
        item; a Solo B after a cameo grows the host back."""
        for name, items, opts in self.each():
            for dial in (3, 6, 10):
                plan = relay.plan_relay(items, {**opts, "dial": dial})
                parts, scenes = plan["lanes"]["B"], plan["scenes"]
                total = sum(p["length"] for p in parts)
                self.assertAlmostEqual(total, plan["stats"]["totalSeconds"], delta=0.05)
                used = [p for sc in scenes for p in sc["parts"]]
                self.assertEqual(used, list(range(len(parts))), name)
                splits_tl = splits(plan)
                stacks = [k for k, sc in enumerate(scenes) if sc["layout"] == "stack"]
                self.assertEqual(len(stacks), len(splits_tl), name)
                for k, seg in zip(stacks, splits_tl):
                    prev = scenes[k - 1]
                    self.assertEqual(prev["layout"], "soloB")
                    self.assertEqual(parts[prev["parts"][-1]]["item"], seg["top"])
                    self.assertTrue(scenes[k]["relay"])
                    self.assertEqual({parts[p]["item"] for p in scenes[k]["parts"]}, {seg["bottom"]})
                    if k + 1 < len(scenes):
                        nxt = scenes[k + 1]
                        self.assertEqual(nxt["into"], "takeover")
                        first = parts[nxt["parts"][0]]["item"]
                        self.assertEqual(nxt.get("grow") == "A", first == seg["top"])


class Fixtures(unittest.TestCase):
    def test_lemon_prune(self):
        opts = {"photo_seconds": 4}
        pcts = [relay.plan_relay(LEMON, {**opts, "dial": d})["stats"]["splitPct"] for d in (1, 3, 5, 8, 10)]
        self.assertEqual(pcts[0], 0)
        self.assertTrue(all(a < b for a, b in zip(pcts, pcts[1:])), pcts)
        for d in (3, 5, 8):
            plan = relay.plan_relay(LEMON, {**opts, "dial": d})
            self.assertEqual(relay.check(plan, LEMON, {**opts, "dial": d}), [])
            # photos shot while a long clip recorded appear in it, at their moment
            by_bottom = {s["bottom"]: s for s in cameos(plan)}
            for g, host in ((6, 5), (7, 5), (10, 9)):
                self.assertIn(g, by_bottom, f"dial {d}: photo {g} should be a cameo")
                seg = by_bottom[g]
                self.assertEqual(seg["top"], host)
                host_in = min(s["at"] for s in plan["timeline"] if host in (s["top"], s["bottom"]))
                moment = LEMON[g]["shot_at"] - LEMON[host]["shot_at"]
                self.assertGreaterEqual(seg["at"] - host_in, moment - 0.01)
                self.assertLess(seg["at"] - host_in, moment + 6.1)   # at most a cameo gap late
            self.assertGreaterEqual(plan["stats"]["cameoCount"], 3)
        s = relay.plan_relay(LEMON, {**opts, "dial": 5})["stats"]
        self.assertEqual((s["longCount"], s["shortCount"], s["photoCount"]), (9, 1, 5))

    def test_all_photos(self):
        plan = relay.plan_relay(ALL_PHOTOS, {"dial": 10, "photo_seconds": 4})
        st = plan["stats"]
        self.assertEqual(st["limitedBy"], "photos")
        self.assertGreater(st["splitPct"], 0)
        for seg in splits(plan):
            self.assertLessEqual(seg["len"], 2.0)   # short photo + photo splits
        on = {}
        for seg in plan["timeline"]:
            for k in (seg["top"], seg["bottom"]):
                if k is not None:
                    on[k] = on.get(k, 0) + seg["len"]
        self.assertTrue(all(v <= 4.001 for v in on.values()), on)
        self.assertLess(relay.plan_relay(ALL_PHOTOS, {"dial": 6})["stats"]["splitPct"], 1)

    def test_one_long_six_photos(self):
        plan4 = relay.plan_relay(ONE_LONG_SIX_PHOTOS, {"dial": 4, "photo_seconds": 4})
        self.assertEqual(plan4["stats"]["cameoCount"], 0)
        firsts = []
        for seg in plan4["timeline"]:
            for k in (seg["top"], seg["bottom"]):
                if k is not None and k not in firsts:
                    firsts.append(k)
        self.assertEqual(firsts, list(range(7)))   # the photos after the video, in order
        plan8 = relay.plan_relay(ONE_LONG_SIX_PHOTOS, {"dial": 8, "photo_seconds": 4})
        cs = cameos(plan8)
        self.assertGreaterEqual(len(cs), 4)
        self.assertTrue(all(c["at"] >= 90 for c in cs))   # the video's back half
        for a, b in zip(cs, cs[1:]):
            self.assertGreaterEqual(b["at"] - (a["at"] + a["len"]), 1.5)
        self.assertEqual([c["bottom"] for c in cs], sorted(c["bottom"] for c in cs))

    def test_two_long(self):
        overlaps = []
        for d in range(1, 11):
            plan = relay.plan_relay(TWO_LONG, {"dial": d})
            sp = splits(plan)
            overlaps.append(sp[0]["len"] if sp else 0)
        self.assertEqual(overlaps[0], 0)
        self.assertEqual(overlaps, sorted(overlaps))
        self.assertGreater(overlaps[-1], overlaps[1])
        self.assertLessEqual(max(overlaps), 25.0 - relay.MIN_SCENE + 1e-6)

    def test_quiet_cut_cameo_snaps_to_kept_moment(self):
        plan = relay.plan_relay(QUIET, {"dial": 5, "photo_seconds": 4})
        cs = cameos(plan)
        self.assertEqual(len(cs), 1)
        self.assertAlmostEqual(cs[0]["at"], 20.0, delta=0.01)   # 30s was cut; the nearest kept moment
        # the host's parts skip the quiet stretch
        parts = [p for p in plan["lanes"]["B"] if p["item"] == 0]
        self.assertTrue(all(not (20.01 < p["start"] < 39.99) for p in parts), parts)

    def test_stretches(self):
        # at most 4 (or as asked): all of them from two minutes, fewer below
        self.assertEqual(relay.stretch_count(180), 4)
        self.assertEqual(relay.stretch_count(120), 4)
        self.assertEqual(relay.stretch_count(60), 2)
        self.assertEqual(relay.stretch_count(30), 1)
        self.assertEqual(relay.stretch_count(600, 6), 6)
        self.assertEqual(relay.stretch_count(11), 1)
        self.assertEqual(len(relay.stretches(0, 600, 20)), 4)          # a long clip doesn't take over
        self.assertEqual(len(relay.stretches(0, 600, 20, most=2)), 2)
        self.assertEqual(relay.stretches(0, 60, 20), [(6.0, 20.0), (34.0, 20.0)])   # evenly through it
        three_min = relay.stretches(0, 180, 20)
        gaps = [b - (a + la) for (a, la), (b, _) in zip(three_min, three_min[1:])]
        self.assertTrue(all(abs(g - gaps[0]) < 0.01 for g in gaps))   # evenly spaced
        for d in (11, 25, 47, 121.7, 180, 333):
            for cap in (None, 20, 30, 60):
                for most in (1, 2, 4, 6):
                    st = relay.stretches(3.0, d, cap, most=most)
                    self.assertLessEqual(len(st), most if cap else 1)
                    first, last = st[0][0] - 3.0, 3.0 + d - (st[-1][0] + st[-1][1])
                    self.assertAlmostEqual(first, last, delta=0.01)          # centred
                    self.assertGreaterEqual(first, min(relay.BREATH, d / 4) - 0.01)   # room at each end
                    self.assertTrue(all(cap is None or l <= cap + 1e-9 for _, l in st))
                    for (a, la), (b, _) in zip(st, st[1:]):
                        self.assertGreaterEqual(b, a + la - 1e-9)   # no overlaps
        self.assertEqual(relay.stretches(0, 40, None), [(2.0, 36.0)])

    def test_stretches_of_a_clip_relay_among_themselves(self):
        clip = video(at(1), 180.0)
        items = []
        st = relay.stretches(0, 180, 20)
        bounds = [0.0] + [(a + l + b) / 2 for (a, l), (b, _) in zip(st, st[1:])] + [180.0]
        for k, (s, l) in enumerate(st):
            items.append({**clip, "start": s, "avail": l, "clip": 7, "match": (bounds[k], bounds[k + 1])})
        items += [photo(at(1, 50)), video(at(5), 30.0)]   # a photo while it recorded (in a skip), then a clip
        for d in range(1, 11):
            plan = relay.plan_relay(items, {"dial": d})
            self.assertEqual(relay.check(plan, items, {"dial": d}), [])
            # each stretch hands on to the next: the later moment comes in under the earlier
            hand = {(s["top"], s["bottom"]) for s in splits(plan)}
            for k in range(3):
                self.assertEqual((k, k + 1) in hand, d >= relay.PAIR_LONG_LONG, (d, k, hand))
            if d >= 3:   # the photo at 0:50, in the skip after 20..40, goes in the nearest stretch
                c = cameos(plan)
                self.assertEqual([(s["top"], s["bottom"]) for s in c][:1], [(1, 4)])
            self.assertEqual(plan["stats"]["longCount"], 2)
            self.assertEqual(plan["stats"]["longPieces"], 5)

    def test_a_photo_keeps_its_own_hold(self):
        items = [video(at(1), 30.0), {**photo(at(1, 10)), "hold": 6.5}, photo(at(3))]
        for d in (1, 5, 10):
            plan = relay.plan_relay(items, {"dial": d, "photo_seconds": 4})
            self.assertEqual(relay.check(plan, items, {"dial": d, "photo_seconds": 4}), [])
            on = {}
            for seg in plan["timeline"]:
                for k in (seg["top"], seg["bottom"]):
                    if k is not None:
                        on[k] = on.get(k, 0) + seg["len"]
            self.assertAlmostEqual(on[1], 6.5, delta=0.01)
            self.assertAlmostEqual(on[2], 4.0, delta=0.01)

    def test_fit_to_a_target_length(self):
        clips = [video(at(1), 180.0), photo(at(4)), video(at(5), 95.0), photo(at(7)), video(at(8), 140.0)]

        def make(cap):
            out = []
            for k, c in enumerate(clips):
                if c["kind"] == "video":
                    for s, l in relay.stretches(0, c["duration"], cap):
                        out.append({**c, "start": s, "avail": l, "clip": k})
                else:
                    out.append(c)
            return out
        for target in (60, 90, 120, 180):
            for dial in (1, 5, 9):
                opts = {"dial": dial, "photo_seconds": 4}
                items, plan, cap = relay.fit_target(make, opts, target, 180.0)
                got = plan["stats"]["totalSeconds"]
                self.assertLess(abs(got - target), max(4.0, target * 0.05), (target, dial, got, cap))
                self.assertEqual(relay.check(plan, items, {**opts, "cap": cap}), [])
        # everything at full length is under the target: full length, no cap
        _, plan, cap = relay.fit_target(make, {"dial": 5}, 2000, 180.0)
        self.assertIsNone(cap)
        # can't get that short: the shortest stretches
        _, plan, cap = relay.fit_target(make, {"dial": 5}, 5, 180.0)
        self.assertEqual(cap, relay.MIN_STRETCH)

    def test_dial_and_migration(self):
        self.assertEqual(relay.dial_of(None, "single"), 3)
        self.assertEqual(relay.dial_of(None, "even"), 5)
        self.assertEqual(relay.dial_of(None, "split"), 8)
        self.assertEqual(relay.dial_of(None), relay.DIAL_DEFAULT)
        self.assertEqual(relay.dial_of(42), 10)
        self.assertEqual(relay.dial_of("0"), 1)


if __name__ == "__main__":
    unittest.main()
