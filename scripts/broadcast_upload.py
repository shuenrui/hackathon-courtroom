#!/usr/bin/env python3
"""Upload one broadcast-ready case to the public ifhost site.

Additive upload (never wipes existing cases): tar the new files ->
machines write to /tmp -> extract into /app. `machines write` caps at
10MB per file, so audio is batched into <=8MB tars. Order is safe:
audio first, then the segment, then playlist.json last — the public
player never sees a case before its files exist.

NOTE: `ifhost machines push` REPLACES the whole target dir — never use it
for per-case uploads. Full-tree push lives in deploy_broadcast.sh only.

Usage: python3 scripts/broadcast_upload.py case_T03
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BROADCAST = REPO / "broadcast"
SEGMENTS = BROADCAST / "segments"
APP = "hackathon-broadcast"
REMOTE_TAR = "/tmp/broadcast_upload.tar.gz"
BATCH_LIMIT = 8 * 1024 * 1024


def upload_stage(stage: Path, label: str) -> bool:
    tar_path = stage.parent / (stage.name + ".tar.gz")
    if subprocess.run(["tar", "czf", str(tar_path), "-C", str(stage), "."]).returncode != 0:
        print(f"upload failed ({label}): tar error", file=sys.stderr)
        return False
    if tar_path.stat().st_size > 10 * 1024 * 1024:
        tar_path.unlink(missing_ok=True)
        print(f"upload failed ({label}): stage exceeds 10MB write cap", file=sys.stderr)
        return False
    try:
        r = subprocess.run(
            ["ifhost", "machines", "write", str(tar_path), "--to", REMOTE_TAR, "--app", APP],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"upload failed ({label}):\n{r.stderr[-400:]}", file=sys.stderr)
            return False
        r = subprocess.run(
            ["ifhost", "machines", "exec", "--app", APP, "--", "sh", "-c",
             f"tar xzf {REMOTE_TAR} -C /app && chmod -R a+rX /app && rm {REMOTE_TAR}"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"upload failed ({label}): extract error\n{r.stderr[-400:]}", file=sys.stderr)
            return False
    finally:
        tar_path.unlink(missing_ok=True)
    print(f"  uploaded: {label}")
    return True


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].startswith("case_"):
        sys.exit("usage: broadcast_upload.py case_T03")
    case = sys.argv[1]
    seg_path = SEGMENTS / f"{case}.json"
    if not seg_path.exists():
        sys.exit(f"no segment for {case} — run the pipeline first")
    seg = json.loads(seg_path.read_text())

    audio_files = []
    for line in seg["lines"]:
        rel = line.get("audio")
        if rel and (BROADCAST / rel).exists():
            audio_files.append(BROADCAST / rel)

    root = Path(tempfile.mkdtemp())
    try:
        batch, batch_size = [], 0
        for src in audio_files:
            size = src.stat().st_size
            if batch and batch_size + size > BATCH_LIMIT:
                stage = root / f"audio_batch_{len(list(root.iterdir()))}"
                (stage / "sources" / "audio").mkdir(parents=True)
                for f in batch:
                    shutil.copy(f, stage / "sources" / "audio" / f.name)
                if not upload_stage(stage, f"{case} audio batch ({len(batch)} clips)"):
                    return 1
                shutil.rmtree(stage)
                batch, batch_size = [], 0
            batch.append(src)
            batch_size += size
        if batch:
            stage = root / "audio_final"
            (stage / "sources" / "audio").mkdir(parents=True)
            for f in batch:
                shutil.copy(f, stage / "sources" / "audio" / f.name)
            if not upload_stage(stage, f"{case} audio ({len(batch)} clips)"):
                return 1
            shutil.rmtree(stage)

        stage = root / "segment"
        (stage / "segments").mkdir(parents=True)
        shutil.copy(seg_path, stage / "segments" / seg_path.name)
        if not upload_stage(stage, f"{case} segment"):
            return 1
        shutil.rmtree(stage)

        stage = root / "playlist"
        (stage / "segments").mkdir(parents=True)
        shutil.copy(SEGMENTS / "playlist.json", stage / "segments" / "playlist.json")
        if not upload_stage(stage, "playlist.json (case goes live)"):
            return 1
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print(f"LIVE — {case} on https://{APP}.host.impossibuild.ai")
    return 0


if __name__ == "__main__":
    sys.exit(main())
