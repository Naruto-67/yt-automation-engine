"""
engine/managers/voice_normalizer.py — Phonetic Script Normalizer & Studio TTS Engine (v2.1)
Primary Engine: Official Kokoro-82M (hexgrad/kokoro) for studio-grade neural voice synthesis.
Fallback Engine: Edge-TTS WebSocket streamer with resilient 3-tier duration fallbacks.
"""

import os
import re
import asyncio
from typing import List, Tuple, Optional

def _int_to_words(n: int) -> str:
    """Zero-dependency pure Python number to words converter for numbers up to billions."""
    if n == 0:
        return "zero"
    if n < 0:
        return f"minus {_int_to_words(abs(n))}"

    units = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
             "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
             "seventeen", "eighteen", "nineteen"]
    tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]

    def _convert_chunk(num: int) -> str:
        parts = []
        if num >= 100:
            parts.append(f"{units[num // 100]} hundred")
            num %= 100
        if num >= 20:
            parts.append(tens[num // 10])
            num %= 10
        if num > 0:
            parts.append(units[num])
        return " ".join(parts)

    scales = [(1_000_000_000, "billion"), (1_000_000, "million"), (1_000, "thousand")]
    result = []
    for scale_val, scale_name in scales:
        if n >= scale_val:
            chunk = n // scale_val
            result.append(f"{_convert_chunk(chunk)} {scale_name}")
            n %= scale_val

    if n > 0:
        result.append(_convert_chunk(n))

    return " ".join(result).strip()


try:
    from num2words import num2words
except ImportError:
    def num2words(n: int) -> str:
        return _int_to_words(int(n))

from engine.models import WordTimestamp


class VoiceNormalizer:
    """Sanitizes text for natural TTS pronunciation while capturing exact word-level timing."""

    @classmethod
    def normalize_text(cls, text: str) -> str:
        """
        Translates numbers, symbols, and abbreviations into spoken phonetic English.
        Leaves raw text for display captions untouched.
        """
        # 0. Strip markdown bold / italic formatting
        text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
        text = text.replace("**", "").replace("*", "")

        # 0b. Strip leading ellipses, dots, hyphens, and whitespace to prevent silence delay
        text = re.sub(r"^[\.\s…\-]+", "", text).strip()
        if text and text[0].islower():
            text = text[0].upper() + text[1:]

        # 1. Expand currency: e.g. $100 -> one hundred dollars
        def replace_currency(match):
            amount = match.group(1).replace(",", "")
            try:
                words = num2words(int(amount))
                return f"{words} dollars"
            except Exception:
                return f"{amount} dollars"

        text = re.sub(r"\$(\d+(?:,\d+)*(?:\.\d+)?)", replace_currency, text)

        # 2. Expand percentages: 15% -> fifteen percent
        def replace_percent(match):
            num = match.group(1).replace(",", "")
            try:
                words = num2words(int(num))
                return f"{words} percent"
            except Exception:
                return f"{num} percent"

        text = re.sub(r"(\d+)%", replace_percent, text)

        # 3. Expand hashtag ranking: #1 -> number 1
        text = re.sub(r"#(\d+)", r"number \1", text)

        # 4. Expand raw numbers: e.g. 125 -> one hundred and twenty-five
        def replace_numbers(match):
            start = match.start()
            if start >= 7 and text[start-7:start].lower() == "number ":
                return match.group(0)
            num = match.group(0).replace(",", "")
            try:
                return num2words(int(num))
            except Exception:
                return num

        text = re.sub(r"\b\d+\b", replace_numbers, text)

        # 5. Expand common symbols and abbreviations
        abbreviations = {
            r"\be\.g\.?(?=\s|$)": "for example",
            r"\bi\.e\.?(?=\s|$)": "that is",
            r"\bvs\.?(?=\s|$)": "versus",
            r"\bDr\.?(?=\s|$)": "Doctor",
            r"\bMr\.?(?=\s|$)": "Mister",
            r"\bMrs\.?(?=\s|$)": "Missus",
            r"&": "and",
            r"@": "at",
        }
        for pattern, replacement in abbreviations.items():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        # 6. Normalize extra whitespace
        text = re.sub(r"\s+", " ", text).strip()

        return text

    # ─── KOKORO VOICE CATALOG & FALLBACK MAPPINGS ────────────────────────────────
    KOKORO_VOICES = {
        # American English (Female)
        "af_heart": "American Female - Heart (Flagship, Warm & Natural)",
        "af_bella": "American Female - Bella (High Energy, Viral & Punchy)",
        "af_nicole": "American Female - Nicole (Whisper / ASMR / Intimate)",
        "af_sarah": "American Female - Sarah (Conversational & Friendly)",
        "af_aoede": "American Female - Aoede (Storyteller)",
        "af_kore": "American Female - Kore (Direct & Clear)",
        "af_alloy": "American Female - Alloy",
        "af_nova": "American Female - Nova",
        "af_sky": "American Female - Sky",
        "af_jessica": "American Female - Jessica",
        "af_river": "American Female - River",
        # American English (Male)
        "am_michael": "American Male - Michael (Documentary & Authoritative)",
        "am_fenrir": "American Male - Fenrir (Cinematic Baritone)",
        "am_puck": "American Male - Puck (Youthful & Animated)",
        "am_echo": "American Male - Echo",
        "am_eric": "American Male - Eric",
        "am_liam": "American Male - Liam",
        "am_onyx": "American Male - Onyx",
        # British English
        "bf_emma": "British Female - Emma (BBC Narrator, High Quality)",
        "bf_isabella": "British Female - Isabella",
        "bm_george": "British Male - George (Classic British Documentary)",
        "bm_fable": "British Male - Fable",
        # International
        "hf_alpha": "Hindi Female - Alpha",
        "hf_beta": "Hindi Female - Beta",
        "hm_omega": "Hindi Male - Omega",
        "hm_psi": "Hindi Male - Psi",
        "ff_siwis": "French Female - Siwis",
        "ef_dora": "Spanish Female - Dora",
        "em_alex": "Spanish Male - Alex",
        "if_sara": "Italian Female - Sara",
        "im_nicola": "Italian Male - Nicola",
        "pf_dora": "Portuguese Female - Dora",
        "pm_alex": "Portuguese Male - Alex",
        "jf_alpha": "Japanese Female - Alpha",
        "zf_xiaobei": "Mandarin Female - Xiaobei",
        "zm_yunjian": "Mandarin Male - Yunjian",
    }

    KOKORO_TO_EDGE_VOICE_MAP = {
        "af_heart": "en-US-JennyNeural",
        "af_bella": "en-US-AvaNeural",
        "af_nicole": "en-US-AnaNeural",
        "af_sarah": "en-US-JennyNeural",
        "af_aoede": "en-US-MichelleNeural",
        "af_kore": "en-US-JennyNeural",
        "af_alloy": "en-US-MichelleNeural",
        "af_nova": "en-US-AvaNeural",
        "af_sky": "en-US-JennyNeural",
        "af_jessica": "en-US-JennyNeural",
        "af_river": "en-US-JennyNeural",
        "am_michael": "en-US-GuyNeural",
        "am_fenrir": "en-US-GuyNeural",
        "am_adam": "en-US-GuyNeural",
        "am_puck": "en-US-EricNeural",
        "am_echo": "en-US-GuyNeural",
        "am_eric": "en-US-EricNeural",
        "am_liam": "en-US-GuyNeural",
        "am_onyx": "en-US-GuyNeural",
        "bf_emma": "en-GB-RyanNeural",
        "bf_isabella": "en-GB-ThomasNeural",
        "bm_george": "en-GB-RyanNeural",
        "bm_fable": "en-GB-ThomasNeural",
        "hf_alpha": "hi-IN-MadhurNeural",
        "hf_beta": "hi-IN-MadhurNeural",
        "hm_omega": "hi-IN-MadhurNeural",
        "hm_psi": "hi-IN-MadhurNeural",
        "ff_siwis": "fr-FR-HenriNeural",
        "ef_dora": "es-ES-AlvaroNeural",
        "em_alex": "es-ES-AlvaroNeural",
        "if_sara": "it-IT-DiegoNeural",
        "im_nicola": "it-IT-DiegoNeural",
        "pf_dora": "pt-BR-AntonioNeural",
        "pm_alex": "pt-BR-AntonioNeural",
        "jf_alpha": "ja-JP-KeitaNeural",
        "zf_xiaobei": "zh-CN-YunxiNeural",
        "zm_yunjian": "zh-CN-YunxiNeural",
    }

    FEMALE_KOKORO_TO_MALE_MAP = {
        "af_heart": "am_adam",
        "af_bella": "am_fenrir",
        "af_nicole": "am_adam",
        "af_sarah": "am_puck",
        "af_aoede": "am_adam",
        "af_kore": "am_adam",
        "af_alloy": "am_adam",
        "af_nova": "am_fenrir",
        "af_sky": "am_adam",
        "af_jessica": "am_adam",
        "af_river": "am_adam",
        "bf_emma": "bm_george",
        "bf_isabella": "bm_fable",
        "hf_alpha": "hm_omega",
        "hf_beta": "hm_psi",
        "ff_siwis": "am_adam",
        "ef_dora": "em_alex",
        "if_sara": "im_nicola",
        "pf_dora": "pm_alex",
        "jf_alpha": "am_adam",
        "zf_xiaobei": "zm_yunjian",
    }

    FEMALE_EDGE_TO_MALE_MAP = {
        "en-US-JennyNeural": "en-US-GuyNeural",
        "en-US-AvaNeural": "en-US-GuyNeural",
        "en-US-AnaNeural": "en-US-GuyNeural",
        "en-US-MichelleNeural": "en-US-GuyNeural",
        "en-US-AriaNeural": "en-US-GuyNeural",
        "en-GB-SoniaNeural": "en-GB-RyanNeural",
        "en-GB-MaisieNeural": "en-GB-ThomasNeural",
        "hi-IN-SwaraNeural": "hi-IN-MadhurNeural",
        "fr-FR-DeniseNeural": "fr-FR-HenriNeural",
        "es-ES-ElviraNeural": "es-ES-AlvaroNeural",
        "it-IT-ElsaNeural": "it-IT-DiegoNeural",
        "pt-BR-FranciscaNeural": "pt-BR-AntonioNeural",
        "ja-JP-NanamiNeural": "ja-JP-KeitaNeural",
        "zh-CN-XiaoxiaoNeural": "zh-CN-YunxiNeural",
    }

    @classmethod
    def enforce_male_voice(cls, voice: str) -> str:
        """
        Enforces male-only voices across all speech synthesis tiers.
        Remaps any requested female voice IDs to their premier male counterpart.
        """
        if not voice:
            return "am_adam"

        v = voice.strip()
        # Direct Kokoro female mapping
        if v in cls.FEMALE_KOKORO_TO_MALE_MAP:
            return cls.FEMALE_KOKORO_TO_MALE_MAP[v]

        # Direct Edge-TTS female mapping
        if v in cls.FEMALE_EDGE_TO_MALE_MAP:
            return cls.FEMALE_EDGE_TO_MALE_MAP[v]

        # Pattern check for Kokoro female voices (e.g. af_*, bf_*, etc.)
        if len(v) >= 2 and v[1] == "f" and "_" in v:
            return "am_adam"

        # Edge-TTS general female heuristic check
        female_edge_keywords = [
            "jenny", "ava", "ana", "michelle", "aria", "sonia", "maisie",
            "swara", "denise", "elvira", "elsa", "francisca", "nanami", "xiaoxiao"
        ]
        if any(kw in v.lower() for kw in female_edge_keywords):
            return "en-US-GuyNeural"

        return v

    @classmethod
    def detect_lang_code(cls, voice: str) -> str:
        """Infers Kokoro language code ('a', 'b', 'h', 'f', 'e', 'i', 'p', 'j', 'z') from voice name."""
        if not voice:
            return "a"
        primary = voice.split("+")[0].strip()
        if len(primary) >= 2 and primary[1] in ("f", "m") and "_" in primary:
            code = primary[0].lower()
            if code in ("a", "b", "e", "f", "h", "i", "j", "p", "z"):
                return code
        return "a"

    @classmethod
    def is_kokoro_voice(cls, voice: str) -> bool:
        """Checks whether the given voice name represents a Kokoro voice identifier."""
        if not voice:
            return False
        primary = voice.split("+")[0].strip()
        return (
            primary in cls.KOKORO_VOICES
            or (len(primary) >= 2 and primary[1] in ("f", "m") and "_" in primary)
        )

    @classmethod
    def _synthesize_kokoro(
        cls,
        phonetic_text: str,
        output_audio_path: str,
        voice: str = "am_michael",
        speed: float = 1.0,
    ) -> Tuple[float, List[WordTimestamp]]:
        """
        Primary TTS: Synthesizes high-fidelity speech via official hexgrad/kokoro KPipeline.
        Exact microsecond duration and word timestamps derived from 24kHz audio buffers.
        """
        import warnings
        warnings.filterwarnings("ignore", category=UserWarning)
        warnings.filterwarnings("ignore", category=FutureWarning)
        from kokoro import KPipeline
        import soundfile as sf
        import numpy as np

        lang_code = cls.detect_lang_code(voice)
        print(f"🎙️ [KOKORO] Initializing official KPipeline (lang_code='{lang_code}', voice='{voice}', speed={speed})...", flush=True)

        pipeline = KPipeline(lang_code=lang_code, repo_id="hexgrad/Kokoro-82M")
        generator = pipeline(phonetic_text, voice=voice, speed=speed)

        all_chunks = []
        word_timestamps: List[WordTimestamp] = []
        current_time = 0.0

        for i, item in enumerate(generator):
            if not item:
                continue
            gs = item[0] if len(item) > 0 else ""
            audio = item[2] if len(item) > 2 else None

            if audio is None:
                continue

            if hasattr(audio, "cpu"):
                samples = audio.cpu().numpy()
            elif hasattr(audio, "numpy"):
                samples = audio.numpy()
            else:
                samples = np.array(audio, dtype=np.float32)

            if len(samples) == 0:
                continue

            chunk_dur = len(samples) / 24000.0
            all_chunks.append(samples)

            # Map word timestamps for this chunk
            chunk_words = gs.strip().split()
            if chunk_words and chunk_dur > 0:
                w_step = chunk_dur / len(chunk_words)
                for w_idx, w in enumerate(chunk_words):
                    w_start = round(current_time + (w_idx * w_step), 3)
                    w_end = round(current_time + ((w_idx + 1) * w_step), 3)
                    word_timestamps.append(
                        WordTimestamp(word=w, start=w_start, end=w_end)
                    )

            current_time += chunk_dur

        if not all_chunks:
            raise RuntimeError("Kokoro generator produced no audio samples.")

        combined_samples = np.concatenate(all_chunks)
        total_duration = round(len(combined_samples) / 24000.0, 2)

        os.makedirs(os.path.dirname(output_audio_path) or ".", exist_ok=True)

        # Save audio
        wav_path = output_audio_path if output_audio_path.endswith(".wav") else output_audio_path.rsplit(".", 1)[0] + ".wav"
        sf.write(wav_path, combined_samples, 24000)

        if output_audio_path.endswith(".mp3"):
            converted = False
            try:
                import subprocess
                subprocess.run(
                    ["ffmpeg", "-y", "-nostats", "-loglevel", "error", "-i", wav_path, "-codec:a", "libmp3lame", "-b:a", "192k", output_audio_path],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                converted = True
            except Exception:
                pass

            if not converted:
                try:
                    from pydub import AudioSegment
                    seg = AudioSegment.from_wav(wav_path)
                    seg.export(output_audio_path, format="mp3", bitrate="192k")
                    converted = True
                except Exception:
                    pass

            if not converted and not os.path.exists(output_audio_path):
                import shutil
                shutil.copyfile(wav_path, output_audio_path)

        # CapCut-style acoustic caption alignment (faster-whisper / energy VAD)
        from engine.managers.caption_aligner import CaptionAligner
        aligned_words = CaptionAligner.align_captions(
            audio_path=wav_path,
            script_text=phonetic_text,
            existing_timestamps=word_timestamps
        )
        if aligned_words:
            word_timestamps = aligned_words

        print(f"✅ [KOKORO] Synthesized {total_duration:.2f}s audio successfully ({len(word_timestamps)} word timestamps captured).", flush=True)
        return (total_duration, word_timestamps)

    @classmethod
    async def _synthesize_edge_tts(
        cls,
        phonetic_text: str,
        output_audio_path: str,
        voice: str = "en-US-ChristopherNeural"
    ) -> Tuple[float, List[WordTimestamp]]:
        """
        Fallback TTS: Generates MP3 audio using Edge-TTS WebSocket stream.
        """
        import edge_tts

        os.makedirs(os.path.dirname(output_audio_path) or ".", exist_ok=True)
        communicate = edge_tts.Communicate(phonetic_text, voice)
        word_timestamps: List[WordTimestamp] = []

        with open(output_audio_path, "wb") as audio_file:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_file.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    start_sec = chunk["offset"] / 10_000_000.0
                    duration_sec = chunk["duration"] / 10_000_000.0
                    word = chunk["text"]
                    word_timestamps.append(
                        WordTimestamp(word=word, start=start_sec, end=start_sec + duration_sec)
                    )

        # Multi-tier duration check
        duration = word_timestamps[-1].end if word_timestamps else 0.0

        if duration <= 0.0:
            try:
                from mutagen.mp3 import MP3
                audio = MP3(output_audio_path)
                if audio.info and audio.info.length > 0:
                    duration = round(float(audio.info.length), 2)
            except Exception:
                pass

        if duration <= 0.0:
            try:
                if os.path.exists(output_audio_path):
                    file_size = os.path.getsize(output_audio_path)
                    if file_size > 1000:
                        duration = round(file_size / 6000.0, 2)
            except Exception:
                pass

        if duration <= 0.0:
            words_count = len(phonetic_text.split())
            duration = max(15.0, round(words_count / 2.5, 2))

        if not word_timestamps and duration > 0.0:
            words = phonetic_text.split()
            if words:
                step = duration / len(words)
                for i, w in enumerate(words):
                    word_timestamps.append(
                        WordTimestamp(
                            word=w,
                            start=round(i * step, 3),
                            end=round((i + 1) * step, 3)
                        )
                    )
        # CapCut-style acoustic caption alignment (faster-whisper / energy VAD)
        from engine.managers.caption_aligner import CaptionAligner
        aligned_words = CaptionAligner.align_captions(
            audio_path=output_audio_path,
            script_text=phonetic_text,
            existing_timestamps=word_timestamps
        )
        if aligned_words:
            word_timestamps = aligned_words

        return (duration, word_timestamps)

    @classmethod
    async def synthesize_with_word_boundaries(
        cls,
        phonetic_text: str,
        output_audio_path: str,
        voice: str = "am_michael",
        speed: float = 1.0,
        prefer_provider: Optional[str] = None
    ) -> Tuple[float, List[WordTimestamp]]:
        """
        Synthesizes speech using Kokoro TTS (Primary) with automatic Edge-TTS fallback.
        Strictly enforces male-only voices across all providers.
        """
        voice = cls.enforce_male_voice(voice)

        # 1. Primary Engine: Kokoro TTS
        should_try_kokoro = (prefer_provider != "edge-tts")
        if should_try_kokoro:
            try:
                import kokoro  # noqa: F401
                kokoro_voice = voice if cls.is_kokoro_voice(voice) else "am_adam"
                kokoro_voice = cls.enforce_male_voice(kokoro_voice)
                return cls._synthesize_kokoro(
                    phonetic_text=phonetic_text,
                    output_audio_path=output_audio_path,
                    voice=kokoro_voice,
                    speed=speed
                )
            except Exception as e:
                print(f"⚠️ [TTS] Kokoro unavailable or failed ({e}) — falling back to Edge-TTS.", flush=True)

        # 2. Fallback Engine: Edge-TTS
        if voice in cls.KOKORO_TO_EDGE_VOICE_MAP:
            edge_voice = cls.KOKORO_TO_EDGE_VOICE_MAP[voice]
        elif voice and ("Neural" in voice or voice.startswith("en-")):
            edge_voice = voice
        else:
            edge_voice = "en-US-GuyNeural"

        edge_voice = cls.enforce_male_voice(edge_voice)

        print(f"🎙️ [EDGE-TTS] Synthesizing speech with fallback voice '{edge_voice}'...", flush=True)
        return await cls._synthesize_edge_tts(
            phonetic_text=phonetic_text,
            output_audio_path=output_audio_path,
            voice=edge_voice
        )

    @classmethod
    def synthesize_sync(
        cls,
        phonetic_text: str,
        output_audio_path: str,
        voice: str = "am_michael",
        speed: float = 1.0,
        prefer_provider: Optional[str] = None
    ) -> Tuple[float, List[WordTimestamp]]:
        """Synchronous wrapper for synthesize_with_word_boundaries."""
        return asyncio.run(
            cls.synthesize_with_word_boundaries(
                phonetic_text, output_audio_path, voice=voice, speed=speed, prefer_provider=prefer_provider
            )
        )

    @classmethod
    def rescale_audio_duration(cls, input_audio_path: str, output_audio_path: str, speed_factor: float) -> bool:
        """
        Dynamically rescales audio playback speed to guarantee duration stays within platform limits.
        Uses ffmpeg atempo filter.
        """
        if not os.path.exists(input_audio_path) or speed_factor <= 0.0 or abs(speed_factor - 1.0) < 0.01:
            return False

        try:
            import subprocess
            atempo_val = max(0.5, min(2.0, speed_factor))
            cmd = [
                "ffmpeg", "-y", "-nostats", "-loglevel", "error",
                "-i", input_audio_path,
                "-filter:a", f"atempo={atempo_val}",
                "-c:a", "libmp3lame" if output_audio_path.endswith(".mp3") else "pcm_s16le",
                output_audio_path
            ]
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=30)
            if res.returncode == 0 and os.path.exists(output_audio_path) and os.path.getsize(output_audio_path) > 1000:
                print(f"⚡ [AUDIO RESCALE] Successfully adjusted audio duration by {speed_factor:.3f}x via FFmpeg atempo.", flush=True)
                return True
        except Exception as e:
            print(f"⚠️ [AUDIO RESCALE] FFmpeg atempo failed: {e}", flush=True)

        return False


