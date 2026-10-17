import sqlite3

from dagi_core.state import StateStore


def test_goal_lifecycle_persists_checks_feedback_and_budget_group(tmp_path):
    path = tmp_path / "state.sqlite3"
    state = StateStore(path)
    session_id = state.create_session("goal session")
    checks = [{"type": "file_exists", "path": "result.txt"}]
    goal_id = state.create_goal(session_id, "write a result", checks, max_iterations=2)
    run_id = state.create_run(session_id, budget_group_id=goal_id)
    state.link_goal_run(goal_id, run_id)
    call_id = state.create_provider_call(run_id, "test-model", "agent")
    state.record_usage(call_id, {
        "source": "actual", "input_tokens": 10, "output_tokens": 5, "cost_usd": "0.01",
    })
    second_run = state.create_run(session_id, budget_group_id=goal_id, agent_name="test-model")
    state.link_goal_run(goal_id, second_run)
    compression_id = state.create_provider_call(second_run, "test-model", "context_compression")
    state.record_usage(compression_id, {
        "source": "actual", "input_tokens": 4, "output_tokens": 2, "cost_usd": "0.02",
    })
    state.update_goal(goal_id, "running", iteration=1, feedback=[{"passed": False}])
    state.close()

    reopened = StateStore(path)
    goal = reopened.get_goal(goal_id)
    assert goal["objective"] == "write a result"
    assert goal["checks"] == checks
    assert goal["status"] == "running"
    assert goal["iteration"] == 1
    assert goal["feedback"] == [{"passed": False}]
    assert goal["runs"] == [run_id, second_run]
    first_run = reopened.get_run(run_id)
    assert first_run is not None and first_run["budget_group_id"] == goal_id
    budget = reopened.usage_summary_for_budget(second_run)
    assert budget["provider_calls"] == 2
    assert str(budget["cost_usd"]) == "0.03"
    reopened.update_goal(goal_id, "completed", iteration=1, feedback=[{"passed": True}])
    assert reopened.get_goal(goal_id)["status"] == "completed"
    reopened.close()


def test_startup_recovery_marks_running_goals_interrupted(tmp_path):
    path = tmp_path / "state.sqlite3"
    state = StateStore(path)
    session_id = state.create_session("recovery")
    goal_id = state.create_goal(session_id, "finish safely", [{"type": "file_exists", "path": "x"}], 3)
    state.close()

    reopened = StateStore(path)
    reopened.recover_goals()
    goal = reopened.get_goal(goal_id)
    assert goal["status"] == "interrupted"
    assert goal["iteration"] == 0
    reopened.close()


def test_goal_schema_upgrade_preserves_existing_sessions_and_runs(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    db = sqlite3.connect(path)
    db.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE sessions(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, created_at TEXT NOT NULL);
        CREATE TABLE runs(
            run_id TEXT PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            error TEXT
        );
        INSERT INTO sessions(id, title, created_at) VALUES(41, 'preserve-me', '2026-01-01T00:00:00+00:00');
        INSERT INTO runs(run_id, session_id, status, started_at) VALUES('legacy-run', 41, 'completed', '2026-01-01T00:01:00+00:00');
    """)
    db.commit()
    db.close()

    state = StateStore(path)
    session = state.get_session(41)
    run = state.get_run("legacy-run")
    assert session["title"] == "preserve-me"
    assert run["status"] == "completed"
    assert run["budget_group_id"] == "legacy-run"
    assert state.list_goals(41) == []
    state.close()
