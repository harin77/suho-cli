"""Unit tests for TaskState."""

from __future__ import annotations

import pytest
from datetime import timezone, datetime
from suho_agent.agent.state import TaskState, TaskStatus, ToolCall, FileChange


class TestTaskState:
    def make_state(self) -> TaskState:
        return TaskState(
            user_request="Fix the build",
            working_directory="/tmp/project",
        )

    def test_initial_status(self):
        state = self.make_state()
        assert state.status == TaskStatus.PENDING
        assert state.iteration_count == 0
        assert state.tool_call_count == 0

    def test_add_observation_capped(self):
        state = self.make_state()
        for i in range(60):
            state.add_observation(f"obs {i}")
        assert len(state.observations) <= 50

    def test_is_at_limit_iterations(self):
        state = self.make_state()
        state.iteration_count = 30
        assert state.is_at_limit

    def test_is_at_limit_tool_calls(self):
        state = self.make_state()
        state.tool_call_count = 100
        assert state.is_at_limit

    def test_record_file_change_no_duplicate(self):
        state = self.make_state()
        state.record_file_change("main.py", "modified")
        state.record_file_change("main.py", "modified")
        assert len(state.files_changed) == 1

    def test_duration_ms_increases(self):
        state = self.make_state()
        d1 = state.duration_ms
        import time; time.sleep(0.01)
        d2 = state.duration_ms
        assert d2 >= d1

    def test_add_tool_call(self):
        state = self.make_state()
        state.add_tool_call(ToolCall(
            tool="filesystem.read_file",
            args={"path": "main.py"},
            result_success=True,
            result_summary="Read 100 lines",
            duration_ms=50,
        ))
        assert state.tool_call_count == 1
        assert len(state.tool_calls) == 1

    def test_to_summary_dict(self):
        state = self.make_state()
        summary = state.to_summary_dict()
        assert "task_id" in summary
        assert "status" in summary
        assert summary["iterations"] == 0


from suho_agent.agent.loop import _try_detect_fast_path


class TestFastPathDetection:
    def test_file_creation(self):
        res = _try_detect_fast_path("create hello.txt", "/tmp")
        assert res is not None
        assert res["tool"] == "filesystem.write_file"
        assert res["args"]["path"] == "hello.txt"

        res2 = _try_detect_fast_path("create styles.css inside test-app", "/tmp")
        assert res2 is not None
        assert res2["tool"] == "filesystem.write_file"
        assert res2["args"]["path"] == "test-app/styles.css"

    def test_directory_creation(self):
        res = _try_detect_fast_path("create a folder called test-folder", "/tmp")
        assert res is not None
        assert res["tool"] == "filesystem.create_directory"
        assert res["args"]["path"] == "test-folder"

        res2 = _try_detect_fast_path("mkdir assets", "/tmp")
        assert res2 is not None
        assert res2["tool"] == "filesystem.create_directory"

    def test_ambiguous_creation(self):
        res = _try_detect_fast_path("create test-folder", "/tmp")
        assert res is None
