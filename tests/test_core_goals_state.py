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
        CREATE TABLE messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            tool_calls TEXT,
            tool_call_id TEXT,
            name TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE provider_calls(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            model TEXT NOT NULL,
            purpose TEXT NOT NULL,
            usage_source TEXT NOT NULL,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cost_usd TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT
        );
        CREATE TABLE skills(
            name TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            triggers TEXT NOT NULL DEFAULT '[]',
            body TEXT NOT NULL,
            use_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        INSERT INTO sessions(id, title, created_at) VALUES(41, 'preserve-me', '2026-01-01T00:00:00+00:00');
        INSERT INTO runs(run_id, session_id, status, started_at) VALUES('legacy-run', 41, 'completed', '2026-01-01T00:01:00+00:00');
        INSERT INTO messages(id, session_id, role, content, created_at)
            VALUES(51, 41, 'assistant', 'old transcript survives', '2026-01-01T00:02:00+00:00');
        INSERT INTO provider_calls(id, run_id, model, purpose, usage_source, input_tokens, output_tokens, cost_usd, started_at)
            VALUES(61, 'legacy-run', 'old-model', 'agent', 'actual', 12, 4, '0.12', '2026-01-01T00:03:00+00:00');
        INSERT INTO skills(name, description, triggers, body, use_count, created_at)
            VALUES('old-skill', 'preserve this skill', '[]', 'skill body survives', 2, '2026-01-01T00:04:00+00:00');
    """)
    db.commit()
    db.close()

    state = StateStore(path)
    session = state.get_session(41)
    run = state.get_run("legacy-run")
    assert session is not None and session["title"] == "preserve-me"
    assert run is not None and run["status"] == "completed"
    assert run is not None and run["budget_group_id"] == "legacy-run"
    assert state.messages(41)[0]["content"] == "old transcript survives"
    usage = state.usage_summary("legacy-run")
    assert usage["provider_calls"] == 1
    assert str(usage["cost_usd"]) == "0.12"
    legacy_skill = state.get_skill("old-skill")
    assert legacy_skill is not None and legacy_skill["body"] == "skill body survives"
    assert state.list_goals(41) == []
    state.close()
