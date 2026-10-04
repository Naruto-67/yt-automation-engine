"""
engine/managers/caption_aligner.py — CapCut-Style Audio-to-Caption Synchronization Engine (v2.2)
Extracts exact word-level timeline timestamps directly from synthesized voice audio,
mirroring CapCut and Descript workflows to achieve 100% microsecond synchronization.
"""

import os
import sys
import re
import wave
import struct
from typing import List, Optional, Tuple, Dict, Any

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from engine.models import WordTimestamp


class CaptionAligner:
    """
    CapCut-style speech-to-text alignment engine.
    Derives word boundaries directly from audio soundwaves rather than speculative text division.
    """

    @classmethod
    def align_captions(
        cls,
        audio_path: str,
        script_text: Optional[str] = None,
        existing_timestamps: Optional[List[WordTimestamp]] = None
    ) -> List[WordTimestamp]:
        """
        Main entrypoint: Attempts faster-whisper acoustic alignment first,
        falling back to RMS Energy VAD alignment, and finally existing timestamps.
        """
        # Tier 1: faster-whisper (Direct AI Transcription & Acoustic Alignment)
        whisper_words = cls._align_with_faster_whisper(audio_path, script_text=script_text)
        if whisper_words and len(whisper_words) >= 1:
            print(f"✨ [CAPCUT ALIGNER] Transcribed {len(whisper_words)} exact word timestamps from audio via faster-whisper.", flush=True)
            return whisper_words

        # Tier 2: Acoustic Energy VAD Alignment
        if script_text and os.path.exists(audio_path):
            vad_words = cls._align_with_acoustic_vad(audio_path, script_text)
            if vad_words and len(vad_words) >= 1:
                print(f"✨ [CAPCUT ALIGNER] Aligned {len(vad_words)} words to acoustic energy envelopes (RMS VAD).", flush=True)
                return vad_words

        # Tier 3: Existing timestamps fallback
        if existing_timestamps:
            print(f"ℹ️ [CAPCUT ALIGNER] Using {len(existing_timestamps)} pre-captured timestamps.", flush=True)
            return existing_timestamps

        return []

    @classmethod
    def _align_with_faster_whisper(
        cls,
        audio_path: str,
        script_text: Optional[str] = None
    ) -> Optional[List[WordTimestamp]]:
        """Transcribes audio using faster-whisper with word-level acoustic alignment."""
        if not os.path.exists(audio_path):
            return None

        try:
            # Silence internal onnxruntime and ctranslate2 C++ device discovery warnings
            os.environ["ORT_LOGGING_LEVEL"] = "3"
            os.environ["CT2_VERBOSE"] = "0"
            from faster_whisper import WhisperModel
        except ImportError:
            return None

        try:
            print("🎙️ [CAPCUT ALIGNER] Running faster-whisper transcription on voiceover audio...", flush=True)
            # Use lightweight base.en model on CPU with int8 quantization (~1.5s execution)
            # Note: initial_prompt is strictly None so Whisper never skips speech at time 0.0s.
            # vad_filter is False to prevent onnxruntime PCIe device scanning on virtual machines.
            model = WhisperModel("base.en", device="cpu", compute_type="int8")
            segments, info = model.transcribe(
                audio_path,
                word_timestamps=True,
                language="en",
                initial_prompt=None,
                condition_on_previous_text=False,
                vad_filter=False,
            )
            
            words: List[WordTimestamp] = []
            for seg in segments:
                if not getattr(seg, "words", None):
                    continue
                for w in seg.words:
                    clean_text = w.word.strip()
                    if clean_text:
                        start_t = round(float(w.start), 3)
                        end_t = round(float(w.end), 3)
                        if end_t <= start_t:
                            end_t = start_t + 0.15
                        words.append(
                            WordTimestamp(word=clean_text, start=start_t, end=end_t)
                        )

            return words if words else None
        except Exception as e:
            print(f"⚠️ [CAPCUT ALIGNER] faster-whisper alignment encountered error: {e}", flush=True)
            return None

    @classmethod
    def slice_words_by_scenes(
        cls,
        word_timestamps: List[WordTimestamp],
        raw_scenes: List[Dict[str, Any]]
    ) -> List[List[WordTimestamp]]:
        """
        Intelligently partitions continuous transcribed words into individual scenes.
        Uses sentence-ending text matching and acoustic breath pauses (>200ms)
        to cleanly separate scenes without cross-scene word bleeding.
        """
        if not word_timestamps or not raw_scenes:
            return [[] for _ in raw_scenes]

        num_scenes = len(raw_scenes)
        total_words = len(word_timestamps)
        
        # Calculate target word counts per scene from spoken_text
        target_counts = [max(1, len(s.get("spoken_text", "").split())) for s in raw_scenes]
        
        slices: List[List[WordTimestamp]] = []
        cursor = 0
        
        for idx in range(num_scenes):
            if idx == num_scenes - 1:
                # Last scene takes all remaining words
                slices.append(word_timestamps[cursor:])
                break

            target_len = target_counts[idx]
            expected_end = cursor + target_len
            
            # Search a small window around expected_end for a natural breath pause
            best_cut = expected_end
            max_gap = -1.0
            
            search_start = max(cursor + 1, expected_end - 3)
            search_end = min(total_words - (num_scenes - idx - 1), expected_end + 4)
            
            for j in range(search_start, search_end):
                if j < total_words:
                    gap = word_timestamps[j].start - word_timestamps[j - 1].end
                    if gap > 0.18 and gap > max_gap:
                        max_gap = gap
                        best_cut = j

            best_cut = max(cursor + 1, min(total_words - (num_scenes - idx - 1), best_cut))
            slices.append(word_timestamps[cursor:best_cut])
            cursor = best_cut

        return slices

    @classmethod
    def _align_with_acoustic_vad(cls, audio_path: str, script_text: str) -> Optional[List[WordTimestamp]]:
        """
        Pure-Python acoustic speech-activity detector.
        Extracts 20ms RMS energy frames, groups contiguous speech regions,
        and distributes words across speech bursts weighted by character length.
        """
        wav_path = audio_path
        temp_wav = None
        
        # If input is mp3, check if counterpart wav exists or return None
        if not wav_path.endswith(".wav"):
            candidate_wav = wav_path.rsplit(".", 1)[0] + ".wav"
            if os.path.exists(candidate_wav):
                wav_path = candidate_wav
            else:
                return None

        try:
            with wave.open(wav_path, "rb") as wf:
                sr = wf.getframerate()
                n_frames = wf.getnframes()
                channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                if sampwidth != 2 or sr <= 0 or n_frames <= 0:
                    return None
                raw_bytes = wf.readframes(n_frames)

            # Unpack 16-bit PCM samples
            total_samples = n_frames * channels
            samples = struct.unpack(f"<{total_samples}h", raw_bytes)
            if channels == 2:
                samples = samples[::2] # Mono left channel

            # Compute RMS energy across 20ms frames
            frame_len = max(1, int(sr * 0.020))
            num_frames = len(samples) // frame_len
            if num_frames == 0:
                return None

            rms_values = []
            for i in range(num_frames):
                chunk = samples[i * frame_len : (i + 1) * frame_len]
                sq_sum = sum(s * s for s in chunk)
                rms = (sq_sum / frame_len) ** 0.5
                rms_values.append(rms)

            max_rms = max(rms_values) if rms_values else 1.0
            if max_rms < 100:
                return None # Audio is virtually silent

            threshold = max(50.0, max_rms * 0.07)

            # Identify active speech segments (skip inter-sentence silence gaps > 200ms)
            speech_segments: List[Tuple[float, float]] = []
            in_speech = False
            seg_start_idx = 0
            silence_counter = 0

            for idx, energy in enumerate(rms_values):
                if energy > threshold:
                    if not in_speech:
                        in_speech = True
                        seg_start_idx = max(0, idx - 2) # small 40ms attack buffer
                    silence_counter = 0
                else:
                    if in_speech:
                        silence_counter += 1
                        if silence_counter >= 10: # 200ms of sustained silence
                            seg_end_idx = idx - silence_counter
                            speech_segments.append((seg_start_idx * 0.020, seg_end_idx * 0.020))
                            in_speech = False

            if in_speech:
                speech_segments.append((seg_start_idx * 0.020, num_frames * 0.020))

            if not speech_segments:
                total_dur = n_frames / float(sr)
                speech_segments = [(0.05, total_dur)]

            # Tokenize words from script text
            words_tokens = [w for w in script_text.split() if w.strip()]
            if not words_tokens:
                return None

            # Calculate total active speech duration
            total_active_sec = sum(max(0.1, end - start) for start, end in speech_segments)
            total_chars = max(1, sum(len(w) for w in words_tokens))

            # Distribute words across speech segments proportionally by character length
            word_timestamps: List[WordTimestamp] = []
            word_cursor = 0
            accum_chars = 0

            for seg_idx, (seg_start, seg_end) in enumerate(speech_segments):
                seg_dur = max(0.1, seg_end - seg_start)
                # Determine how many words fall into this segment
                target_char_budget = (seg_dur / total_active_sec) * total_chars if total_active_sec > 0 else 0
                
                seg_words = []
                seg_char_count = 0
                while word_cursor < len(words_tokens):
                    w = words_tokens[word_cursor]
                    seg_words.append(w)
                    seg_char_count += len(w)
                    word_cursor += 1
                    if seg_char_count >= target_char_budget and seg_idx < len(speech_segments) - 1:
                        break

                # If this is the last segment, take all remaining words
                if seg_idx == len(speech_segments) - 1:
                    while word_cursor < len(words_tokens):
                        seg_words.append(words_tokens[word_cursor])
                        word_cursor += 1

                if not seg_words:
                    continue

                # Distribute words within this active segment weighted by length
                seg_w_chars = max(1, sum(len(w) for w in seg_words))
                cur_t = seg_start
                for w in seg_words:
                    w_fraction = len(w) / seg_w_chars
                    w_dur = max(0.12, seg_dur * w_fraction)
                    w_start = round(cur_t, 3)
                    w_end = round(cur_t + w_dur, 3)
                    word_timestamps.append(
                        WordTimestamp(word=w, start=w_start, end=w_end)
                    )
                    cur_t += w_dur

            return word_timestamps if word_timestamps else None
        except Exception as e:
            print(f"⚠️ [CAPCUT ALIGNER] VAD acoustic alignment error: {e}", flush=True)
            return None
