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
                cursor.execute("ALTER TABLE events ADD COLUMN end_time TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE events ADD COLUMN occurrences INTEGER DEFAULT 1")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE events ADD COLUMN vlm_latency_ms INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE events ADD COLUMN rule_latency_ms INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE events ADD COLUMN status TEXT DEFAULT 'new'")
            except sqlite3.OperationalError:
                pass
            conn.commit()

    def update_event_status(self, event_id: int, status: str) -> bool:
        """Updates incident status (new, acknowledged, dismissed, escalated)."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE events SET status = ? WHERE id = ?", (status, event_id))
            conn.commit()
            return cursor.rowcount > 0

    def find_recent_matching_incident(
        self,
        camera_id: str,
        category: str,
        track_ids: List[int],
        within_seconds: float = 60.0,
    ) -> Optional[int]:
        """Finds an existing active incident within within_seconds that shares at least one track ID."""
        if not track_ids:
            return None
        target_ids = set(track_ids)
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, timestamp, end_time, track_ids
                FROM events
                WHERE camera_id = ? AND category = ?
                ORDER BY id DESC LIMIT 10
                """,
                (camera_id, category),
            )
            rows = cursor.fetchall()
            now = datetime.now()
            for r in rows:
                t_str = r["end_time"] or r["timestamp"]
                try:
                    dt = datetime.fromisoformat(t_str)
                    elapsed = abs((now - dt).total_seconds())
                except Exception:
                    elapsed = 0.0

                if elapsed <= within_seconds:
                    try:
                        row_tids = set(json.loads(r["track_ids"]))
                    except Exception:
                        row_tids = set()
                    if target_ids.intersection(row_tids):
                        return r["id"]
        return None

    def extend_incident(
        self,
        event_id: int,
        end_time: str,
        keyframe_path: Optional[str] = None,
        vlm_latency_ms: int = 0,
    ):
        """Extends an existing incident duration and occurrences counter."""
        with self._connection() as conn:
            cursor = conn.cursor()
            if keyframe_path:
                cursor.execute(
                    """
                    UPDATE events
                    SET occurrences = COALESCE(occurrences, 1) + 1,
                        end_time = ?,
                        keyframe_path = ?,
                        vlm_latency_ms = CASE WHEN ? > 0 THEN ? ELSE vlm_latency_ms END
                    WHERE id = ?
                    """,
                    (end_time, keyframe_path, vlm_latency_ms, vlm_latency_ms, event_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE events
                    SET occurrences = COALESCE(occurrences, 1) + 1,
                        end_time = ?,
                        vlm_latency_ms = CASE WHEN ? > 0 THEN ? ELSE vlm_latency_ms END
                    WHERE id = ?
                    """,
                    (end_time, vlm_latency_ms, vlm_latency_ms, event_id),
                )
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
        end_time = event.get("end_time") or timestamp
        verified = 1 if event.get("verified", True) else 0
        occurrences = int(event.get("occurrences", 1))
        vlm_latency = int(event.get("vlm_latency_ms", event.get("latency_ms", 0)))
        rule_latency = int(event.get("rule_latency_ms", 0))
        status = str(event.get("status", "new"))

        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO events (
                    timestamp, camera_id, category, confidence, summary,
                    keyframe_path, track_ids, latency_ms, tags,
                    verified, end_time, occurrences, vlm_latency_ms, rule_latency_ms, status
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
                    int(event.get("latency_ms", 0)),
                    tags_str,
                    verified,
                    end_time,
                    occurrences,
                    vlm_latency,
                    rule_latency,
                    status,
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
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Filters events based on category, camera, and timestamp."""
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

            # Counts per category
            cursor.execute(
                """
                SELECT category, COUNT(*) as count
                FROM events
                GROUP BY category
                """
            )
            counts_by_cat = {cat: 0 for cat in VALID_CATEGORIES}
            for row in cursor.fetchall():
                counts_by_cat[row["category"]] = row["count"]

            # Events today
            cursor.execute(
                "SELECT COUNT(*) as count FROM events WHERE timestamp LIKE ?",
                (f"{today_prefix}%",),
            )
            events_today = cursor.fetchone()["count"]

            # Total events
            cursor.execute("SELECT COUNT(*) as count FROM events")
            total_events = cursor.fetchone()["count"]

            # Open incidents
            try:
                cursor.execute("SELECT COUNT(*) as count FROM events WHERE status != 'dismissed'")
                open_incidents = cursor.fetchone()["count"]
            except Exception:
                open_incidents = total_events

            # Latency stats (p50 and avg)
            cursor.execute(
                "SELECT latency_ms FROM events WHERE latency_ms > 0 ORDER BY latency_ms"
            )
            lat_rows = cursor.fetchall()
            if lat_rows:
                lats = [r["latency_ms"] for r in lat_rows]
                avg_latency = round(sum(lats) / len(lats), 1)
                p50_latency = round(lats[len(lats) // 2], 1)
            else:
                avg_latency = 0.0
                p50_latency = 0.0

            return {
                "categories": counts_by_cat,
                "events_today": events_today,
                "total_events": total_events,
                "open_incidents": open_incidents,
                "avg_latency_ms": avg_latency,
                "p50_latency_ms": p50_latency,
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

        # Read optional extension columns defensively
        keys = row.keys()
        verified = bool(row["verified"]) if "verified" in keys and row["verified"] is not None else True
        end_time = row["end_time"] if "end_time" in keys and row["end_time"] else row["timestamp"]
        occurrences = int(row["occurrences"]) if "occurrences" in keys and row["occurrences"] is not None else 1
        vlm_latency = int(row["vlm_latency_ms"]) if "vlm_latency_ms" in keys and row["vlm_latency_ms"] is not None else row["latency_ms"]
        rule_latency = int(row["rule_latency_ms"]) if "rule_latency_ms" in keys and row["rule_latency_ms"] is not None else 0
        status = str(row["status"]) if "status" in keys and row["status"] else "new"

        return {
            "id": row["id"],
            "timestamp": row["timestamp"],
            "end_time": end_time,
            "occurrences": occurrences,
            "verified": verified,
            "status": status,
            "camera_id": row["camera_id"],
            "category": row["category"],
            "confidence": round(float(row["confidence"]), 2),
            "summary": row["summary"],
            "keyframe_url": keyframe_url,
            "track_ids": track_ids,
            "latency_ms": row["latency_ms"],
            "vlm_latency_ms": vlm_latency,
            "rule_latency_ms": rule_latency,
            "tags": tags,
        }
