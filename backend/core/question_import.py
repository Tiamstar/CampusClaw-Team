"""Bounded, deterministic teacher imports. No model calls or implicit answer inference."""
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, BadZipFile
from lxml import etree

from docx import Document
from openpyxl import load_workbook, Workbook

HEADERS = ['题型', '题干', '选项', '答案', '分值', '解析', '知识点']
KINDS = {'单选': 'single', '多选': 'multiple', '判断': 'boolean', '填空': 'blank', '简答': 'short'}
MAX_ROWS = 200
MAX_FILE = 5 * 1024 * 1024
MAX_EXPANDED = 20 * 1024 * 1024


def check_package(raw):
    if not raw or len(raw) > MAX_FILE:
        raise ValueError('文件须为5 MiB以内的XLSX或DOCX')
    try:
        with ZipFile(BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > 1000 or len({e.filename for e in entries}) != len(entries):
                raise ValueError('文档压缩包条目异常')
            if sum(e.file_size for e in entries) > MAX_EXPANDED or any(e.flag_bits & 1 for e in entries):
                raise ValueError('文档解压后超过20 MiB或包含加密内容')
            for entry in entries:
                lower = entry.filename.lower()
                if any(v in lower for v in ['vbaproject', 'embeddings/', 'activex/', '/media/', '/drawings/']):
                    raise ValueError('不支持含宏、图片、绘图、嵌入对象或活动控件的题库；请改为文本和LaTeX公式')
                if lower.endswith(('.xml', '.rels')):
                    data = archive.read(entry)
                    tree = etree.fromstring(data, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
                    if tree.getroottree().docinfo.doctype:
                        raise ValueError('不支持包含DTD或实体声明的文档')
                    if lower.endswith('.rels') and tree.xpath('//*[local-name()="Relationship"][@TargetMode="External"]'):
                        raise ValueError('不支持外部链接或外部数据源，请将内容粘贴为文本')
                    if lower.startswith('xl/worksheets/'):
                        if tree.xpath('//*[local-name()="mergeCell"] | //*[local-name()="row" or local-name()="col"][@hidden="1" or @hidden="true"]'):
                            raise ValueError('题库不支持合并单元格或隐藏行列，请取消后重试')
                    if lower == 'word/document.xml':
                        if tree.xpath('//*[local-name()="gridSpan" or local-name()="vMerge" or local-name()="oMath" or local-name()="oMathPara" or local-name()="del" or local-name()="ins" or local-name()="vanish" or local-name()="fldChar" or local-name()="altChunk"]'):
                            raise ValueError('Word包含合并单元格、修订、隐藏内容或非文本公式/域；请转换为普通文本和LaTeX')
    except (BadZipFile, etree.XMLSyntaxError, RuntimeError, OSError) as exc:
        raise ValueError('文件不是有效的Office文档或已经损坏') from exc


def parse_file(name, raw):
    suffix = Path(name).suffix.lower()
    if suffix not in {'.xlsx', '.docx'}:
        raise ValueError('请选择XLSX或DOCX模板文件；旧版XLS/DOC请先另存为新格式')
    check_package(raw)
    try:
        if suffix == '.xlsx':
            workbook = load_workbook(BytesIO(raw), read_only=True, data_only=False, keep_links=False)
            try:
                if len(workbook.worksheets) != 1:
                    raise ValueError('工作簿须只有一个题库工作表，避免遗漏其他工作表')
                sheet = workbook.worksheets[0]
                if sheet.sheet_state != 'visible':
                    raise ValueError('题库工作表必须可见')
                sheet.reset_dimensions()
                rows = []
                for index, row in enumerate(sheet.iter_rows()):
                    if index > MAX_ROWS:
                        raise ValueError('每批最多200道题，请拆分文件')
                    if any(cell.data_type == 'f' for cell in row):
                        raise ValueError(f'第{index+1}行包含公式单元格，请粘贴为文本或数值')
                    if len(row) > len(HEADERS) and any(c.value is not None for c in row[len(HEADERS):]):
                        raise ValueError(f'第{index+1}行包含模板外列')
                    values = [c.value for c in row[:len(HEADERS)]]
                    rows.append(values + [None] * (len(HEADERS) - len(values)))
            finally:
                workbook.close()
        else:
            doc = Document(BytesIO(raw))
            if len(doc.tables) != 1:
                raise ValueError('Word文件须包含一个题库表格，请使用模板')
            if doc.inline_shapes or any(p.text.strip() for p in doc.paragraphs):
                raise ValueError('Word内容须全部位于题库表格中；图片和表外正文不会被静默忽略')
            table = doc.tables[0]
            if len(table.rows) > MAX_ROWS + 1:
                raise ValueError('每批最多200道题，请拆分文件')
            rows = []
            for index, row in enumerate(table.rows):
                if len(row.cells) != len(HEADERS) or len({id(c._tc) for c in row.cells}) != len(HEADERS):
                    raise ValueError(f'第{index+1}行须为7列且不能合并单元格')
                if any(c.tables for c in row.cells):
                    raise ValueError('题库表格不支持嵌套表格')
                rows.append([c.text for c in row.cells])
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('Office文档无法读取，请检查格式、密码和文件完整性') from exc
    rows = [[str(v).strip() if v is not None else '' for v in row] for row in rows]
    if not rows or rows[0] != HEADERS:
        raise ValueError('首行须依次为：' + '、'.join(HEADERS))
    result = []
    for number, row in enumerate(rows[1:], 2):
        if not any(row):
            continue
        if len(row) != len(HEADERS):
            raise ValueError(f'第{number}行须完整提供7列（可为空的列也须保留）')
        if any(len(v) > 20000 for v in row):
            raise ValueError(f'第{number}行字段过长')
        kind, body, options, answer, score, explanation, points = row
        kind = KINDS.get(kind, kind)
        option_values = [v.strip() for v in options.splitlines() if v.strip()]
        values = [v.strip() for v in answer.splitlines() if v.strip()]
        if kind == 'boolean':
            values = [{'正确': 'true', '错误': 'false', '对': 'true', '错': 'false'}.get(v, v) for v in values]
        if kind in {'single', 'multiple'}:
            letters = [chr(65+i) for i in range(len(option_values))]
            values = [str(letters.index(v.upper())) if v.upper() in letters else v for v in values]
        result.append({'row': number, 'point_names': [v.strip() for v in points.splitlines() if v.strip()],
                       'kind': kind, 'body': body, 'options': option_values,
                       'answer': {'values': values}, 'score': score, 'explanation': explanation})
    if not result:
        raise ValueError('文件没有题目')
    return result


def template_bytes(format):
    stream = BytesIO()
    example = ['单选', '计算 $1+1$。', '1\n2\n3', 'B', '10', '相加得到2。', '']
    if format == 'xlsx':
        wb = Workbook()
        ws = wb.active
        ws.title = '题库'
        ws.append(HEADERS)
        ws.append(example)
        from openpyxl.styles import Alignment, Font
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for row in ws:
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical='top')
        for column in ['A', 'B', 'C', 'D', 'E', 'F', 'G']:
            ws.column_dimensions[column].width = 24 if column != 'B' else 48
        ws.freeze_panes = 'A2'
        wb.save(stream)
    elif format == 'docx':
        doc = Document()
        table = doc.add_table(rows=1, cols=len(HEADERS))
        table.style = 'Table Grid'
        for cell, value in zip(table.rows[0].cells, HEADERS):
            cell.text = value
        for cell, value in zip(table.add_row().cells, example):
            cell.text = value
        doc.save(stream)
    else:
        raise ValueError('模板格式无效')
    return stream.getvalue()
