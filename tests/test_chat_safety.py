"""Unit tests for ChatEngine SQL Validation and Safety (Standard Library unittest)."""

import tempfile
import unittest
from pathlib import Path
from backend.server.chat import ChatEngine
from backend.server.db import Database


class TestChatSafety(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmpdir.name) / "test.db"))
        self.chat_engine = ChatEngine(db=self.db)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_valid_select_query(self):
        sql = "SELECT * FROM events WHERE category = 'tailgating' LIMIT 20;"
        valid, sanitized = self.chat_engine.validate_sql(sql)
        self.assertTrue(valid)
        self.assertIn("LIMIT 20", sanitized)
        self.assertTrue(sanitized.startswith("SELECT"))

    def test_reject_drop_table(self):
        sql = "DROP TABLE events;"
        valid, _ = self.chat_engine.validate_sql(sql)
        self.assertFalse(valid)

    def test_reject_insert_update_delete(self):
        for bad_sql in [
            "INSERT INTO events (category) VALUES ('tailgating')",
            "UPDATE events SET category = 'none'",
            "DELETE FROM events WHERE id = 1",
        ]:
            valid, _ = self.chat_engine.validate_sql(bad_sql)
            self.assertFalse(valid)

    def test_reject_semicolon_stacking(self):
        sql = "SELECT * FROM events; DROP TABLE events"
        valid, _ = self.chat_engine.validate_sql(sql)
        self.assertFalse(valid)

    def test_reject_other_tables(self):
        sql = "SELECT * FROM sqlite_master"
        valid, _ = self.chat_engine.validate_sql(sql)
        self.assertFalse(valid)

    def test_clamp_large_limit(self):
        sql = "SELECT * FROM events LIMIT 500"
        valid, sanitized = self.chat_engine.validate_sql(sql)
        self.assertTrue(valid)
        self.assertIn("LIMIT 100", sanitized)

    def test_auto_inject_limit_if_missing(self):
        sql = "SELECT * FROM events WHERE camera_id = 'cam1'"
        valid, sanitized = self.chat_engine.validate_sql(sql)
        self.assertTrue(valid)
        self.assertIn("LIMIT 50", sanitized)

    def test_normalize_ilike_to_like(self):
        sql = "SELECT * FROM events WHERE summary ILIKE '%gun%' LIMIT 10"
        valid, sanitized = self.chat_engine.validate_sql(sql)
        self.assertTrue(valid)
        self.assertNotIn("ILIKE", sanitized)
        self.assertIn("LIKE", sanitized)

    def test_fallback_sql_weapons_and_hazards(self):
        sql_weapon = self.chat_engine._template_sql_fallback("Were any firearms or weapons detected?", "2026-10-16")
        self.assertIn("weapon", sql_weapon.lower())

        sql_hazard = self.chat_engine._template_sql_fallback("Show dangerous terrain and fall hazards", "2026-10-16")
        self.assertTrue("hazard" in sql_hazard.lower() or "terrain" in sql_hazard.lower())


if __name__ == "__main__":
    unittest.main()
