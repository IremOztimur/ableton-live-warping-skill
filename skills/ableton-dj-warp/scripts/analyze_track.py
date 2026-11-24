"""Analyze a full track for Ableton warping: exact BPM, tempo stability, grid origin,
bar phase (which beat is "1"), phrase boundaries, and the 1.1.1 time IN ABLETON'S TIMELINE
(MP3 decoder offset included).

Usage:
  python -I analyze_track.py <audio file> <tagged_bpm> [--bars]
    --bars   also print a per-bar energy table (sub / kick / mid / high dB) for section work

Needs: numpy, librosa (+ soundfile), ffmpeg/ffprobe on PATH.
Output: human-readable report + a final JSON line starting with "RESULT ".
"""
import json
import subprocess
import sys

import librosa
import numpy as np

SR = 44100
HOP = 64


def native_sr(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                          "stream=sample_rate", "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
    out = out.split("\n")[0].split(",")[0].strip()  # some files print "44100," (extra side data)
    return int(out or SR)


def ffmpeg_samples(path, untrimmed, sr=SR):
    cmd = ["ffmpeg", "-v", "error"]
    if untrimmed:
        cmd += ["-flags2", "+skip_manual"]
    cmd += ["-i", path, "-f", "s16le", "-ac", "1", "-ar", str(sr), "-"]
    return len(subprocess.run(cmd, capture_output=True).stdout) // 2


def mp3_offset(path):
    """Ableton does NOT apply MP3 gapless trimming and also decodes the LAME/Xing info
    frame as audio. Empirically: ableton_sample_length == untrimmed + (encoder_delay + 1152)
    and Ableton time == gapless-decoder time + (encoder_delay + 1152) samples.
    Verified against Ableton's own Warp-From-Here markers (median error 0.25 ms).
    All counts are in the file's NATIVE sample rate (= Ableton's clip sample_rate):
    a 48 kHz MP3 has offset 2257 samples = 47.0 ms, not 51.2 ms.
    Returns (offset_samples, expected_sample_length, native_sr)."""
    nsr = native_sr(path)
    if not path.lower().endswith(".mp3"):
        return 0, None, nsr
    st = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                         "stream=start_time", "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
    st = st.split("\n")[0].split(",")[0].strip()
    delay = int(round(float(st or 0) * nsr))
    untrimmed = ffmpeg_samples(path, untrimmed=True, sr=nsr)
    gapless = ffmpeg_samples(path, untrimmed=False, sr=nsr)
    has_info = gapless < untrimmed  # ffmpeg only trims when a LAME/Xing info frame exists
    off = delay + (1152 if has_info else 0)
    expected_len = untrimmed + off
    return off, expected_len, nsr


def flux(S, f, lo, hi):
    e = np.log1p(S[(f >= lo) & (f < hi)].sum(0))
    return np.maximum(0, np.diff(e, prepend=e[0]))


def circ_fit(on, bpm):
    spb = 60.0 / bpm
    z = np.exp(2j * np.pi * on / spb)
    m = z.mean()
    return abs(m), (np.angle(m) / (2 * np.pi)) % 1.0 * spb


def main():
    path, tag_bpm = sys.argv[1], float(sys.argv[2])
    show_bars = "--bars" in sys.argv
    y, _ = librosa.load(path, sr=SR, mono=True)
    dur = len(y) / SR
    first_sound = float(np.argmax(np.abs(y) > 0.01) / SR)
    on = librosa.onset.onset_detect(y=y, sr=SR, hop_length=HOP, units="time", backtrack=True, delta=0.2)

    # 1) exact BPM: grid search of a clap+hat+full onset envelope (kick band excluded: long
    #    808/sub notes smear low-frequency onsets). Search tag +-0.6 BPM, phase 1 frame.
    S = np.abs(librosa.stft(y, n_fft=1024, hop_length=HOP))
    f = librosa.fft_frequencies(sr=SR, n_fft=1024)
    fps = SR / HOP
    nrm = lambda e: e / (e.max() + 1e-9)
    full = librosa.onset.onset_strength(S=librosa.amplitude_to_db(S), sr=SR, hop_length=HOP)
    genv = nrm(flux(S, f, 1500, 6000)) + nrm(flux(S, f, 8000, 16000)) + 0.5 * nrm(full)

    def grid_score(b):
        per = fps * 60.0 / b
        n = int((len(genv) - per) / per)
        idx = (np.arange(int(per))[:, None] + np.arange(n)[None, :] * per).round().astype(int)
        v = genv[idx].mean(1)
        return float(v.max()), float(np.argmax(v) / fps)

    cands = np.arange(tag_bpm - 0.6, tag_bpm + 0.6001, 0.01)
    sc = [grid_score(b) for b in cands]
    best = int(np.argmax([x[0] for x in sc]))
    bpm = float(cands[best])
    if abs(bpm - round(bpm)) <= 0.05 and grid_score(round(bpm))[0] >= 0.985 * sc[best][0]:
        bpm = float(round(bpm))  # commercial tracks are almost always integer BPM
    spb = 60.0 / bpm
    t0 = grid_score(bpm)[1]
    lowenv = nrm(flux(S, f, 30, 150)) + 0.5 * nrm(full)
    def at(env, start):
        idx = (start * fps + np.arange(int((len(env) / fps - start) / spb) - 1) * spb * fps).round().astype(int)
        return float(np.mean([env[max(0, i - 10):i + 11].max() for i in idx]))  # +-15 ms
    # Busy 16th-note claps/hats can lock the grid onto an 8th or 16th off-beat: test all four
    # 16th positions and keep the one where the low end (kick/bass) is strongest.
    cand = [((t0 + q * spb / 4) % spb) for q in range(4)]
    lows = [at(lowenv, c) for c in cand]
    if max(lows) > 1.1 * lows[0]:
        t0 = cand[int(np.argmax(lows))]
    t0_coarse = t0
    for _ in range(2):  # refine origin with median residual of near-grid (backtracked) onsets
        ph = (on - t0) / spb
        near = np.abs(ph - np.round(ph)) < 0.08
        t0 = float(np.median(on[near] - np.round(ph[near]) * spb))
    d_ref = (t0 - t0_coarse + spb / 2) % spb - spb / 2
    if abs(d_ref) > spb / 8:   # refinement jumped to another subdivision: keep the coarse beat
        t0 = t0_coarse
    ph = (on - t0) / spb
    near = np.abs(ph - np.round(ph)) < 0.08
    res = (on[near] - t0 - np.round(ph[near]) * spb) * 1000
    seg = []
    for a in range(0, int(dur), 30):
        m = (on[near] >= a) & (on[near] < a + 30)
        if m.sum() >= 8:
            seg.append((a, round(float(np.median(res[m])), 1), int(m.sum())))
    drift_span = (max(s[1] for s in seg) - min(s[1] for s in seg)) if seg else 0.0

    # windowed tempo (20 s windows, +-12% search) to spot tempo changes / ramps
    win = []
    for a in np.arange(0, dur - 20, 15):
        seg_env = genv[int(a * fps):int((a + 20) * fps)]
        best_w = (0, None)
        for b in np.arange(bpm * 0.88, bpm * 1.12, 0.1):
            per = fps * 60.0 / b
            n = int((len(seg_env) - per) / per)
            if n < 8:
                continue
            idx = (np.arange(int(per))[:, None] + np.arange(n)[None, :] * per).round().astype(int)
            v = float(seg_env[idx].mean(1).max())
            if v > best_w[0]:
                best_w = (v, b)
        if best_w[1] is not None:
            win.append((int(a), round(float(best_w[1]), 1), round(best_w[0], 2)))
    wv = np.array([w[1] for w in win]) if win else np.array([bpm])
    win_mad = float(np.median(np.abs(wv - np.median(wv))))
    off_windows = [(a, b) for a, b, _ in win if abs(b - bpm) > 1.5]

    # 2) per-band offsets per segment (kick band is unreliable under long 808/sub notes)
    bands = {"kick": flux(S, f, 30, 150), "clap": flux(S, f, 1500, 6000), "hat": flux(S, f, 8000, 16000)}
    t0g = t0 % spb
    nb = int((dur - t0g) / spb) - 1
    gt = t0g + np.arange(nb) * spb
    strength, band_seg = {}, {}
    for name, env in bands.items():
        st, off = [], []
        for g in gt:
            a, b = max(0, int((g - 0.06) * fps)), int((g + 0.06) * fps)
            i = a + int(np.argmax(env[a:b]))
            st.append(env[i]); off.append((i / fps - g) * 1000)
        st, off = np.array(st), np.array(off)
        strength[name] = st
        thr = np.percentile(st, 70)
        band_seg[name] = [round(float(np.median(off[(gt >= a) & (gt < a + 30) & (st > thr)])), 1)
                          if ((gt >= a) & (gt < a + 30) & (st > thr)).sum() > 2 else None
                          for a in range(0, int(dur), 30)]

    # 3) bar phase: kick on "1" (and clap on 3 in half-time / 2&4 in four-on-floor)
    k_by = [float(strength["kick"][p::4].mean()) for p in range(4)]
    c_by = [float(strength["clap"][p::4].mean()) for p in range(4)]
    # bar-boundary energy change score per phase
    S2 = np.abs(librosa.stft(y, n_fft=2048, hop_length=512)); f2 = librosa.fft_frequencies(sr=SR, n_fft=2048); fps2 = SR / 512
    bandsdb = [(20, 60), (60, 150), (200, 2000), (4000, 11000)]

    def bar_table(start):
        bar = 4 * spb; rows = []
        for i in range(int((dur - start) / bar)):
            a, b = int((start + i * bar) * fps2), int((start + (i + 1) * bar) * fps2)
            rows.append([20 * np.log10(S2[(f2 >= lo) & (f2 < hi), a:b].mean() + 1e-9) for lo, hi in bandsdb])
        return np.array(rows)

    # Section-boundary votes: beats where the 4 beats after differ most from the 4 beats before
    # (drops, breakdowns, builds start on bar lines). Take the 6 largest, vote by beat%4.
    lowE = np.log1p(S2[f2 < 120].sum(0)); fullE = np.log1p(S2.sum(0))
    def beat_mean(E, i):
        a, b = int((t0g + i * spb) * fps2), int((t0g + (i + 1) * spb) * fps2)
        return E[a:b].mean() if b > a else 0.0
    nbt = int((dur - t0g) / spb) - 1
    Lb = np.array([beat_mean(lowE, i) for i in range(nbt)]); Fb = np.array([beat_mean(fullE, i) for i in range(nbt)])
    ch = []
    for i in range(8, nbt - 8):  # 2 bars before vs 2 bars after: sections, not single fills
        ch.append((abs(Lb[i:i+8].mean() - Lb[i-8:i].mean()) + abs(Fb[i:i+8].mean() - Fb[i-8:i].mean()), i))
    ch.sort(reverse=True); picks = []
    for dv, i in ch:
        if all(abs(i - j) > 6 for _, j in picks):
            picks.append((dv, i))
        if len(picks) == 6:
            break
    bscore = [float(sum(dv for dv, i in picks if i % 4 == p)) for p in range(4)]
    bound_phase = int(np.argmax(bscore))
    # Most club tracks start on a downbeat: which phase puts the first sound on beat 1?
    first_phase = int(round((first_sound - t0g) / spb)) % 4
    kick_phase = int(np.argmax(k_by))
    kick_dominant = sorted(k_by)[-1] > 1.15 * sorted(k_by)[-2]
    votes = [bound_phase, first_phase] + ([kick_phase] if kick_dominant else [])
    phase = max(set(votes), key=votes.count)
    if votes.count(phase) == 1:
        phase = first_phase  # tie: club tracks almost always start on a downbeat
    ambiguous = not (bound_phase == first_phase == phase)

    # 4) 1.1.1 = first downbeat at/after the first sound (allow 50 ms tolerance)
    db0 = t0g + phase * spb
    k = int(np.ceil((first_sound - 0.06 - db0) / (4 * spb)))  # may be negative (origin wrapped)
    first_db = max(0.0, db0 + k * 4 * spb)
    off_samples, expected_len, nsr = mp3_offset(path)
    off_s = off_samples / nsr
    tb = bar_table(first_db)
    d = np.abs(np.diff(tb, axis=0)).sum(1)
    big = [int(i + 2) for i in np.argsort(d)[-10:]]  # bar numbers (1-based) where a big change starts
    big.sort()

    print(f"file            {path.split('/')[-1]}")
    print(f"duration        {dur:.2f} s, first sound {first_sound:.4f} s, onsets {len(on)} ({near.sum()} on grid)")
    print(f"BPM             {bpm:.3f} (tag {tag_bpm})")
    print(f"tempo windows   " + ", ".join(f"{a}s:{b}" for a, b, _ in win) + f"   (MAD {win_mad:.2f}; windows >1.5 BPM off: {off_windows})")
    print(f"grid residual   per 30 s (ms, should be flat): {[s[1] for s in seg]}  span {drift_span:.1f} ms")
    for n in bands:
        print(f"  {n:5s} band offset per 30 s: {band_seg[n]}")
    print(f"bar phase       kick by beat%4 {[round(x,3) for x in k_by]}, clap by beat%4 {[round(x,3) for x in c_by]}")
    print(f"                section-boundary votes by phase {[round(x,1) for x in bscore]} (beats {sorted(i for _, i in picks)}) -> boundaries {bound_phase}, first-sound {first_phase}, kick {kick_phase}{'' if kick_dominant else ' (not dominant, ignored)'} => phase {phase}"
          + ("  ** AMBIGUOUS: confirm by ear / phrase structure **" if ambiguous else ""))
    print(f"MP3 offset      {off_samples} samples ({off_s*1000:.1f} ms); expected Ableton sample_length {expected_len}")
    print(f"1.1.1 file time {first_db:.4f} s  ->  ABLETON downbeat_sec {first_db + off_s:.4f}")
    print(f"big changes at bars (from 1.1.1): {big}")
    verdict = "CONSTANT" if (drift_span <= 10 and win_mad <= 0.5 and len(off_windows) <= 1) else "CHECK: possible tempo change / drift"
    print(f"tempo verdict   {verdict}")
    if show_bars:
        print("bar   abl_time   sub   kick   mid   high")
        for i, r in enumerate(tb):
            print(f"{i+1:4d} {first_db + off_s + i*4*spb:8.1f}s " + " ".join(f"{v:6.1f}" for v in r))
    print("RESULT " + json.dumps({
        "bpm": round(bpm, 3), "downbeat_file_sec": round(first_db, 4),
        "downbeat_sec_ableton": round(first_db + off_s, 4), "mp3_offset_samples": off_samples,
        "expected_ableton_sample_length": expected_len, "bar_phase_ambiguous": bool(ambiguous),
        "residual_span_ms": round(drift_span, 1), "tempo_verdict": verdict, "big_change_bars": big}))


if __name__ == "__main__":
    main()
