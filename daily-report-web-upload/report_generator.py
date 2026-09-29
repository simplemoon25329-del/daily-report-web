from __future__ import annotations

import csv
import io
import re
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Pt, RGBColor


FIELDS = ("专业", "今日工作", "危险作业", "完成情况", "人员", "明日计划", "明日危险作业", "备注")


@dataclass(frozen=True)
class WorkItem:
    profession: str
    today: str
    today_hazard: str
    status: str
    people: str
    tomorrow: str
    tomorrow_hazard: str
    remark: str


def apply_defaults(item: WorkItem) -> WorkItem:
    """Fill missing values only on the side with work; preserve explicit input."""
    return replace(
        item,
        today_hazard=item.today_hazard.strip() or ("否" if item.today.strip() else ""),
        status=(item.status.strip() or "已完成") if item.today.strip() else "",
        tomorrow_hazard=item.tomorrow_hazard.strip() or ("否" if item.tomorrow.strip() else ""),
        remark=item.remark.strip(),
    )


def align_work_items(items: list[WorkItem]) -> list[WorkItem]:
    """Align each profession's today and tomorrow work from the first row."""
    groups: OrderedDict[str, list[WorkItem]] = OrderedDict()
    for item in items:
        groups.setdefault(item.profession, []).append(item)

    aligned = []
    for profession, profession_items in groups.items():
        today_items = [item for item in profession_items if item.today]
        tomorrow_items = [item for item in profession_items if item.tomorrow]
        row_count = max(len(today_items), len(tomorrow_items))
        for index in range(row_count):
            today_item = today_items[index] if index < len(today_items) else None
            tomorrow_item = tomorrow_items[index] if index < len(tomorrow_items) else None
            remark = today_item.remark if today_item and today_item.remark else (
                tomorrow_item.remark if tomorrow_item else ""
            )
            aligned.append(WorkItem(
                profession=profession,
                today=today_item.today if today_item else "",
                today_hazard=today_item.today_hazard if today_item else "",
                status=today_item.status if today_item else "",
                people=today_item.people if today_item else "",
                tomorrow=tomorrow_item.tomorrow if tomorrow_item else "",
                tomorrow_hazard=tomorrow_item.tomorrow_hazard if tomorrow_item else "",
                remark=remark,
            ))
        aligned.extend(item for item in profession_items if not item.today and not item.tomorrow)
    return aligned


def parse_comma_text(text: str) -> list[WorkItem]:
    """解析英文逗号分隔文本；支持 CSV 双引号转义及可选标题行。"""
    rows = []
    reader = csv.reader(io.StringIO(text.strip()), delimiter=",", quotechar='"', skipinitialspace=True, strict=True)
    for line_no, raw in enumerate(reader, 1):
        if not raw or all(not value.strip() for value in raw):
            continue
        values = [value.strip() for value in raw]
        if not rows and values[0] in {"专业", "专业名称"}:
            continue
        if len(values) != 8:
            raise ValueError(f"第 {line_no} 行有 {len(values)} 个字段，应为 8 个。请检查英文逗号数量；字段内英文逗号需用双引号包住。")
        if not values[0]:
            raise ValueError(f"第 {line_no} 行的“专业”不能为空。")
        rows.append(apply_defaults(WorkItem(*values)))
    if not rows:
        raise ValueError("没有识别到可生成的数据。")
    return rows


def _clear_vmerge(row) -> None:
    for cell in row.cells:
        tc_pr = cell._tc.get_or_add_tcPr()
        for element in list(tc_pr.findall(qn("w:vMerge"))):
            tc_pr.remove(element)


def _set_cell_text(cell, value: str) -> None:
    paragraph = cell.paragraphs[0]
    run_properties = None
    if paragraph.runs and paragraph.runs[0]._r.rPr is not None:
        run_properties = deepcopy(paragraph.runs[0]._r.rPr)
    for run in list(paragraph.runs):
        paragraph._p.remove(run._r)
    new_run = paragraph.add_run(value)
    if run_properties is not None:
        new_run._r.insert(0, run_properties)
    for extra in cell.paragraphs[1:]:
        cell._tc.remove(extra._p)


def _replace_title_date(document: Document, report_date: date) -> None:
    value = f"{report_date:%m}月{report_date:%d}日"
    pattern = re.compile(r"\d{1,2}月\d{1,2}日")
    for paragraph in document.paragraphs:
        if pattern.search(paragraph.text):
            new_text = pattern.sub(value, paragraph.text)
            if paragraph.runs:
                paragraph.runs[0].text = new_text
                for run in paragraph.runs[1:]:
                    run.text = ""
            else:
                paragraph.add_run(new_text)
            break


def generate_report(template_path: str | Path, items: list[WorkItem], report_date: date, output_path, auto_style=True):
    """基于原 Word 模板生成日报，保留表头、列宽、边框和基础单元格样式。"""
    document = Document(str(template_path))
    if not document.tables:
        raise ValueError("模板中没有找到表格。")
    table = document.tables[0]
    if len(table.rows) < 3 or len(table.columns) != 11:
        raise ValueError("模板结构不符合预期：应至少有 3 行、11 列。")

    template_row_xml = deepcopy(table.rows[2]._tr)
    order = list(dict.fromkeys(r.cells[1].text.strip() for r in table.rows[2:]))
    aliases = {"机务检修": "机务", "电气": "电气检修"}
    hazard_aliases = {"动火作业": "动火", "有限空间作业": "有限"}
    if not items:
        raise ValueError("没有工作记录。")
    for row in list(table.rows[2:]):
        table._tbl.remove(row._tr)

    groups: OrderedDict[str, list[WorkItem]] = OrderedDict()
    for item in align_work_items(items):
        item = apply_defaults(item)
        name = aliases.get(item.profession.strip(), item.profession.strip())
        if not name:
            raise ValueError("专业不能为空。")
        groups.setdefault(name, []).append(item)
    groups = OrderedDict((n, groups[n]) for n in order + [n for n in groups if n not in order] if n in groups)
    for row in table.rows[:2]:
        pr = row._tr.get_or_add_trPr()
        if pr.find(qn("w:tblHeader")) is None:
            pr.append(OxmlElement("w:tblHeader"))

    for profession_no, (profession, profession_items) in enumerate(groups.items(), 1):
        group_rows = []
        today_no = tomorrow_no = 0
        for item_no, item in enumerate(profession_items, 1):
            row_xml = deepcopy(template_row_xml)
            table._tbl.append(row_xml)
            row = table.rows[-1]
            _clear_vmerge(row)
            today_no += bool(item.today)
            tomorrow_no += bool(item.tomorrow)
            today, tomorrow, remark = item.today, item.tomorrow, item.remark
            if auto_style and len(remark) > 4:
                if today:
                    today += "（备注：" + remark + "）"
                    remark = ""
                elif tomorrow:
                    tomorrow += "（备注：" + remark + "）"
                    remark = ""
            values = (
                str(profession_no) if item_no == 1 else "",
                profession if item_no == 1 else "",
                str(today_no) if item.today else "",
                today,
                hazard_aliases.get(item.today_hazard, item.today_hazard),
                item.status,
                item.people,
                str(tomorrow_no) if item.tomorrow else "",
                tomorrow,
                hazard_aliases.get(item.tomorrow_hazard, item.tomorrow_hazard),
                remark,
            )
            for column, (cell, value) in enumerate(zip(row.cells, values)):
                _set_cell_text(cell, value)
                if column in (4, 9):
                    # Override red inherited from the template for both hazard columns.
                    color = "FF0000" if value.strip() and value.strip() != "否" else "000000"
                    for paragraph in cell.paragraphs:
                        for run in paragraph.runs:
                            run.font.color.rgb = RGBColor.from_string(color)
                            if value.strip() == "否":
                                run.bold = False
                if auto_style and column == 1:
                    direction = cell._tc.tcPr.find(qn("w:textDirection"))
                    if direction is not None:
                        direction.set(qn("w:val"), "lrTb")
                    _set_cell_text(cell, "\n".join(value))
                borders = cell._tc.get_or_add_tcPr().find(qn("w:tcBorders"))
                if borders is None:
                    borders = OxmlElement("w:tcBorders")
                    cell._tc.tcPr.append(borders)
                top = borders.find(qn("w:top"))
                if top is None:
                    top = OxmlElement("w:top")
                    borders.append(top)
                top.set(qn("w:val"), "single")
                top.set(qn("w:sz"), "18" if item_no == 1 else "4")
                for p in cell.paragraphs:
                    p.paragraph_format.keep_with_next = False
                    if auto_style:
                        if column == 1:
                            p.paragraph_format.left_indent = Pt(0)
                            p.paragraph_format.right_indent = Pt(0)
                        props = p._p.get_or_add_pPr()
                        snap = props.find(qn("w:snapToGrid"))
                        if snap is None:
                            snap = OxmlElement("w:snapToGrid")
                            props.append(snap)
                        snap.set(qn("w:val"), "0")
                        p.paragraph_format.space_before = Pt(0)
                        p.paragraph_format.space_after = Pt(0)
                        p.paragraph_format.line_spacing = 1.0
            group_rows.append(row)

        if len(group_rows) > 1:
            group_rows[0].cells[0].merge(group_rows[-1].cells[0])
            group_rows[0].cells[1].merge(group_rows[-1].cells[1])
            _set_cell_text(group_rows[0].cells[0], str(profession_no))
            _set_cell_text(group_rows[0].cells[1], "\n".join(profession) if auto_style else profession)

    _replace_title_date(document, report_date)
    if hasattr(output_path, "write"):
        document.save(output_path)
        return output_path
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(output)
    return output
