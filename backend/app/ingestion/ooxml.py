"""Small read-only OOXML reader for tabular `.xlsx` source sheets.

The importer deliberately reads cell text from the XML package so identifiers are
never routed through a numeric dataframe representation.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from xml.etree import ElementTree as ET

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CELL_REF = re.compile(r"^([A-Z]+)([0-9]+)$")


class WorkbookFormatError(ValueError):
    """Raised when a workbook is missing required OOXML structures."""


def _column_index(cell_reference: str) -> int:
    match = CELL_REF.fullmatch(cell_reference)
    if match is None:
        raise WorkbookFormatError(f"Invalid cell reference: {cell_reference!r}")
    value = 0
    for char in match.group(1):
        value = value * 26 + ord(char) - ord("A") + 1
    return value - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return [
        "".join(node.text or "" for node in item.findall(f".//{{{MAIN_NS}}}t")) for item in root
    ]


def _sheet_paths(archive: zipfile.ZipFile) -> dict[str, str]:
    try:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except KeyError as error:
        raise WorkbookFormatError(f"Missing workbook structure: {error}") from error

    targets = {
        relation.attrib["Id"]: relation.attrib["Target"]
        for relation in relationships.findall(f"{{{PKG_REL_NS}}}Relationship")
    }
    result: dict[str, str] = {}
    for sheet in workbook.findall(f".//{{{MAIN_NS}}}sheet"):
        relationship_id = sheet.attrib[f"{{{DOC_REL_NS}}}id"]
        target = targets[relationship_id]
        path = target.lstrip("/") if target.startswith("/") else str(PurePosixPath("xl") / target)
        result[sheet.attrib["name"]] = str(PurePosixPath(path))
    return result


def _cell_text(cell: ET.Element, shared: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(f".//{{{MAIN_NS}}}t"))
    value = cell.find(f"{{{MAIN_NS}}}v")
    if value is None or value.text is None:
        return ""
    if cell_type == "s":
        try:
            return shared[int(value.text)]
        except (IndexError, ValueError) as error:
            raise WorkbookFormatError("Invalid shared-string index") from error
    if cell_type == "b":
        return "TRUE" if value.text == "1" else "FALSE"
    return value.text


type WorkbookSource = Path | BinaryIO


def list_sheets(path: WorkbookSource) -> list[str]:
    """Return worksheet names in workbook order."""

    with zipfile.ZipFile(path) as archive:
        return list(_sheet_paths(archive))


def read_sheet(path: WorkbookSource, sheet_name: str) -> list[list[str]]:
    """Read a worksheet as rows of text while retaining identifier digits."""

    with zipfile.ZipFile(path) as archive:
        paths = _sheet_paths(archive)
        if sheet_name not in paths:
            raise WorkbookFormatError(
                f"Worksheet {sheet_name!r} not found; available={list(paths)}"
            )
        shared = _shared_strings(archive)
        root = ET.fromstring(archive.read(paths[sheet_name]))

    rows: list[list[str]] = []
    for row in root.findall(f".//{{{MAIN_NS}}}sheetData/{{{MAIN_NS}}}row"):
        values: dict[int, str] = {}
        for cell in row.findall(f"{{{MAIN_NS}}}c"):
            reference = cell.attrib.get("r")
            if reference is None:
                raise WorkbookFormatError("Cell without coordinate")
            values[_column_index(reference)] = _cell_text(cell, shared)
        width = max(values, default=-1) + 1
        rows.append([values.get(index, "") for index in range(width)])
    return rows
