---
name: ableton-dj-warp
description: Use when warping full tracks or splitting them into section clips in Ableton Live (via the AbletonMCP Remote Script) for a DJ set - finding the exact BPM and the 1.1.1 downbeat, checking for tempo changes, handling MP3 decoder offsets, or when a warped clip drifts from the metronome, sits a fraction of a beat off, shows a wrong/120 Seg. BPM, or "Warp From Here" misreads an intro/outro.
---

# Ableton full-track warping (DJ sets)

## Core principle

For constant-tempo club tracks, the correct warp is **one straight grid**: 1.1.1 on the first
downbeat, exact integer BPM, Complex Pro, loop off. The whole job is finding the downbeat
**in Ableton's timeline** to ~1 ms and proving it with numbers before the user listens.
Never eyeball, never trust Live's auto-warp for this, and never report a clip setting you did not read back.

## Setup (once)

- ffmpeg/ffprobe on PATH, and a Python venv kept OUTSIDE the plugin folder (plugin updates replace it):
  `python3 -m venv ~/.ableton-dj-warp/venv && ~/.ableton-dj-warp/venv/bin/pip install -r requirements.txt`.
  Below, `$PY` = `~/.ableton-dj-warp/venv/bin/python`. Create the venv if it is missing.
- Remote Script must have the warp commands: `python3 -I scripts/live.py set_clip_markers '{"track_index":999}'`
  must answer "Track index out of range". If "Unknown command", follow `reference/remote-script.md` (patch, then the user fully restarts Live after Cmd+S).
- Run Python that reads user audio with `-I`. Paths below are relative to this skill directory.

## Workflow

1. **Find the clip and file.** `python3 -I scripts/live.py get_track_info '{"track_index":N}'`. The file
   path is the user's audio file (take BPM from its tag/filename, e.g. `1A_140_Title.mp3` → 140).
   If the track is not loaded: `create_audio_track` / `create_audio_clip` (see reference). Do not create
   a duplicate if the user already loaded it - check every track first.
2. **Analyze:** `$PY -I scripts/analyze_track.py "<file>" <tag_bpm>` (add `--bars` for a per-bar
   energy table). Read the report, not only the RESULT line.
3. **Decide** with the table below.
4. **Check the bar phase** before applying: `$PY -I scripts/check_sections.py "<file>" --bpm <bpm> --downbeat <d> --bars <first drop, 2-3 later sections>`.
   The sub level must step up at `+0.0`, not at `-0.5`/`-1.0` beats. The analyzer has repeatedly picked a
   downbeat a half or whole beat late (first sound 200-430 ms before its 1.1.1); fix that here, not after.
5. **Apply + verify:** `$PY -I scripts/warp_clip.py --track T --clip C --file "<file>" --bpm <bpm> --downbeat <downbeat_sec_ableton>`.
   It refuses if Ableton's decoded length differs from the prediction, retries Live's flaky first call,
   sets play range + loop brace, then checks marker positions, tempo between markers and onset
   alignment (median per 30 s, must be within ±5 ms). Exit 1 = do not report success.
6. **Report to the user** (their language): BPM, 1.1.1 in seconds, where the clip is, the verification
   numbers, and 2-3 bar numbers/times to check with the metronome (first drop, a later section).
   Remind them to press **Save Default Clip** (disk icon in the clip title bar; no API) and Cmd+S.
7. **Section clips (if asked).** The user names bar ranges ("1-16 intro, 17-32 drop, 73-80 outro loop"):
   ranges are inclusive, so 17-32 = beats 64-128. Load the same file into slots 0..n-1 of the track,
   warp each with warp_clip.py, then
   `$PY -I scripts/split_sections.py --track T --prefix "<song>" "intro:1-16" "drop:17-32" "outro:73-80:loop"`.
   It names clips `<name>_<bars>`, sets each range and reads them back (exit 1 on mismatch).
   Before a loop at the end of the song, check the file is long enough: a loop past the last sample
   leaves a silent gap every cycle; shorten it and tell the user.

| analyze_track result | Action |
|---|---|
| `CONSTANT`, not ambiguous | Apply with warp_clip.py. |
| `CONSTANT`, `AMBIGUOUS` bar phase | Grid (beats) is right; which beat is "1" is uncertain. Show the user the votes and `big_change_bars`; the phase that puts drops/sections on bars 9/17/33/49/65… (8k+1) wins. Apply after deciding; ask the user to check the first drop lands on the accented click. |
| `CHECK: possible tempo change / drift` | **Do not straight-warp.** Report the off-tempo windows (e.g. "150-165 s ≈ 140, 180 s+ = 112"). Options: per-bar markers via `set_warp_markers` from a beat tracker, or the user does Live's plain "Warp From Here" and fixes sections. Get the user's decision. |
| warp_clip grid FAIL on one 30 s window | Run `scripts/check_bands.py` (clap/hat/broad medians + onsets at section bars). Swung percussion or a beatless break can fail one window with a correct grid. Report the FAIL and the evidence; never call it a pass. |
| warp_clip decode-check WARNING | MP3 offset rule unverified for this file: apply with `--force` only after telling the user, then confirm by ear. |

## Facts that decide correctness (each one caused a real wrong warp)

| Fact | Consequence |
|---|---|
| **Ableton does not trim MP3 encoder delay and decodes the LAME/Xing info frame as audio.** Ableton time = gapless-decoder time + (encoder_delay + 1152) samples, usually 2257 = **51.2 ms**; `sample_length == untrimmed + offset`. FLAC/WAV: 0. | Times from librosa/ffmpeg are 51 ms early for MP3s. analyze_track adds it; warp_clip verifies it via sample_length. Proven with a click-track MP3: all 64 clicks sat exactly +2257 samples in Live's decoded file. Count samples at the file's **native** rate: a 48 kHz MP3 is +2257 samples = **47.0 ms** (proven via the decoding cache, corr 1.0), not 51.2 ms. |
| MP3 **without** a LAME/Xing info frame (ffprobe start_time 0.000000): offset is **0** (proven via the decoding cache, corr 1.0), but Live's sample_length can still exceed the prediction by a few hundred samples of tail padding. | warp_clip's decode check then WARNs although the offset is right: confirm the offset by cross-correlating the cache wav with the ffmpeg decode, then use `--force`. |
| **Ground truth = Live's decoding cache.** Live writes every decoded MP3 to `~/Library/Caches/Ableton/Cache/Decoding/<file name>.wav` (macOS); its sample 0 = Ableton time 0. | When the user says "the grid looks off", measure onsets in THAT wav against the clip's warp markers (beat b at marker0 + b·60/bpm) instead of asking them to zoom and compare. Waveform overviews smear transients by tens of ms; a hit that "looks early" on screen can be on the line in the audio. |
| Use **backtracked onset times** (attack start), not onset-strength peaks. | Peaks sit 5-15 ms late; a 10 ms early/late grid is audible to a DJ. |
| **Kick band is unreliable** under long 808/sub notes (±30 ms jitter); clap/hat bands are tight. | Fit BPM/phase on clap+hat; use low end only to choose beat vs off-beat. |
| Busy 16th claps/hats can lock the grid to an 8th/16th **off-beat**. | analyze_track tests all four 16th positions by low-end energy. Symptom: few onsets "on grid", 1.1.1 a quarter/half beat off. |
| Club tracks almost always start on a downbeat; sections start on bars 8k+1. Some don't (e.g. 2-bar pre-roll: drops at 19, 43…). | Keep 1.1.1 at the first downbeat; tell the user when sections are offset instead of shifting 1.1.1 by bars. |
| Sections land on bars 8k (one bar early) and the file has an earlier downbeat. | Move 1.1.1 one bar earlier so sections land on 8k+1. With a genuine 4-bar intro (sections at 5, 21, 37…), keep 1.1.1 and tell the user. |
| Beatless intros give bogus tempo windows (e.g. "137" in a 140 track). | Judge tempo on the drum sections only. |
| Live's plain **"Warp From Here" is auto-warp**: follows transients and misreads beatless intros/outros (an outro read as 152-162 BPM → 1.2 s off at the end). | Constant tracks: straight grid only ("Warp <BPM> BPM From Here" = set_clip_warp). |
| Master tempo ≠ track tempo is fine: markers are in beats; Complex Pro keeps key. **Never Re-Pitch** (150→140 = -1.2 semitones, breaks Camelot). | Warp at the track's own BPM; the set tempo (e.g. 140) stretches it. |
| Even a 140 track in a 140 set must be warped: unwarped clips ignore the grid offset and master tempo changes. | Always warp. |
| "Auto-Warp Long Samples" off → new long clips arrive unwarped; Seg. BPM may show 120. | Expected. A saved .asd (Save Default Clip) restores the warp on the next drag. |
| **Unlooped clip End = `loop_end`, not `end_marker`.** | Judge clip length via `get_track_info` length. Misreading end_marker produced a false "End is wrong" diagnosis once. |

## Red flags - stop and re-check

- About to tell the user a setting is wrong → read it back from Live first (and from the angle they see: clip length, Start/End).
- Overwriting a warp the user made by hand → ask first; read their markers (they encode what their ear accepted).
- `grid check` medians drift across the track, or <40 % of onsets on grid → BPM or phase is wrong, or tempo varies.
- Reporting success without warp_clip exit 0.

## Explaining the manual method to the user

Warp on, Complex Pro → project tempo = track BPM → zoom to the first downbeat transient (attack start,
not the peak; on clap/hat if the kick is buried in sub) → double-click to make a marker → right-click
**Set 1.1.1 Here** → right-click **Warp <BPM> BPM From Here** → metronome check at the start, a drop,
and the last drum bar → Save Default Clip → set tempo back. Anchor can be any clear downbeat later in the
song (grid extends backwards); 1.1.1 can be moved afterwards with Set 1.1.1 Here **on a bar line** - it
only relabels, it does not re-warp.
