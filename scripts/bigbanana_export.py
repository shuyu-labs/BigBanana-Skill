"""Export generated shot videos into a master video using ffmpeg."""
from __future__ import annotations
import argparse, json, shutil, subprocess, tempfile
from pathlib import Path

def main():
    ap = argparse.ArgumentParser(description="Export a BigBanana project")
    ap.add_argument("--project", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--subtitles", default=None, help="write an SRT from script.json")
    ap.add_argument("--mix-audio", action="store_true", help="mix per-shot *_vo audio when ffmpeg supports it")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    args = ap.parse_args()
    project = Path(args.project).expanduser().resolve()
    if not shutil.which(args.ffmpeg):
        raise SystemExit("ffmpeg not found; install it or pass --ffmpeg PATH")
    videos = sorted(project.glob("s[0-9][0-9].mp4"))
    if not videos: raise SystemExit(f"no shot videos found in {project}")
    out = Path(args.out).expanduser().resolve() if args.out else project / "master.mp4"
    if args.subtitles:
        script_path = project / "script.json"
        if not script_path.exists(): raise SystemExit("script.json required for subtitles")
        shots = json.loads(script_path.read_text(encoding="utf-8")).get("shots", [])
        elapsed = 0.0; lines = []
        for i, shot in enumerate(shots, 1):
            text = str(shot.get("dialogue") or shot.get("narration") or "").strip()
            seconds = float(shot.get("duration_seconds") or 6)
            if text:
                def ts(v):
                    h=int(v//3600); m=int(v%3600//60); s=int(v%60); ms=int(round(v%1*1000)); return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
                lines += [str(i), f"{ts(elapsed)} --> {ts(elapsed+seconds)}", text, ""]
            elapsed += seconds
        Path(args.subtitles).expanduser().resolve().write_text("\n".join(lines), encoding="utf-8")
        print(f"Wrote subtitles -> {Path(args.subtitles).expanduser().resolve()}")
    temp_media = []
    concat_videos = list(videos)
    if args.mix_audio:
        tmp_dir = Path(tempfile.mkdtemp(prefix="bigbanana-export-"))
        for video in videos:
            audio = next(iter(project.glob(f"{video.stem}_vo.*")), None)
            if not audio: continue
            muxed = tmp_dir / video.name
            subprocess.run([args.ffmpeg, "-y", "-i", str(video), "-i", str(audio), "-shortest", "-c:v", "copy", "-c:a", "aac", str(muxed)], check=True)
            temp_media.append(muxed)
            concat_videos[videos.index(video)] = muxed
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        listing = Path(f.name)
        for video in concat_videos:
            # ffmpeg concat files use single quotes; escape embedded quotes.
            f.write("file '" + str(video).replace("'", "'\\''") + "'\n")
    try:
        cmd = [args.ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(listing)]
        if args.mix_audio:
            # Audio mixing is intentionally opt-in; concat copy remains the safe default.
            cmd += ["-c:v", "copy", "-c:a", "aac"]
        else:
            cmd += ["-c", "copy"]
        cmd += [str(out)]
        subprocess.run(cmd, check=True)
    finally:
        listing.unlink(missing_ok=True)
        if temp_media:
            shutil.rmtree(temp_media[0].parent, ignore_errors=True)
    print(f"Exported {len(videos)} shot(s) -> {out}")
if __name__ == "__main__": main()
