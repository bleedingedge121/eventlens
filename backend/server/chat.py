"""EventLens Natural Language Conversational Querying.

Adheres strictly to AGENTS.md Section 12 rules:
1. Gives the model the schema and example question-to-SQL pairs.
2. Resolves time keywords ("today", "last hour") in Python before prompting.
3. Strictly validates generated SQL:
   - Starts with SELECT
   - References ONLY 'events' table
   - Contains NO semicolons or multiple statements
   - Contains NO write/mutating keywords (DROP, DELETE, UPDATE, INSERT, ALTER, etc.)
   - Enforces LIMIT <= 100
4. Executes on read-only SQLite connection.
5. Falls back to deterministic rule templates if validation or model fails.
6. Returns {"answer": str, "sql": str, "events": list}.
"""

from datetime import datetime, timedelta
import json
import re
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from backend.server.db import Database

FORBIDDEN_SQL_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "replace", "pragma", "attach", "detach", "vacuum", "reindex", "exec", "execute"
}


class ChatEngine:
    def __init__(
        self,
        db: Database,
        ollama_host: str = "http://localhost:11434",
        model_name: str = "Hermes-4-14B:latest",
    ):
        self.db = db
        self.ollama_host = ollama_host.rstrip("/")
        self.model_name = model_name

    def answer_question(self, question: str) -> Dict[str, Any]:
        """Translates natural language question -> validated SQL -> executes -> formats answer."""
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        one_hour_ago = (now - timedelta(hours=1)).isoformat(timespec="seconds")

        # 1. Attempt LLM text-to-SQL
        sql = self._generate_sql_with_llm(question, today_str, one_hour_ago)

        # 2. Validate SQL strictly
        is_valid, sanitized_sql = self.validate_sql(sql)
        if not is_valid:
            # Fallback to deterministic template matching
            sanitized_sql = self._template_sql_fallback(question, today_str)

        # 3. Execute query
        try:
            events = self.db.run_readonly_query(sanitized_sql)
        except Exception:
            # If query failed, fallback to default safe query
            sanitized_sql = "SELECT * FROM events ORDER BY id DESC LIMIT 10"
            events = self.db.run_readonly_query(sanitized_sql)

        # 4. Generate summary answer
        answer = self._synthesize_answer(question, events, sanitized_sql)

        return {
            "answer": answer,
            "sql": sanitized_sql,
            "events": events,
        }

    def validate_sql(self, sql: str) -> Tuple[bool, str]:
        """Validates that SQL is a single, safe, read-only SELECT query on the events table."""
        if not sql:
            return False, ""

        cleaned = sql.strip().strip(";").strip()
        cleaned_lower = cleaned.lower()

        # Must start with SELECT
        if not cleaned_lower.startswith("select"):
            return False, ""

        # Normalize PostgreSQL ILIKE to SQLite LIKE
        cleaned = re.sub(r"\bILIKE\b", "LIKE", cleaned, flags=re.IGNORECASE)
        cleaned_lower = cleaned.lower()

        # Reject any semicolon in the body
        if ";" in cleaned:
            return False, ""

        # Reject forbidden mutation words
        tokens = re.findall(r"\b[a-zA-Z_]+\b", cleaned_lower)
        for token in tokens:
            if token in FORBIDDEN_SQL_KEYWORDS:
                return False, ""

        # Must query only the 'events' table
        from_matches = re.findall(r"\bfrom\s+([a-zA-Z0-9_]+)", cleaned_lower)
        if not from_matches or any(table != "events" for table in from_matches):
            return False, ""

        # Enforce or inject LIMIT
        if "limit" not in cleaned_lower:
            cleaned += " LIMIT 50"
        else:
            # If limit is > 100, clamp it
            match = re.search(r"\blimit\s+(\d+)", cleaned_lower)
            if match and int(match.group(1)) > 100:
                cleaned = re.sub(r"\blimit\s+\d+", "LIMIT 100", cleaned, flags=re.IGNORECASE)

        return True, cleaned

    def _generate_sql_with_llm(self, question: str, today_str: str, one_hour_ago: str) -> str:
        prompt = f"""You are an expert SQLite translator for the EventLens video surveillance system.
Convert the user question into ONE SINGLE valid SQLite SELECT query on the 'events' table.

TABLE SCHEMA:
events (
  id INTEGER PRIMARY KEY,
  timestamp TEXT,        -- Format: YYYY-MM-DDTHH:MM:SS
  camera_id TEXT,        -- e.g. 'cam1', 'cam2'
  category TEXT,         -- one of: 'person_down', 'fighting', 'tailgating', 'crowd_incident', 'suspicious_activity', 'suicide_risk'
  confidence REAL,       -- 0.0 to 1.0
  summary TEXT,          -- description text
  track_ids TEXT,        -- JSON array of person IDs e.g. '[1, 2]'
  tags TEXT,             -- JSON array of tags e.g. '["tailgating", "weapon_detected", "dangerous_terrain", "fall_hazard"]'
  latency_ms INTEGER
)

TEMPORAL CONTEXT:
Current date is: {today_str}
One hour ago was: {one_hour_ago}

EXAMPLES:
Q: "Show all tailgating events from camera 2 today"
SQL: SELECT * FROM events WHERE category = 'tailgating' AND camera_id = 'cam2' AND timestamp LIKE '{today_str}%' ORDER BY timestamp DESC LIMIT 50;

Q: "Show all events with weapons"
SQL: SELECT * FROM events WHERE summary LIKE '%[WEAPON%' OR tags LIKE '%weapon%' ORDER BY id DESC LIMIT 50;

Q: "Show dangerous terrain or hazard zone events"
SQL: SELECT * FROM events WHERE category = 'suicide_risk' OR tags LIKE '%dangerous_terrain%' OR tags LIKE '%hazard%' ORDER BY id DESC LIMIT 50;

Q: "Did anyone fall down in the last hour?"
SQL: SELECT * FROM events WHERE category = 'person_down' AND timestamp >= '{one_hour_ago}' ORDER BY timestamp DESC LIMIT 20;

Q: "Count events by category"
SQL: SELECT * FROM events ORDER BY id DESC LIMIT 50;

RULES:
- Return ONLY the raw SQL statement. No explanations, no markdown codeblocks.
- Use only SELECT queries on the 'events' table.
- Always include LIMIT (maximum 100).

User Question: {question}
SQL:"""

        try:
            req = urllib.request.Request(
                f"{self.ollama_host}/api/generate",
                data=json.dumps({
                    "model": self.model_name,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.0, "num_predict": 80}
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                sql = data.get("response", "").strip()
                # Clean markdown backticks if returned
                sql = re.sub(r"```(?:sql)?", "", sql).replace("```", "").strip()
                return sql
        except Exception:
            return ""

    def _template_sql_fallback(self, question: str, today_str: str) -> str:
        """Rule-based fallback SQL generator if Ollama is unreachable or returns invalid syntax."""
        q = question.lower()

        # Camera detection
        cam = None
        if "camera 1" in q or "cam 1" in q or "cam1" in q:
            cam = "cam1"
        elif "camera 2" in q or "cam 2" in q or "cam2" in q:
            cam = "cam2"

        # Category detection
        category = None
        if "tailgating" in q or "tailgate" in q:
            category = "tailgating"
        elif "person down" in q or "fall" in q or "fell" in q or "collapsed" in q:
            category = "person_down"
        elif "fight" in q or "fighting" in q or "altercation" in q:
            category = "fighting"
        elif "crowd" in q or "gathering" in q:
            category = "crowd_incident"
        elif "suspicious" in q or "loitering" in q:
            category = "suspicious_activity"

        # Weapon / firearm detection
        is_weapon = any(w in q for w in ["weapon", "gun", "firearm", "pistol", "rifle", "knife", "blade", "armed", "shooting", "shot"])

        # Today detection
        is_today = "today" in q

        clauses = []
        if category:
            clauses.append(f"category = '{category}'")
        if cam:
            clauses.append(f"camera_id = '{cam}'")
        if is_today:
            clauses.append(f"timestamp LIKE '{today_str}%'")
        if is_weapon:
            clauses.append("(summary LIKE '%[WEAPON%' OR summary LIKE '%gun%' OR summary LIKE '%knife%' OR tags LIKE '%weapon%')")

        # Dangerous terrain / hazard detection
        is_hazard = any(t in q for t in ["terrain", "hazard", "ledge", "balcony", "spill", "slip", "stairwell", "drop", "voltage"])
        if is_hazard:
            clauses.append("(category = 'suicide_risk' OR tags LIKE '%dangerous_terrain%' OR tags LIKE '%hazard%' OR summary LIKE '%hazard%' OR summary LIKE '%ledge%')")

        where_str = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return f"SELECT * FROM events{where_str} ORDER BY id DESC LIMIT 50"

    def _synthesize_answer(self, question: str, events: List[Dict[str, Any]], sql: str) -> str:
        """Formats a natural, transparent English response."""
        count = len(events)
        if count == 0:
            return f"No events matched your query ({sql}). The surveillance database currently records 0 matching incidents."

        latest = events[0]
        cat_counts = {}
        for ev in events:
            c = ev.get("category", "event")
            cat_counts[c] = cat_counts.get(c, 0) + 1

        breakdown = ", ".join(f"{cnt} {cat}" for cat, cnt in cat_counts.items())

        answer = (
            f"Found {count} matching event{'s' if count != 1 else ''} ({breakdown}). "
            f"Most recent: [ID #{latest['id']} on {latest['camera_id']} at {latest['timestamp']}] "
            f"\"{latest['summary']}\""
        )
        return answer
