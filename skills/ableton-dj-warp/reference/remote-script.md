# AbletonMCP Remote Script: warp commands

The stock AbletonMCP server (github.com/ahujasid/ableton-mcp) has **no warp commands**. This skill
talks straight to the Remote Script socket (`127.0.0.1:9877`, JSON `{"type", "params"}`) with
`scripts/live.py`. The extra commands below must be patched into the Remote Script.

Location (macOS): `~/Music/Ableton/User Library/Remote Scripts/AbletonMCP/__init__.py`

## Check whether the patch is installed

```bash
python3 -I scripts/live.py set_clip_markers '{"track_index":999}'
```
- `"Unknown command: set_clip_markers"` → not installed / Live not restarted
- `"Track index out of range"` → installed and loaded

## Install

1. Back up `__init__.py`.
2. Paste the methods from `remote_script_warp_methods.py` into the ControlSurface class (next to `_create_locator`).
3. Add the 4 command names to the **main-thread** command list (the `if command_type in [...]` that builds a `response_queue`):
   `"set_clip_warp", "get_clip_warp", "set_warp_markers", "set_clip_markers"`
4. Add the dispatch branches inside that main-thread task:

```python
elif command_type == "set_clip_warp":
    result = self._set_clip_warp(params.get("track_index", 0), params.get("clip_index", 0),
                                 params.get("bpm"), params.get("downbeat_sec"), params.get("warp_mode", 6))
elif command_type == "set_warp_markers":
    result = self._set_warp_markers(params.get("track_index", 0), params.get("clip_index", 0),
                                    params.get("markers", []), params.get("warp_mode", 6))
elif command_type == "set_clip_markers":
    result = self._set_clip_markers(params.get("track_index", 0), params.get("clip_index", 0), params)
elif command_type == "get_clip_warp":
    result = self._get_clip_warp(params.get("track_index", 0), params.get("clip_index", 0))
```
5. `python3 -m py_compile __init__.py`
6. **Fully quit and reopen Live.** Toggling the Control Surface in Preferences does NOT reload Python
   modules. Tell the user to save (Cmd+S) first; unsaved clips are lost on restart.

## Commands

| Command | Params | Does |
|---|---|---|
| `get_clip_warp` | track_index, clip_index | warping, warp_mode, looping, start/end_marker, sample_length, sample_rate, warp_markers [{beat_time, sample_time(s)}] |
| `set_clip_warp` | track_index, clip_index, bpm, downbeat_sec, warp_mode=6 | straight grid: marker (0 → downbeat_sec) and (last full bar → downbeat + n·60/bpm); removes other markers; warping on, loop off, start 0, end_marker last full bar. Equivalent of "Set 1.1.1 Here" + "Warp <bpm> BPM From Here". |
| `set_warp_markers` | track_index, clip_index, markers [{beat_time, sample_time}], warp_mode=6 | arbitrary marker list (variable-tempo tracks). Beat 0 = 1.1.1. Both columns must increase. |
| `set_clip_markers` | track_index, clip_index, start, end, looping, loop_start, loop_end (beats) | play range / loop brace without touching warp markers. |
| `create_audio_clip` (stock) | track_index, clip_index, path | load a file into a Session slot (Live 12.0.5+). |
| `create_audio_track` (stock) | index (-1 = end) | |
| `set_clip_name`, `set_track_name`, `get_track_info`, `get_session_info`, `delete_clip` (stock) | | |

`warp_mode`: 0 Beats, 1 Tones, 2 Texture, 3 Re-Pitch, 4 Complex, 6 Complex Pro.

## Live API facts learned the hard way

- **Unlooped clip: the Clip View "End" field is `loop_end`, NOT `end_marker`.** `end_marker` is a separate
  sample marker. Reading `end_marker` to judge a clip's length gives wrong answers. Use
  `get_track_info` → clip `length` (beats), or `loop_start/loop_end`.
- Turning looping off restores Live's remembered unlooped end. Reliable sequence for a range [S, E]:
  `set_clip_markers {looping:true, loop_start:S, loop_end:E, start:S}` then
  `set_clip_markers {looping:false, start:S, end:E}`. This also sets the loop brace (Position/Length),
  otherwise Position/Length stay at the full song.
- `set_clip_warp` sometimes fails the first call while moving marker 0. Retry. If the error is
  `Segment length out of range` (an old marker has the same sample time at another beat, e.g. the
  user dragged 1.1.1), warp to `downbeat + 0.5 s` first, then to the target.
- Live adds a tiny helper marker 1/32 beat after the last marker (e.g. 360.03125). Harmless.
- Clip View "Seg. BPM" can show **120** on clips whose visible region contains no warp marker
  (section clips, looped clips). Display only: playback follows the markers. Never "fix" it by typing
  in the BPM box. Clicking a warp marker shows the true value.
- There is no API for: Save Default Clip (.asd), Follow Actions, launch quantization, "Warp From Here"
  (Live's auto-warp). Ask the user to press the disk icon in the clip title bar.
