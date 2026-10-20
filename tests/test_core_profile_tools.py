"""A run exposes only the tools of the session profile.

The profile tool list is the Fabra ``tools.allow`` list translated into Dagi
tool names. The model must not see the whole registry: an agent that may only
list files must not be offered the document tools, and an unknown name in the
profile must not leave the model with no tools at all.
"""

import pytest

from dagi_core.state import StateStore
from dagi_core.tools import ToolRegistry


@pytest.fixture()
def registry(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    try:
        session_id = state.create_session("scoped")
        tools = ToolRegistry(tmp_path / "workspace", state, session_id)
        yield state, session_id, tools
    finally:
        state.close()


def test_profile_limits_the_tools_the_model_sees(registry):
    _, _, tools = registry
    tools.restrict_to(["list_dir"])
    assert {tool.name for tool in tools.specs()} == {"list_dir"}


def test_unknown_profile_tool_falls_back_to_the_full_registry(registry):
    _, _, tools = registry
    known = {tool.name for tool in tools.specs()}
    tools.restrict_to(["tool_that_does_not_exist"])
    assert tools.model_tool_names is None
    assert {tool.name for tool in tools.specs()} == known


def test_empty_profile_leaves_every_tool_visible(registry):
    _, _, tools = registry
    assert tools.model_tool_names is None
    assert len(tools.specs()) > 1


def test_profile_tools_are_the_only_ones_offered_to_the_model(registry):
    _, _, tools = registry
    tools.restrict_to(["list_dir"])
    visible = {tool.name for tool in tools.specs()}
    assert "write_file" not in visible
    # The tool itself still exists in the registry: the profile narrows what
    # the model is offered, not the capability of the runtime.
    assert "write_file" in tools._tools


def test_restriction_can_be_cleared(registry):
    _, _, tools = registry
    tools.restrict_to(["list_dir"])
    tools.restrict_to(None)
    assert tools.model_tool_names is None
    assert len(tools.specs()) > 1
