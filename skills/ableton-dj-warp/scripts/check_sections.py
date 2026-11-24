"""Check that section entries land on bar lines, and catch a bar phase that is half/one beat off.

The analyzer can pick a downbeat that is a half or whole beat late: the first sound then sits
200-430 ms BEFORE the proposed 1.1.1, and drops enter a beat early. This script measures, in
ABLETON's timeline (MP3 offset applied), what happens around given bars.

Usage:
  python -I check_sections.py <audio file> --bpm 140 --downbeat 0.4289 --bars 5,21,37,61

For each bar it prints:
  entry   largest sub (30-120 Hz) and broadband energy jump within +-0.6 s, and its time
          relative to the bar line (a section that enters on the bar shows a jump near +0 ms)
  sub/8th sub level (dB) per 8th note from -4 to +4 beats around the bar line: a drop's bass
          should step up at +0.0, not at -1.0 or -0.5
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--bpm", type=float, required=True)
    ap.add_argument("--downbeat", type=float, required=True, help="1.1.1 in Ableton seconds")
    ap.add_argument("--bars", required=True, help="comma separated bar numbers, e.g. 9,17,33")
    a = ap.parse_args()

    off_samples, _, nsr = mp3_offset(a.file)
    off = off_samples / nsr
    x, _ = librosa.load(a.file, sr=SR, mono=True)
    x = np.concatenate([np.zeros(int(round(off * SR))), x])  # now sample 0 = Ableton time 0
    beat = 60.0 / a.bpm
    bar_len = 4 * beat

    sub = sosfiltfilt(butter(4, [30, 120], btype="band", fs=SR, output="sos"), x)
    deep = sosfiltfilt(butter(4, [30, 90], btype="band", fs=SR, output="sos"), x)
    env = {k: np.convolve(y ** 2, np.ones(240) / 240, "same") for k, y in (("sub", sub), ("broad", x))}
    h = int(0.01 * SR)
    deep_db = 10 * np.log10(np.array([np.mean(deep[i:i + h] ** 2) for i in range(0, len(deep) - h, h)]) + 1e-12)

    print(f"MP3 offset applied: {off * 1000:.1f} ms" if off else "no decoder offset (not an MP3)")
    for bar in [int(v) for v in a.bars.split(",")]:
        t = a.downbeat + (bar - 1) * bar_len
        out = []
        for nm, e in env.items():
            i0 = max(0, int((t - 0.6) * SR))
            w = 10 * np.log10(e[i0:int((t + 0.6) * SR)] + 1e-12)
            st = int(0.01 * SR)
            idx = list(range(3 * st, len(w) - 3 * st, 48))
            if not idx:
                out.append(f"{nm}: n/a")
                continue
            rise = [w[j + st:j + 3 * st].max() - w[j - 3 * st:j].mean() for j in idx]
            k = int(np.argmax(rise))
            out.append(f"{nm} +{rise[k]:.1f} dB at {((i0 + idx[k]) / SR - t) * 1000:+.0f} ms")
        print(f"bar {bar:>3} @ {t:8.3f}s  entry: " + ", ".join(out))
        cells = []
        for k in range(-8, 9):
            tt = a.downbeat + ((bar - 1) * 4 + k * 0.5) * beat
            i = int(tt / 0.01)
            seg = deep_db[max(0, i):i + int(beat / 2 / 0.01)]
            cells.append(f"{k / 2:+.1f}:{seg.mean():.0f}" if len(seg) else f"{k / 2:+.1f}:--")
        print("          sub/8th: " + " ".join(cells))


if __name__ == "__main__":
    main()
