import json
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


def test_goal_reflection_is_idempotent_and_records_the_following_check(tmp_path):
    path = tmp_path / "state.sqlite3"
    state = StateStore(path)
    session_id = state.create_session("reflection")
    goal_id = state.create_goal(
        session_id, "create valid JSON", [{"type": "json_valid", "path": "result.json"}], 2
    )
    observation = {"passed": False, "detail": "file is absent"}
    kwargs = {
        "goal_id": goal_id,
        "iteration": 0,
        "check_index": 0,
        "expected": {"type": "json_valid", "path": "result.json"},
        "observed": observation,
        "evidence_ids": ["goal-check:goal-1:0:0"],
        "failure_fingerprint": "f" * 64,
        "action_fingerprint": "a" * 64,
    }

    first = state.record_goal_reflection(**kwargs)
    replay = state.record_goal_reflection(**kwargs)
    assert replay["id"] == first["id"]
    assert state.update_goal_reflection_followup(goal_id, 0, True) is True
    state.close()

    reopened = StateStore(path)
    reflections = reopened.list_goal_reflections(goal_id)
    assert len(reflections) == 1
    assert reflections[0]["observed"] == observation
    assert reflections[0]["cause_hypothesis"] is None
    assert reflections[0]["next_change"] is None
    assert reflections[0]["following_check_passed"] is True
    reopened.close()


def test_goal_reflection_schema_upgrade_preserves_existing_record(tmp_path):
    path = tmp_path / "state.sqlite3"
    state = StateStore(path)
    session_id = state.create_session("legacy-reflection")
    goal_id = state.create_goal(
        session_id, "create valid JSON", [{"type": "json_valid", "path": "result.json"}], 2
    )
    state.close()

    db = sqlite3.connect(path)
    db.execute("DROP INDEX IF EXISTS goal_reflections_goal_iteration")
    db.execute("DROP TABLE goal_reflections")
    db.executescript("""
        CREATE TABLE goal_reflections (
            reflection_id TEXT PRIMARY KEY,
            goal_id TEXT NOT NULL REFERENCES goals(goal_id) ON DELETE CASCADE,
            iteration INTEGER NOT NULL,
            check_index INTEGER NOT NULL,
            trigger TEXT NOT NULL,
            expected_json TEXT NOT NULL,
            observed_json TEXT NOT NULL,
            evidence_ids_json TEXT NOT NULL,
            cause_hypothesis TEXT,
            next_change TEXT,
            following_check_passed INTEGER,
            created_at TEXT NOT NULL,
            UNIQUE(goal_id, iteration, check_index)
        );
    """)
    db.execute(
        """INSERT INTO goal_reflections(
               reflection_id, goal_id, iteration, check_index, trigger, expected_json,
               observed_json, evidence_ids_json, created_at
           ) VALUES(?, ?, 0, 0, 'acceptance_check_failed', ?, ?, ?, '2026-01-01T00:00:00+00:00')""",
        (
            "legacy-reflection-id", goal_id,
            json.dumps({"type": "json_valid", "path": "result.json"}),
            json.dumps({"passed": False, "detail": "file is absent"}),
            json.dumps(["goal-check:legacy:0:0"]),
        ),
    )
    db.commit()
    db.close()

    upgraded = StateStore(path)
    reflection = upgraded.list_goal_reflections(goal_id)[0]
    assert reflection["id"] == "legacy-reflection-id"
    assert reflection["observed"]["detail"] == "file is absent"
    assert reflection["failure_fingerprint"] == ""
    assert reflection["action_fingerprint"] == ""
    assert reflection["repeat_count"] == 0
    upgraded.close()


def test_lessons_are_idempotent_scoped_and_promoted_by_independent_goal_support(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    session_a = state.create_session("project-a")
    session_b = state.create_session("project-b")
    check = {"type": "json_valid", "path": "result.json"}
    fingerprint = "a" * 64

    def support(session_id, evidence_key):
        goal_id = state.create_goal(session_id, "create valid JSON", [check], 2)
        reflection = state.record_goal_reflection(
            goal_id=goal_id,
            iteration=0,
            check_index=0,
            expected=check,
            observed={"passed": False, "detail": "invalid JSON"},
            evidence_ids=[f"goal-check:{evidence_key}"],
            failure_fingerprint="f" * 64,
            action_fingerprint="b" * 64,
        )
        state.update_goal_reflection_followup(
            goal_id,
            0,
            True,
            next_change="Observed tool calls: write_file",
            evidence_ids=[f"run:{evidence_key}", f"tool:{evidence_key}"],
        )
        reflection = state.get_latest_goal_reflection(goal_id, 0)
        return state.record_goal_lesson(
            session_id=session_id,
            goal_id=goal_id,
            reflection_id=reflection["id"],
            check_type="json_valid",
            check_key="result.json",
            pattern_fingerprint=fingerprint,
            lesson="Observed valid JSON after a changed write action.",
            evidence_ids=reflection["evidence_ids"],
        ), goal_id, reflection["id"]

    first, first_goal, first_reflection = support(session_a, "a1")
    replay = state.record_goal_lesson(
        session_id=session_a,
        goal_id=first_goal,
        reflection_id=first_reflection,
        check_type="json_valid",
        check_key="result.json",
        pattern_fingerprint=fingerprint,
        lesson="Observed valid JSON after a changed write action.",
        evidence_ids=first["evidence_ids"],
    )
    assert first["status"] == "candidate" and first["support_count"] == 1
    assert replay["support_count"] == 1

    second, _second_goal, _second_reflection = support(session_a, "a2")
    assert second["lesson_id"] == first["lesson_id"]
    assert second["status"] == "verified" and second["support_count"] == 2
    assert "tool:a2" in second["evidence_ids"]

    isolated, _isolated_goal, _isolated_reflection = support(session_b, "b1")
    assert isolated["lesson_id"] != first["lesson_id"]
    assert state.list_goal_lessons(
        session_a, check_type="json_valid", check_key="result.json", limit=10
    ) == [second]
    assert state.list_goal_lessons(
        session_a, check_type="json_valid", check_key="other.json"
    ) == []
    assert state.list_goal_lessons(
        session_b, check_type="json_valid", check_key="result.json"
    ) == [isolated]
    state.close()


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
