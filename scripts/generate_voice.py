# scripts/generate_voice.py
# Ghost Engine V26.0.0 — Punctuation-Based Prosody & Full Feature Preservation
import os
import re
import time
import torch
import numpy as np
import soundfile as sf
from engine.logger import logger
from engine.config_manager import config_manager
from scripts.quota_manager import quota_manager

# Attempt to load Kokoro; fallback to CPU if no GPU is present
try:
    from kokoro import KPipeline
    HAS_KOKORO = True
except ImportError:
    HAS_KOKORO = False

def clean_text_for_tts(text: str) -> str:
    """
    V26: Cleans text while strictly preserving 'Prosody Punctuation'.
    We keep ellipses (...) and exclamation marks as they drive Kokoro's emotional pacing.
    """
    # Remove bracketed AI thoughts or stage directions [e.g. [happy]]
    text = re.sub(r'\[.*?\]', '', text)
    # Remove asterisks often used for *emphasis* in LLM outputs
    text = text.replace('*', '')
    # Standardize ellipses for the pipeline to recognize them as rhythmic pauses
    text = re.sub(r'\.{2,}', '...', text)
    return text.strip()

def _get_fallback_voice(target_voice: str) -> str:
    """
    Internal logic from current repo: Maps Kokoro voices to Cloud fallbacks.
    """
    settings = config_manager.get_settings()
    voice_map = settings.get("voice_actors", {}).get("kokoro_to_groq_map", {})
    return voice_map.get(target_voice, "aura-asteria-en")

def generate_audio_kokoro(text: str, output_path: str, voice: str = "am_adam") -> bool:
    """
    Primary V26 Generator using Kokoro-82M for emotional delivery.
    """
    if not HAS_KOKORO:
        return False

    try:
        clean_text = clean_text_for_tts(text)
        
        # lang_code selection logic: 'a' for American, 'b' for British
        lang_code = 'b' if voice.startswith('bf') or voice.startswith('bm') else 'a'
        pipeline = KPipeline(lang_code=lang_code)
        
        # Generator yields (graphemes, phonemes, audio_tensor)
        generator = pipeline(clean_text, voice=voice, speed=1.1, split_pattern=r'\n+')
        
        full_audio = []
        for _, _, audio in generator:
            if audio is not None:
                full_audio.append(audio)
        
        if not full_audio:
            return False
            
        combined = np.concatenate(full_audio)
        # Write at Kokoro's native 24k sample rate
        sf.write(output_path, combined, 24000)
        return True
    except Exception as e:
        logger.error(f"Kokoro Generation Error: {e}")
        return False

def generate_audio_groq(text: str, output_path: str, voice: str = "aura-asteria-en") -> bool:
    """
    V26 Fallback Generator using Cloud endpoints (OpenAI/Groq compatible).
    """
    try:
        clean_text = clean_text_for_tts(text)
        success = quota_manager.generate_speech(
            text=clean_text,
            output_path=output_path,
            voice=voice
        )
        return success
    except Exception as e:
        logger.error(f"Groq TTS Fallback Error: {e}")
        return False

def generate_audio(text: str, output_base: str, target_voice: str = "am_adam"):
    """
    Main entry point for Step 3 Audio Production.
    Preserves existing metadata return structure and fallback selection logic.
    """
    output_path = f"{output_base}.wav"
    
    # Attempt Primary Voice (Local Kokoro)
    logger.generation(f"Synthesizing V26 voice: {target_voice} (Kokoro-82M)...")
    if generate_audio_kokoro(text, output_path, voice=target_voice):
        try:
            info = sf.info(output_path)
            duration = info.duration
            return True, "Kokoro-82M", duration
        except Exception as e:
            logger.error(f"Failed to read audio info: {e}")
            return True, "Kokoro-82M", 0.0

    # Attempt Fallback Voice (Cloud Providers)
    logger.warning(f"Local Kokoro failed. Engaging Cloud Fallback for {target_voice}...")
    fallback_v = _get_fallback_voice(target_voice)
    
    if generate_audio_groq(text, output_path, voice=fallback_v):
        try:
            info = sf.info(output_path)
            duration = info.duration
            return True, "Groq-Cloud", duration
        except Exception as e:
            logger.error(f"Failed to read cloud audio info: {e}")
            return True, "Groq-Cloud", 0.0

    return False, "FAILED", 0.0
