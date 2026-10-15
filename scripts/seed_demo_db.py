"""Seed script to populate data/events.db with initial mock events.

Creates sample keyframes in data/frames/ and inserts mock events into SQLite.
"""

import json
from pathlib import Path
import sys

# Ensure backend can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.server.db import Database


def seed():
    base_dir = Path(__file__).resolve().parent.parent
    mock_file = base_dir / "backend" / "server" / "mock_events.json"
    frames_dir = base_dir / "data" / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    db = Database(str(base_dir / "data" / "events.db"))

    # Create dummy placeholder JPEG frames if PIL is available, or write raw byte markers
    try:
        from PIL import Image, ImageDraw, ImageFont

        for i in range(1, 7):
            frame_path = frames_dir / f"{i}.jpg"
            img = Image.new("RGB", (640, 360), color=(20, 24, 33))
            draw = ImageDraw.Draw(img)
            draw.rectangle([(20, 20), (620, 340)], outline=(56, 189, 248), width=2)
            draw.text((40, 40), f"EventLens Keyframe #{i}", fill=(240, 246, 252))
            draw.text((40, 70), "Simulated Event Capture", fill=(148, 163, 184))
            img.save(frame_path, "JPEG")
    except Exception:
        # Fallback to minimal 1x1 JPEG bytes
        minimal_jpg = (
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\x08\x06"
            b"\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f"
            b"\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff"
            b"\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01"
            b"\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n"
            b"\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
        )
        for i in range(1, 7):
            (frames_dir / f"{i}.jpg").write_bytes(minimal_jpg)

    if mock_file.exists():
        with open(mock_file, "r", encoding="utf-8") as f:
            events = json.load(f)
            for ev in events:
                ev["keyframe_path"] = str(frames_dir / f"{ev['id']}.jpg")
                db.insert_event(ev)
        print(f"Successfully seeded {len(events)} mock events into data/events.db")
    else:
        print("Mock events file not found.")


if __name__ == "__main__":
    seed()
