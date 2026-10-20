"""The .docx engine: create, read, edit, verify Word documents."""
import io
import zipfile

import pytest

from dagi_core.docx import (
    DocumentError,
    create_document,
    read_document,
    replace_fields,
    verify_document,
)


def _contract_blocks():
    return [
        {"type": "title", "text": "Договор подряда"},
        {"type": "heading", "level": 1, "text": "1. Стороны"},
        {"type": "paragraph", "text": "Заказчик: {{customer}}, {{customer_details}}"},
        {"type": "paragraph", "text": "Подрядчик: {{contractor}}, {{contractor_details}}"},
        {"type": "heading", "level": 1, "text": "2. Работы"},
        {"type": "paragraph", "text": "{{works}}"},
        {"type": "paragraph", "text": "Объект: {{object}}"},
        {"type": "heading", "level": 1, "text": "3. Сроки, цена и приёмка"},
        {"type": "paragraph", "text": "Начало: {{start}} Дата: {{deadline}} Цена: {{price}}"},
        {"type": "paragraph", "text": "Оплата: {{payment}}"},
        {"type": "heading", "level": 1, "text": "4. Приёмка"},
        {"type": "paragraph", "text": "{{acceptance}}"},
        {"type": "heading", "level": 2, "text": "Этапы"},
        {"type": "number", "index": 1, "text": "{{stage_1}}"},
        {"type": "number", "index": 2, "text": "{{stage_2}}"},
        {"type": "heading", "level": 1, "text": "5. Особые условия"},
        {"type": "paragraph", "text": "{{special}}"},
        {"type": "table", "rows": [["Позиция", "Сумма"], ["Этап 1", "1000"], ["Итого", "1000"]]},
    ]


def test_a_created_document_reads_back_with_its_structure():
    data = create_document(_contract_blocks())
    content = read_document(data)
    assert content["paragraphs"][0]["text"] == "Договор подряда"
    assert content["paragraphs"][1]["style"] == "Heading1"
    assert content["tables"] and content["tables"][0]["rows"][0] == ["Позиция", "Сумма"]
    assert "Заказчик: {{customer}}" in content["text"]


def test_a_created_document_is_a_valid_word_package():
    data = create_document(_contract_blocks())
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        assert {"[Content_Types].xml", "_rels/.rels", "word/document.xml", "word/styles.xml"} <= names
        assert archive.read("[Content_Types].xml").startswith(b"<?xml")


def test_reading_a_file_that_is_not_a_word_document_fails_cleanly():
    with pytest.raises(DocumentError):
        read_document(b"not a zip file at all")
    with pytest.raises(DocumentError):
        read_document(b"")


def test_filling_fields_removes_the_placeholders_and_reports_the_rest():
    data = create_document(_contract_blocks())
    updated, report = replace_fields(data, {
        "customer": "ООО «Заказчик»",
        "contractor": "ИП «Подрядчик»",
        "works": "Разработка документации",
        "object": "Объект №1",
        "deadline": "2026-12-31",
        "price": "100 000 ₽",
        "payment": "50% аванс, 50% по факту",
        "acceptance": "Приёмка по акту",
        "stage_1": "Анализ",
        "stage_2": "Разработка",
        "customer_details": "ИНН 7700000000",
        "contractor_details": "ИНН 7700000001",
        "materials": "Заказчик",
        "start": "2026-10-20",
    })
    content = read_document(updated)
    assert "ООО «Заказчик»" in content["text"]
    assert "{{customer}}" not in content["text"]
    assert "{{special}}" in content["text"], "an unfilled field stays visible"
    assert "customer" in report["filled"]
    assert report["remaining"] == ["special"]


def test_filling_preserves_the_rest_of_the_document():
    data = create_document(_contract_blocks())
    updated, _ = replace_fields(data, {"customer": "ООО «Заказчик»"})
    content = read_document(updated)
    assert content["paragraphs"][0]["text"] == "Договор подряда"
    assert content["tables"][0]["rows"][1] == ["Этап 1", "1000"]
    assert "4. Приёмка" in content["text"]


def test_verification_finds_open_placeholders_and_missing_fields():
    data = create_document(_contract_blocks())
    verdict = verify_document(data, required=["customer", "works", "payment"])
    assert verdict["ok"] is False
    assert "customer" in verdict["missing"]
    assert verdict["placeholders"]

    filled, _ = replace_fields(data, {
        "customer": "ООО «Заказчик»", "contractor": "ИП", "works": "Работы", "object": "Объект",
        "materials": "Заказчик", "deadline": "2026-12-31", "price": "1000", "payment": "Аванс",
        "acceptance": "Акт", "stage_1": "Этап 1", "stage_2": "Этап 2", "special": "Нет",
        "start": "2026-10-20", "customer_details": "ИНН 1", "contractor_details": "ИНН 2",
    })
    verdict = verify_document(filled, required=["customer", "works", "payment"])
    assert verdict["ok"] is True
    assert verdict["missing"] == []
    assert verdict["paragraphs"] > 10


def test_unknown_block_types_and_oversized_documents_are_rejected():
    with pytest.raises(DocumentError):
        create_document([{"type": "unknown"}])
    with pytest.raises(DocumentError):
        create_document([])


def test_field_values_must_be_text():
    data = create_document(_contract_blocks())
    with pytest.raises(DocumentError):
        replace_fields(data, {"customer": 42})
    with pytest.raises(DocumentError):
        replace_fields(data, {"customer": "x" * 30_000})
