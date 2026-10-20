"""Document-agent tools: template, create, read, edit, verify, latest.

These tools implement the document side of a contract agent: a template with
explicit fields, a real .docx file, edits that are saved back, a verification
pass that refuses to call a half-filled document ready, and a way to find the
document that was produced last.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .docx import (
    DocumentError,
    PLACEHOLDER_PATTERN,
    create_document,
    read_document,
    replace_fields,
    verify_document,
)

MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_FIELDS = 60
MAX_FIELD_LENGTH = 20_000

CONTRACT_TEMPLATE = {
    "kind": "work-contract",
    "title": "Договор подряда",
    "lead": "Опишите конкретный результат работ, этапы и деньги — мастер соберёт договор и приложения.",
    "sections": ["Стороны", "Работы", "Сроки и деньги", "Приёмка", "Особые условия"],
    "required": [
        "customer", "contractor", "works", "object", "materials",
        "deadline", "price", "payment", "acceptance",
    ],
    "optional": [
        "customer_details", "contractor_details", "start", "stages", "warranty", "special",
    ],
    "fields": {
        "customer": {"label": "Заказчик", "section": "Стороны"},
        "contractor": {"label": "Подрядчик", "section": "Стороны"},
        "customer_details": {"label": "Реквизиты заказчика", "section": "Стороны"},
        "contractor_details": {"label": "Реквизиты подрядчика", "section": "Стороны"},
        "works": {"label": "Перечень и результат работ", "section": "Работы"},
        "object": {"label": "Объект или место работ", "section": "Работы"},
        "materials": {"label": "Кто предоставляет материалы", "section": "Работы"},
        "start": {"label": "Начало работ", "section": "Сроки и деньги"},
        "deadline": {"label": "Окончание работ", "section": "Сроки и деньги"},
        "stages": {"label": "Этапы", "section": "Сроки и деньги"},
        "price": {"label": "Цена или смета", "section": "Сроки и деньги"},
        "payment": {"label": "Порядок оплаты", "section": "Сроки и деньги"},
        "acceptance": {"label": "Порядок сдачи и приёмки", "section": "Приёмка"},
        "warranty": {"label": "Гарантия", "section": "Приёмка"},
        "special": {"label": "Особые условия", "section": "Особые условия"},
    },
    "clarification": {"policy": "only_when_blocked", "max_questions": 1},
    "delivery": "The finished .docx is attached to the chat for the customer.",
}

PROOFREAD_PATTERNS = (
    (re.compile(r"\bTODO\b|\bTBD\b|\bXXX\b", re.I), "unresolved marker"),
    (re.compile(r"_{3,}"), "blank line to fill"),
    (re.compile(r"\[\s*\]|\(\s*\)"), "empty bracket"),
    (re.compile(r"\s{3,}"), "long run of spaces"),
)


def template_blocks(values: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Build the contract document blocks; missing fields stay as placeholders."""
    values = values or {}

    def field(name: str) -> str:
        # Every field is written as a tagged content control. The tag is what
        # lets a later edit find the field again, filled or not; the
        # placeholder is only the visible hint of an unfilled value.
        value = str(values.get(name, "")).strip()
        return value if value else "{{" + name + "}}"
    stages = str(values.get("stages", "")).strip()
    stage_items = [line.strip() for line in stages.splitlines() if line.strip()]
    if not stage_items:
        stage_items = ["{{stage_1}}"]
    blocks: list[dict[str, Any]] = [
        {"type": "title", "text": CONTRACT_TEMPLATE["title"]},
        {"type": "heading", "level": 1, "text": "1. Стороны"},
        {"type": "paragraph", "text": "Заказчик: "},
        {"type": "field", "name": "customer", "text": field("customer")},
        {"type": "paragraph", "text": "Реквизиты заказчика: "},
        {"type": "field", "name": "customer_details", "text": field("customer_details")},
        {"type": "paragraph", "text": "Подрядчик: "},
        {"type": "field", "name": "contractor", "text": field("contractor")},
        {"type": "paragraph", "text": "Реквизиты подрядчика: "},
        {"type": "field", "name": "contractor_details", "text": field("contractor_details")},
        {"type": "heading", "level": 1, "text": "2. Работы"},
        {"type": "field", "name": "works", "text": field("works")},
        {"type": "paragraph", "text": "Объект или место выполнения работ: "},
        {"type": "field", "name": "object", "text": field("object")},
        {"type": "paragraph", "text": "Материалы предоставляет: "},
        {"type": "field", "name": "materials", "text": field("materials")},
        {"type": "heading", "level": 1, "text": "3. Сроки, цена и порядок расчётов"},
        {"type": "paragraph", "text": "Начало работ: "},
        {"type": "field", "name": "start", "text": field("start")},
        {"type": "paragraph", "text": "Окончание работ: "},
        {"type": "field", "name": "deadline", "text": field("deadline")},
        {"type": "paragraph", "text": "Цена работ: "},
        {"type": "field", "name": "price", "text": field("price")},
        {"type": "paragraph", "text": "Порядок оплаты: "},
        {"type": "field", "name": "payment", "text": field("payment")},
    ]
    blocks.append({"type": "heading", "level": 2, "text": "Этапы работ"})
    for index, stage in enumerate(stage_items, start=1):
        blocks.append({"type": "number", "index": index, "text": f"Этап {index}"})
        blocks.append({"type": "field", "name": f"stage_{index}", "text": stage})
    blocks += [
        {"type": "heading", "level": 1, "text": "4. Сдача и приёмка"},
        {"type": "field", "name": "acceptance", "text": field("acceptance")},
        {"type": "paragraph", "text": "Гарантия: "},
        {"type": "field", "name": "warranty", "text": field("warranty")},
        {"type": "heading", "level": 1, "text": "5. Особые условия"},
        {"type": "field", "name": "special", "text": field("special")},
        {"type": "heading", "level": 1, "text": "6. Подписи сторон"},
        {"type": "table", "rows": [
            ["Сторона", "Должность", "ФИО", "Подпись"],
            ["Заказчик", "", str(values.get("customer", "")).strip() or "—", ""],
            ["Подрядчик", "", str(values.get("contractor", "")).strip() or "—", ""],
        ]},
    ]
    return blocks


def normalize_values(values: Any) -> dict[str, str]:
    if not isinstance(values, dict):
        raise DocumentError("field values must be an object")
    if len(values) > MAX_FIELDS:
        raise DocumentError("too many fields")
    normalized: dict[str, str] = {}
    for key, value in values.items():
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,64}", key):
            raise DocumentError(f"invalid field name: {key!r}")
        if not isinstance(value, str):
            raise DocumentError(f"field {key!r} must be text")
        if len(value) > MAX_FIELD_LENGTH:
            raise DocumentError(f"field {key!r} is too long")
        normalized[key] = value.strip()
    return normalized


def create_contract(values: dict[str, str]) -> bytes:
    return create_document(template_blocks(values))


def proofread(text: str) -> list[str]:
    """Report the markers that a finished document must not contain."""
    findings = []
    for pattern, label in PROOFREAD_PATTERNS:
        for match in pattern.finditer(text):
            findings.append(f"{label}: {match.group(0).strip()[:60]}")
    return findings


def verify_contract(data: bytes, values: dict[str, str] | None = None) -> dict[str, Any]:
    """Verify a contract document: completeness, then proofreading.

    The verdict is taken from the document itself: a required field counts as
    missing when its tagged value is empty or still a placeholder.
    """
    required = list(CONTRACT_TEMPLATE["required"])
    verdict = verify_document(data, required=required)
    content = read_document(data)
    findings = proofread(content["text"])
    fields = content.get("fields") or {}
    missing = []
    for name in required:
        value = str(fields.get(name, (values or {}).get(name, ""))).strip()
        if not value or PLACEHOLDER_PATTERN.fullmatch(value):
            missing.append(name)
    optional_open = [
        name for name in verdict["placeholders"]
        if name not in required and not name.startswith("stage_")
    ]
    problems = list(verdict["problems"])
    if missing:
        problems.append("required fields are empty: " + ", ".join(missing))
    if optional_open:
        problems.append(
            "optional fields are still open (fill them or write \"—\"): " + ", ".join(optional_open)
        )
    if findings:
        problems.extend(findings)
    return {
        "ok": not problems,
        "paragraphs": verdict["paragraphs"],
        "tables": verdict["tables"],
        "characters": verdict["characters"],
        "placeholders": verdict["placeholders"],
        "missing_fields": missing,
        "optional_open": optional_open,
        "proofread": findings,
        "problems": problems,
    }


def read_contract(data: bytes) -> dict[str, Any]:
    content = read_document(data)
    return {
        "paragraphs": content["paragraphs"],
        "tables": content["tables"],
        "text": content["text"],
        "placeholders": content["placeholders"],
    }


def edit_contract(data: bytes, values: dict[str, str]) -> tuple[bytes, dict[str, Any]]:
    updated, report = replace_fields(data, values)
    return updated, report


def latest_document(workspace: Path) -> Path | None:
    candidates = [
        path for path in Path(workspace).glob("**/*.docx")
        if path.is_file() and not path.name.startswith("~$")
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)
