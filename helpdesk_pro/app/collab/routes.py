# -*- coding: utf-8 -*-
"""
Collaboration (chat) routes.
AJAX-driven chat experience with conversations, direct messages, and attachments.
"""

import os
import re
import uuid
import time
import shutil
from datetime import datetime, timezone

from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    flash,
    current_app,
    send_from_directory,
    url_for,
)
from flask_login import login_required, current_user
from flask_babel import gettext as _
from sqlalchemy import and_, or_, func
from app.utils.files import secure_filename

from app import db, csrf
from app.models import (
    User,
    ChatConversation,
    ChatMembership,
    ChatMessage,
    ChatMessageRead,
    ChatFavorite,
    AssistantSession,
    AssistantDocument,
)
from app.assistant.routes import (
    _assistant_upload_folder,
    _extract_document_text,
    generate_assistant_reply,
)


collab_bp = Blueprint("collab", __name__, url_prefix="/collab")

_TYPING_TTL_SECONDS = 5
_typing_states = {}

_AI_ASSISTANT_USERNAME = "helpdesk-assistant"
_AI_ASSISTANT_EMAIL = "helpdesk-assistant@system.local"
_AI_SESSION_TITLE = "__collab_ai_session__"
_AI_MENTION_PATTERNS = [
    re.compile(r"@ai\b", re.IGNORECASE),
    re.compile(r"@ai\s+assistant\b", re.IGNORECASE),
    re.compile(r"@helpdesk-assistant\b", re.IGNORECASE),
]


def _get_ai_user(create=True):
    ai_user = User.query.filter_by(username=_AI_ASSISTANT_USERNAME).first()
    if ai_user or not create:
        return ai_user
    return _ensure_ai_user()


def _ensure_ai_user():
    ai_user = User.query.filter_by(username=_AI_ASSISTANT_USERNAME).first()
    if ai_user:
        return ai_user
    ai_user = User(
        username=_AI_ASSISTANT_USERNAME,
        email=_AI_ASSISTANT_EMAIL,
        full_name="AI Assistant",
        role="assistant",
        active=False,
    )
    ai_user.set_password(uuid.uuid4().hex)
    db.session.add(ai_user)
    db.session.commit()
    return ai_user


def _ensure_ai_direct_conversation(user):
    ai_user = _ensure_ai_user()
    conv_candidates = (
        ChatConversation.query.filter_by(is_direct=True)
        .join(ChatMembership)
        .filter(ChatMembership.user_id == user.id)
        .all()
    )
    for conv in conv_candidates:
        member_ids = {m.user_id for m in conv.members}
        if member_ids == {user.id, ai_user.id}:
            return conv
    conversation = ChatConversation(
        is_direct=True,
        created_by=user.id,
        is_bot=True,
        name=_("AI Assistant"),
    )
    db.session.add(conversation)
    db.session.flush()
    for uid in (user.id, ai_user.id):
        db.session.add(ChatMembership(conversation_id=conversation.id, user_id=uid))
    db.session.commit()
    return conversation


def _is_ai_conversation(conversation):
    if not conversation or not conversation.is_direct:
        return False
    ai_user = _get_ai_user(create=False)
    if not ai_user:
        return False
    member_ids = {m.user_id for m in conversation.members}
    return ai_user.id in member_ids


def _contains_ai_mention(body):
    if not body:
        return False
    return any(pattern.search(body) for pattern in _AI_MENTION_PATTERNS)


def _ensure_ai_session(user):
    session = AssistantSession.query.filter_by(user_id=user.id, title=_AI_SESSION_TITLE).first()
    if session:
        return session
    session = AssistantSession(user_id=user.id, title=_AI_SESSION_TITLE)
    db.session.add(session)
    db.session.commit()
    return session


def _ingest_assistant_document(session, source_path, original_filename, mimetype):
    if not source_path or not os.path.exists(source_path):
        return None
    upload_folder = _assistant_upload_folder()
    safe_name = secure_filename(original_filename or "attachment", allow_unicode=True) or "attachment"
    stored_name = f"{uuid.uuid4().hex}_{safe_name}"
    dest_path = os.path.join(upload_folder, stored_name)
    try:
        shutil.copy2(source_path, dest_path)
    except OSError:
        return None
    try:
        file_size = os.path.getsize(dest_path)
    except OSError:
        file_size = None
    extracted_text = _extract_document_text(dest_path, mimetype)
    status = "ready" if extracted_text else "uploaded"
    document = AssistantDocument(
        session_id=session.id,
        user_id=current_user.id,
        original_filename=original_filename or safe_name,
        stored_filename=stored_name,
        mimetype=mimetype,
        file_size=file_size,
        extracted_text=extracted_text,
        status=status,
    )
    db.session.add(document)
    return document


def _trigger_assistant_response(conversation, user, prompt_text, attachments=None):
    session = _ensure_ai_session(user)
    attachments = attachments or []
    for attachment in attachments:
        _ingest_assistant_document(
            session,
            attachment.get("path"),
            attachment.get("original"),
            attachment.get("mimetype"),
        )
    if attachments:
        db.session.flush()
        session = AssistantSession.query.get(session.id)

    prompt = (prompt_text or "").strip()
    if not prompt:
        if attachments:
            db.session.commit()
        return {"success": True}

    result = generate_assistant_reply(user, prompt, session=session, require_permission=False)
    if not result.get("success"):
        return result

    ai_user = _ensure_ai_user()
    reply_text = result.get("reply") or ""
    ai_message = ChatMessage(
        conversation_id=conversation.id,
        sender_id=ai_user.id,
        body=reply_text,
    )
    db.session.add(ai_message)
    db.session.flush()
    conversation.updated_at = datetime.utcnow()
    db.session.add(ChatMessageRead(message_id=ai_message.id, user_id=user.id))
    db.session.commit()
    return {"success": True}

def _chat_upload_folder():
    upload_folder = current_app.config.get("COLLAB_UPLOAD_FOLDER")
    if not upload_folder:
        upload_folder = os.path.join(current_app.instance_path, "chat_uploads")
        current_app.config["COLLAB_UPLOAD_FOLDER"] = upload_folder
    os.makedirs(upload_folder, exist_ok=True)
    return upload_folder


def _ensure_general_conversation():
    convo = ChatConversation.query.filter_by(is_direct=False).order_by(ChatConversation.id.asc()).first()
    if not convo:
        convo = ChatConversation(name=_("General Chat"), is_direct=False, created_by=None)
        db.session.add(convo)
        db.session.commit()
    return convo


def _ensure_membership(conversation_id, user_id):
    membership = ChatMembership.query.filter_by(conversation_id=conversation_id, user_id=user_id).first()
    if not membership:
        membership = ChatMembership(conversation_id=conversation_id, user_id=user_id)
        db.session.add(membership)
        db.session.commit()
    return membership


def _conversation_payload(conversation, user_id):
    last_message = (
        ChatMessage.query.filter_by(conversation_id=conversation.id)
        .order_by(ChatMessage.created_at.desc())
        .first()
    )
    unread_count = (
        db.session.query(ChatMessage.id)
        .outerjoin(ChatMessageRead, and_(ChatMessageRead.message_id == ChatMessage.id, ChatMessageRead.user_id == user_id))
        .filter(ChatMessage.conversation_id == conversation.id)
        .filter(ChatMessage.sender_id != user_id)
        .filter(ChatMessageRead.id.is_(None))
        .count()
    )
    label = conversation.name or _("Direct Chat")
    ai_user = _get_ai_user(create=False)
    is_ai = bool(getattr(conversation, "is_bot", False))
    if conversation.is_direct:
        other = (
            db.session.query(User)
            .join(ChatMembership, ChatMembership.user_id == User.id)
            .filter(ChatMembership.conversation_id == conversation.id)
            .filter(User.id != user_id)
            .first()
        )
        if other:
            label = other.full_name or other.username
            if ai_user and other.id == ai_user.id:
                label = _("AI Assistant")
                is_ai = True
    member_ids = {m.user_id for m in conversation.members}
    if conversation.created_by:
        can_delete = conversation.is_direct and conversation.created_by == user_id
    else:
        can_delete = conversation.is_direct and user_id in member_ids and len(member_ids) <= 2
    return {
        "id": conversation.id,
        "label": label,
        "is_direct": conversation.is_direct,
        "last_message": {
            "text": last_message.body if last_message else "",
            "time": last_message.created_at.strftime("%H:%M") if last_message else "",
        },
        "unread": unread_count,
        "can_delete": can_delete,
        "is_ai": is_ai,
    }


def _active_typers(conversation_id):
    now = time.time()
    states = _typing_states.get(conversation_id)
    if not states:
        return []
    active = []
    for user_id, ts in list(states.items()):
        if now - ts > _TYPING_TTL_SECONDS:
            del states[user_id]
            continue
        user = User.query.get(user_id)
        if not user or user_id == current_user.id:
            continue
        active.append({"id": user.id, "name": user.username})
    if not states:
        _typing_states.pop(conversation_id, None)
    return active

@collab_bp.route("/")
@login_required
def chat_home():
    general_convo = _ensure_general_conversation()
    _ensure_membership(general_convo.id, current_user.id)
    ai_user = _ensure_ai_user()

    conversations = (
        ChatConversation.query.join(ChatMembership)
        .filter(ChatMembership.user_id == current_user.id)
        .order_by(ChatConversation.is_direct.asc(), ChatConversation.updated_at.desc())
        .all()
    )
    convo_payloads = [_conversation_payload(conv, current_user.id) for conv in conversations]
    ai_conversation = next((conv for conv in conversations if getattr(conv, "is_bot", False)), None)

    users = (
        User.query.filter(User.id != current_user.id)
        .order_by(User.username.asc())
        .all()
    )
    users = sorted(users, key=lambda u: (u.id != ai_user.id, (u.username or "").lower()))
    favorites = {fav.favorite_user_id for fav in ChatFavorite.query.filter_by(user_id=current_user.id)}

    total_conversations = len(conversations)
    direct_conversations = sum(1 for conv in conversations if conv.is_direct)
    channel_conversations = max(total_conversations - direct_conversations, 0)
    unread_total = sum(payload.get("unread", 0) for payload in convo_payloads)
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    messages_today = (
        db.session.query(func.count(ChatMessage.id))
        .join(ChatConversation, ChatConversation.id == ChatMessage.conversation_id)
        .join(ChatMembership, and_(ChatMembership.conversation_id == ChatConversation.id, ChatMembership.user_id == current_user.id))
        .filter(ChatMessage.created_at >= today_start)
        .scalar()
        or 0
    )
    collab_stats = {
        "total": total_conversations,
        "direct": direct_conversations,
        "channels": channel_conversations,
        "unread": unread_total,
        "today": messages_today,
        "favorites": len(favorites),
    }

    return render_template(
        "collab/chat.html",
        general_conversation=general_convo,
        ai_conversation=ai_conversation,
        ai_user=ai_user,
        conversations=convo_payloads,
        users=users,
        favorites=favorites,
        collab_stats=collab_stats,
        ai_aliases=["@AI", "@AI Assistant", "@helpdesk-assistant"],
    )


@collab_bp.route("/api/conversations", methods=["GET"])
@login_required
def api_conversations():
    general_convo = _ensure_general_conversation()
    _ensure_membership(general_convo.id, current_user.id)
    conversations = (
        ChatConversation.query.join(ChatMembership)
        .filter(ChatMembership.user_id == current_user.id)
        .order_by(ChatConversation.is_direct.asc(), ChatConversation.updated_at.desc())
        .all()
    )
    return jsonify([_conversation_payload(conv, current_user.id) for conv in conversations])


@collab_bp.route("/api/conversations/direct", methods=["POST"])
@login_required
def api_direct_conversation():
    data = request.get_json(silent=True) or {}
    target_id = data.get("user_id")
    try:
        target_id = int(target_id)
    except (TypeError, ValueError):
        target_id = None
    if not target_id or target_id == current_user.id:
        return jsonify({"success": False, "message": _("Invalid user.")}), 400

    target = User.query.get(target_id)
    if not target:
        return jsonify({"success": False, "message": _("User not found.")}), 404

    conv_candidates = (
        ChatConversation.query.filter_by(is_direct=True)
        .join(ChatMembership)
        .filter(ChatMembership.user_id == current_user.id)
        .all()
    )
    conversation = None
    for conv in conv_candidates:
        member_ids = {m.user_id for m in conv.members}
        if member_ids == {current_user.id, target_id}:
            conversation = conv
            break

    user_ids = sorted([current_user.id, target_id])
    if not conversation:
        conversation = ChatConversation(is_direct=True, created_by=current_user.id)
        db.session.add(conversation)
        db.session.flush()
        for uid in user_ids:
            db.session.add(ChatMembership(conversation_id=conversation.id, user_id=uid))
        db.session.commit()
    else:
        for uid in user_ids:
            _ensure_membership(conversation.id, uid)
    return jsonify({"success": True, "conversation": _conversation_payload(conversation, current_user.id)})


def _serialize_message(message):
    attachment_info = None
    if message.attachment_filename:
        url = url_for("collab.download_attachment", filename=message.attachment_filename)
        mimetype = message.attachment_mimetype or ""
        is_image = mimetype.startswith("image/")
        youtube_thumb = None
        youtube_id = None
        if not is_image and message.attachment_original:
            match = re.search(r"youtu(?:\.be|be\.com)/(?:watch\?v=)?([\w-]{11})", message.attachment_original)
            if match:
                youtube_id = match.group(1)
                youtube_thumb = f"https://img.youtube.com/vi/{youtube_id}/hqdefault.jpg"
        attachment_info = {
            "original": message.attachment_original,
            "url": url,
            "mimetype": mimetype,
            "is_image": is_image,
            "youtube_thumb": youtube_thumb,
            "youtube_id": youtube_id,
        }

    created_at = message.created_at
    if created_at:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        created_at_iso = created_at.isoformat()
    else:
        created_at_iso = None

    ai_user = _get_ai_user(create=False)

    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "sender_id": message.sender_id,
        "sender_name": User.query.get(message.sender_id).username if message.sender_id else _("Unknown"),
        "body": message.body or "",
        "created_at": created_at_iso,
        "isMine": message.sender_id == current_user.id,
        "attachment": attachment_info,
        "isAssistant": bool(ai_user and message.sender_id == ai_user.id),
    }


@collab_bp.route("/api/messages/<int:conversation_id>", methods=["GET"])
@login_required
def api_get_messages(conversation_id):
    convo = ChatConversation.query.get_or_404(conversation_id)
    membership = ChatMembership.query.filter_by(conversation_id=conversation_id, user_id=current_user.id).first()
    if not membership:
        return jsonify({"success": False, "message": _("You are not part of this conversation.")}), 403

    limit = min(int(request.args.get("limit", 100)), 200)
    messages = (
        ChatMessage.query.filter_by(conversation_id=conversation_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
        .all()
    )
    messages = list(reversed(messages))

    # mark as read
    for msg in messages:
        if msg.sender_id == current_user.id:
            continue
        existing = ChatMessageRead.query.filter_by(message_id=msg.id, user_id=current_user.id).first()
        if not existing:
            db.session.add(ChatMessageRead(message_id=msg.id, user_id=current_user.id))
    db.session.commit()

    typing_users = _active_typers(conversation_id)

    return jsonify(
        {
            "success": True,
            "messages": [_serialize_message(m) for m in messages],
            "typing_users": typing_users,
        }
    )


@collab_bp.route("/api/messages/<int:conversation_id>", methods=["POST"])
@login_required
def api_post_message(conversation_id):
    convo = ChatConversation.query.get_or_404(conversation_id)
    membership = ChatMembership.query.filter_by(conversation_id=conversation_id, user_id=current_user.id).first()
    if not membership:
        return jsonify({"success": False, "message": _("You are not part of this conversation.")}), 403

    body = ""
    file = None
    content_type = request.content_type or ""
    if "multipart/form-data" in content_type:
        body = (request.form.get("body") or "").strip()
        file = request.files.get("attachment")
    elif content_type.startswith("application/json"):
        data = request.get_json(silent=True) or {}
        body = (data.get("body") or "").strip()
    else:
        body = (request.values.get("body") or "").strip()
    if not body and (not file or not getattr(file, 'filename', '')):
        return jsonify({"success": False, "message": _("Message cannot be empty.")}), 400

    attachment_filename = None
    attachment_original = None
    attachment_mimetype = None
    attachment_path = None

    if file and file.filename:
        upload_folder = _chat_upload_folder()
        attachment_original = file.filename
        safe_name = f"{uuid.uuid4().hex}_{secure_filename(attachment_original, allow_unicode=True)}"
        path = os.path.join(upload_folder, safe_name)
        file.save(path)
        attachment_filename = safe_name
        attachment_mimetype = file.mimetype
        attachment_path = path

    message = ChatMessage(
        conversation_id=conversation_id,
        sender_id=current_user.id,
        body=body,
        attachment_filename=attachment_filename,
        attachment_original=attachment_original,
        attachment_mimetype=attachment_mimetype,
    )
    db.session.add(message)
    db.session.flush()
    convo.updated_at = datetime.utcnow()
    db.session.add(ChatMessageRead(message_id=message.id, user_id=current_user.id))
    db.session.commit()
    typer_state = _typing_states.get(conversation_id)
    if typer_state and current_user.id in typer_state:
        typer_state.pop(current_user.id, None)
        if not typer_state:
            _typing_states.pop(conversation_id, None)
    assistant_error = None
    assistant_triggered = False
    is_ai_convo = _is_ai_conversation(convo)
    mention_triggered = _contains_ai_mention(body)
    prompt_text = (body or "").strip()
    attachments_payload = []
    if attachment_path:
        attachments_payload.append(
            {
                "path": attachment_path,
                "original": attachment_original,
                "mimetype": attachment_mimetype,
            }
        )

    if is_ai_convo and attachments_payload and not prompt_text:
        _trigger_assistant_response(convo, current_user, "", attachments=attachments_payload)

    if prompt_text and (is_ai_convo or mention_triggered):
        assistant_triggered = True
        result = _trigger_assistant_response(
            convo,
            current_user,
            prompt_text,
            attachments=attachments_payload if prompt_text else None,
        )
        if not result.get("success"):
            assistant_error = result.get("message") or _("Assistant was unable to reply.")

    response_payload = {"success": True, "message": _serialize_message(message)}
    if assistant_triggered:
        response_payload["assistant_invoked"] = True
    if assistant_error:
        response_payload["assistant_error"] = assistant_error
    return jsonify(response_payload)


@collab_bp.route("/api/conversations/<int:conversation_id>/typing", methods=["POST"])
@login_required
def api_conversation_typing(conversation_id):
    ChatConversation.query.get_or_404(conversation_id)
    membership = ChatMembership.query.filter_by(conversation_id=conversation_id, user_id=current_user.id).first()
    if not membership:
        return jsonify({"success": False, "message": _("You are not part of this conversation.")}), 403
    state = _typing_states.setdefault(conversation_id, {})
    state[current_user.id] = time.time()
    return jsonify({"success": True})


@collab_bp.route("/api/conversations/<int:conversation_id>/purge", methods=["POST"])
@login_required
def api_purge_conversation(conversation_id):
    if current_user.role != "admin":
        return jsonify({"success": False, "message": _("You are not authorized to do this.")}), 403

    general_convo = _ensure_general_conversation()
    if conversation_id != general_convo.id:
        return jsonify({"success": False, "message": _("Only the general chat can be purged.")}), 400

    convo = ChatConversation.query.get_or_404(conversation_id)
    _ensure_membership(conversation_id, current_user.id)

    messages = ChatMessage.query.filter_by(conversation_id=conversation_id).all()
    upload_folder = _chat_upload_folder()
    removed = 0
    for message in messages:
        if message.attachment_filename:
            path = message.attachment_path(upload_folder)
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        db.session.delete(message)
        removed += 1
    convo.updated_at = datetime.utcnow()
    db.session.commit()
    _typing_states.pop(conversation_id, None)
    return jsonify({"success": True, "removed": removed})

@collab_bp.route("/api/favorites/<int:target_id>", methods=["POST"])
@login_required
def api_toggle_favorite(target_id):
    if target_id == current_user.id:
        return jsonify({"success": False, "message": _("Cannot favorite yourself.")}), 400
    target = User.query.get(target_id)
    if not target:
        return jsonify({"success": False, "message": _("User not found.")}), 404
    fav = ChatFavorite.query.filter_by(user_id=current_user.id, favorite_user_id=target_id).first()
    if fav:
        db.session.delete(fav)
        db.session.commit()
        return jsonify({"success": True, "favorited": False})
    fav = ChatFavorite(user_id=current_user.id, favorite_user_id=target_id)
    db.session.add(fav)
    db.session.commit()
    return jsonify({"success": True, "favorited": True})


@collab_bp.route("/api/unread-count", methods=["GET"])
@login_required
def api_unread_count():
    general_convo = _ensure_general_conversation()
    _ensure_membership(general_convo.id, current_user.id)
    unread_count = (
        db.session.query(ChatMessage.id)
        .join(ChatConversation, ChatConversation.id == ChatMessage.conversation_id)
        .join(ChatMembership, and_(ChatMembership.conversation_id == ChatConversation.id, ChatMembership.user_id == current_user.id))
        .outerjoin(ChatMessageRead, and_(ChatMessageRead.message_id == ChatMessage.id, ChatMessageRead.user_id == current_user.id))
        .filter(ChatMessage.sender_id != current_user.id)
        .filter(ChatMessageRead.id.is_(None))
        .count()
    )
    return jsonify({"unread": unread_count})


@collab_bp.route("/attachments/<path:filename>")
@login_required
def download_attachment(filename):
    message = ChatMessage.query.filter_by(attachment_filename=filename).first_or_404()
    membership = ChatMembership.query.filter_by(conversation_id=message.conversation_id, user_id=current_user.id).first()
    if not membership:
        flash(_("You do not have access to this file."), "warning")
        return jsonify({"success": False}), 403
    upload_folder = _chat_upload_folder()
    return send_from_directory(upload_folder, filename, as_attachment=True)
@collab_bp.route("/api/conversations/<int:conversation_id>/delete", methods=["POST"])
@login_required
def api_delete_conversation(conversation_id):
    convo = ChatConversation.query.get_or_404(conversation_id)
    if not convo.is_direct:
        return jsonify({"success": False, "message": _("You cannot delete this conversation.")}), 403
    member_ids = {m.user_id for m in convo.members}
    can_delete = False
    if convo.created_by:
        can_delete = convo.created_by == current_user.id
    else:
        # legacy conversations without creator info: allow if exactly two members and user is one of them
        can_delete = current_user.id in member_ids and len(member_ids) <= 2

    if not can_delete:
        return jsonify({"success": False, "message": _("You cannot delete this conversation.")}), 403

    db.session.delete(convo)
    db.session.commit()
    return jsonify({"success": True})
