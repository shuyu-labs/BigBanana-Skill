"""Unified CLI for the BigBanana skill."""
from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMMANDS = {
    "generate": "bigbanana_generate.py", "workflow": "bigbanana_workflow.py",
    "quality": "bigbanana_quality.py", "export": "bigbanana_export.py",
    "image": "bigbanana_image.py", "video": "bigbanana_video.py",
    "audio": "bigbanana_audio.py", "auth": "antsk.py",
    "visual": "bigbanana_visual.py",
}
def main():
    # Forward subcommand help/options verbatim; argparse would otherwise
    # consume `bigbanana generate -h` as top-level help.
    if len(sys.argv) > 1 and sys.argv[1] in COMMANDS:
        return subprocess.call([sys.executable, str(HERE / COMMANDS[sys.argv[1]]), *sys.argv[2:]])
    ap = argparse.ArgumentParser(prog="bigbanana", description="BigBanana unified CLI")
    ap.add_argument("command", choices=sorted(COMMANDS)); ap.parse_args()
if __name__ == "__main__": raise SystemExit(main())
