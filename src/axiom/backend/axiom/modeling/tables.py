"""Spreadsheet preview and write-back into AML sets, parameters, and constant right-hand sides."""

from __future__ import annotations

import csv
import io
import re
from typing import Any

from openpyxl import load_workbook

from axiom.errors import AxiomError
from axiom.modeling.emitter import emit_aml
from axiom.modeling.ir import Model, ParamDecl, SetDecl, const
from axiom.modeling.parser import parse_aml

_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5")
_PREVIEW_ROWS = 40


def preview_table(data: bytes, filename: str = "data.csv", encoding: str | None = None, sheet: str | None = None) -> dict:
    if not data:
        raise AxiomError("文件是空的。", "The file is empty.", code="empty_table")
    name = (filename or "data.csv").lower()
    if name.endswith(".xlsx") or name.endswith(".xlsm"):
        return _preview_xlsx(data, filename, sheet)
    text, used = _decode(data, encoding)
    return _preview_rows(text, filename, used, None, [])


def apply_table(dsl: str, columns: list[str], rows: list[list[Any]], mapping: list[dict]) -> str:
    model = parse_aml(dsl) if (dsl or "").strip() else Model(name="Imported")
    headers = [str(item) for item in columns]
    index_of = {header: position for position, header in enumerate(headers)}
    plans = []
    for item in mapping:
        column = str(item.get("column") or "")
        if column not in index_of:
            raise AxiomError(f"没有列 {column}。", f"Column {column} is missing.", code="missing_column")
        role = str(item.get("role") or "ignore")
        if role not in {"ignore", "set", "parameter"}:
            raise AxiomError("列只能映射为忽略、集合或参数。", "A column is ignore, set, or parameter.", code="bad_role")
        plans.append(
            {
                "column": column,
                "index": index_of[column],
                "role": role,
                "name": _ident(str(item.get("name") or column), "col"),
                "indexes": [str(part) for part in item.get("indexes") or []],
            }
        )
    set_names = {plan["column"]: plan["name"] for plan in plans if plan["role"] == "set"}
    for plan in plans:
        if plan["role"] != "set":
            continue
        elements: list[str] = []
        for row in rows:
            value = _cell(row, plan["index"])
            if value and value not in elements:
                elements.append(value)
        if not elements:
            continue
        model.sets[plan["name"]] = SetDecl(name=plan["name"], elements=elements)
    for plan in plans:
        if plan["role"] != "parameter":
            continue
        index_sets = []
        index_columns = []
        for ref in plan["indexes"]:
            if ref in set_names:
                index_sets.append(set_names[ref])
                index_columns.append(index_of[ref])
            elif ref in model.sets:
                index_sets.append(ref)
                if ref in index_of:
                    index_columns.append(index_of[ref])
            else:
                raise AxiomError(f"参数 {plan['name']} 的索引 {ref} 不是集合。", f"Index {ref} of {plan['name']} is not a set.", code="bad_index")
        values: dict[tuple[str, ...], float] = {}
        for row in rows:
            raw = _cell(row, plan["index"])
            if raw == "":
                continue
            try:
                number = float(str(raw).replace(",", ""))
            except ValueError as exc:
                raise AxiomError(f"列 {plan['column']} 里有非数字 {raw}。", f"Column {plan['column']} has a non-numeric value {raw}.", code="bad_number") from exc
            key = tuple(_cell(row, position) for position in index_columns)
            if any(part == "" for part in key):
                continue
            values[key] = number
        model.parameters[plan["name"]] = ParamDecl(name=plan["name"], index_sets=index_sets, values=values)
    return emit_aml(model)


def outline(model: Model) -> dict:
    rhs = []
    for con in model.constraints:
        if con.kind == "comparison" and con.rhs is not None and con.rhs.op == "const" and not con.quants:
            rhs.append({"name": con.name, "sense": con.relation, "value": float(con.rhs.value or 0)})
    return {
        "sets": [item.to_dict() for item in model.sets.values()],
        "parameters": [item.to_dict() for item in model.parameters.values()],
        "rhs": rhs,
    }


def apply_outline(dsl: str, payload: dict) -> str:
    model = parse_aml(dsl) if (dsl or "").strip() else Model(name="Edited")
    for item in payload.get("sets") or []:
        decl = SetDecl.from_dict(item)
        if not decl.elements:
            raise AxiomError(f"集合 {decl.name} 不能是空的。", f"Set {decl.name} cannot be empty.", code="empty_set")
        model.sets[decl.name] = decl
    for item in payload.get("parameters") or []:
        decl = ParamDecl.from_dict(item)
        model.parameters[decl.name] = decl
    rhs_values = {str(item.get("name")): float(item.get("value")) for item in payload.get("rhs") or [] if item.get("name")}
    for con in model.constraints:
        if con.name in rhs_values and con.rhs is not None and con.rhs.op == "const":
            con.rhs = const(rhs_values[con.name])
    return emit_aml(model)


def _preview_xlsx(data: bytes, filename: str, sheet: str | None) -> dict:
    try:
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise AxiomError("这个 Excel 文件打不开。", "This Excel file could not be opened.", code="bad_workbook") from exc
    names = list(book.sheetnames)
    chosen = sheet if sheet in names else (names[0] if names else None)
    if chosen is None:
        raise AxiomError("工作簿里没有工作表。", "The workbook has no sheets.", code="empty_table")
    grid = []
    for row in book[chosen].iter_rows(values_only=True):
        grid.append(["" if cell is None else str(cell).strip() for cell in row])
    book.close()
    return _from_grid(grid, filename, "utf-8", chosen, names)


def _preview_rows(text: str, filename: str, encoding: str, sheet: str | None, sheets: list[str]) -> dict:
    sample = text.lstrip("\ufeff")
    try:
        dialect = csv.Sniffer().sniff(sample[:2048], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    grid = [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(sample), dialect)]
    return _from_grid(grid, filename, encoding, sheet, sheets)


def _from_grid(grid: list[list[str]], filename: str, encoding: str, sheet: str | None, sheets: list[str]) -> dict:
    grid = [row for row in grid if any(cell.strip() for cell in row)]
    if len(grid) < 2:
        raise AxiomError("表格至少需要表头和一行数据。", "A table needs a header and one data row.", code="empty_table")
    width = max(len(row) for row in grid)
    columns = []
    for index, cell in enumerate(grid[0]):
        columns.append(cell or f"col{index + 1}")
    while len(columns) < width:
        columns.append(f"col{len(columns) + 1}")
    rows = []
    for row in grid[1:]:
        padded = list(row) + [""] * (width - len(row))
        rows.append(padded[:width])
    return {
        "filename": filename,
        "encoding": encoding,
        "sheet": sheet,
        "sheets": sheets,
        "columns": columns,
        "rows": rows[:_PREVIEW_ROWS],
        "row_count": len(rows),
        "mapping": _suggest(columns, rows),
    }


def _suggest(columns: list[str], rows: list[list[str]]) -> list[dict]:
    roles = []
    for index, column in enumerate(columns):
        values = [_cell(row, index) for row in rows if _cell(row, index)]
        numeric = bool(values) and all(_number(value) for value in values)
        roles.append("parameter" if numeric else "set")
    set_columns = [column for column, role in zip(columns, roles) if role == "set"]
    mapping = []
    for column, role in zip(columns, roles):
        item = {"column": column, "role": role, "name": _ident(column, "col" if role == "set" else "p")}
        if role == "parameter":
            item["indexes"] = list(set_columns)
        else:
            item["indexes"] = []
        mapping.append(item)
    return mapping


def _decode(data: bytes, encoding: str | None) -> tuple[str, str]:
    if encoding:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError as exc:
            raise AxiomError(f"不能用 {encoding} 解码。", f"Could not decode as {encoding}.", code="bad_encoding") from exc
    for candidate in _ENCODINGS:
        try:
            return data.decode(candidate), candidate
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8"


def _cell(row: list[Any], index: int) -> str:
    if index >= len(row) or row[index] is None:
        return ""
    return str(row[index]).strip()


def _number(value: str) -> bool:
    try:
        float(str(value).replace(",", ""))
    except ValueError:
        return False
    return True


def _ident(text: str, fallback: str) -> str:
    raw = re.sub(r"[^A-Za-z0-9_]", "_", text.strip())
    raw = re.sub(r"_+", "_", raw).strip("_")
    if not raw or raw[0].isdigit():
        raw = f"{fallback}_{raw}" if raw else fallback
    if not raw.isidentifier():
        raw = fallback
    return raw[:64]
