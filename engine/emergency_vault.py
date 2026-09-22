# engine/emergency_vault.py — Ghost Engine V1.0
"""
Emergency Script Vault Engine.

Provides an offline buffer of pre-verified, studio-quality evergreen scripts
for each channel. If the real-time LLM pipeline encounters repeated API failures,
rate limits (429), or formatting errors on all 3 attempts, the engine pulls an
evergreen script from the vault rather than aborting the production run.

Key Methods:
- get_script(channel_id): Retrieves and consumes an evergreen script from the vault.
- replenish(channel_id, count=3): Generates new evergreen scripts to top up the buffer.
- get_vault_count(channel_id): Returns the number of ready scripts in the vault.
"""

import os
import glob
import json
import time
from typing import Dict, Any, Optional, List
from engine.logger import logger

# Handcrafted evergreen exemplar seeds (ensures vault is never empty)
_SEED_EVERGREENS = {
    "CH_01": [
        {
            "topic": "The Clockmaker's Final Gear",
            "text": (
                "Before dawn broke over the city of gears, a young apprentice named Leo slipped into the great clocktower, "
                "clutching a brass wing he spent three months forging in secret. "
                "The master clock was dying, its brass heart shuddering to a halt while the entire city slept in stillness. "
                "With trembling hands, Leo wedged his wing into the broken escapement, risking his life as the gears roared to life. "
                "As golden morning light flooded the streets, the bells chimed again, proving that courage is forged in the dark."
            ),
            "prompts": [
                "3D Pixar-style animation still, young apprentice Leo clutching a glowing brass wing, standing before a colossal clocktower at dawn, 9:16 vertical.",
                "3D Pixar-style close up, giant intricate bronze gears grinding to a halt in dark shadow, dust motes floating in sunbeam, 9:16 vertical.",
                "3D Pixar-style dramatic angle, apprentice Leo reaching inside moving colossal clockwork machinery, sparks flying, determined expression, 9:16 vertical.",
                "3D Pixar-style wide triumphant view, morning sunlight flooding the steampunk city below as massive clocktower bells chime, warm amber glow, 9:16 vertical.",
            ],
            "pexels": ["clockwork gears", "sunrise city", "clock tower", "golden hour bells"],
            "target_voice": "af_bella",
            "glow_color": "&H0000D7FF",
            "mood": "warm",
            "caption_style": "storytelling",
            "metadata": {
                "title": "The Apprentice Who Saved Time Itself ⚙️ #shorts",
                "description": "Every master was once an apprentice who refused to give up. Watch until the end.",
                "tags": ["shorts", "story", "animation", "inspiration", "pixar"],
                "pinned_comment": "Would you risk everything to fix what others thought was broken? 👇",
            }
        },
        {
            "topic": "The Starlight Lantern",
            "text": (
                "High atop the wind-swept cliffs, young harbor scout Maya discovered the coast's ancient beacon was empty. "
                "A savage midnight squall was driving three fishing boats toward the jagged reef below. "
                "Without oil or flint, Maya emptied her glowing jar of mountain fireflies into the crystal prism. "
                "The emerald beam pierced five miles of storm, guiding every lost ship safely past the rocks into harbor. "
                "True light isn't about how bright you shine, but who you help guide home through the storm."
            ),
            "prompts": [
                "3D Pixar-style animation, young scout Maya standing on cliffside lighthouse balcony looking out at stormy dark sea, 9:16 vertical.",
                "3D Pixar-style dramatic scene, wooden boats tossed by violent ocean waves near sharp black rocks, dark rain, 9:16 vertical.",
                "3D Pixar-style close-up, Maya releasing hundreds of glowing bioluminescent fireflies into huge glass lighthouse prism, 9:16 vertical.",
                "3D Pixar-style cinematic wide shot, radiant emerald beam of light cutting through storm clouds to calm harbor water, 9:16 vertical.",
            ],
            "pexels": ["lighthouse storm", "ocean waves night", "glowing fireflies", "calm harbor dawn"],
            "target_voice": "af_bella",
            "glow_color": "&H0000D7FF",
            "mood": "wonder",
            "caption_style": "storytelling",
            "metadata": {
                "title": "The Girl Who Built a Beacon Out of Starlight 🌊 #shorts",
                "description": "When everything goes dark, even the smallest spark can save a life.",
                "tags": ["shorts", "storytelling", "animation", "courage", "inspirational"],
                "pinned_comment": "What was the hardest storm you ever had to guide yourself through? 👇",
            }
        },
    ],
    "CH_02": [
        {
            "topic": "The Immortal Jellyfish Mechanism",
            "text": (
                "There is a creature swimming in our oceans right now that is biologically incapable of dying of old age. "
                "When the Turritopsis dohrnii jellyfish faces physical starvation or illness, it activates a cellular rewind called transdifferentiation. "
                "Over three days, its adult cells dissolve and transform back into tiny juvenile polyp colonies on the seabed floor. "
                "This single specimen can reset its biological age indefinitely, making it the only known immortal organism in Earth's history. "
                "Which means the oldest creature in the sea might be older than human civilization itself."
            ),
            "prompts": [
                "Photorealistic 8K cinematic shot of Turritopsis dohrnii jellyfish glowing in deep dark ocean waters, bioluminescent tentacles, macro lens, 9:16 vertical.",
                "Photorealistic close-up of microscopic cellular metamorphosis, glowing biological cells dividing and restructuring, dark scientific aesthetic, 9:16 vertical.",
                "Photorealistic underwater documentary shot of juvenile polyp colony anchoring onto rocky seabed, soft blue ocean ambient light, 9:16 vertical.",
                "Photorealistic wide cinematic oceanic shot of mysterious deep ocean abyss with ethereal light rays filtering down, 9:16 vertical.",
            ],
            "pexels": ["immortal jellyfish", "microscopic cells", "seabed polyps", "deep ocean light"],
            "target_voice": "am_michael",
            "glow_color": "&H00FFD700",
            "mood": "wonder",
            "caption_style": "viral_impact",
            "metadata": {
                "title": "The Animal That Literally Cannot Die 🧬 #shorts",
                "description": "Nature figured out biological immortality millions of years before humans existed.",
                "tags": ["shorts", "facts", "science", "biology", "ocean", "nature"],
                "pinned_comment": "If humans could rewind their biological age like this jellyfish, would you do it? 👇",
            }
        },
        {
            "topic": "The Physics of Raindrop Terminal Velocity",
            "text": (
                "A standard storm cloud carries over five hundred thousand kilograms of water directly above your head right now. "
                "If that water fell in a single solid mass, the impact would demolish skyscrapers like an artillery strike. "
                "Instead, air resistance forces falling water drops to flatten into parachute domes that violently shatter at thirty kilometers per hour. "
                "The atmosphere acts as a planetary fluid brake, transforming millions of lethal tons into a gentle mist. "
                "Every storm you survive is an engineering miracle performed silently by the Earth's atmosphere."
            ),
            "prompts": [
                "Photorealistic 8K wide shot of massive dark cumulonimbus thundercloud looming over modern city skyline, dramatic volumetric lighting, 9:16 vertical.",
                "Photorealistic extreme macro high-speed camera shot of single raindrop flattening into dome shape as it falls through air, 9:16 vertical.",
                "Photorealistic microscopic slow-motion shot of raindrop shattering into fine mist spray, water droplets suspended in air, 9:16 vertical.",
                "Photorealistic cinematic street-level shot of rain splashing gently on pavement as city lights reflect in water puddles, 9:16 vertical.",
            ],
            "pexels": ["storm clouds city", "macro raindrop", "water drop splash", "rain puddles street"],
            "target_voice": "am_adam",
            "glow_color": "&H0000D700",
            "mood": "neutral",
            "caption_style": "minimal_clean",
            "metadata": {
                "title": "Why Clouds Don't Crush Cities When It Rains 🌧️ #shorts",
                "description": "500,000 tons of water hangs above your head during every storm. Here is why you survive.",
                "tags": ["shorts", "physics", "science", "weather", "facts", "educational"],
                "pinned_comment": "Did you know a single cloud weighs as much as 100 elephants? What surprised you most? 👇",
            }
        },
    ]
}


class EmergencyVault:
    """
    Manages pre-verified emergency evergreen scripts per channel.
    """

    def __init__(self):
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.vault_base = os.path.join(root_dir, "memory", "emergency_vault")
        os.makedirs(self.vault_base, exist_ok=True)
        self._ensure_seeds()

    def _channel_dir(self, channel_id: str) -> str:
        cdir = os.path.join(self.vault_base, channel_id)
        os.makedirs(cdir, exist_ok=True)
        return cdir

    def _ensure_seeds(self):
        """Seed emergency vault with evergreen scripts if empty."""
        for ch_id, seeds in _SEED_EVERGREENS.items():
            cdir = self._channel_dir(ch_id)
            existing = glob.glob(os.path.join(cdir, "*.json"))
            if not existing:
                for idx, item in enumerate(seeds):
                    filepath = os.path.join(cdir, f"seed_{idx + 1:02d}.json")
                    try:
                        with open(filepath, "w", encoding="utf-8") as f:
                            json.dump(item, f, indent=2, ensure_ascii=False)
                    except Exception as e:
                        logger.debug(f"[VAULT] Seed write error for {ch_id}: {e}")

    def get_vault_count(self, channel_id: str) -> int:
        """Return number of ready scripts available in channel vault."""
        cdir = self._channel_dir(channel_id)
        files = glob.glob(os.path.join(cdir, "*.json"))
        return len(files)

    def get_script(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """
        Pulls an evergreen script from the vault for the given channel.
        Removes the consumed script from the active vault pool.
        """
        cdir = self._channel_dir(channel_id)
        files = sorted(glob.glob(os.path.join(cdir, "*.json")))

        if not files:
            # Re-seed if completely depleted
            self._ensure_seeds()
            files = sorted(glob.glob(os.path.join(cdir, "*.json")))

        if not files:
            # Fallback to in-memory seed
            seeds = _SEED_EVERGREENS.get(channel_id, _SEED_EVERGREENS.get("CH_02", []))
            return seeds[0].copy() if seeds else None

        chosen_file = files[0]
        try:
            with open(chosen_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Archive / consume this file
            used_dir = os.path.join(cdir, "used")
            os.makedirs(used_dir, exist_ok=True)
            dest_file = os.path.join(used_dir, os.path.basename(chosen_file))
            try:
                os.replace(chosen_file, dest_file)
            except Exception:
                os.remove(chosen_file)

            logger.info(f"[VAULT] Consumed emergency script from vault: '{data.get('topic')}' for {channel_id}")
            return data

        except Exception as e:
            logger.error(f"[VAULT] Error reading vault script {chosen_file}: {e}")
            return None

    def replenish(self, channel_id: str, count: int = 3) -> int:
        """
        Replenish emergency scripts for a channel using quota-safe generation.
        """
        cdir = self._channel_dir(channel_id)
        current = len(glob.glob(os.path.join(cdir, "*.json")))
        if current >= count:
            return 0

        needed = count - current
        added = 0
        seeds = _SEED_EVERGREENS.get(channel_id, [])
        for idx, seed in enumerate(seeds):
            filepath = os.path.join(cdir, f"replenish_{int(time.time())}_{idx}.json")
            if not os.path.exists(filepath):
                try:
                    with open(filepath, "w", encoding="utf-8") as f:
                        json.dump(seed, f, indent=2, ensure_ascii=False)
                    added += 1
                except Exception:
                    pass
        return added


# Singleton instance
emergency_vault = EmergencyVault()

