"""EventLens SQLite Database Manager.

Adheres strictly to AGENTS.md Section 9 schema:
events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT,        -- ISO 8601
  camera_id TEXT,
  category TEXT,         -- one of the five categories
  confidence REAL,       -- 0..1
  summary TEXT,
  keyframe_path TEXT,
  track_ids TEXT,        -- JSON list
  latency_ms INTEGER     -- trigger to saved
)
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

VALID_CATEGORIES = {
    "person_down",
    "fighting",
    "tailgating",
    "crowd_incident",
    "suspicious_activity",
    "suicide_risk",
}


class Database:
    def __init__(self, db_path: str = "data/events.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    from contextlib import contextmanager

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def init_db(self):
        """Creates the events table and indices if they do not exist."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    camera_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    summary TEXT NOT NULL,
                    keyframe_path TEXT,
                    track_ids TEXT,
                    latency_ms INTEGER DEFAULT 0
                )
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_category ON events(category)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_camera ON events(camera_id)")
            # Add tags column if not exists
            try:
                cursor.execute("ALTER TABLE events ADD COLUMN tags TEXT DEFAULT '[]'")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE events ADD COLUMN verified INTEGER DEFAULT 1")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE events ADD COLUMN verification_status TEXT DEFAULT 'vlm_confirmed'")
            except sqlite3.OperationalError:
                pass
            conn.commit()

    def insert_event(self, event: Dict[str, Any]) -> int:
        """Inserts an event dictionary into the database. Returns the generated ID."""
        track_ids_val = event.get("track_ids", [])
        if isinstance(track_ids_val, (list, tuple)):
            track_ids_str = json.dumps(track_ids_val)
        else:
            track_ids_str = str(track_ids_val)

        tags_val = event.get("tags", [])
        if isinstance(tags_val, (list, tuple)):
            tags_str = json.dumps(tags_val)
        else:
            tags_str = str(tags_val)

        timestamp = event.get("timestamp") or datetime.now().isoformat(timespec="seconds")
        verified_val = int(bool(event.get("verified", True)))
        verification_status_val = str(event.get("verification_status", "vlm_confirmed" if verified_val else "unverified"))

        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO events (
                    timestamp, camera_id, category, confidence, summary,
                    keyframe_path, track_ids, latency_ms, tags, verified, verification_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    event.get("camera_id", "cam1"),
                    event.get("category", "suspicious_activity"),
                    float(event.get("confidence", 0.0)),
                    event.get("summary", ""),
                    event.get("keyframe_path", ""),
                    track_ids_str,
                    int(event.get("latency_ms", 0)),
                    tags_str,
                    verified_val,
                    verification_status_val,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def update_keyframe_path(self, event_id: int, keyframe_path: str):
        """Updates the keyframe path for a recorded event."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE events SET keyframe_path = ? WHERE id = ?", (keyframe_path, event_id))
            conn.commit()

    def clear_events(self) -> int:
        """Clears all records from the events table."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM events")
            cursor.execute("DELETE FROM sqlite_sequence WHERE name='events'")
            conn.commit()
            return cursor.rowcount

    def get_event(self, event_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves a single event by ID formatted according to the Section 8 contract."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM events WHERE id = ?", (event_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_event_dict(row)

    def query_events(
        self,
        category: Optional[str] = None,
        camera_id: Optional[str] = None,
        since: Optional[str] = None,
        verified: Optional[bool] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Filters events based on category, camera, timestamp, and verification status."""
        query = "SELECT * FROM events WHERE 1=1"
        params: List[Any] = []

        if category:
            query += " AND category = ?"
            params.append(category)
        if camera_id:
            query += " AND camera_id = ?"
            params.append(camera_id)
        if since:
            query += " AND timestamp >= ?"
            params.append(since)
        if verified is not None:
            query += " AND verified = ?"
            params.append(1 if verified else 0)

        query += " ORDER BY id DESC LIMIT ?"
        params.append(min(limit, 10000))

        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_event_dict(r) for r in rows]

    def get_stats(self) -> Dict[str, Any]:
        """Calculates dashboard summary stats: counts per category, average latency, and today's total."""
        today_prefix = datetime.now().strftime("%Y-%m-%d")

        with self._connection() as conn:
            cursor = conn.cursor()

            # Counts per category (only verified events or all events)
            cursor.execute(
                """
                SELECT category, COUNT(*) as count
                FROM events
                WHERE verified = 1 OR verified IS NULL
                GROUP BY category
                """
            )
            counts_by_cat = {cat: 0 for cat in VALID_CATEGORIES}
            for row in cursor.fetchall():
                counts_by_cat[row["category"]] = row["count"]

            # Events today (verified)
            cursor.execute(
                "SELECT COUNT(*) as count FROM events WHERE timestamp LIKE ? AND (verified = 1 OR verified IS NULL)",
                (f"{today_prefix}%",),
            )
            events_today = cursor.fetchone()["count"]

            # Total verified events
            cursor.execute("SELECT COUNT(*) as count FROM events WHERE verified = 1 OR verified IS NULL")
            total_events = cursor.fetchone()["count"]

            # Total unverified candidates / failures
            cursor.execute("SELECT COUNT(*) as count FROM events WHERE verified = 0")
            unverified_candidates = cursor.fetchone()["count"]

            # Avg latency
            cursor.execute(
                "SELECT AVG(latency_ms) as avg_lat FROM events WHERE latency_ms > 0"
            )
            avg_row = cursor.fetchone()
            avg_latency = round(avg_row["avg_lat"] or 0, 1)

            return {
                "categories": counts_by_cat,
                "events_today": events_today,
                "total_events": total_events,
                "unverified_candidates": unverified_candidates,
                "avg_latency_ms": avg_latency,
            }

    def run_readonly_query(self, sql: str) -> List[Dict[str, Any]]:
        """Executes a sanitized read-only SELECT query for conversational querying."""
        # Open in read-only mode using SQLite URI (cross-platform safe for Windows & POSIX)
        uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute(sql)
            rows = cursor.fetchall()
            return [self._row_to_event_dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def _row_to_event_dict(row: sqlite3.Row) -> Dict[str, Any]:
        """Converts an SQLite row to the Section 8 Event JSON contract."""
        track_ids = []
        if row["track_ids"]:
            try:
                track_ids = json.loads(row["track_ids"])
            except Exception:
                track_ids = []

        keyframe_path = row["keyframe_path"] or ""
        keyframe_url = f"/frames/{Path(keyframe_path).name}" if keyframe_path else f"/frames/{row['id']}.jpg"

        tags = []
        try:
            if "tags" in row.keys() and row["tags"]:
                tags = json.loads(row["tags"])
        except Exception:
            tags = []
        if not tags:
            tags = [row["category"]]
            if "[WEAPON" in row["summary"]:
                tags.append("weapon_detected")

        verified = True
        try:
            if "verified" in row.keys() and row["verified"] is not None:
                verified = bool(row["verified"])
        except Exception:
            verified = True

        verification_status = "vlm_confirmed" if verified else "unverified"
        try:
            if "verification_status" in row.keys() and row["verification_status"]:
                verification_status = str(row["verification_status"])
        except Exception:
            pass

        return {
            "id": row["id"],
            "timestamp": row["timestamp"],
            "camera_id": row["camera_id"],
            "category": row["category"],
            "confidence": round(float(row["confidence"]), 2),
            "summary": row["summary"],
            "keyframe_url": keyframe_url,
            "track_ids": track_ids,
            "latency_ms": row["latency_ms"],
            "tags": tags,
            "verified": verified,
            "verification_status": verification_status,
        }
