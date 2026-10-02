"""
engine/managers/voice_normalizer.py — Phonetic Script Normalizer & Word-Boundary TTS Streamer (v2.0)
Converts raw scripts to spoken phonetic text and extracts millisecond word boundaries via Edge-TTS WebSocket events.
"""

import os
import re
import asyncio
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

        # 3. Expand raw numbers: e.g. 125 -> one hundred and twenty-five
        def replace_numbers(match):
            num = match.group(0).replace(",", "")
            try:
                return num2words(int(num))
            except Exception:
                return num

        text = re.sub(r"\b\d+\b", replace_numbers, text)

        # 4. Expand common symbols and abbreviations
        abbreviations = {
            r"\be\.g\.\b": "for example",
            r"\bi\.e\.\b": "that is",
            r"\bvs\.?\b": "versus",
            r"\bDr\.\b": "Doctor",
            r"\bMr\.\b": "Mister",
            r"\bMrs\.\b": "Missus",
            r"&": "and",
            r"@": "at",
        }
        for pattern, replacement in abbreviations.items():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        return text

    @classmethod
    async def synthesize_with_word_boundaries(
        cls,
        phonetic_text: str,
        output_audio_path: str,
        voice: str = "en-US-ChristopherNeural"
    ) -> Tuple[float, List[WordTimestamp]]:
        """
        Generates MP3 audio using Edge-TTS and streams WordBoundary events.
        Edge-TTS offset and duration are measured in 100ns ticks (1 second = 10,000,000 ticks).
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
                    # Offset and duration are in 100ns units
                    start_sec = chunk["offset"] / 10_000_000.0
                    duration_sec = chunk["duration"] / 10_000_000.0
                    word = chunk["text"]
                    word_timestamps.append(
                        WordTimestamp(word=word, start=start_sec, end=start_sec + duration_sec)
                    )

        # Measure audio duration
        duration = word_timestamps[-1].end if word_timestamps else 0.0
        return (duration, word_timestamps)

    @classmethod
    def synthesize_sync(
        cls, phonetic_text: str, output_audio_path: str, voice: str = "en-US-ChristopherNeural"
    ) -> Tuple[float, List[WordTimestamp]]:
        """Synchronous wrapper for synthesize_with_word_boundaries."""
        return asyncio.run(
            cls.synthesize_with_word_boundaries(phonetic_text, output_audio_path, voice)
        )

