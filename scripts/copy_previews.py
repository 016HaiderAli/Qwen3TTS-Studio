#!/usr/bin/env python3
"""Copy generated preview WAV files for built-in speakers to frontend/public/samples/.

This script queries the Voice Studio database for narrations whose title matches
one of the 9 built-in speakers (Vivian, Serena, Uncle_Fu, Dylan, Eric, Ryan,
Aiden, Ono_Anna, Sohee), finds their completed final.wav output, and copies
them to frontend/public/samples/{speaker_id}.wav for instant static loading.
"""

import shutil
import sqlite3
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent / "backend"
FRONTEND_DIR = BACKEND_DIR / "frontend"
SAMPLES_DIR = FRONTEND_DIR / "public" / "samples"
STORAGE_DIR = BACKEND_DIR / "storage"
DB_PATH = BACKEND_DIR / "data" / "voice_studio.db"

SPEAKER_IDS = [
    "Vivian",
    "Serena",
    "Uncle_Fu",
    "Dylan",
    "Eric",
    "Ryan",
    "Aiden",
    "Ono_Anna",
    "Sohee",
]


def find_narration_audio(narration_id: str) -> Path | None:
    narration_dir = STORAGE_DIR / "narrations" / narration_id
    final_wav = narration_dir / "final.wav"
    if final_wav.exists():
        return final_wav
    return None


def main() -> int:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    copied = 0
    for speaker_id in SPEAKER_IDS:
        cursor.execute(
            """
            SELECT id, final_audio_path
            FROM narrations
            WHERE status = 'ready'
              AND title LIKE ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (f"%{speaker_id}%",),
        )
        row = cursor.fetchone()

        if not row:
            print(f"  [SKIP] No ready narration found for speaker: {speaker_id}")
            continue

        narration_id = row["id"]
        final_path_str = row["final_audio_path"]

        audio_path: Path | None = None
        if final_path_str:
            audio_path = Path(final_path_str)
            if not audio_path.is_absolute():
                audio_path = STORAGE_DIR / final_path_str

        if not audio_path or not audio_path.exists():
            audio_path = find_narration_audio(narration_id)

        if not audio_path or not audio_path.exists():
            print(
                f"  [SKIP] Narration {narration_id} found for {speaker_id} "
                f"but audio file not found at {audio_path or final_path_str}"
            )
            continue

        dest = SAMPLES_DIR / f"{speaker_id}.wav"
        shutil.copy2(audio_path, dest)
        size_kb = audio_path.stat().st_size // 1024
        print(f"  [COPY] {speaker_id}: {audio_path} -> {dest} ({size_kb} KB)")
        copied += 1

    conn.close()

    if copied == 0:
        print("\nWARNING: No preview files were copied.")
        print("Generate previews for the built-in speakers first using the app,")
        print("then re-run this script to copy the generated files here.")
        return 1

    print(f"\nDone. Copied {copied} preview file(s) to {SAMPLES_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
