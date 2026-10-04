"""
scripts/optimize_vault_assets.py — Curated B-Roll Vault Ingestion & Compression Tool
Optimizes raw downloaded videos (mutes audio, crops/scales to 1080x1920, trims to 10-12s, compresses to H.264)
so they fit cleanly inside the Git repository (~1-2 MB each instead of 70 MB) with zero audio/copyright risk.
"""

import os
import sys
import glob
import subprocess
import argparse
import re

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def find_ffmpeg_bin() -> str:
    """Finds best available FFmpeg binary (CapCut build on Windows or system FFmpeg)."""
    capcut_path = r"C:\Users\Yuvraj\AppData\Local\CapCut\Apps\9.5.0.4050\ffmpeg.exe"
    if os.path.exists(capcut_path):
        return capcut_path
    
    # Try system PATH
    try:
        res = subprocess.run(["where.exe", "ffmpeg"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0:
            lines = res.stdout.strip().splitlines()
            if lines:
                return lines[0].strip()
    except Exception:
        pass
    
    return "ffmpeg"


def detect_archetype(filename: str) -> str:
    """Classifies video filename into BrainBlud sensory archetypes."""
    fn = filename.lower()
    # Specific known Pexels IDs
    if "5871934" in fn or "6150668" in fn or "6150669" in fn:
        return "slime_floam"
    if "15324548" in fn:
        return "candy_craft"
    if "14506613" in fn:
        return "tactile_macro"
    if "180776" in fn:
        return "physics_marble"

    if "kinetic" in fn or "sand" in fn:
        return "kinetic_sand"
    elif "soap" in fn:
        return "soap_cubes"
    elif "honey" in fn:
        return "honeycomb"
    elif "jelly" in fn or "gelatin" in fn:
        return "jelly_slice"
    elif "slime" in fn or "floam" in fn or "bead" in fn or "cornstarch" in fn:
        return "slime_floam"
    elif "hedge" in fn or "bush" in fn:
        return "hedge_trim"
    elif "wash" in fn or ("clean" in fn and "stone" not in fn and "shale" not in fn):
        return "power_wash"
    elif "bottle" in fn and ("stair" in fn or "bottom" in fn):
        return "bottle_stairs"
    elif "paint" in fn or "pastel" in fn or "watercolor" in fn or "drawing" in fn or "art" in fn:
        return "art_paint"
    elif "candy" in fn or "ice cream" in fn or "gelato" in fn:
        return "candy_craft"
    elif "stone" in fn or "rock" in fn or "shale" in fn:
        return "natural_stone"
    elif any(kw in fn for kw in ["glass", "marble", "physics"]):
        return "physics_marble"
    else:
        return "tactile_macro"


def main():
    parser = argparse.ArgumentParser(description="Optimize downloaded B-roll clips for the repository vault.")
    parser.add_argument("--src", default=r"C:\Users\Yuvraj\Downloads\assests", help="Source folder of downloaded videos")
    parser.add_argument("--dest", default="assets/broll_vault/satisfying", help="Destination vault folder in repo")
    parser.add_argument("--max-duration", type=float, default=12.0, help="Max duration in seconds per clip")
    parser.add_argument("--bitrate", default="8000k", help="Video bitrate for compression if re-encoding")
    parser.add_argument("--lossless", action="store_true", default=True, help="Preserve full original video bitstream without re-encoding (strip audio only)")
    parser.add_argument("--reencode", action="store_true", help="Force re-encoding and cropping")
    parser.add_argument("--dry-run", action="store_true", help="Inspect without transcoding")
    args = parser.parse_args()

    use_lossless = args.lossless and not args.reencode

    if not os.path.exists(args.src):
        print(f"❌ Source directory '{args.src}' does not exist.")
        sys.exit(1)

    os.makedirs(args.dest, exist_ok=True)
    ffmpeg_bin = find_ffmpeg_bin()
    print(f"🔧 [VAULT OPTIMIZER] Using FFmpeg: {ffmpeg_bin}")
    print(f"📂 [VAULT OPTIMIZER] Source: '{args.src}' -> Dest: '{args.dest}' (Lossless: {use_lossless})")

    raw_files = sorted(glob.glob(os.path.join(args.src, "*.mp4")) + glob.glob(os.path.join(args.src, "*.mov")))
    if not raw_files:
        print("⚠️ No video files found in source folder.")
        sys.exit(0)

    print(f"🎬 Found {len(raw_files)} video clips to process.\n")

    # Determine encoder: prefer h264_mf on Windows (hardware accelerated via Media Foundation) or libx264
    test_encoder = "h264_mf" if sys.platform == "win32" else "libx264"

    total_orig_bytes = 0
    total_opt_bytes = 0
    counters = {}

    for idx, fpath in enumerate(raw_files):
        orig_size = os.path.getsize(fpath)
        total_orig_bytes += orig_size
        orig_fname = os.path.basename(fpath)

        archetype = detect_archetype(orig_fname)
        counters[archetype] = counters.get(archetype, 0) + 1
        clean_name = f"{archetype}_{counters[archetype]:02d}.mp4"
        out_path = os.path.join(args.dest, clean_name)

        if args.dry_run:
            print(f"  [DRY-RUN] {orig_fname[:40]} -> {clean_name} ({orig_size/(1024*1024):.2f}MB)")
            continue

        if use_lossless:
            print(f"  ⚡ [{idx+1}/{len(raw_files)}] Lossless Muting (-c:v copy -an): {orig_fname[:35]}... -> {clean_name}")
            cmd = [
                ffmpeg_bin, "-y",
                "-i", fpath,
                "-c:v", "copy",
                "-an",
                out_path
            ]
        else:
            print(f"  ⚡ [{idx+1}/{len(raw_files)}] Transcoding: {orig_fname[:35]}... -> {clean_name}")
            vf_filter = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30"
            cmd = [
                ffmpeg_bin, "-y",
                "-ss", "1.0",
                "-t", str(args.max_duration),
                "-i", fpath,
                "-vf", vf_filter,
                "-c:v", test_encoder,
                "-b:v", args.bitrate,
                "-an",
                out_path
            ]


        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace")
        if res.returncode != 0:
            # Fallback to libx264 if h264_mf fails
            cmd_fallback = [
                ffmpeg_bin, "-y",
                "-ss", "1.0",
                "-t", str(args.max_duration),
                "-i", fpath,
                "-vf", vf_filter,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "22",
                "-an",
                out_path
            ]
            res_fb = subprocess.run(cmd_fallback, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace")
            if res_fb.returncode != 0:
                print(f"    ⚠️ Warning: Failed to optimize {orig_fname}: {res_fb.stderr.strip().splitlines()[-1]}")
                continue

        new_size = os.path.getsize(out_path)
        total_opt_bytes += new_size
        ratio = (1 - (new_size / orig_size)) * 100
        print(f"     ✅ Saved: {orig_size/(1024*1024):.1f}MB -> {new_size/(1024*1024):.2f}MB ({ratio:.1f}% reduction)")

    orig_mb = total_orig_bytes / (1024 * 1024)
    opt_mb = total_opt_bytes / (1024 * 1024)
    saved_mb = orig_mb - opt_mb

    print("\n" + "=" * 50)
    print("🎉 [VAULT OPTIMIZER COMPLETED]")
    print(f"Total Original Size: {orig_mb:.2f} MB")
    print(f"Optimized Vault Size: {opt_mb:.2f} MB")
    if orig_mb > 0:
        print(f"Total Space Saved: {saved_mb:.2f} MB ({(saved_mb/orig_mb)*100:.1f}% reduction)")
    print(f"All clips saved to: {args.dest}")
    print("=" * 50)


if __name__ == "__main__":
    main()
