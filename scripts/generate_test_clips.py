"""Generates synthetic security test videos for EventLens.

Creates 5 test scenarios in data/videos/ at 640x480 @ 10fps:
1. test_tailgating.mp4: Two persons crossing the door zone in rapid succession.
2. test_person_down.mp4: Person collapsing horizontally and staying still.
3. test_crowd.mp4: 6 persons congregating in the lobby.
4. test_suspicious.mp4: Person loitering in the restricted corridor.
5. test_normal.mp4: Normal single-person passage.
"""

from pathlib import Path
import cv2
import numpy as np


def draw_background():
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    img[:] = (20, 24, 33)  # Surveillance console background

    # Floor tiles grid
    for y in range(0, 480, 40):
        cv2.line(img, (0, y), (640, y), (30, 36, 48), 1)
    for x in range(0, 640, 60):
        cv2.line(img, (x, 0), (x, 480), (30, 36, 48), 1)

    # Access Door Zone: [180, 240] to [420, 480]
    cv2.rectangle(img, (180, 240), (420, 480), (40, 65, 80), 2)
    cv2.putText(img, "ACCESS DOOR ZONE", (190, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (80, 140, 180), 1)

    # Restricted Server Room Corridor: [500, 100] to [620, 350]
    cv2.rectangle(img, (500, 100), (620, 350), (60, 35, 45), 2)
    cv2.putText(img, "RESTRICTED", (510, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 70, 90), 1)

    return img


def draw_person(frame, x, y, w, h, label="PERSON", color=(56, 189, 248)):
    cv2.rectangle(frame, (int(x), int(y)), (int(x + w), int(y + h)), color, -1)
    cv2.rectangle(frame, (int(x), int(y)), (int(x + w), int(y + h)), (255, 255, 255), 2)
    # Head
    cx = int(x + w / 2)
    cy = int(y - 12) if h > w else int(y + h / 2)
    cv2.circle(frame, (cx, cy), 10, (230, 230, 230), -1)
    cv2.putText(frame, label, (int(x), int(y - 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)


def generate_clips():
    out_dir = Path("data/videos")
    out_dir.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    fps = 10
    total_frames = 80  # 8 seconds per clip

    # 1. Tailgating Clip
    out_path = out_dir / "test_tailgating.mp4"
    vw = cv2.VideoWriter(str(out_path), fourcc, fps, (640, 480))
    for f in range(total_frames):
        frame = draw_background()
        cv2.putText(frame, "SCENARIO: TAILGATING (2 Persons < 1.5s)", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (245, 158, 11), 2)

        # Person 1 crosses door zone at frame 20-45
        p1_x = 100 + f * 5
        p1_y = 300
        draw_person(frame, p1_x, p1_y, 40, 90, "P1 (Authorized)", (16, 185, 129))

        # Person 2 follows immediately 8 frames (~0.8s) behind
        if f > 8:
            p2_x = 100 + (f - 8) * 5
            p2_y = 300
            draw_person(frame, p2_x, p2_y, 40, 90, "P2 (Tailgater)", (244, 63, 94))

        vw.write(frame)
    vw.release()
    print(f"Generated: {out_path}")

    # 2. Person Down Clip
    out_path = out_dir / "test_person_down.mp4"
    vw = cv2.VideoWriter(str(out_path), fourcc, fps, (640, 480))
    for f in range(total_frames):
        frame = draw_background()
        cv2.putText(frame, "SCENARIO: PERSON DOWN (Collapse & Prone)", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (244, 63, 94), 2)

        if f < 25:
            # Walking upright
            px = 150 + f * 4
            draw_person(frame, px, 300, 40, 90, "Person", (56, 189, 248))
        else:
            # Slipped and lying horizontal (width > height)
            px = 250
            draw_person(frame, px, 350, 95, 35, "PERSON DOWN", (244, 63, 94))

        vw.write(frame)
    vw.release()
    print(f"Generated: {out_path}")

    # 3. Crowd Incident Clip
    out_path = out_dir / "test_crowd.mp4"
    vw = cv2.VideoWriter(str(out_path), fourcc, fps, (640, 480))
    for f in range(total_frames):
        frame = draw_background()
        cv2.putText(frame, "SCENARIO: CROWD SURGE (>5 Persons)", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (251, 191, 36), 2)

        # 6 people congregating near center
        coords = [
            (220, 260), (280, 270), (250, 320),
            (320, 310), (210, 340), (270, 360)
        ]
        for idx, (bx, by) in enumerate(coords):
            # subtle jitter
            jx = bx + int(3 * np.sin(f * 0.2 + idx))
            jy = by + int(2 * np.cos(f * 0.2 + idx))
            draw_person(frame, jx, jy, 36, 80, f"P{idx+1}", (245, 158, 11))

        vw.write(frame)
    vw.release()
    print(f"Generated: {out_path}")

    # 4. Suspicious Activity (Loitering) Clip
    out_path = out_dir / "test_suspicious.mp4"
    vw = cv2.VideoWriter(str(out_path), fourcc, fps, (640, 480))
    for f in range(total_frames):
        frame = draw_background()
        cv2.putText(frame, "SCENARIO: SUSPICIOUS ACTIVITY (Restricted Zone Dwell)", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (56, 189, 248), 2)

        # Person enters restricted corridor [500, 100] to [620, 350] and paces slowly
        px = 530 + int(15 * np.sin(f * 0.1))
        py = 180 + int(20 * np.cos(f * 0.08))
        dwell_time = f / fps
        label = f"Loitering ({dwell_time:.1f}s)" if f > 15 else "Subject"
        draw_person(frame, px, py, 38, 85, label, (244, 63, 94) if f > 40 else (56, 189, 248))

        vw.write(frame)
    vw.release()
    print(f"Generated: {out_path}")

    # 5. Normal Activity Clip
    out_path = out_dir / "test_normal.mp4"
    vw = cv2.VideoWriter(str(out_path), fourcc, fps, (640, 480))
    for f in range(total_frames):
        frame = draw_background()
        cv2.putText(frame, "SCENARIO: ROUTINE PASSAGE (Normal Authorized)", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (16, 185, 129), 2)

        px = 80 + f * 6
        py = 310
        draw_person(frame, px, py, 40, 90, "Staff Member", (16, 185, 129))

        vw.write(frame)
    vw.release()
    print(f"Generated: {out_path}")


if __name__ == "__main__":
    generate_clips()
