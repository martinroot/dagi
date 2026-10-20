"""Publish a produced file as a deliverable of the session.

The Fabra agents call ``artifact.publish`` when the result is a file rather
than a text answer. The Dagi core had no counterpart, so every agent that
produces a document had a tool gap and could not be shipped to the site.

The core tool copies the file into the published folder of the workspace and
reports it as an artifact, so the caller can name it in the final answer.
"""

from __future__ import annotations

from pathlib import Path

from dagi_core.state import StateStore
from dagi_core.tools import ToolError, ToolRegistry


def make_tools(tmp_path: Path):
    state = StateStore(tmp_path / 'state.sqlite3')
    session = state.create_session()
    workspace = tmp_path / 'workspace'
    workspace.mkdir(parents=True, exist_ok=True)
    return state, ToolRegistry(workspace, state, session)


def _write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def test_publish_copies_the_file_into_the_published_folder(tmp_path):
    state, tools = make_tools(tmp_path)
    _write_file(tools.workspace / 'contract.docx', 'body')

    tools.call('artifact_publish', {'path': 'contract.docx'})

    published = tools.workspace / 'published' / 'contract.docx'
    assert published.is_file()
    assert published.read_text(encoding='utf-8') == 'body'


def test_publish_reports_the_artifact(tmp_path):
    state, tools = make_tools(tmp_path)
    _write_file(tools.workspace / 'contract.docx', 'body')

    result = tools.call('artifact_publish', {'path': 'contract.docx'})

    presentation = result.presentation or {}
    artifacts = presentation.get('artifacts') or []
    assert artifacts
    assert artifacts[0]['path'].endswith('contract.docx')
    assert artifacts[0]['kind'] == 'docx'


def test_publish_accepts_a_custom_file_name(tmp_path):
    state, tools = make_tools(tmp_path)
    _write_file(tools.workspace / 'contract.docx', 'body')

    tools.call('artifact_publish', {'path': 'contract.docx', 'filename': 'Договор.docx'})

    assert (tools.workspace / 'published' / 'Договор.docx').is_file()


def test_publish_refuses_a_missing_file(tmp_path):
    state, tools = make_tools(tmp_path)

    try:
        tools.call('artifact_publish', {'path': 'nothing.docx'})
    except ToolError as error:
        assert 'nothing.docx' in str(error)
    else:  # pragma: no cover - the call must fail
        raise AssertionError('publishing a missing file must fail')


def test_publish_refuses_a_path_outside_the_workspace(tmp_path):
    state, tools = make_tools(tmp_path)
    outside = tmp_path / 'outside.txt'
    outside.write_text('secret', encoding='utf-8')

    try:
        tools.call('artifact_publish', {'path': '../outside.txt'})
    except ToolError:
        pass
    else:  # pragma: no cover - the call must fail
        raise AssertionError('publishing outside the workspace must fail')


def test_publish_does_not_touch_the_source_file(tmp_path):
    state, tools = make_tools(tmp_path)
    _write_file(tools.workspace / 'contract.docx', 'body')

    tools.call('artifact_publish', {'path': 'contract.docx'})

    assert (tools.workspace / 'contract.docx').read_text(encoding='utf-8') == 'body'
