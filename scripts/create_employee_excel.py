from __future__ import annotations

import re
import zipfile
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape


SOURCE = Path("/Users/meinardus/.codex/attachments/761f5f62-eccf-455c-b135-1b5e11b0a9f1/pasted-text.txt")
OUTPUT = Path("employee_data.xlsx")
HEADERS = [
    "NO", "NAMA", "LOKASI", "DEPT", "SECTION", "JABATAN", "GROUP", "TYPE",
    "JOIN DATE", "MASA KERJA", "REPORT TO NO", "REPORT TO", "ACCOUNT",
    "REPORT ACCOUNT", "ACC", "RPT", "STATUS",
]
WIDTHS = [12, 24, 16, 10, 20, 28, 16, 10, 14, 14, 16, 24, 22, 22, 9, 9, 20]


def col_name(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def inline_cell(ref: str, value: str, style: int = 0) -> str:
    return f'<c r="{ref}" t="inlineStr" s="{style}"><is><t>{escape(value)}</t></is></c>'


def main() -> None:
    lines = SOURCE.read_text(encoding="utf-8").splitlines()[2:]
    rows = [re.split(r" {2,}", line.strip()) for line in lines if line.strip()]
    for row in rows:
        if len(row) == 16 and row[5].endswith(" LOCAL"):
            row[5:6] = ["Heavy Equipment Operator", "LOCAL"]
    if not rows or any(len(row) != len(HEADERS) for row in rows):
        raise ValueError("Format data sumber tidak sesuai dengan 17 kolom yang diharapkan")

    sheet_rows = []
    header_cells = "".join(inline_cell(f"{col_name(i)}1", value, 1) for i, value in enumerate(HEADERS, 1))
    sheet_rows.append(f'<row r="1" ht="24" customHeight="1">{header_cells}</row>')
    for row_idx, row in enumerate(rows, 2):
        cells = []
        for col_idx, value in enumerate(row, 1):
            ref = f"{col_name(col_idx)}{row_idx}"
            if col_idx == 9:
                date_value = (datetime.strptime(value, "%Y-%m-%d") - datetime(1899, 12, 30)).days
                cells.append(f'<c r="{ref}" s="2"><v>{date_value}</v></c>')
            else:
                cells.append(inline_cell(ref, value, 3 if row_idx % 2 == 0 else 0))
        sheet_rows.append(f'<row r="{row_idx}">{"".join(cells)}</row>')

    cols = "".join(
        f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>'
        for i, width in enumerate(WIDTHS, 1)
    )
    last_row = len(rows) + 1
    sheet_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
  <cols>{cols}</cols>
  <sheetData>{''.join(sheet_rows)}</sheetData>
  <autoFilter ref="A1:Q{last_row}"/>
</worksheet>'''

    files = {
        "[Content_Types].xml": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>''',
        "_rels/.rels": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>''',
        "xl/workbook.xml": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Employee Data" sheetId="1" r:id="rId1"/></sheets></workbook>''',
        "xl/_rels/workbook.xml.rels": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>''',
        "xl/styles.xml": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/><bgColor indexed="64"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFD9EAF7"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf><xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="0" fontId="0" fillId="3" borderId="0" xfId="0" applyFill="1"/></cellXfs></styleSheet>''',
        "xl/worksheets/sheet1.xml": sheet_xml,
    }
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as workbook:
        for name, content in files.items():
            workbook.writestr(name, content)
    print(f"Created {OUTPUT.resolve()} with {len(rows)} data rows")


if __name__ == "__main__":
    main()
