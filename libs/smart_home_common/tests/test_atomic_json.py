"""
Tests for smart_home_common/persistence/atomic_json.py.

Covers:
- atomic_write_json: round-trip, directory creation, atomicity (no stray temps,
  previous file preserved on failure), encoding and formatting options.
- atomic_read_json: round-trip, missing-file default handling, invalid JSON.
"""

import json
from pathlib import Path

import pytest

from smart_home_common.persistence import atomic_read_json, atomic_write_json


class TestAtomicWriteJson:
    def test_round_trip(self, tmp_path: Path):
        target = tmp_path / "state.json"
        data = {"a": 1, "b": [1, 2, 3], "c": {"nested": True}}

        atomic_write_json(target, data)

        assert json.loads(target.read_text(encoding="utf-8")) == data

    def test_creates_parent_directories(self, tmp_path: Path):
        target = tmp_path / "deep" / "nested" / "state.json"

        atomic_write_json(target, {"ok": True})

        assert target.exists()
        assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}

    def test_overwrites_existing_file(self, tmp_path: Path):
        target = tmp_path / "state.json"
        atomic_write_json(target, {"version": 1})
        atomic_write_json(target, {"version": 2})

        assert json.loads(target.read_text(encoding="utf-8")) == {"version": 2}

    def test_no_stray_temp_files_on_success(self, tmp_path: Path):
        target = tmp_path / "state.json"
        atomic_write_json(target, {"ok": True})

        # Only the target file should remain; no leftover .tmp artifacts.
        assert [p.name for p in tmp_path.iterdir()] == ["state.json"]

    def test_non_ascii_preserved(self, tmp_path: Path):
        target = tmp_path / "state.json"
        data = {"ciudad": "A Coruña", "nota": "vacaciones de verano ☀"}

        atomic_write_json(target, data)

        # ensure_ascii defaults to False -> text written verbatim.
        raw = target.read_text(encoding="utf-8")
        assert "A Coruña" in raw
        assert json.loads(raw) == data

    def test_compact_output_when_indent_none(self, tmp_path: Path):
        target = tmp_path / "state.json"
        atomic_write_json(target, {"a": 1, "b": 2}, indent=None)

        assert target.read_text(encoding="utf-8") == '{"a": 1, "b": 2}'

    def test_sort_keys(self, tmp_path: Path):
        target = tmp_path / "state.json"
        atomic_write_json(target, {"b": 1, "a": 2}, indent=None, sort_keys=True)

        assert target.read_text(encoding="utf-8") == '{"a": 2, "b": 1}'

    def test_previous_file_preserved_on_serialization_error(self, tmp_path: Path):
        target = tmp_path / "state.json"
        atomic_write_json(target, {"version": 1})

        # A set is not JSON-serializable; the write must fail without clobbering
        # the previous good file or leaving a temp artifact behind.
        with pytest.raises(TypeError):
            atomic_write_json(target, {"bad": {1, 2, 3}})

        assert json.loads(target.read_text(encoding="utf-8")) == {"version": 1}
        assert [p.name for p in tmp_path.iterdir()] == ["state.json"]

    def test_accepts_str_path(self, tmp_path: Path):
        target = tmp_path / "state.json"
        atomic_write_json(str(target), {"ok": True})

        assert target.exists()


class TestAtomicReadJson:
    def test_round_trip(self, tmp_path: Path):
        target = tmp_path / "state.json"
        data = {"a": 1, "b": "two"}
        atomic_write_json(target, data)

        assert atomic_read_json(target) == data

    def test_missing_file_returns_none_by_default(self, tmp_path: Path):
        assert atomic_read_json(tmp_path / "nope.json") is None

    def test_missing_file_returns_custom_default(self, tmp_path: Path):
        assert atomic_read_json(tmp_path / "nope.json", default={"x": 1}) == {"x": 1}

    def test_invalid_json_raises(self, tmp_path: Path):
        target = tmp_path / "state.json"
        target.write_text("{ not valid json", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            atomic_read_json(target)

    def test_accepts_str_path(self, tmp_path: Path):
        target = tmp_path / "state.json"
        atomic_write_json(target, {"ok": True})

        assert atomic_read_json(str(target)) == {"ok": True}
