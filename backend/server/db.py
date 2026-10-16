"""
EventLens SQLite Database Access Layer.

Handles storage and retrieval of classified video events, keyframe references,
VLM verification status, latency telemetry, and safe read-only queries for conversational search.
"""

from contextlib import contextmanager
from datetime import datetime
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional
import numpy as np

logger = logging.getLogger("eventlens.db")

VALID_CATEGORIES = {
    "person_down",
    "fighting",
    "tailgating",
    "crowd_incident",
    "suspicious_activity",
}


class Database:
    def __init__(self, db_path: str = "data/events.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

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

            # Incremental column additions
            for col_def in [
                ("tags", "TEXT DEFAULT '[]'"),
                ("verified", "INTEGER DEFAULT 1"),
                ("verdict", "TEXT DEFAULT 'yes'"),
                ("status", "TEXT DEFAULT 'verified'"),
                ("vlm_latency_ms", "INTEGER DEFAULT 0"),
                ("raw_response", "TEXT DEFAULT ''"),
                ("rejection_reason", "TEXT DEFAULT ''"),
            ]:
                try:
                    cursor.execute(f"ALTER TABLE events ADD COLUMN {col_def[0]} {col_def[1]}")
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
        verified = 1 if event.get("verified", True) else 0
        status = event.get("status", "verified" if verified else "rejected")
        verdict = event.get("verdict", "yes" if verified else "no")
        latency_ms = int(event.get("latency_ms", 0))
        vlm_latency_ms = int(event.get("vlm_latency_ms", latency_ms))
        if latency_ms == 0 and vlm_latency_ms > 0:
            latency_ms = vlm_latency_ms

        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO events (
                    timestamp, camera_id, category, confidence, summary,
                    keyframe_path, track_ids, latency_ms, tags,
                    verified, verdict, status, vlm_latency_ms, raw_response, rejection_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    event.get("camera_id", "cam1"),
                    event.get("category", "suspicious_activity"),
                    float(event.get("confidence", 0.0)),
                    event.get("summary", ""),
                    event.get("keyframe_path", ""),
                    track_ids_str,
                    latency_ms,
                    tags_str,
                    verified,
                    verdict,
                    status,
                    vlm_latency_ms,
                    event.get("raw_response", ""),
                    event.get("rejection_reason", ""),
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
        status: Optional[str] = "high",
        limit: int = 150,
    ) -> List[Dict[str, Any]]:
        """Filters events based on category, camera, timestamp, and verification/confidence tier."""
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

        # Verification & confidence status tiers
        if status == "high":
            query += " AND verified = 1 AND confidence >= 0.75"
        elif status == "all_verified":
            query += " AND verified = 1"
        elif status == "needs_review":
            query += " AND verified = 1 AND confidence < 0.75"
        elif status == "rejected":
            query += " AND verified = 0"
        elif status == "all":
            pass  # return everything
        else:
            # Default is high confidence
            query += " AND verified = 1 AND confidence >= 0.75"

        # Sort by time descending, secondary sort by confidence
        query += " ORDER BY timestamp DESC, confidence DESC LIMIT ?"
        params.append(min(limit, 10000))

        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_event_dict(r) for r in rows]

    def get_stats(self) -> Dict[str, Any]:
        """Calculates dashboard summary stats: verified count, p50/p95 VLM latency, and categories."""
        today_prefix = datetime.now().strftime("%Y-%m-%d")

        with self._connection() as conn:
            cursor = conn.cursor()

            # Counts per category (only verified events count toward statistics)
            cursor.execute(
                """
                SELECT category, COUNT(*) as count
                FROM events
                WHERE verified = 1
                GROUP BY category
                """
            )
            counts_by_cat = {cat: 0 for cat in VALID_CATEGORIES}
            for row in cursor.fetchall():
                if row["category"] in counts_by_cat:
                    counts_by_cat[row["category"]] = row["count"]

            # Verified events today
            cursor.execute(
                "SELECT COUNT(*) as count FROM events WHERE verified = 1 AND timestamp LIKE ?",
                (f"{today_prefix}%",),
            )
            events_today = cursor.fetchone()["count"]

            # Total verified events
            cursor.execute("SELECT COUNT(*) as count FROM events WHERE verified = 1")
            total_verified = cursor.fetchone()["count"]

            # Total rejected events
            cursor.execute("SELECT COUNT(*) as count FROM events WHERE verified = 0")
            total_rejected = cursor.fetchone()["count"]

            # Compute p50 and p95 latency on verified events
            cursor.execute(
                """
                SELECT COALESCE(NULLIF(vlm_latency_ms, 0), latency_ms) as lat
                FROM events
                WHERE verified = 1 AND (latency_ms > 0 OR vlm_latency_ms > 0)
                """
            )
            lats = [r["lat"] for r in cursor.fetchall()]

            if lats:
                p50 = float(np.percentile(lats, 50))
                p95 = float(np.percentile(lats, 95))
            else:
                p50, p95 = 0.0, 0.0

            return {
                "categories": counts_by_cat,
                "events_today": events_today,
                "total_events": total_verified,
                "total_verified": total_verified,
                "verified_events": total_verified,
                "total_rejected": total_rejected,
                "avg_latency_ms": round(p50, 1),
                "p50_latency_ms": round(p50, 1),
                "p95_latency_ms": round(p95, 1),
            }

    def run_readonly_query(self, sql: str) -> List[Dict[str, Any]]:
        """Executes a sanitized read-only SELECT query for conversational querying."""
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

        tags = []
        try:
            if "tags" in row.keys() and row["tags"]:
                tags = json.loads(row["tags"])
        except Exception:
            tags = []

        verified = True
        try:
            if "verified" in row.keys() and row["verified"] is not None:
                verified = bool(row["verified"])
        except Exception:
            pass

        keyframe_path = row["keyframe_path"] or ""
        keyframe_url = f"/frames/{row['id']}.jpg" if keyframe_path else ""

        return {
            "id": row["id"],
            "timestamp": row["timestamp"],
            "camera_id": row["camera_id"],
            "category": row["category"],
            "confidence": round(float(row["confidence"]), 2),
            "summary": row["summary"],
            "keyframe_path": keyframe_path,
            "keyframe_url": keyframe_url,
            "track_ids": track_ids,
            "latency_ms": row["latency_ms"],
            "tags": tags,
            "verified": verified,
            "status": row["status"] if ("status" in row.keys() and row["status"]) else ("verified" if verified else "rejected"),
        }
