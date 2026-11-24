# --- AbletonMCP Remote Script patch: warp commands (paste these methods into the AbletonMCP ControlSurface class) ---
# Source: AbletonMCP __init__.py (ahujasid/ableton-mcp), extended. Requires Live 12 (Clip.add_warp_marker / remove_warp_marker).

    def _session_audio_clip(self, track_index, clip_index):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        if clip_index < 0 or clip_index >= len(track.clip_slots):
            raise IndexError("Clip index out of range")
        slot = track.clip_slots[clip_index]
        if not slot.has_clip:
            raise Exception("No clip in slot")
        clip = slot.clip
        if not clip.is_audio_clip:
            raise Exception("Clip is not an audio clip")
        return clip

    def _warp_marker_list(self, clip):
        out = []
        for m in clip.warp_markers:
            out.append({"beat_time": float(m.beat_time), "sample_time": float(m.sample_time)})
        return out

    def _get_clip_warp(self, track_index, clip_index):
        clip = self._session_audio_clip(track_index, clip_index)
        return {
            "name": clip.name,
            "warping": bool(clip.warping),
            "warp_mode": int(clip.warp_mode),
            "looping": bool(clip.looping),
            "start_marker": float(clip.start_marker),
            "end_marker": float(clip.end_marker),
            "sample_length": int(clip.sample_length),
            "sample_rate": float(clip.sample_rate),
            "warp_markers": self._warp_marker_list(clip),
        }

    def _add_warp_marker(self, clip, beat_time, sample_time):
        import Live
        errors = []
        try:
            clip.add_warp_marker(Live.Clip.WarpMarker(beat_time=beat_time, sample_time=sample_time))
            return
        except Exception as e:
            errors.append("kw:" + str(e))
        try:
            clip.add_warp_marker(Live.Clip.WarpMarker(sample_time, beat_time))
            return
        except Exception as e:
            errors.append("pos:" + str(e))
        try:
            clip.add_warp_marker({"beat_time": beat_time, "sample_time": sample_time})
            return
        except Exception as e:
            errors.append("dict:" + str(e))
        doc = ""
        try:
            doc = str(Live.Clip.WarpMarker.__init__.__doc__) + " | " + str(clip.add_warp_marker.__doc__)
        except Exception:
            pass
        raise Exception("add_warp_marker failed: %s ; doc: %s" % (errors, doc))

    def _set_clip_warp(self, track_index, clip_index, bpm, downbeat_sec, warp_mode=6):
        """Warp an audio clip on a straight grid: beat 0 (1.1.1) at downbeat_sec,
        constant `bpm` to the end. warp_mode: 0 Beats, 1 Tones, 2 Texture,
        3 Re-Pitch, 4 Complex, 6 Complex Pro."""
        if bpm is None or downbeat_sec is None:
            raise ValueError("bpm and downbeat_sec are required")
        bpm = float(bpm)
        t0 = float(downbeat_sec)
        if bpm <= 0:
            raise ValueError("bpm must be positive")
        clip = self._session_audio_clip(track_index, clip_index)
        before = self._warp_marker_list(clip)

        clip.warping = True
        clip.looping = False

        spb = 60.0 / bpm
        duration = float(clip.sample_length) / float(clip.sample_rate)
        if t0 < 0 or t0 >= duration:
            raise ValueError("downbeat_sec outside the sample")
        n_beats = int((duration - t0) / spb)
        n_end = max(4, n_beats - (n_beats % 4))  # last full bar boundary
        targets = [(0.0, t0), (float(n_end), t0 + n_end * spb)]

        # Remove existing markers that differ from the targets, add the targets.
        def same(m, tgt):
            return abs(m["beat_time"] - tgt[0]) < 1e-6 and abs(m["sample_time"] - tgt[1]) < 1e-4

        # First add target markers whose beat_time is not occupied.
        occupied = set(round(m["beat_time"], 6) for m in self._warp_marker_list(clip))
        pending = []
        for tgt in targets:
            if round(tgt[0], 6) in occupied:
                pending.append(tgt)
            else:
                self._add_warp_marker(clip, tgt[0], tgt[1])
        # Remove every marker that is not a target.
        for m in self._warp_marker_list(clip):
            if not any(same(m, t) for t in targets):
                try:
                    clip.remove_warp_marker(m["beat_time"])
                except Exception as e:
                    self.log_message("remove_warp_marker failed: " + str(e))
        # Add targets that were blocked by an old marker at the same beat.
        current = self._warp_marker_list(clip)
        for tgt in pending:
            if not any(same(m, tgt) for m in current):
                self._add_warp_marker(clip, tgt[0], tgt[1])
        # Clean up anything left over (e.g. markers Live refused to drop earlier).
        for m in self._warp_marker_list(clip):
            if not any(same(m, t) for t in targets):
                try:
                    clip.remove_warp_marker(m["beat_time"])
                except Exception as e:
                    self.log_message("remove_warp_marker (2nd pass) failed: " + str(e))

        clip.warp_mode = int(warp_mode)
        # Clip starts at 1.1.1 and plays to the last full bar.
        try:
            clip.end_marker = float(n_end)
            clip.start_marker = 0.0
        except Exception as e:
            self.log_message("start/end marker set failed: " + str(e))

        result = self._get_clip_warp(track_index, clip_index)
        result["markers_before"] = before
        result["target_bpm"] = bpm
        result["downbeat_sec"] = t0
        return result

    def _set_warp_markers(self, track_index, clip_index, markers, warp_mode=6):
        """Replace all warp markers with the given list of
        {"beat_time": float, "sample_time": float (seconds)}. Beat 0 becomes 1.1.1.
        The clip plays from beat 0 to the last marker; looping off."""
        if not markers or len(markers) < 2:
            raise ValueError("At least two markers are required")
        targets = sorted([(float(m["beat_time"]), float(m["sample_time"])) for m in markers])
        for (b1, s1), (b2, s2) in zip(targets, targets[1:]):
            if not (b2 > b1 and s2 > s1):
                raise ValueError("Markers must increase in both beat_time and sample_time")
        clip = self._session_audio_clip(track_index, clip_index)
        duration = float(clip.sample_length) / float(clip.sample_rate)
        if targets[0][1] < 0 or targets[-1][1] > duration:
            raise ValueError("Marker sample_time outside the sample (0..%.3f s)" % duration)
        before = self._warp_marker_list(clip)
        clip.warping = True
        clip.looping = False

        def same(m, tgt):
            return abs(m["beat_time"] - tgt[0]) < 1e-6 and abs(m["sample_time"] - tgt[1]) < 1e-4

        occupied = set(round(m["beat_time"], 6) for m in self._warp_marker_list(clip))
        pending = []
        for tgt in targets:
            if round(tgt[0], 6) in occupied:
                pending.append(tgt)
            else:
                self._add_warp_marker(clip, tgt[0], tgt[1])
        for m in self._warp_marker_list(clip):
            if not any(same(m, t) for t in targets):
                try:
                    clip.remove_warp_marker(m["beat_time"])
                except Exception as e:
                    self.log_message("remove_warp_marker failed: " + str(e))
        current = self._warp_marker_list(clip)
        for tgt in pending:
            if not any(same(m, tgt) for m in current):
                self._add_warp_marker(clip, tgt[0], tgt[1])
        for m in self._warp_marker_list(clip):
            if not any(same(m, t) for t in targets):
                try:
                    clip.remove_warp_marker(m["beat_time"])
                except Exception as e:
                    self.log_message("remove_warp_marker (2nd pass) failed: " + str(e))

        clip.warp_mode = int(warp_mode)
        try:
            clip.end_marker = targets[-1][0]
            clip.start_marker = 0.0
        except Exception as e:
            self.log_message("start/end marker set failed: " + str(e))
        result = self._get_clip_warp(track_index, clip_index)
        result["markers_before_count"] = len(before)
        result["requested_count"] = len(targets)
        return result

    def _set_clip_markers(self, track_index, clip_index, params):
        """Set play region / loop of a session audio clip without touching warp markers.
        Optional params (beats): start, end, looping (bool), loop_start, loop_end."""
        clip = self._session_audio_clip(track_index, clip_index)
        before = {"start": float(clip.start_marker), "end": float(clip.end_marker),
                  "looping": bool(clip.looping),
                  "loop_start": float(clip.loop_start), "loop_end": float(clip.loop_end)}

        def set_pair(obj, a_name, a_val, b_name, b_val):
            # Live rejects start >= end at any moment; try both orders.
            errs = []
            for order in ((a_name, a_val, b_name, b_val), (b_name, b_val, a_name, a_val)):
                try:
                    if order[1] is not None:
                        setattr(obj, order[0], float(order[1]))
                    if order[3] is not None:
                        setattr(obj, order[2], float(order[3]))
                    return
                except Exception as e:
                    errs.append(str(e))
            raise ValueError("could not set %s/%s: %s" % (a_name, b_name, errs))

        if "looping" in params and params["looping"] is not None:
            clip.looping = bool(params["looping"])
        if clip.looping:
            set_pair(clip, "loop_start", params.get("loop_start"), "loop_end", params.get("loop_end"))
            if params.get("start") is not None:
                clip.start_marker = float(params["start"])
        else:
            # Unlooped clip: the Clip View "Start"/"End" fields are loop_start/loop_end
            # (Live API: "for unlooped clips, this is the clip start/end"); end_marker
            # is a separate sample marker. Set both so they agree.
            set_pair(clip, "loop_start", params.get("start"), "loop_end", params.get("end"))
            try:
                set_pair(clip, "start_marker", params.get("start"), "end_marker", params.get("end"))
            except Exception as e:
                self.log_message("start/end_marker sync failed: " + str(e))
        return {"name": clip.name, "before": before,
                "after": {"start": float(clip.start_marker), "end": float(clip.end_marker),
                          "looping": bool(clip.looping),
                          "loop_start": float(clip.loop_start), "loop_end": float(clip.loop_end)}}

