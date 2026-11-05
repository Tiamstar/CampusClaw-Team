from html import escape
from zipfile import ZipFile, BadZipFile

import pymupdf
from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from PIL import Image
from lxml.etree import Error as XMLError
from django.http import FileResponse, HttpResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .file_access import authorized_file, preview_info


class PreviewUnavailable(Exception):
    pass


def document_page(title, body, note=""):
    return ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
            f"<title>{escape(title)}</title><style>"
            "body{margin:0;background:#e9e9ec;color:#252525;font:16px/1.8 system-ui,sans-serif}"
            "article{max-width:820px;box-sizing:border-box;margin:24px auto;padding:48px;background:white;min-height:85vh}"
            "p,pre,td{overflow-wrap:anywhere}p{white-space:pre-wrap}pre{white-space:pre-wrap;font:inherit}"
            "table{border-collapse:collapse;width:100%;margin:20px 0}td{border:1px solid #bbb;padding:8px}"
            ".note{font-size:13px;color:#666;border-bottom:1px solid #ddd;padding-bottom:16px}"
            "@media(max-width:600px){article{margin:0;padding:20px}}"
            f"</style><article><p class='note'>{escape(note)}</p>{body}</article></html>")


def docx_preview(item):
    with ZipFile(item.file.path) as archive:
        entries = archive.infolist()
        if len(entries) > 2000 or sum(entry.file_size for entry in entries) > 50 * 1024 * 1024:
            raise PreviewUnavailable("文档内容过大，无法在线预览，请下载后查看")
    document = Document(item.file.path)
    blocks = []
    characters = 0
    for element in document.element.body:
        if element.tag == qn('w:p'):
            paragraph = Paragraph(element, document)
            text = paragraph.text
            characters += len(text)
            style = paragraph.style.name if paragraph.style else ""
            tag = "h2" if style.startswith('Heading') or style == 'Title' else "p"
            if text.strip():
                blocks.append(f"<{tag}>{escape(text)}</{tag}>")
        elif element.tag == qn('w:tbl'):
            rows = []
            for row in Table(element, document).rows:
                cells = []
                for cell in row.cells:
                    characters += len(cell.text)
                    cells.append(f"<td>{escape(cell.text).replace(chr(10), '<br>')}</td>")
                rows.append('<tr>' + ''.join(cells) + '</tr>')
            blocks.append('<table>' + ''.join(rows) + '</table>')
        if characters > 500000:
            raise PreviewUnavailable("文档内容过长，无法在线预览，请下载后查看")
    if not blocks:
        raise PreviewUnavailable("文档中没有可预览的正文或表格，请下载原文件查看")
    note = "正文与表格内容预览，复杂排版请下载原文件查看。"
    if document.inline_shapes or document.element.xpath('.//m:oMath'):
        note = "文档包含图形或公式，当前仅预览可提取文字与表格，请下载原文件查看完整内容。"
    return document_page(item.original_name, ''.join(blocks), note)


@api_view(["GET"])
def preview_file(request, file_id):
    item = authorized_file(request.user, file_id)
    if not item.file.storage.exists(item.file.name):
        return Response({"error": "文件不存在"}, status=404)
    info = preview_info(item)
    if not info['preview_supported']:
        return Response({"error": info['preview_note']}, status=415)
    try:
        if info['preview_kind'] == 'pdf':
            with pymupdf.open(item.file.path) as document:
                if not document.is_pdf or document.needs_pass or document.page_count == 0:
                    raise PreviewUnavailable("此 PDF 无法在线预览，可能已加密或内容损坏，请下载后查看")
            response = FileResponse(item.file.open('rb'), content_type='application/pdf')
        elif info['preview_kind'] == 'image':
            with item.file.open('rb') as source, Image.open(source) as image:
                content_type = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}.get(image.format)
                image.verify()
            if not content_type:
                raise PreviewUnavailable("此图片格式无法在线预览，请下载后查看")
            response = FileResponse(item.file.open('rb'), content_type=content_type)
        elif info['preview_kind'] == 'document':
            response = HttpResponse(docx_preview(item), content_type='text/html; charset=utf-8')
        else:
            with item.file.open('rb') as source:
                raw = source.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise PreviewUnavailable("文本较大，请下载后查看")
            try:
                text = raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                text = raw.decode('gb18030')
            response = HttpResponse(document_page(item.original_name, f'<pre>{escape(text)}</pre>', '文本内容预览'),
                                    content_type='text/html; charset=utf-8')
    except PreviewUnavailable as error:
        return Response({"error": str(error)}, status=422)
    except (ValueError, OSError, BadZipFile, KeyError, UnicodeError, Image.DecompressionBombError,
            pymupdf.FileDataError, pymupdf.EmptyFileError, PackageNotFoundError, XMLError):
        return Response({"error": "无法解析文件内容，请下载原文件查看"}, status=422)
    response['Cache-Control'] = 'no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "sandbox; default-src 'none'; style-src 'unsafe-inline'"
    return response
