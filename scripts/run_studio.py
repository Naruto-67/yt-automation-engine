"""
scripts/run_studio.py — CLI Launcher for the Private TOPATO Web Studio

Usage:
    python scripts/run_studio.py
    python scripts/run_studio.py --port 8765 --no-browser
"""

import os
import sys
import argparse
import webbrowser
import threading
import time

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.web_studio.server import create_studio_app, get_studio_secret
from aiohttp import web


def parse_args():
    parser = argparse.ArgumentParser(description="TOPATO Private Web Studio Launcher")
    parser.add_argument("--host", default="127.0.0.1", help="Binding host (default: 127.0.0.1 - strictly localhost)")
    parser.add_argument("--port", type=int, default=8765, help="Server port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically launch web browser")
    return parser.parse_args()


def open_browser_delayed(url: str, delay: float = 1.2):
    def _open():
        time.sleep(delay)
        try:
            print(f"🌐 [LAUNCHER] Opening browser at {url}...", flush=True)
            webbrowser.open(url)
        except Exception as e:
            print(f"⚠️ [LAUNCHER] Could not launch browser automatically: {e}", flush=True)
    threading.Thread(target=_open, daemon=True).start()


def main():
    args = parse_args()

    # Absolute privacy enforcement: do not allow 0.0.0.0
    if args.host not in ("127.0.0.1", "localhost"):
        print(f"🛑 [SECURITY ERROR] For absolute privacy and zero public access, the studio must bind strictly to 127.0.0.1.")
        sys.exit(1)

    secret = get_studio_secret()
    studio_url = f"http://{args.host}:{args.port}/?token={secret}"

    print("\n" + "=" * 76)
    print("🎬  TOPATO PRIVATE WEB STUDIO & INTERACTIVE TIMELINE (v2.1)")
    print("=" * 76)
    print(f"📍 Private URL:   {studio_url}")
    print(f"🔑 Secret Token:  {secret}")
    print(f"🛡️  Access Model:  Strict Localhost (127.0.0.1) & Token Protected")
    print(f"🚫 Network Reach: Zero public access. Rejected across local Wi-Fi/LAN.")
    print("=" * 76 + "\n")

    if not args.no_browser:
        open_browser_delayed(studio_url)

    app = create_studio_app()
    try:
        web.run_app(app, host=args.host, port=args.port, print=None)
    except (KeyboardInterrupt, SystemExit):
        print("\n👋 [STUDIO] Gracefully stopped TOPATO Private Studio. See you next time!", flush=True)


if __name__ == "__main__":
    main()

