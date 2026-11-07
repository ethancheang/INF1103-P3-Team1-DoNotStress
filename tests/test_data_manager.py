"""Tests for Data Manager persistence.

Uses temporary directories so no real data files are touched.
Covers save/load, missing files, and corrupt JSON.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import data_manager


@pytest.fixture
def tmp_data_path(tmp_path: Path) -> Path:
    return tmp_path / "student_records.json"


def _valid_ai_record(**overrides):
    """Minimal record that passes Data Manager AI-success validation."""
    base = {
        "student_id": "test123",
        "source": "gemini",
        "ai_ok": True,
        "risk_category": "Low",
        "stress_score": 1.5,
        "risk_score": 0.2,
        "confidence": 0.9,
        "primary_stressors": [],
        "reasoning": "Steady check-in.",
        "recommended_support": "None needed",
        "soft_label": "You're doing ok",
        "tips": ["short_breaks"],
        "opt_in": True,
    }
    base.update(overrides)
    return base


class TestJsonRecordRepository:
    def test_save_and_load_roundtrip(self, tmp_data_path):
        record = _valid_ai_record()
        result = data_manager.save_record(record, data_path=str(tmp_data_path), opt_in=True)
        assert result.get("ok") is True, result

        loaded = data_manager.load_all_records(data_path=str(tmp_data_path))
        assert loaded["ok"] is True
        assert len(loaded["records"]) >= 1
        assert any(r.get("student_id") == "test123" for r in loaded["records"])

    def test_missing_file_is_tolerated(self, tmp_data_path):
        loaded = data_manager.load_all_records(data_path=str(tmp_data_path))
        assert loaded["ok"] is True
        assert loaded["records"] == []

    def test_corrupt_json_is_handled(self, tmp_data_path):
        tmp_data_path.write_text("{ this is not valid json", encoding="utf-8")
        loaded = data_manager.load_all_records(data_path=str(tmp_data_path))
        assert loaded["ok"] is False or loaded["records"] == []
        assert loaded.get("error") is not None or loaded["records"] == []

    def test_save_requires_opt_in(self, tmp_data_path):
        record = _valid_ai_record()
        result = data_manager.save_record(record, data_path=str(tmp_data_path), opt_in=False)
        assert result.get("ok") is False
        assert "opt-in" in result.get("error", "").lower() or "opt_in" in result.get("error", "")


class TestRepositoryClass:
    def test_repository_load_empty(self, tmp_data_path):
        repo = data_manager.JsonRecordRepository(path=tmp_data_path)
        records = repo.load()
        assert records == []
