import mimetypes
import hashlib
import uuid
import secrets
from datetime import timedelta
from pathlib import Path
from django.conf import settings
from django.contrib.auth import authenticate, password_validation
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.csrf import ensure_csrf_cookie
from django.core.exceptions import ValidationError
from asgiref.sync import async_to_sync
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .auth_throttle import AuthThrottle, CodeThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from .models import Assignment, Course, EmailCode, Material, Membership, StoredFile, Submission, SubmissionVersion, TeacherInvite, User, token_code
from .index_service import enqueue, task_data, validate_key, IndexConflict
from .models import MaterialIndexTask
from .file_access import authorized_file, preview_info

EXTENSIONS = {"doc", "docx", "pdf", "zip", "xls", "xlsx", "ppt", "pptx", "txt", "md", "csv", "png", "jpg", "jpeg", "webp"}
MAX_BYTES = 50 * 1024 * 1024


def fail(message, code=400):
    return Response({"error": message}, status=code)


def member(user, course_id, role=None):
    item = Membership.objects.filter(course_id=course_id, user=user).first()
    return item if item and (role is None or item.role == role) else None


def course_data(course, user):
    m = member(user, course.id)
    return {"id": course.id, "name": course.name, "icon": f"/api/courses/{course.id}/icon/" if course.icon else None,
            "role": m.role, "join_code": course.join_code if m.role == "teacher" else None,
            "member_count": course.memberships.count()}


def file_data(f):
    return {"id": f.id, "name": f.original_name, "size": f.size, "created_at": f.created_at,
            "download_url": f"/api/files/{f.id}/download/", **preview_info(f)}


def validate_file(upload, allowed=EXTENSIONS, max_bytes=MAX_BYTES):
    if not upload:
        return "请选择文件"
    ext = Path(upload.name).suffix.lower().lstrip(".")
    if ext not in allowed:
        return "不支持此文件格式"
    if upload.size == 0 or upload.size > max_bytes:
        return f"文件大小须在 1 字节至 {max_bytes // 1024 // 1024} MB 之间"
    return None


def store_file(course, user, upload, kind):
    return StoredFile.objects.create(course=course, uploaded_by=user, file=upload,
                                     original_name=Path(upload.name).name[:255], size=upload.size, kind=kind)


def token_pair(user):
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


@ensure_csrf_cookie
@api_view(["GET"])
@permission_classes([AllowAny])
def csrf(request):
    return Response({"ok": True})


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([CodeThrottle])
def send_code(request):
    email = str(request.data.get("email", "")).strip().lower()
    purpose = request.data.get("purpose")
    try:
        validate_email(email)
    except ValidationError:
        return fail("邮箱或用途无效")
    if purpose not in ("register", "reset"):
        return fail("邮箱或用途无效")
    exists = User.objects.filter(email=email).exists()
    if (purpose == "register" and exists) or (purpose == "reset" and not exists):
        return fail("邮箱不可用于此操作")
    recent = EmailCode.objects.filter(email=email, purpose=purpose).order_by("-created_at").first()
    if recent and recent.created_at > timezone.now() - timedelta(seconds=60):
        return fail("请稍后再获取验证码", 429)
    code = f"{secrets.randbelow(1000000):06d}"
    send_mail("CampusClaw 验证码", f"验证码：{code}。10 分钟内有效，请勿转发。", settings.DEFAULT_FROM_EMAIL, [email])
    with transaction.atomic():
        EmailCode.objects.filter(email=email, purpose=purpose, consumed_at__isnull=True).update(consumed_at=timezone.now())
        EmailCode.objects.create(email=email, purpose=purpose, code_hash=make_password(code),
                                 expires_at=timezone.now() + timedelta(minutes=10))
    return Response({"ok": True})


def consume_code(email, purpose, code):
    with transaction.atomic():
        item = EmailCode.objects.select_for_update().filter(email=email, purpose=purpose).order_by("-created_at").first()
        if not item or item.consumed_at or item.expires_at <= timezone.now() or item.attempts >= 5:
            return False
        item.attempts += 1
        valid = check_password(code, item.code_hash)
        if valid:
            item.consumed_at = timezone.now()
        item.save(update_fields=["attempts", "consumed_at"])
        return valid


@api_view(["POST"])
@permission_classes([AllowAny])
def register(request):
    email = str(request.data.get("email", "")).strip().lower()
    name = str(request.data.get("display_name", "")).strip()
    password = str(request.data.get("password", ""))
    if User.objects.filter(email=email).exists() or not name or len(name) > 80:
        return fail("请检查邮箱和姓名")
    try:
        password_validation.validate_password(password)
    except ValidationError as error:
        return fail("；".join(error.messages))
    with transaction.atomic():
        if not consume_code(email, "register", str(request.data.get("code", ""))):
            return fail("验证码无效或已过期")
        user = User.objects.create_user(email=email, password=password, display_name=name)
    return Response({"id": user.id, "email": user.email, "display_name": name, **token_pair(user)}, status=201)


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def sign_in(request):
    user = authenticate(request, email=str(request.data.get("email", "")).strip().lower(), password=request.data.get("password"))
    if not user:
        return fail("邮箱或密码错误", 400)
    return Response(token_pair(user))


@api_view(["POST"])
def sign_out(request):
    try:
        refresh = RefreshToken(str(request.data.get("refresh", "")))
        if str(refresh.get("user_id")) != str(request.user.pk):
            return fail("令牌不属于当前用户", 403)
        refresh.blacklist()
    except TokenError:
        return fail("刷新令牌无效", 400)
    return Response({"ok": True})


@api_view(["POST"])
@permission_classes([AllowAny])
def reset_password(request):
    email = str(request.data.get("email", "")).strip().lower()
    password = str(request.data.get("password", ""))
    if not User.objects.filter(email=email).exists():
        return fail("邮箱或密码无效")
    user = User.objects.get(email=email)
    try:
        password_validation.validate_password(password, user)
    except ValidationError as error:
        return fail("；".join(error.messages))
    with transaction.atomic():
        if not consume_code(email, "reset", str(request.data.get("code", ""))):
            return fail("验证码无效或已过期")
        user.set_password(password)
        user.save(update_fields=["password"])
    return Response({"ok": True})


@api_view(["GET"])
def me(request):
    u = request.user
    return Response({"id": u.id, "email": u.email, "display_name": u.display_name,
                     "can_create_course": u.can_create_course})


@api_view(["POST"])
def redeem_invite(request):
    raw = str(request.data.get("code", "")).strip()
    hashed = salted_hmac("teacher-invite", raw).hexdigest()
    with transaction.atomic():
        invite = TeacherInvite.objects.select_for_update().filter(code_hash=hashed).first()
        if not invite or invite.used_at or invite.expires_at <= timezone.now():
            return fail("邀请码无效或已过期")
        invite.used_by = request.user
        invite.used_at = timezone.now()
        invite.save(update_fields=["used_by", "used_at"])
        request.user.can_create_course = True
        request.user.save(update_fields=["can_create_course"])
    return Response({"ok": True})


@api_view(["GET", "POST"])
def courses(request):
    if request.method == "GET":
        qs = Course.objects.filter(memberships__user=request.user).distinct().order_by("-created_at")
        return Response([course_data(c, request.user) for c in qs])
    if not request.user.can_create_course:
        return fail("需要教师邀请码", 403)
    name = str(request.data.get("name", "")).strip()
    if not name or len(name) > 120:
        return fail("课程名不能为空且最多 120 字")
    icon = request.FILES.get("icon")
    if icon and (icon.size > 2 * 1024 * 1024 or Path(icon.name).suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp")):
        return fail("课程图标仅支持 2 MB 内的图片")
    with transaction.atomic():
        course = Course.objects.create(name=name, icon=icon or "", created_by=request.user)
        Membership.objects.create(course=course, user=request.user, role="teacher")
    return Response(course_data(course, request.user), status=201)


@api_view(["POST"])
def join_course(request):
    code = str(request.data.get("code", "")).strip().upper()
    course = Course.objects.filter(join_code=code).first()
    if not course:
        return fail("课程码无效")
    if member(request.user, course.id):
        return fail("你已加入这门课程")
    Membership.objects.create(course=course, user=request.user, role="student")
    return Response(course_data(course, request.user), status=201)


@api_view(["GET"])
def course_detail(request, course_id):
    if not member(request.user, course_id):
        return fail("无权访问课程", 403)
    return Response(course_data(get_object_or_404(Course, pk=course_id), request.user))


@api_view(["GET"])
def course_icon(request, course_id):
    if not member(request.user, course_id):
        return fail("无权查看课程", 403)
    course = get_object_or_404(Course, pk=course_id)
    if not course.icon or not course.icon.storage.exists(course.icon.name):
        return fail("图标不存在", 404)
    response = FileResponse(course.icon.open("rb"))
    response["Content-Type"] = mimetypes.guess_type(course.icon.name)[0] or "application/octet-stream"
    return response


@api_view(["POST"])
def reset_join_code(request, course_id):
    if not member(request.user, course_id, "teacher"):
        return fail("仅教师可重置课程码", 403)
    course = get_object_or_404(Course, pk=course_id)
    course.join_code = token_code()
    course.save(update_fields=["join_code"])
    return Response({"join_code": course.join_code})


@api_view(["GET"])
def members(request, course_id):
    if not member(request.user, course_id):
        return fail("无权查看成员", 403)
    rows = Membership.objects.filter(course_id=course_id).select_related("user").order_by("joined_at")
    teacher = member(request.user, course_id, 'teacher') is not None
    return Response([{"id": m.user_id, "name": m.user.display_name, "role": m.role,
                      **({'email': m.user.email} if teacher else {})} for m in rows])


def material_data(item, teacher=False, task=None):
    entry = getattr(item, 'knowledge_entry', None)
    status = entry.status if entry else 'pending'
    if task and task.status in ('queued', 'running', 'cancelled'):
        status = task.status
    elif status == 'pending' and not task:
        status = 'untracked'
    error = (task.error if task else '索引未完成，请任课教师重建') if status in ('failed', 'cancelled') else ''
    if not teacher and error:
        error = '知识索引未完成，请联系任课教师'
    return {'id': item.id, 'title': item.title, 'attachment': file_data(item.attachment),
            'created_at': item.created_at, 'index_status': status, 'index_error': error,
            'index_task': task_data(task) if teacher and task else None}


@api_view(["GET", "POST"])
def materials(request, course_id):
    m = member(request.user, course_id)
    if not m:
        return fail("无权访问课程", 403)
    course = get_object_or_404(Course, pk=course_id)
    if request.method == "GET":
        rows = list(course.materials.select_related('attachment', 'knowledge_entry').order_by('-created_at'))
        latest = {t.material_id: t for t in MaterialIndexTask.objects.filter(course=course).order_by('material_id', '-id').distinct('material_id')}
        return Response([material_data(item, m.role == 'teacher', latest.get(item.pk)) for item in rows])
    if m.role != "teacher":
        return fail("仅教师可上传资料", 403)
    upload = request.FILES.get("file")
    error = validate_file(upload)
    if error:
        return fail(error)
    title = str(request.data.get('title', '')).strip()[:200] or upload.name
    try:
        key = validate_key(request.data.get('request_key', uuid.uuid4().hex))
    except ValueError as exc:
        return fail(str(exc))
    digest = hashlib.sha256()
    for part in upload.chunks():
        digest.update(part)
    upload.seek(0)
    digest.update(str((title, upload.name)).encode())
    payload_hash = digest.hexdigest()
    stored = None
    try:
        with transaction.atomic():
            Course.objects.select_for_update().get(pk=course_id)
            if not member(request.user, course_id, 'teacher'):
                return fail('任课教师权限已撤销', 403)
            old = MaterialIndexTask.objects.filter(course=course, requested_by=request.user, request_key=key).select_related('material__attachment', 'material__knowledge_entry').first()
            if old:
                if old.payload_hash != payload_hash:
                    return fail('请求标识已用于其他内容，请使用新的请求标识', 409)
                return Response(material_data(old.material, True, old), status=202)
            stored = store_file(course, request.user, upload, 'material')
            item = Material.objects.create(course=course, title=title, attachment=stored)
            task = enqueue(item, request.user, key, payload_hash, request.request_id)
    except Exception:
        if stored:
            stored.file.delete(save=False)
        raise
    return Response(material_data(item, True, task), status=202)


@api_view(["GET"])
def download_file(request, file_id):
    f = authorized_file(request.user, file_id)
    if not f.file.storage.exists(f.file.name):
        return fail("文件不存在", 404)
    response = FileResponse(f.file.open("rb"), as_attachment=True, filename=f.original_name)
    response["Content-Type"] = mimetypes.guess_type(f.original_name)[0] or "application/octet-stream"
    response["Cache-Control"] = "no-store"
    return response
