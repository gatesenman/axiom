"""Markdown, Excel, and PDF reports for a completed run."""

from __future__ import annotations

import io
from pathlib import Path

from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

_FONT = "AxiomCJK"
_FONT_READY = False


def _ensure_font() -> str:
    global _FONT_READY
    if _FONT_READY:
        return _FONT
    path = Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf")
    if path.exists():
        pdfmetrics.registerFont(TTFont(_FONT, str(path)))
        _FONT_READY = True
        return _FONT
    return "Helvetica"


def markdown_report(run: dict, locale: str = "zh-CN") -> str:
    zh = locale.startswith("zh")
    title = run.get("title") or ("求解报告" if zh else "Solution report")
    lines = [f"# {title}", ""]
    lines.append(run.get("statement") or "")
    lines.append("")
    if zh:
        lines.append(f"- 状态：{run.get('status')}")
        lines.append(f"- 求解器：{run.get('solver')}")
        lines.append(f"- 目标值：{run.get('objective')}")
    else:
        lines.append(f"- Status: {run.get('status')}")
        lines.append(f"- Solver: {run.get('solver')}")
        lines.append(f"- Objective: {run.get('objective')}")
    lines.append("")
    lines.append("## AML" if not zh else "## 模型")
    lines.append("")
    lines.append("```aml")
    lines.append((run.get("dsl") or "").rstrip())
    lines.append("```")
    lines.append("")
    form = run.get("standard_form") or {}
    if form.get("plain") or form.get("latex"):
        lines.append("## Standard equations" if not zh else "## 标准方程")
        lines.append("")
        if form.get("plain"):
            lines.append("```")
            lines.append(str(form.get("plain") or "").rstrip())
            lines.append("```")
            lines.append("")
        if form.get("latex"):
            lines.append("```latex")
            lines.append(str(form.get("latex") or "").rstrip())
            lines.append("```")
            lines.append("")
    lines.append("## Variables" if not zh else "## 变量")
    lines.append("")
    lines.append("| name | value |")
    lines.append("| --- | --- |")
    for key, value in list((run.get("variables") or {}).items())[:80]:
        if str(key).startswith("_"):
            continue
        lines.append(f"| {key} | {value:.6g} |")
    if run.get("summary"):
        lines.extend(["", "## Analysis" if not zh else "## 说明", "", run["summary"]])
    lines.extend(_figure_notes(run, zh))
    lines.append("")
    return "\n".join(lines)


def excel_report(run: dict) -> bytes:
    book = Workbook()
    summary = book.active
    summary.title = "Summary"
    summary.append(["field", "value"])
    for key in ("title", "status", "solver", "objective"):
        summary.append([key, run.get(key)])
    variables = book.create_sheet("Variables")
    variables.append(["name", "value"])
    for key, value in (run.get("variables") or {}).items():
        variables.append([key, value])
    equations = book.create_sheet("Equations")
    equations.append(["role", "name", "plain", "latex"])
    for row in (run.get("standard_form") or {}).get("equations") or []:
        equations.append([row.get("role"), row.get("name") or row.get("key"), row.get("plain"), row.get("latex")])
    constraints = book.create_sheet("Constraints")
    constraints.append(["name", "sense", "lhs", "rhs", "slack", "binding"])
    for row in run.get("constraints") or []:
        constraints.append([row.get("name"), row.get("sense"), row.get("lhs"), row.get("rhs"), row.get("slack"), row.get("binding")])
    sensitivity = book.create_sheet("Sensitivity")
    sensitivity.append(["name", "low", "base", "high", "span"])
    for row in (run.get("sensitivity") or {}).get("rows", []) if isinstance(run.get("sensitivity"), dict) else []:
        sensitivity.append([row.get("name"), row.get("low"), row.get("base"), row.get("high"), row.get("span")])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def pdf_report(run: dict, locale: str = "zh-CN") -> bytes:
    font = _ensure_font()
    buffer = io.BytesIO()
    sheet = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 16 * mm
    zh = locale.startswith("zh")
    sheet.setFont(font, 9)
    sheet.drawString(18 * mm, y, "公理 Axiom")
    y -= 8 * mm
    sheet.setFont(font, 16)
    sheet.drawString(18 * mm, y, run.get("title") or ("求解报告" if zh else "Solution report"))
    y -= 10 * mm
    sheet.setFont(font, 10)
    rows = [
        f"{'状态' if zh else 'Status'}: {run.get('status')}",
        f"{'求解器' if zh else 'Solver'}: {run.get('solver')}",
        f"{'目标值' if zh else 'Objective'}: {run.get('objective')}",
        run.get("summary") or "",
    ]
    for row in rows:
        for chunk in _wrap(str(row), 42):
            if y < 20 * mm:
                sheet.showPage()
                sheet.setFont(font, 10)
                y = height - 20 * mm
            sheet.drawString(18 * mm, y, chunk)
            y -= 6 * mm
    form = run.get("standard_form") or {}
    plain = str(form.get("plain") or "").strip()
    if plain:
        y -= 4 * mm
        sheet.setFont(font, 12)
        if y < 20 * mm:
            sheet.showPage()
            sheet.setFont(font, 12)
            y = height - 20 * mm
        sheet.drawString(18 * mm, y, "标准方程" if zh else "Standard equations")
        y -= 7 * mm
        sheet.setFont(font, 9)
        for chunk in _wrap(plain, 48)[:48]:
            if y < 18 * mm:
                sheet.showPage()
                sheet.setFont(font, 9)
                y = height - 20 * mm
            sheet.drawString(18 * mm, y, chunk)
            y -= 5 * mm
    y -= 4 * mm
    sheet.setFont(font, 12)
    sheet.drawString(18 * mm, y, "变量" if zh else "Variables")
    y -= 7 * mm
    sheet.setFont(font, 9)
    for key, value in list((run.get("variables") or {}).items())[:40]:
        if str(key).startswith("_"):
            continue
        if y < 18 * mm:
            sheet.showPage()
            sheet.setFont(font, 9)
            y = height - 20 * mm
        sheet.drawString(18 * mm, y, f"{key}    {float(value):.6g}")
        y -= 5 * mm
    y = _pdf_figures(sheet, run, y, height, font, zh)
    sheet.save()
    return buffer.getvalue()


def _figure_notes(run: dict, zh: bool) -> list[str]:
    lines = ["", "## 图" if zh else "## Figures", ""]
    index = 1
    sensitivity = (run.get("sensitivity") or {}).get("rows") if isinstance(run.get("sensitivity"), dict) else None
    if sensitivity:
        caption = "灵敏度龙卷图：各因素在 ±10% 扰动下目标值的下偏与上偏。" if zh else "Sensitivity tornado: objective shortfall and upside under a ±10% perturbation."
        lines.append(f"图{index}  {caption}" if zh else f"Fig. {index}  {caption}")
        lines.append("")
        lines.append("```latex")
        lines.append(_latex("tornado", caption))
        lines.append("```")
        lines.append("")
        index += 1
    if run.get("duals"):
        caption = "约束影子价格（求解器对偶值）。" if zh else "Constraint shadow prices (solver dual values)."
        lines.append(f"图{index}  {caption}" if zh else f"Fig. {index}  {caption}")
        lines.append("")
        lines.append("```latex")
        lines.append(_latex("duals", caption))
        lines.append("```")
        lines.append("")
        index += 1
    region = (run.get("figures") or {}).get("feasible_region")
    if region and region.get("polygon"):
        caption = f"可行域，坐标为 {region.get('x')} 与 {region.get('y')}。" if zh else f"Feasible region in {region.get('x')} and {region.get('y')}."
        lines.append(f"图{index}  {caption}" if zh else f"Fig. {index}  {caption}")
        lines.append("")
        lines.append("```latex")
        lines.append(_latex("feasible", caption))
        lines.append("```")
        lines.append("")
        index += 1
    if index == 1:
        return []
    return lines


def _latex(label: str, caption: str) -> str:
    safe = caption.replace("&", "\\&").replace("%", "\\%")
    return "\n".join(
        [
            "\\begin{figure}[htbp]",
            "  \\centering",
            f"  \\includegraphics[width=0.82\\linewidth]{{fig-{label}.pdf}}",
            f"  \\caption{{{safe}}}",
            f"  \\label{{fig:{label}}}",
            "\\end{figure}",
        ]
    )


def _pdf_figures(sheet, run: dict, y: float, height: float, font: str, zh: bool) -> float:
    from reportlab.lib.units import mm

    figures = []
    sensitivity = (run.get("sensitivity") or {}).get("rows") if isinstance(run.get("sensitivity"), dict) else None
    if sensitivity:
        rows = sorted(sensitivity, key=lambda row: abs(float(row.get("high", 0)) - float(row.get("low", 0))), reverse=True)[:8]
        figures.append((
            "灵敏度（目标值跨度）" if zh else "Sensitivity (objective span)",
            [str(row.get("name")) for row in rows],
            [abs(float(row.get("high", 0)) - float(row.get("low", 0))) for row in rows],
            "目标值单位" if zh else "objective units",
        ))
    duals = run.get("duals") or {}
    if duals:
        items = [(key, float(value)) for key, value in list(duals.items())[:8] if abs(float(value)) > 1e-8]
        if items:
            figures.append((
                "影子价格" if zh else "Shadow prices",
                [key for key, _value in items],
                [value for _key, value in items],
                "对偶值" if zh else "dual value",
            ))
    for index, (title, labels, values, unit) in enumerate(figures, start=1):
        y -= 8 * mm
        if y < 70 * mm:
            sheet.showPage()
            y = height - 18 * mm
        sheet.setFont(font, 11)
        sheet.drawString(18 * mm, y, f"{'图' if zh else 'Fig.'} {index}  {title}")
        y -= 5 * mm
        sheet.setFont(font, 8)
        sheet.drawString(18 * mm, y, unit)
        y -= 4 * mm
        y = _hbar(sheet, y, labels, values, font)
        sheet.setFont(font, 8)
        caption = f"{'图' if zh else 'Fig.'} {index}. {title}."
        sheet.drawString(18 * mm, y, caption)
        y -= 6 * mm
    region = (run.get("figures") or {}).get("feasible_region") or {}
    if region.get("polygon"):
        index = len(figures) + 1
        y -= 4 * mm
        if y < 28 * mm:
            sheet.showPage()
            y = height - 18 * mm
        sheet.setFillColorRGB(0, 0, 0)
        sheet.setFont(font, 11)
        title = "可行域" if zh else "Feasible region"
        sheet.drawString(18 * mm, y, f"{'图' if zh else 'Fig.'} {index}  {title}")
        y -= 5 * mm
        sheet.setFont(font, 8)
        axes = f"{region.get('x')} × {region.get('y')}"
        sheet.drawString(18 * mm, y, f"{'图' if zh else 'Fig.'} {index}. {title}, {axes}.")
        y -= 6 * mm
    sheet.setFillColorRGB(0, 0, 0)
    return y


def _hbar(sheet, y: float, labels: list[str], values: list[float], font: str) -> float:
    from reportlab.lib.units import mm

    peak = max((abs(value) for value in values), default=1.0) or 1.0
    width = 110 * mm
    left = 62 * mm
    for label, value in zip(labels, values):
        if y < 22 * mm:
            sheet.showPage()
            sheet.setFont(font, 8)
            y = 270 * mm
        sheet.setFillColorRGB(0.15, 0.15, 0.15)
        sheet.setFont(font, 8)
        sheet.drawRightString(left - 2 * mm, y - 1, label[:22])
        sheet.setFillColorRGB(0.24, 0.32, 0.4)
        bar = width * (abs(value) / peak)
        sheet.rect(left, y - 3, max(bar, 0.4 * mm), 3.2 * mm, stroke=0, fill=1)
        sheet.setFillColorRGB(0.15, 0.15, 0.15)
        sheet.drawString(left + bar + 1.5 * mm, y - 1, f"{value:.4g}")
        y -= 6 * mm
    return y


def package_report(run: dict, locale: str = "zh-CN") -> bytes:
    import json
    import zipfile

    payload = {
        "title": run.get("title"),
        "status": run.get("status"),
        "solver": run.get("solver"),
        "objective": run.get("objective"),
        "variables": run.get("variables") or {},
        "constraints": run.get("constraints") or [],
        "summary": run.get("summary"),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("model.aml", (run.get("dsl") or "").rstrip() + "\n")
        archive.writestr("results.json", json.dumps(payload, ensure_ascii=False, indent=2))
        archive.writestr("report.md", markdown_report(run, locale))
        archive.writestr("report.pdf", pdf_report(run, locale))
    return buffer.getvalue()


def _wrap(text: str, size: int) -> list[str]:
    text = text.replace("\n", " ")
    if not text:
        return [""]
    return [text[index : index + size] for index in range(0, len(text), size)]
