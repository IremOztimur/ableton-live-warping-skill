# ableton-dj-warp

A [Claude Code](https://claude.com/claude-code) plugin that warps full tracks in Ableton Live for DJ sets, sample-accurate.
It finds the exact BPM and the true 1.1.1 downbeat, corrects MP3 encoder delay, and checks every warp against Live's own decoded audio before reporting it as done.

You tell Claude:

> warp `5A_137_Fogo.mp3` and set 1.1.1

Claude analyzes the file, sets the grid in Live and reads it back. Real output from the check scripts on a 140 BPM track (1.1.1 = 0.4289 s):

```
clap  on-grid onsets= 306  median ms per 30 s: +0.7 +0.0 +0.7 -0.1 +1.3
hat   on-grid onsets= 305  median ms per 30 s: +0.4 +0.9 +0.5 +0.5 +0.9
bar   5 @   7.2860s  first onset vs bar line: -0.5 ms
bar  21 @  34.7146s  first onset vs bar line: +0.6 ms
```

Then you can split the track into section clips:

> 1-16 intro, 17-24 breakdown, 25-40 build, 41-72 drop, 73-96 build, 97-128 drop

## Why

- **Ableton's auto-warp drifts.** Live's "Warp From Here" follows transients and misreads beatless intros and outros. For a constant-tempo club track the right warp is one straight grid at an integer BPM. This plugin builds that grid and proves it with numbers.
- **MP3s in Ableton are 47-51 ms late.** Live doesn't trim the MP3 encoder delay and decodes the LAME/Xing info frame as audio. Ableton time = gapless time + (encoder delay + 1152) samples: 51.2 ms at 44.1 kHz, 47.0 ms at 48 kHz. Every analyzer that ignores this puts 1.1.1 audibly early. This was verified against Live's own decoding cache.
- **"Which beat is 1" is checked, not guessed.** Beat trackers often land a half or whole beat off. The plugin measures where the bass of each drop enters, per 8th note, and corrects the phase before applying.
- **Every setting is read back from Live.** Nothing is reported as done until marker positions, tempo between markers and onset alignment pass (±5 ms per 30 s window).

## What it does

| Step | Script |
|---|---|
| Exact BPM, tempo-stability check, downbeat, bar phase, MP3 offset | `analyze_track.py` |
| Bass-entry check per 8th note around the drops (catches half/one-beat phase errors) | `check_sections.py` |
| Straight-grid warp (Complex Pro), play range, then full read-back verification | `warp_clip.py` |
| Per-band (clap/hat/broad) grid check when one window fails | `check_bands.py` |
| Split into named section clips (`intro_16`, `DROP_16`, `OUTRO_LOOP_8` …) | `split_sections.py` |
| Raw socket client for the Remote Script | `live.py` |

Claude reads [`SKILL.md`](skills/ableton-dj-warp/SKILL.md), which holds the workflow and the decision rules. Each rule there comes from a real wrong warp.

## Requirements

- Ableton Live 12 (macOS tested; the decoding-cache path in the docs is macOS-specific).
- The [AbletonMCP](https://github.com/ahujasid/ableton-mcp) Remote Script, **patched with four warp commands**. Follow the steps in [`reference/remote-script.md`](skills/ableton-dj-warp/reference/remote-script.md); the methods to paste are in `remote_script_warp_methods.py`.
- `ffmpeg` / `ffprobe` on PATH.
- Python 3.10+ with the packages in [`requirements.txt`](skills/ableton-dj-warp/requirements.txt):

```bash
python3 -m venv ~/.ableton-dj-warp/venv
~/.ableton-dj-warp/venv/bin/pip install -r skills/ableton-dj-warp/requirements.txt
```

(Claude creates this venv itself if it is missing.)

## Install

In Claude Code:

```
/plugin marketplace add IremOztimur/ableton-live-warping-skill
/plugin install ableton-dj-warp@ableton-dj-warp
```

Or copy `skills/ableton-dj-warp` into `~/.claude/skills/`.

## Use

1. Open your Live Set and load the track into a Session slot (or ask Claude to load it).
2. Ask Claude to warp it. Include the BPM if the filename doesn't have it (a `1A_140_Title.mp3` style name works).
3. Check the bars Claude names against the metronome.
4. Press **Save Default Clip** (the disk icon in the clip title bar; there is no API for it) and save the set.
5. Optionally, give Claude bar ranges for section clips.

Live's API can't do these, so they stay manual: Save Default Clip (.asd), Follow Actions, launch quantization.

## Limits

- Built for constant-tempo tracks. When the analyzer finds tempo changes, it stops and asks instead of forcing a straight grid.
- Uses Complex Pro and never Re-Pitch, so keys stay intact for harmonic (Camelot) mixing.

## License

MIT. Not affiliated with or endorsed by Ableton AG. Ableton and Live are trademarks of Ableton AG.
