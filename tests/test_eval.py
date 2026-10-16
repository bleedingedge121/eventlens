"""Unit and regression tests for EventLens Evaluation Harness."""

from pathlib import Path
import pytest
from eval.run_eval import (
    CATEGORIES,
    calculate_metrics_from_counts,
    compute_latency_percentiles,
    load_ground_truth,
    find_video_clip,
    run_simulation_mode,
)


class TestEvalHarness:
    def test_calculate_metrics_known_matrix(self):
        tp = {"person_down": 8, "fighting": 5, "tailgating": 10, "crowd_incident": 0, "suspicious_activity": 0}
        fp = {"person_down": 2, "fighting": 0, "tailgating": 0, "crowd_incident": 1, "suspicious_activity": 0}
        fn = {"person_down": 2, "fighting": 5, "tailgating": 0, "crowd_incident": 0, "suspicious_activity": 4}

        metrics = calculate_metrics_from_counts(tp, fp, fn)

        # person_down: TP=8, FP=2, FN=2 -> P = 8/10 = 0.8, R = 8/10 = 0.8, F1 = 0.8
        assert metrics["person_down"]["precision"] == 0.8
        assert metrics["person_down"]["recall"] == 0.8
        assert metrics["person_down"]["f1"] == 0.8

        # fighting: TP=5, FP=0, FN=5 -> P = 5/5 = 1.0, R = 5/10 = 0.5, F1 = (2*1.0*0.5)/1.5 = 0.667
        assert metrics["fighting"]["precision"] == 1.0
        assert metrics["fighting"]["recall"] == 0.5
        assert metrics["fighting"]["f1"] == 0.667

        # tailgating: TP=10, FP=0, FN=0 -> P=1.0, R=1.0, F1=1.0
        assert metrics["tailgating"]["precision"] == 1.0
        assert metrics["tailgating"]["recall"] == 1.0
        assert metrics["tailgating"]["f1"] == 1.0

        # suspicious_activity: TP=0, FP=0, FN=4 -> P=0.0, R=0.0, F1=0.0
        assert metrics["suspicious_activity"]["precision"] == 0.0
        assert metrics["suspicious_activity"]["recall"] == 0.0
        assert metrics["suspicious_activity"]["f1"] == 0.0

    def test_calculate_metrics_zero_division_safety(self):
        tp = {c: 0 for c in CATEGORIES}
        fp = {c: 0 for c in CATEGORIES}
        fn = {c: 0 for c in CATEGORIES}

        metrics = calculate_metrics_from_counts(tp, fp, fn)
        for c in CATEGORIES:
            assert metrics[c]["precision"] == 0.0
            assert metrics[c]["recall"] == 0.0
            assert metrics[c]["f1"] == 0.0
        assert metrics["overall"]["precision"] == 0.0

    def test_compute_latency_percentiles(self):
        # Empty latencies
        res_empty = compute_latency_percentiles([])
        assert res_empty["samples"] == 0
        assert res_empty["median_latency_ms"] == 0.0
        assert res_empty["p95_latency_ms"] == 0.0

        # Known latencies: [100, 200, 300, 400, 500]
        lats = [100.0, 200.0, 300.0, 400.0, 500.0]
        res = compute_latency_percentiles(lats)
        assert res["samples"] == 5
        assert res["median_latency_ms"] == 300.0
        assert res["min_latency_ms"] == 100.0
        assert res["max_latency_ms"] == 500.0
        assert res["mean_latency_ms"] == 300.0

    def test_load_ground_truth_missing_file_handled(self, tmp_path):
        missing = tmp_path / "nonexistent.csv"
        gt = load_ground_truth(missing)
        assert gt == []

    def test_find_video_clip(self, tmp_path):
        dir1 = tmp_path / "v1"
        dir1.mkdir()
        clip = dir1 / "clip_a.mp4"
        clip.write_bytes(b"dummy")

        dir2 = tmp_path / "v2"
        dir2.mkdir()

        found = find_video_clip("clip_a.mp4", [dir2, dir1])
        assert found == clip

        not_found = find_video_clip("clip_missing.mp4", [dir2, dir1])
        assert not_found is None

    def test_simulation_mode_is_explicitly_labeled(self):
        sample_gt = [
            {"clip_name": "test1.mp4", "category": "person_down", "start_sec": 1.0},
            {"clip_name": "test2.mp4", "category": "tailgating", "start_sec": 2.0},
        ]
        res = run_simulation_mode(sample_gt)
        assert res["is_simulated"] is True
        assert "warning" in res
        assert res["classification"]["person_down"]["tp"] == 1
        assert res["classification"]["tailgating"]["tp"] == 1
