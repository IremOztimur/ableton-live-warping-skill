"""Split a warped track into Session section clips (one slot per section) and read them back.

Every slot on the track must already hold the same file, warped with warp_clip.py
(slot 0 is warped first; load the file into the next slots and warp each one too).

Usage:
  python -I split_sections.py --track T "intro:1-16" "drop:17-32" "outro:73-80:loop" [--prefix NAME]

  Bar ranges are INCLUSIVE, as a DJ says them: "17-32" = bar 17 up to the end of bar 32
  (16 bars). Bars are counted from 1.1.1. A ":loop" suffix turns looping on for that clip.
  --prefix  prepended to the first clip's name (e.g. the song name), others keep the short name.
  The clip name gets the bar count appended: "drop" over 17-32 -> "drop_16".

Prints one line per clip and exits 1 if any clip's read-back length or loop state is wrong.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def live(cmd, params):
    out = subprocess.run([sys.executable, "-I", os.path.join(HERE, "live.py"), cmd, json.dumps(params)],
                         capture_output=True, text=True).stdout
    return json.loads(out)


def parse(spec):
    parts = spec.split(":")
    if len(parts) not in (2, 3) or (len(parts) == 3 and parts[2] != "loop"):
        sys.exit(f"bad section '{spec}', expected name:FIRST-LAST[:loop]")
    a, b = (int(v) for v in parts[1].split("-"))
    if a < 1 or b < a:
        sys.exit(f"bad bar range in '{spec}'")
    return parts[0], a, b, len(parts) == 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", type=int, required=True)
    ap.add_argument("--prefix", default="")
    ap.add_argument("sections", nargs="+")
    a = ap.parse_args()
    secs = [parse(s) for s in a.sections]
    if len(secs) > 8:
        print("note: more than 8 sections; make sure the track has enough scene slots")

    info = live("get_track_info", {"track_index": a.track})["result"]
    slots = info["clip_slots"]
    for i in range(len(secs)):
        if i >= len(slots) or not slots[i].get("has_clip"):
            sys.exit(f"slot {i} on track {a.track} is empty: load and warp the file there first")

    plan = []
    for i, (name, first, last, loop) in enumerate(secs):
        bars = last - first + 1
        full = f"{name}_{bars}"
        if i == 0 and a.prefix:
            full = f"{a.prefix}_{full}"
        s, e = (first - 1) * 4.0, last * 4.0
        live("set_clip_name", {"track_index": a.track, "clip_index": i, "name": full})
        # loop-toggle trick: sets loop brace + start, then (for one-shots) the unlooped end
        live("set_clip_markers", {"track_index": a.track, "clip_index": i, "looping": True,
                                  "loop_start": s, "loop_end": e, "start": s})
        if not loop:
            live("set_clip_markers", {"track_index": a.track, "clip_index": i, "looping": False,
                                      "start": s, "end": e})
        plan.append((i, full, first, last, loop, e - s))

    ok = True
    for i, full, first, last, loop, want_len in plan:
        w = live("get_clip_warp", {"track_index": a.track, "clip_index": i})["result"]
        clip = live("get_track_info", {"track_index": a.track})["result"]["clip_slots"][i]["clip"]
        good = abs(clip["length"] - want_len) < 1e-6 and bool(w["looping"]) == loop and w["warping"]
        ok &= good
        print(f"slot {i}: {clip['name']:<40} bars {first}-{last} ({want_len / 4:g} bars) "
              f"len={clip['length']:g} beats loop={w['looping']} warp={w['warping']} "
              f"{'OK' if good else 'MISMATCH'}")
    print("RESULT", json.dumps({"ok": ok, "clips": len(plan)}))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
