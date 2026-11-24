"""Apply a straight-grid warp to a Session clip in Ableton and verify it.

Usage:
  python -I warp_clip.py --track T --clip C --file <audio path> --bpm 140 --downbeat 0.0982 [--force]

  --downbeat  = downbeat_sec_ableton from analyze_track.py (seconds in ABLETON's timeline)
  --force     = continue even if Ableton's decoded length differs from the expected one

Does, in order:
  1. checks the clip is the expected file (Ableton sample_length vs predicted length for MP3s)
  2. set_clip_warp (1.1.1 at --downbeat, constant --bpm, Complex Pro, loop off), with retries
     and the "Segment length out of range" workaround
  3. sets the clip's play range to the whole warped track (start 1.1.1, end = last full bar),
     using the loop-toggle trick so Clip View Start/End/Position/Length all agree
  4. reads everything back and checks: marker at beat 0 == downbeat, tempo between markers == bpm,
     and the track's onsets sit on the Ableton grid (median per 30 s)
Prints a report and a final "RESULT {json}" line. Exit code 1 if any check fails.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def live(cmd, params):
    out = subprocess.run([sys.executable, "-I", os.path.join(HERE, "live.py"), cmd, json.dumps(params)],
                         capture_output=True, text=True).stdout
    return json.loads(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", type=int, required=True)
    ap.add_argument("--clip", type=int, required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--bpm", type=float, required=True)
    ap.add_argument("--downbeat", type=float, required=True)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    T, C = a.track, a.clip
    ok = True

    import numpy as np
    import librosa
    from analyze_track import mp3_offset  # same rules as the analysis
    off_samples, expected_len, nsr = mp3_offset(a.file)

    info = live("get_clip_warp", {"track_index": T, "clip_index": C})
    if info.get("status") != "success":
        sys.exit(f"get_clip_warp failed: {info}")
    r = info["result"]
    sr = r["sample_rate"]
    print(f"clip            {r['name']}  (sample_length {r['sample_length']}, sr {sr})")
    if expected_len is not None:
        exp = expected_len if int(sr) == nsr else None
        if exp is not None and abs(r["sample_length"] - exp) > 2:
            msg = f"sample_length {r['sample_length']} != expected {exp}: MP3 offset rule may not hold for this file"
            print("WARNING         " + msg)
            if not a.force:
                sys.exit(msg + " (re-run with --force after checking by ear)")
        else:
            print(f"decode check    OK (expected {exp}) -> MP3 offset {off_samples} samples is valid")

    # 2) warp with retries
    params = {"track_index": T, "clip_index": C, "bpm": a.bpm, "downbeat_sec": a.downbeat, "warp_mode": 6}
    res = None
    for attempt in range(4):
        res = live("set_clip_warp", params)
        if res.get("status") == "success":
            break
        msg = res.get("message", "")
        print(f"retry {attempt+1}: {msg[:120]}")
        if "add_warp_marker failed" in msg or "Segment length out of range" in msg:
            # Old markers collide with the new ones (same sample time at another beat, or order
            # inversion when 1.1.1 moves by bars). Warp to an intermediate grid first, then retry.
            for shift in (0.5, -0.5, 0.25, -0.25):
                if a.downbeat + shift < 0:
                    continue
                if live("set_clip_warp", dict(params, downbeat_sec=a.downbeat + shift)).get("status") == "success":
                    break
    if res.get("status") != "success":
        sys.exit(f"set_clip_warp failed: {res}")
    end = float(res["result"]["end_marker"])

    # 3) play range = whole warped track; loop brace too
    live("set_clip_markers", {"track_index": T, "clip_index": C, "looping": True,
                              "loop_start": 0, "loop_end": end, "start": 0})
    rm = live("set_clip_markers", {"track_index": T, "clip_index": C, "looping": False, "start": 0, "end": end})
    if rm.get("status") != "success":
        print(f"WARNING         set_clip_markers failed: {rm.get('message')} (old Remote Script? see reference/remote-script.md)")
        ok = False

    # 4) verify
    r = live("get_clip_warp", {"track_index": T, "clip_index": C})["result"]
    m = [x for x in r["warp_markers"]]
    m0 = [x for x in m if abs(x["beat_time"]) < 1e-9]
    # whole-beat markers only: Live adds a helper marker 1/32 beat after the last one
    big = [x for x in m if x["beat_time"] >= 4 and abs(x["beat_time"] - round(x["beat_time"])) < 1e-6]
    tempo = None
    if m0 and big:
        tempo = 60 * big[-1]["beat_time"] / (big[-1]["sample_time"] - m0[0]["sample_time"])
    print(f"markers         {[(round(x['beat_time'],3), round(x['sample_time'],4)) for x in m]}")
    print(f"warp            warping={r['warping']} mode={r['warp_mode']} looping={r['looping']}")
    if not m0 or abs(m0[0]["sample_time"] - a.downbeat) > 0.0005:
        print("FAIL            1.1.1 marker not at --downbeat"); ok = False
    if tempo is None or abs(tempo - a.bpm) > 0.005:
        print(f"FAIL            tempo between markers {tempo} != {a.bpm}"); ok = False
    if not r["warping"] or r["warp_mode"] != 6 or r["looping"]:
        print("FAIL            expected warping on, Complex Pro (6), loop off"); ok = False

    y, fsr = librosa.load(a.file, sr=44100, mono=True)
    on = librosa.onset.onset_detect(y=y, sr=fsr, hop_length=64, units="time", backtrack=True, delta=0.2) + off_samples / nsr
    spb = 60.0 / a.bpm
    ph = (on - a.downbeat) / spb
    near = np.abs(ph - np.round(ph)) < 0.08
    resid = (on[near] - a.downbeat - np.round(ph[near]) * spb) * 1000
    segs = []
    for s0 in range(0, int(on.max()) + 1, 30):
        mm = (on[near] >= s0) & (on[near] < s0 + 30)
        if mm.sum() >= 8:
            segs.append(round(float(np.median(resid[mm])), 1))
    print(f"grid check      {near.sum()}/{len(on)} onsets on grid; median ms per 30 s: {segs}")
    if segs and max(abs(x) for x in segs) > 5:
        print("FAIL            onsets drift off the grid (>5 ms): wrong BPM/downbeat or variable tempo"); ok = False
    print("RESULT " + json.dumps({"ok": ok, "track": T, "clip": C, "bpm": a.bpm, "downbeat_sec": a.downbeat,
                                  "end_beats": end, "tempo_between_markers": tempo, "grid_median_ms": segs}))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
