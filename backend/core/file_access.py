"""One permission boundary for private file downloads and previews."""
from pathlib import Path

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied

from .models import Assignment, Material, Membership, StoredFile, SubmissionVersion


def authorized_file(user, file_id):
    item = get_object_or_404(StoredFile, pk=file_id)
    membership = Membership.objects.filter(course_id=item.course_id, user=user).first()
    if not membership:
        raise PermissionDenied("无权访问文件")
    if item.kind == "material":
        allowed = Material.objects.filter(course_id=item.course_id, attachment=item).exists()
    elif item.kind == "assignment":
        allowed = Assignment.objects.filter(course_id=item.course_id, attachment=item).exists()
    else:
        versions = SubmissionVersion.objects.filter(
            Q(attachment=item) | Q(files=item), submission__assignment__course_id=item.course_id,
        )
        if membership.role == "student":
            versions = versions.filter(submission__student=user)
        allowed = versions.exists()
    if not allowed:
        raise PermissionDenied("无权访问文件")
    return item


def preview_info(item):
    extension = Path(item.original_name).suffix.lower()
    if extension == ".pdf":
        kind, note = "pdf", "PDF 预览"
    elif extension in {".png", ".jpg", ".jpeg", ".webp"}:
        kind, note = "image", "图片预览"
    elif extension == ".docx":
        kind, note = "document", "正文和表格预览，复杂排版请下载原文件查看"
    elif extension in {".txt", ".md", ".csv"} and item.size <= 2 * 1024 * 1024:
        kind, note = "text", "文本预览"
    else:
        kind = "unsupported"
        note = "文件较大，请下载后查看" if extension in {".txt", ".md", ".csv"} else f"{extension.lstrip('.').upper() or '此格式'} 暂不支持在线预览，请下载后查看"
    return {"preview_kind": kind, "preview_supported": kind != "unsupported", "preview_note": note,
            "preview_url": f"/api/files/{item.id}/preview/"}
