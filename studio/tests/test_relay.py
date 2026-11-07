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

    def test_dial_and_migration(self):
        self.assertEqual(relay.dial_of(None, "single"), 3)
        self.assertEqual(relay.dial_of(None, "even"), 5)
        self.assertEqual(relay.dial_of(None, "split"), 8)
        self.assertEqual(relay.dial_of(None), relay.DIAL_DEFAULT)
        self.assertEqual(relay.dial_of(42), 10)
        self.assertEqual(relay.dial_of("0"), 1)


if __name__ == "__main__":
    unittest.main()
