"""Minimal, dependency-free Word (.docx) support for document agents.

A .docx file is a zip archive with WordprocessingML inside. This module writes
and edits that subset: titles, headings, paragraphs, bullet and numbered lists,
tables and page breaks. It keeps the existing formatting of a document when it
replaces a placeholder, and it never executes anything from the file.

Scope and limits, stated plainly:

- It reads and writes the paragraphs, tables and placeholders it needs. It
  does not render images, fields, footnotes, styles beyond the headings it
  writes, or tracked changes.
- Replacing a placeholder rewrites the affected paragraph into the formatting
  of its first run, so mixed formatting inside one replaced paragraph is lost.
  Everything outside the replaced paragraph is preserved byte for byte.
"""
from __future__ import annotations

import copy
import io
import re
import zipfile
from typing import Any
from xml.etree import ElementTree

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_PARAGRAPHS = 4000
PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([A-Za-z0-9_.]{1,64})\s*\}\}")
PLAIN_TEXT_PATTERN = re.compile(r"[^<>&\"']+")

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    "</Types>"
)
ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    "</Relationships>"
)
DOCUMENT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    "</Relationships>"
)
STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
    '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="40"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/></w:style>'
    "</w:styles>"
)


class DocumentError(ValueError):
    """The document cannot be read, written or edited."""


def _tag(name: str) -> str:
    return f"{{{WORD_NS}}}{name}"


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _run(text: str, *, bold: bool = False, size: int | None = None) -> str:
    properties = ""
    if bold or size:
        properties = "<w:rPr>" + ("<w:b/>" if bold else "") + (
            f'<w:sz w:val="{size}"/>' if size else ""
        ) + "</w:rPr>"
    return f'<w:r>{properties}<w:t xml:space="preserve">{_escape(text)}</w:t></w:r>'


def _paragraph_xml(text: str, style: str | None = None, *, bold: bool = False, indent: int = 0) -> str:
    properties = ""
    if style or indent:
        properties = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "") + (
            f'<w:ind w:left="{indent}"/>' if indent else ""
        ) + "</w:pPr>"
    return f"<w:p>{properties}{_run(text, bold=bold)}</w:p>"


def _table_xml(rows: list[list[str]], widths: list[int] | None = None) -> str:
    if not rows:
        return ""
    columns = max(len(row) for row in rows)
    if widths is None or len(widths) != columns:
        widths = [max(1, 9000 // columns)] * columns
    borders = "".join(
        f'<w:{edge} w:val="single" w:sz="4" w:space="0" w:color="999999"/>'
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV")
    )
    grid = "".join(f'<w:gridCol w:w="{width}"/>' for width in widths)
    body = []
    for index, row in enumerate(rows):
        cells = []
        for column in range(columns):
            value = row[column] if column < len(row) else ""
            cells.append(
                "<w:tc><w:tcPr><w:tcW w:w=\"%d\" w:type=\"dxa\"/></w:tcPr>%s</w:tc>"
                % (widths[column], _paragraph_xml(value, bold=index == 0))
            )
        body.append("<w:tr>" + "".join(cells) + "</w:tr>")
    return (
        "<w:tbl><w:tblPr><w:tblBorders>" + borders + "</w:tblBorders>"
        f'<w:tblW w:w="9000" w:type="dxa"/></w:tblPr><w:tblGrid>{grid}</w:tblGrid>'
        + "".join(body)
        + "</w:tbl>"
    )


def _field_xml(name: str, text: str) -> str:
    """Wrap a field value in a tagged content control.

    The tag is what makes a later edit possible: the field can be found by
    name even after it was filled, so a value can be changed, not only added.
    """
    return (
        "<w:sdt><w:sdtPr>"
        f'<w:alias w:val="{_escape(name)}"/><w:tag w:val="{_escape(name)}"/>'
        "</w:sdtPr><w:sdtContent>"
        + _run(text)
        + "</w:sdtContent></w:sdt>"
    )


def build_document_xml(blocks: list[dict[str, Any]]) -> str:
    """Build the document body from a list of block dictionaries."""
    body = []
    for block in blocks:
        if not isinstance(block, dict):
            raise DocumentError("a document block must be an object")
        kind = block.get("type", "paragraph")
        text = str(block.get("text", ""))
        if kind == "title":
            body.append(_paragraph_xml(text, "Title"))
        elif kind == "heading":
            level = int(block.get("level", 1))
            body.append(_paragraph_xml(text, f"Heading{min(max(level, 1), 2)}"))
        elif kind == "paragraph":
            body.append(_paragraph_xml(text, block.get("style")))
        elif kind == "bullet":
            body.append(_paragraph_xml(f"• {text}", "ListParagraph", indent=360))
        elif kind == "number":
            body.append(_paragraph_xml(f"{block.get('index', 1)}. {text}", "ListParagraph", indent=360))
        elif kind == "field":
            name = str(block.get("name", "")).strip()
            if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", name):
                raise DocumentError("a field needs a simple name")
            body.append(
                '<w:p><w:pPr><w:ind w:left="0"/></w:pPr>'
                + _field_xml(name, text)
                + "</w:p>"
            )
        elif kind == "bold":
            body.append(_paragraph_xml(text, bold=True))
        elif kind == "spacer":
            body.append("<w:p/>")
        elif kind == "pagebreak":
            body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        elif kind == "table":
            rows = block.get("rows") or []
            body.append(_table_xml(rows, block.get("widths")))
        else:
            raise DocumentError(f"unknown document block type: {kind!r}")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{WORD_NS}" xmlns:r="{REL_NS}"><w:body>'
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="850" w:bottom="1134" w:left="1701" w:header="708" w:footer="708" w:gutter="0"/>'
        "</w:sectPr></w:body></w:document>"
    )


def create_document(blocks: list[dict[str, Any]]) -> bytes:
    """Create a .docx file from block dictionaries."""
    if not isinstance(blocks, list) or not blocks:
        raise DocumentError("a document needs at least one block")
    if len(blocks) > MAX_PARAGRAPHS:
        raise DocumentError("a document is limited to a bounded number of blocks")
    document = build_document_xml(blocks)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", ROOT_RELS)
        archive.writestr("word/_rels/document.xml.rels", DOCUMENT_RELS)
        archive.writestr("word/styles.xml", STYLES)
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def _read_parts(data: bytes) -> tuple[ElementTree.Element, dict[str, bytes]]:
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise DocumentError("document is empty")
    if len(data) > MAX_DOCUMENT_BYTES:
        raise DocumentError("document is too large")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            if "word/document.xml" not in names:
                raise DocumentError("not a Word document: word/document.xml is missing")
            parts = {name: archive.read(name) for name in names if name.endswith(".xml")}
            document = ElementTree.fromstring(archive.read("word/document.xml"))
    except zipfile.BadZipFile as exc:
        raise DocumentError("not a Word document: the file is not a valid archive") from exc
    except ElementTree.ParseError as exc:
        raise DocumentError("the document body cannot be parsed") from exc
    return document, parts


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    return "".join(
        node.text or "" for node in paragraph.iter(_tag("t"))
    )


def _paragraph_style(paragraph: ElementTree.Element) -> str | None:
    properties = paragraph.find(_tag("pPr"))
    if properties is None:
        return None
    style = properties.find(_tag("pStyle"))
    if style is None:
        return None
    return style.get(_tag("val"))


def read_document(data: bytes) -> dict[str, Any]:
    """Read paragraphs, tables and placeholders from a .docx file."""
    document, _ = _read_parts(data)
    body = document.find(_tag("body"))
    paragraphs: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    text_parts: list[str] = []
    for child in list(body) if body is not None else []:
        if child.tag == _tag("p"):
            text = _paragraph_text(child)
            paragraphs.append({"index": len(paragraphs), "style": _paragraph_style(child), "text": text})
            text_parts.append(text)
        elif child.tag == _tag("tbl"):
            rows = []
            for row in child.findall(_tag("tr")):
                cells = []
                for cell in row.findall(_tag("tc")):
                    cells.append("".join(_paragraph_text(p) for p in cell.findall(_tag("p"))))
                rows.append(cells)
            tables.append({"index": len(tables), "rows": rows})
            text_parts.extend(" | ".join(row) for row in rows)
    if len(paragraphs) > MAX_PARAGRAPHS:
        raise DocumentError("document has too many paragraphs")
    placeholders = sorted({
        match.group(1)
        for text in text_parts
        for match in PLACEHOLDER_PATTERN.finditer(text)
    })
    fields: dict[str, str] = {}
    for control in document.iter(_tag("sdt")):
        properties = control.find(_tag("sdtPr"))
        if properties is None:
            continue
        tag = properties.find(_tag("tag"))
        if tag is None:
            continue
        name = tag.get(_tag("val"))
        if not name:
            continue
        content = control.find(_tag("sdtContent"))
        value = "" if content is None else "".join(
            node.text or "" for node in content.iter(_tag("t"))
        )
        fields[name] = value
    return {
        "paragraphs": paragraphs,
        "tables": tables,
        "text": "\n".join(text_parts),
        "placeholders": placeholders,
        "fields": fields,
    }


def replace_fields(data: bytes, values: dict[str, str]) -> tuple[bytes, dict[str, Any]]:
    """Replace {{placeholders}} in a document and return the new file.

    The replaced paragraph keeps the formatting of its first run; the rest of
    the document is preserved. The report names every placeholder that was
    filled and every placeholder that is still open.
    """
    if not isinstance(values, dict):
        raise DocumentError("field values must be an object")
    for key, value in values.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise DocumentError("field names and values must be text")
        if len(value) > 20_000:
            raise DocumentError(f"field {key!r} is too long")
    document, parts = _read_parts(data)
    body = document.find(_tag("body"))
    if body is None:
        raise DocumentError("document body is missing")
    filled: list[str] = []
    for control in document.iter(_tag("sdt")):
        properties = control.find(_tag("sdtPr"))
        content = control.find(_tag("sdtContent"))
        if properties is None or content is None:
            continue
        tag = properties.find(_tag("tag"))
        if tag is None:
            continue
        name = tag.get(_tag("val"))
        if not name or name not in values:
            continue
        value = values[name]
        runs = list(content.iter(_tag("r")))
        if not runs:
            continue
        first = runs[0]
        for node in list(first):
            if node.tag == _tag("t"):
                first.remove(node)
        text_node = ElementTree.Element(_tag("t"))
        text_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        text_node.text = value
        first.append(text_node)
        for run in runs[1:]:
            for node in list(run):
                if node.tag == _tag("t"):
                    run.remove(node)
        filled.append(name)
    for paragraph in body.iter(_tag("p")):
        text = _paragraph_text(paragraph)
        matches = PLACEHOLDER_PATTERN.findall(text)
        if not matches:
            continue
        updated = text
        for name in matches:
            if name in values and name not in filled:
                updated = updated.replace("{{" + name + "}}", values[name])
                updated = re.sub(r"\{\{\s*" + re.escape(name) + r"\s*\}\}", values[name], updated)
                filled.append(name)
        if updated == text:
            continue
        runs = list(paragraph.iter(_tag("r")))
        if not runs:
            continue
        first = runs[0]
        for node in list(first):
            if node.tag == _tag("t"):
                first.remove(node)
        text_node = ElementTree.Element(_tag("t"))
        text_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        text_node.text = updated
        first.append(text_node)
        for run in runs[1:]:
            for node in list(run):
                if node.tag == _tag("t"):
                    run.remove(node)
    remaining = read_document(ElementTree.tostring(document, encoding="utf-8") and _repack(document, parts))["placeholders"]
    report = {
        "filled": sorted(set(filled)),
        "remaining": remaining,
        "open_fields": sorted(set(remaining)),
    }
    return _repack(document, parts), report


def _repack(document: ElementTree.Element, parts: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    body = ElementTree.tostring(document, encoding="utf-8", xml_declaration=True)
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            if name == "word/document.xml":
                continue
            archive.writestr(name, content)
        archive.writestr("word/document.xml", body)
    return buffer.getvalue()


def verify_document(data: bytes, required: list[str] | None = None) -> dict[str, Any]:
    """Check a document for completeness: no open placeholders, required fields present."""
    content = read_document(data)
    placeholders = content["placeholders"]
    text = content["text"]
    missing = []
    for name in required or []:
        if not str(name).strip():
            continue
        if f"{{{{{name}}}}}" in text:
            missing.append(name)
    problems = []
    if placeholders:
        problems.append("unfilled placeholders: " + ", ".join(placeholders))
    if missing:
        problems.append("missing required fields: " + ", ".join(missing))
    if not text.strip():
        problems.append("the document is empty")
    return {
        "ok": not problems,
        "paragraphs": len(content["paragraphs"]),
        "tables": len(content["tables"]),
        "characters": len(text),
        "placeholders": placeholders,
        "missing": missing,
        "problems": problems,
    }
