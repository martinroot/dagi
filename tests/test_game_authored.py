import copy

import pytest

from game.studio import browser_report, build, digest, review
from game.world import fresh_world


def component(code="return {commands:[{type:'text',x:5,y:20,text:'A tool I invented'}],state:{}};"):
    return {"operation": "component", "component": {"id": "novel-instrument", "title": "Invented instrument", "x": 350, "y": 65,
        "width": 300, "height": 180, "code": code, "events": [{"id": "refresh", "label": "Refresh"}]}}


def draft():
    world = fresh_world(1)
    build(world, {"operation": "begin", "objective": "Invent a new visual instrument"})
    build(world, {"operation": "edit", "changes": [component()]})
    return world


def execution(world, status="passed"):
    candidate = world["draft"]["candidate"]
    return {"version": 0, "view": "draft", "render_key": digest(candidate), "width": 1200, "height": 900, "overflow": False, "issues": [],
        "components": [{"id": "novel-instrument", "code_hash": candidate["components"][0]["code_hash"], "status": status,
                        "detail": "Compiled and executed" if status == "passed" else "SyntaxError: Unexpected token"}]}


def test_authored_code_requires_an_actual_current_browser_execution_report():
    world = draft()
    assert world["components"] == []
    build(world, {"operation": "test"})
    assert world["draft"]["report"]["checks"]["authored_components_executed"] is False
    with pytest.raises(ValueError, match="passing"):
        build(world, {"operation": "commit"})
    browser_report(world, execution(world))
    build(world, {"operation": "test"})
    assert world["draft"]["report"]["passed"] is True


def test_code_errors_are_observable_and_editing_source_invalidates_execution_evidence():
    world = draft()
    browser_report(world, execution(world, "error"))
    candidate = copy.deepcopy(world)
    candidate.update(world["draft"]["candidate"])
    assert review(candidate)["component_execution"][0]["status"] == "error"
    build(world, {"operation": "test"})
    assert world["draft"]["report"]["passed"] is False
    old = execution(world)
    build(world, {"operation": "edit", "changes": [component("return {commands:[],state:{fixed:true}};")]})
    with pytest.raises(ValueError, match="different scene"):
        browser_report(world, old)
    browser_report(world, execution(world))
    build(world, {"operation": "test"})
    assert world["draft"]["report"]["passed"] is True


def test_component_events_cannot_invent_unregistered_host_capabilities():
    world = draft()
    change = component()
    change["component"]["events"][0]["target"] = {"type": "javascript", "text": "fetch('/secrets')"}
    with pytest.raises(ValueError, match="target type"):
        build(world, {"operation": "edit", "changes": [change]})
