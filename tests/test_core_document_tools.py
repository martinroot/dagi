"""Document tools: template, create, read, edit, verify, latest."""
import json

import pytest

from dagi_core.state import StateStore
from dagi_core.tools import ToolRegistry

VALUES = {
    "customer": "ООО «Заказчик»",
    "contractor": "ИП «Подрядчик»",
    "works": "Разработка технической документации",
    "object": "Объект №1",
    "materials": "Заказчик",
    "deadline": "31.12.2026",
    "price": "100 000 ₽",
    "payment": "50% аванс, 50% по акту",
    "acceptance": "Приёмка по акту",
}


def _registry(tmp_path, documents=True):
    state = StateStore(tmp_path / "state.sqlite3")
    session_id = state.create_session("contract")
    registry = ToolRegistry(tmp_path / "work", state, session_id, documents_enabled=documents)
    return registry, state, session_id


def test_document_tools_are_absent_unless_enabled(tmp_path):
    registry, state, _ = _registry(tmp_path, documents=False)
    names = {tool.name for tool in registry.specs()}
    assert "document_create" not in names
    state.close()


def test_the_template_lists_the_required_and_optional_fields(tmp_path):
    registry, state, _ = _registry(tmp_path)
    result = registry.call("document_template", {})
    payload = json.loads(result.content)
    assert payload["kind"] == "work-contract"
    assert "customer" in payload["required"]
    assert "stages" in payload["optional"]
    assert result.presentation["type"] == "document_template"
    state.close()


def test_the_agent_creates_edits_and_verifies_a_contract(tmp_path):
    registry, state, _ = _registry(tmp_path)
    created = registry.call("document_create", {"values": VALUES, "filename": "contract.docx"})
    assert "contract.docx" in created.content
    artifact = created.presentation["artifacts"][0]
    assert artifact["kind"] == "docx" and artifact["operation"] == "create"
    saved = tmp_path / "work" / "contract.docx"
    assert saved.is_file() and saved.stat().st_size > 0

    edited = registry.call("document_edit", {
        "path": "contract.docx",
        "values": {
            "price": "120 000 ₽",
            "special": "Работы по заявке",
            "customer_details": "ИНН 7700000000",
            "contractor_details": "ИНН 7700000001",
            "start": "20.10.2026",
            "warranty": "12 месяцев",
            "stage_1": "Анализ и смета",
        },
    })
    assert "filled 7" in edited.content, "an edit changes a filled field and fills an open one"
    assert edited.presentation["diagnostics"]["remaining"] == []
    assert "120 000" in registry.call("document_read", {"path": "contract.docx"}).content

    verified = registry.call("document_verify", {"path": "contract.docx"})
    assert verified.presentation["diagnostics"]["ok"] is True
    assert verified.presentation["diagnostics"]["missing_fields"] == []

    latest = registry.call("document_latest", {})
    assert "contract.docx" in latest.content
    state.close()


def test_verification_refuses_a_half_filled_contract(tmp_path):
    registry, state, _ = _registry(tmp_path)
    registry.call("document_create", {"values": {"customer": "ООО «Заказчик»"}, "filename": "partial.docx"})
    verified = registry.call("document_verify", {"path": "partial.docx"})
    diagnostics = verified.presentation["diagnostics"]
    assert diagnostics["ok"] is False
    assert "works" in diagnostics["missing_fields"]
    assert diagnostics["placeholders"]
    state.close()


def test_editing_a_document_keeps_the_file_and_reports_open_fields(tmp_path):
    registry, state, _ = _registry(tmp_path)
    registry.call("document_create", {"values": VALUES, "filename": "contract.docx"})
    before = (tmp_path / "work" / "contract.docx").read_bytes()
    edited = registry.call("document_edit", {"path": "contract.docx", "values": {"price": "150 000 ₽"}})
    after = (tmp_path / "work" / "contract.docx").read_bytes()
    assert after != before
    assert "price" in edited.presentation["diagnostics"]["filled"], "a filled field can be changed again"
    assert "150 000" in registry.call("document_read", {"path": "contract.docx"}).content
    state.close()


def test_reading_a_missing_or_foreign_document_is_an_error(tmp_path):
    registry, state, _ = _registry(tmp_path)
    with pytest.raises(Exception):
        registry.call("document_read", {"path": "missing.docx"})
    (tmp_path / "work" / "notes.txt").write_text("plain text")
    with pytest.raises(Exception):
        registry.call("document_read", {"path": "notes.txt"})
    state.close()


def test_a_document_name_must_be_a_simple_docx_file(tmp_path):
    registry, state, _ = _registry(tmp_path)
    with pytest.raises(Exception):
        registry.call("document_create", {"values": VALUES, "filename": "../escape.docx"})
    with pytest.raises(Exception):
        registry.call("document_create", {"values": VALUES, "filename": "contract.txt"})
    state.close()
