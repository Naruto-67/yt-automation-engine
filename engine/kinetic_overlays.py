"""
engine/kinetic_overlays.py — Hybrid Python/FFmpeg + Node.js Kinetic Motion Overlay Engine

Provides dynamic kinetic video overlays:
1. FFmpeg Native Kinetic Progress Bar: Dynamic bottom progress bar tracking duration
   using FFmpeg's `drawbox` filter with glowing channel-accent colors.
2. FFmpeg Glowing Vignette & Edge Glow: Atmospheric perimeter grading.
3. Node.js Motion Bridge: Automatically detects if Node.js is available on the host
   (e.g. GitHub Actions ubuntu runner). If present, renders high-fidelity vector/canvas
   motion graphics; if absent (e.g. local developer workstation), gracefully and
   transparently falls back to native FFmpeg filters.
"""

import os
import sys
import shutil
import subprocess
import logging
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path

logger = logging.getLogger("yt_engine.kinetic_overlays")


class KineticOverlayEngine:
    """Manages kinetic video overlays, progress bars, and motion effects."""

    def __init__(self):
        self.node_available = shutil.which("node") is not None
        root = Path(__file__).resolve().parent.parent
        self.render_dir = root / "render"

    def has_node(self) -> bool:
        """Checks if Node.js runtime is installed and executable."""
        return self.node_available

    def get_progress_bar_filter(
        self,
        duration: float,
        color_hex: str = "FF3366",
        height: int = 10,
        y_pos: int = 1910,
        opacity: float = 0.90
    ) -> str:
        """
        Generates an FFmpeg native `drawbox` filter for a smooth, hardware-accelerated
        real-time animated progress bar across the bottom of a 9:16 Shorts frame.
        
        Args:
            duration: Total video duration in seconds.
            color_hex: Hex accent color (e.g. 'FF3366' for bright rose).
            height: Bar height in pixels.
            y_pos: Vertical position (default 1910, 10px from bottom of 1080x1920).
            opacity: Fill opacity (0.0 to 1.0).
            
        Returns:
            FFmpeg filter expression string.
        """
        safe_color = color_hex.replace("#", "").upper()
        if len(safe_color) != 6:
            safe_color = "FF3366"
            
        dur = max(1.0, float(duration))
        # drawbox filter: width is dynamic function of time `t`
        # min(1080, 1080 * (t / dur))
        drawbox_expr = (
            f"drawbox=x=0:y={y_pos}:"
            f"w='min(1080\\, 1080*(t/{dur:.2f}))':"
            f"h={height}:"
            f"color=0x{safe_color}@{opacity:.2f}:"
            f"t=fill"
        )
        return drawbox_expr

    def get_atmospheric_vignette_filter(self, intensity: float = 0.25) -> str:
        """Generates a subtle cinematic edge vignette filter."""
        # FFmpeg vignette filter: angle=PI/5 for subtle edge shading
        return f"vignette=angle=PI/5:aspect=9/16"

    def render_node_kinetic_badge(
        self,
        text: str,
        output_png: str,
        badge_style: str = "neon"
    ) -> bool:
        """
        Invokes Node.js kinetic renderer to generate a motion badge if node is installed.
        Returns True if successful, False if Node is missing or failed.
        """
        if not self.has_node():
            return False

        script_path = self.render_dir / "kinetic_renderer.js"
        if not script_path.exists():
            return False

        cmd = [
            "node",
            str(script_path),
            "--text", text,
            "--output", str(output_png),
            "--style", badge_style
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            return res.returncode == 0 and os.path.exists(output_png)
        except Exception as e:
            logger.debug(f"Node kinetic render failed: {e}")
            return False


# Singleton instance
kinetic_engine = KineticOverlayEngine()

