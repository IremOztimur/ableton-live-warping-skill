"""Second opinion when warp_clip.py reports a grid FAIL on one 30 s window.

One window can fail without the grid being wrong: swung percussion, a beatless break, or
arrangement hits off the beat. This checks the grid per band (clap / hat / broadband), in
ABLETON's timeline, and the first-onset time at chosen bar lines.

Usage:
  python -I check_bands.py <audio file> --bpm 140 --downbeat 0.4289 [--bars 17,33]

A correct grid: medians within +-5 ms in the bands that carry the beat in that window, and
section onsets at ~0 ms. A wrong grid: every band drifts the same way, or onsets sit a fixed
amount early/late at every section.
"""
import argparse
import os
import sys

import librosa
import numpy as np
from scipy.signal import butter, sosfiltfilt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_track import mp3_offset  # noqa: E402

SR = 44100
BANDS = {"clap": (1500, 5000), "hat": (7000, 14000), "broad": None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--bpm", type=float, required=True)
    ap.add_argument("--downbeat", type=float, required=True, help="1.1.1 in Ableton seconds")
    ap.add_argument("--bars", default="", help="comma separated bar numbers")
    a = ap.parse_args()

    off_samples, _, nsr = mp3_offset(a.file)
    x, _ = librosa.load(a.file, sr=SR, mono=True)
    x = np.concatenate([np.zeros(int(round(off_samples / nsr * SR))), x])
    beat = 60.0 / a.bpm
    dur = len(x) / SR

    for nm, band in BANDS.items():
        y = x if band is None else sosfiltfilt(butter(4, list(band), btype="band", fs=SR, output="sos"), x)
        o = librosa.onset.onset_detect(y=y, sr=SR, hop_length=64, backtrack=True, units="time")
        b = (o - a.downbeat) / beat
        r = (b - np.round(b)) * beat * 1000
        ok = np.abs(r) < 15
        meds = []
        for w in range(0, int(dur), 30):
            m = ok & (o >= w) & (o < w + 30)
            meds.append(f"{np.median(r[m]):+.1f}" if m.sum() > 5 else "  -- ")
        print(f"{nm:<5} on-grid onsets={ok.sum():>4}  median ms per 30 s: {' '.join(meds)}")

    if a.bars:
        e = np.convolve(x ** 2, np.ones(48) / 48, "same")
        win = int(0.08 * SR)
        for bar in [int(v) for v in a.bars.split(",")]:
            t = a.downbeat + (bar - 1) * 4 * beat
            i = int(t * SR)
            w = 10 * np.log10(e[max(0, i - win):i + win] + 1e-12)
            pre_n = min(i, win)
            pre = np.median(w[:max(1, pre_n - int(0.02 * SR))]) if pre_n > 500 else -120
            hit = np.where(w > pre + 12)[0]
            rel = f"{(hit[0] - pre_n) / SR * 1000:+.1f} ms" if len(hit) else "no clear onset"
            print(f"bar {bar:>3} @ {t:8.4f}s  first onset vs bar line: {rel}")


if __name__ == "__main__":
    main()
