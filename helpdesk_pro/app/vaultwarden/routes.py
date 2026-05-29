import json
from datetime import datetime
from math import ceil
from typing import Optional
from urllib.parse import urlencode

from flask import (
    Blueprint,
    abort,
    current_app,
    flash as flask_flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_babel import gettext as _
from flask_login import current_user, login_required
from sqlalchemy import asc, cast, literal, or_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import joinedload

from app import db
from app.models import (
    VaultAuditLog,
    VaultCollection,
    VaultCollectionAccess,
    VaultFolder,
    VaultItem,
    VaultOrganization,
    VaultOrganizationKeyShare,
    VaultOrganizationMembership,
    VaultUserProfile,
)
from app.vaultwarden.forms import VaultFolderForm, VaultItemForm

vaultwarden_bp = Blueprint("vaultwarden", __name__, url_prefix="/vaultwarden")

SORT_OPTIONS = {
    "updated_at": VaultItem.updated_at.desc(),
    "created_at": VaultItem.created_at.desc(),
    "name": asc(VaultItem.name),
    "last_accessed": VaultItem.last_accessed.desc(),
}
COLLECTION_MODIFY_ACCESS_LEVELS = {"edit", "manage"}
LEGACY_VAULT_SALT = "helpdesk-pro-vaultwarden"


class VaultItemAccessError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _redirect_back(default: str = "vaultwarden.index"):
    target = request.referrer
    if target:
        return redirect(target)
    return redirect(url_for(default))


def _collection_access_level(collection_id: Optional[int]) -> Optional[str]:
    if not collection_id:
        return None
    access = VaultCollectionAccess.query.filter_by(
        collection_id=collection_id,
        user_id=current_user.id,
    ).first()
    if not access:
        return None
    return access.access_level


def _item_for_user(
    item_id: int,
    *,
    allow_trashed: bool = False,
    require_modify_access: bool = False,
) -> VaultItem:
    query = VaultItem.query.filter_by(id=item_id)
    if not allow_trashed:
        query = query.filter(VaultItem.trashed.is_(False))
    item = query.first()
    if not item:
        raise VaultItemAccessError("missing")
    if item.owner_id == current_user.id:
        return item
    access_level = _collection_access_level(item.collection_id)
    if not access_level:
        raise VaultItemAccessError("collection_no_access")
    if require_modify_access and access_level not in COLLECTION_MODIFY_ACCESS_LEVELS:
        raise VaultItemAccessError("collection_insufficient_access")
    return item


def _vault_alert_redirect(message: str):
    session["vault_alert_message"] = message
    return _redirect_back()


def _parse_tags(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [tag.strip() for tag in value.split(",") if tag.strip()]


def _visible_folder_query(
    *,
    organization_ids: Optional[set[int]] = None,
    accessible_collection_ids: Optional[set[int]] = None,
):
    query = VaultFolder.query
    clauses = [VaultFolder.user_id == current_user.id]
    if organization_ids:
        clauses.append(VaultFolder.organization_id.in_(organization_ids))
    if accessible_collection_ids:
        clauses.append(VaultFolder.collection_id.in_(accessible_collection_ids))
    if len(clauses) == 1:
        return query.filter(clauses[0])
    return query.filter(or_(*clauses))


def _build_folder_choices(
    *,
    organization_ids: Optional[set[int]] = None,
    accessible_collection_ids: Optional[set[int]] = None,
):
    folders = (
        _visible_folder_query(
            organization_ids=organization_ids,
            accessible_collection_ids=accessible_collection_ids,
        )
        .order_by(VaultFolder.name)
        .all()
    )
    choices = [(0, _("- No folder -"))]
    for folder in folders:
        choices.append((folder.id, folder.name))
    return choices


def _record(action: str, *, item: Optional[VaultItem] = None, metadata: Optional[dict] = None):
    VaultAuditLog.record(
        action=action,
        user_id=current_user.id,
        item_id=getattr(item, "id", None),
        organization_id=getattr(item, "organization_id", None),
        details=metadata or {},
    )


def _safe_json_payload(payload: str) -> Optional[dict]:
    try:
        return json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return None


def _vault_profile_payload(profile: Optional[VaultUserProfile]) -> dict:
    if not profile:
        return {"configured": False, "reset_required": False}
    configured = bool(
        not profile.reset_required
        and profile.kdf_salt
        and profile.verification_blob
    )
    return {
        "configured": configured,
        "reset_required": profile.reset_required,
        "kdf_algorithm": profile.kdf_algorithm,
        "kdf_salt": profile.kdf_salt,
        "verification_blob": profile.verification_blob,
        "version": profile.version,
    }


def _apply_filters(query, *, show_trash: bool, favorites_only: bool, folder_id: Optional[int], tag: Optional[str], item_type: Optional[str], search: str):
    if not show_trash:
        query = query.filter(VaultItem.trashed.is_(False))
    if favorites_only:
        query = query.filter(VaultItem.favorite.is_(True))
    if folder_id:
        query = query.filter(VaultItem.folder_id == folder_id)
    if tag:
        serialized = json.dumps([tag])
        query = query.filter(
            cast(VaultItem.tags, JSONB).op("@>")(
                cast(literal(serialized), JSONB)
            )
        )
    if item_type:
        query = query.filter(VaultItem.item_type == item_type)
    if search:
        search_term = f"%{search}%"
        query = query.filter(VaultItem.name.ilike(search_term))
    return query


def _load_user_organization_memberships():
    memberships = (
        VaultOrganizationMembership.query
        .filter_by(user_id=current_user.id)
        .options(
            joinedload(VaultOrganizationMembership.organization)
            .joinedload(VaultOrganization.collections)
        )
        .all()
    )
    organizations = {}
    for membership in memberships:
        org = membership.organization
        if org:
            organizations[org.id] = org
    return memberships, organizations


def _build_org_choices(organizations: dict[int, VaultOrganization]):
    choices = [(0, _("Personal vault"))]
    sorted_orgs = sorted(organizations.values(), key=lambda org: (org.name or "").lower())
    for org in sorted_orgs:
        choices.append((org.id, org.name))
    return choices


def _build_collection_options(collections: list[VaultCollection]):
    choices = [(0, _("No collection"))]
    options = [{"id": 0, "label": _("No collection"), "org_id": 0}]
    sorted_collections = sorted(collections, key=lambda coll: ((coll.organization.name or "").lower(), (coll.name or "").lower()))
    for collection in sorted_collections:
        label = f"{collection.organization.name} · {collection.name}"
        choices.append((collection.id, label))
        options.append({"id": collection.id, "label": label, "org_id": collection.organization_id})
    return choices, options


def _get_user_collection_access_data(memberships: Optional[list[VaultOrganizationMembership]] = None):
    entries = (
        VaultCollectionAccess.query
        .options(joinedload(VaultCollectionAccess.collection).joinedload(VaultCollection.organization))
        .filter_by(user_id=current_user.id)
        .all()
    )
    collections = []
    collection_ids = set()
    for entry in entries:
        if not entry.collection or entry.collection_id in collection_ids:
            continue
        collections.append(entry.collection)
        collection_ids.add(entry.collection_id)
    if memberships:
        for membership in memberships:
            org = membership.organization
            if not org:
                continue
            for collection in org.collections:
                if collection.id not in collection_ids:
                    collections.append(collection)
                    collection_ids.add(collection.id)
    return entries, collections, collection_ids


@vaultwarden_bp.route("/")
@login_required
def index():
    show_trash = request.args.get("trash") == "1"
    favorites_only = request.args.get("favorites") == "1"
    folder_filter = request.args.get("folder")
    tag = request.args.get("tag")
    item_type = request.args.get("type")
    search = (request.args.get("q") or "").strip()
    sort_key = request.args.get("sort", "updated_at")
    page = request.args.get("page", "1")

    try:
        page = max(1, int(page))
    except ValueError:
        page = 1

    folder_id = None
    if folder_filter and folder_filter.isdigit():
        folder_id = int(folder_filter)

    organization_memberships, organizations = _load_user_organization_memberships()
    organization_memberships.sort(key=lambda membership: (membership.organization.name or "").lower() if membership.organization else "")
    organization_ids = set(organizations.keys())
    collection_access_entries, raw_collections, shared_collection_ids = _get_user_collection_access_data(organization_memberships)
    collection_access_map = {
        entry.collection_id: entry.access_level
        for entry in collection_access_entries
        if entry.collection_id
    }
    collections = sorted(
        raw_collections,
        key=lambda coll: coll.created_at or datetime.utcnow(),
        reverse=True,
    )
    collections_by_org: dict[int, list[VaultCollection]] = {}
    for collection in collections:
        collections_by_org.setdefault(collection.organization_id, []).append(collection)
    base_filter = VaultItem.owner_id == current_user.id
    if shared_collection_ids:
        base_filter = or_(base_filter, VaultItem.collection_id.in_(shared_collection_ids))
    query = VaultItem.query.options(joinedload(VaultItem.folder), joinedload(VaultItem.owner)).filter(base_filter)
    query = _apply_filters(
        query,
        show_trash=show_trash,
        favorites_only=favorites_only,
        folder_id=folder_id,
        tag=tag,
        item_type=item_type,
        search=search,
    )

    order_clause = SORT_OPTIONS.get(sort_key, VaultItem.updated_at.desc())
    per_page = 30
    total_owner_items = query.with_entities(db.func.count(VaultItem.id)).scalar() or 0
    items = (
        query.order_by(order_clause)
        .limit(per_page)
        .offset((page - 1) * per_page)
        .all()
    )
    total_pages = ceil(total_owner_items / per_page) if per_page else 1

    total_items = VaultItem.query.filter_by(owner_id=current_user.id).count()
    favorites_count = VaultItem.query.filter_by(owner_id=current_user.id, favorite=True).count()
    trashed_count = VaultItem.query.filter_by(owner_id=current_user.id, trashed=True).count()
    folders = (
        _visible_folder_query(
            organization_ids=organization_ids,
            accessible_collection_ids=shared_collection_ids,
        )
        .order_by(VaultFolder.name)
        .all()
    )
    folder_count = len(folders)

    org_choices = _build_org_choices(organizations)
    collection_choices, collection_options = _build_collection_options(collections)

    vault_stats = {
        "total": total_items,
        "favorites": favorites_count,
        "trashed": trashed_count,
        "folders": folder_count,
        "organizations": len(organization_ids),
        "collections": len(collections),
    }

    available_tags = sorted({tag for item in items for tag in item.tag_list})

    recent_activity = (
        VaultAuditLog.query
        .filter(VaultAuditLog.user_id == current_user.id)
        .order_by(VaultAuditLog.created_at.desc())
        .limit(6)
        .all()
    )
    vault_profile = VaultUserProfile.query.filter_by(user_id=current_user.id).first()
    personal_item_count = VaultItem.query.filter_by(
        owner_id=current_user.id,
        collection_id=None,
    ).count()
    vault_setup_sample_blob = None
    if personal_item_count and not vault_profile:
        sample_item = (
            VaultItem.query
            .filter_by(owner_id=current_user.id, collection_id=None)
            .order_by(VaultItem.created_at.asc())
            .first()
        )
        vault_setup_sample_blob = sample_item.encrypted_blob if sample_item else None

    item_form = VaultItemForm()
    item_form.folder_id.choices = _build_folder_choices(
        organization_ids=organization_ids,
        accessible_collection_ids=shared_collection_ids,
    )
    item_form.organization_id.choices = org_choices
    item_form.collection_id.choices = collection_choices
    item_form.organization_id.data = item_form.organization_id.data or 0
    item_form.collection_id.data = item_form.collection_id.data or 0
    folder_form = VaultFolderForm()
    folder_form.organization_id.choices = org_choices
    folder_form.collection_id.choices = collection_choices

    pagination = {
        "current": page,
        "per_page": per_page,
        "total_items": total_owner_items,
        "total_pages": total_pages,
    }

    filters = {
        "show_trash": show_trash,
        "favorites": favorites_only,
        "search": search,
        "folder": folder_id or 0,
        "tag": tag,
        "item_type": item_type,
        "sort": sort_key,
    }

    query_params = {}
    if show_trash:
        query_params["trash"] = "1"
    if favorites_only:
        query_params["favorites"] = "1"
    if filters["search"]:
        query_params["q"] = filters["search"]
    if filters["folder"]:
        query_params["folder"] = filters["folder"]
    if filters["tag"]:
        query_params["tag"] = filters["tag"]
    if filters["item_type"]:
        query_params["type"] = filters["item_type"]
    filters_query = f"&{urlencode(query_params)}" if query_params else ""
    vault_alert_message = session.pop("vault_alert_message", None)
    return render_template(
        "vaultwarden/index.html",
        items=items,
        item_form=item_form,
        folder_form=folder_form,
        vault_stats=vault_stats,
        filters=filters,
        available_tags=available_tags,
        organization_memberships=organization_memberships,
        collections=collections,
        collections_by_org=collections_by_org,
        collection_options=collection_options,
        folders=folders,
        recent_activity=recent_activity,
        pagination=pagination,
        filters_query=filters_query,
        shared_collection_ids=shared_collection_ids,
        collection_access_map=collection_access_map,
        modify_access_levels=sorted(COLLECTION_MODIFY_ACCESS_LEVELS),
        vault_alert_message=vault_alert_message,
        vault_profile=_vault_profile_payload(vault_profile),
        vault_setup_salt=LEGACY_VAULT_SALT if personal_item_count and not vault_profile else None,
        vault_setup_sample_blob=vault_setup_sample_blob,
    )


@vaultwarden_bp.route("/items/create", methods=["POST"])
@login_required
def create_item():
    organization_memberships, organizations = _load_user_organization_memberships()
    organization_ids = set(organizations.keys())
    org_choices = _build_org_choices(organizations)
    collection_entries, accessible_collections, accessible_collection_ids = _get_user_collection_access_data(organization_memberships)
    form = VaultItemForm()
    form.folder_id.choices = _build_folder_choices(
        organization_ids=organization_ids,
        accessible_collection_ids=accessible_collection_ids,
    )
    collection_choices, collection_options = _build_collection_options(accessible_collections)
    collection_map = {collection.id: collection for collection in accessible_collections}
    form.organization_id.choices = org_choices
    form.collection_id.choices = collection_choices

    if not form.validate_on_submit():
        flask_flash(_("Vault item cannot be created. Please check the highlighted fields."), "danger")
        current_app.logger.debug("Vault item validation failed: %s", form.errors)
        return _redirect_back()

    encrypted_payload = _safe_json_payload(form.encrypted_blob.data)
    if not encrypted_payload:
        flask_flash(_("Encrypted payload is required and must be valid JSON."), "danger")
        return _redirect_back()

    metadata_payload = _safe_json_payload(form.metadata_blob.data) or {}
    tags = _parse_tags(form.tags.data)

    folder = None
    if form.folder_id.data and form.folder_id.data > 0:
        folder = (
            _visible_folder_query(
                organization_ids=organization_ids,
                accessible_collection_ids=accessible_collection_ids,
            )
            .filter_by(id=form.folder_id.data)
            .first()
        )
        if not folder:
            flask_flash(_("Selected folder was not found."), "danger")
            return _redirect_back()

    selected_org = None
    if form.organization_id.data and form.organization_id.data > 0:
        selected_org = organizations.get(form.organization_id.data)
        if not selected_org:
            flask_flash(_("Selected organization is not available."), "danger")
            return _redirect_back()

    selected_collection = None
    if form.collection_id.data and form.collection_id.data > 0:
        selected_collection = collection_map.get(form.collection_id.data)
        if not selected_collection:
            flask_flash(_("Selected collection is not available."), "danger")
            return _redirect_back()
        if selected_collection.organization_id not in organizations:
            flask_flash(_("Selected collection belongs to an organization you are not a member of."), "danger")
            return _redirect_back()
        if selected_collection.id not in accessible_collection_ids:
            flask_flash(_("You do not have access to the selected collection."), "danger")
            return _redirect_back()
        if not selected_org:
            selected_org = selected_collection.organization

    item = VaultItem(
        owner_id=current_user.id,
        name=form.name.data.strip(),
        item_type=form.item_type.data,
        folder=folder,
        organization=selected_org,
        collection=selected_collection,
        tags=tags,
        encrypted_blob=encrypted_payload,
        metadata_blob=metadata_payload,
    )
    if form.favorite.data:
        item.favorite = True

    db.session.add(item)
    _record("vault_item_create", item=item, metadata={"type": item.item_type})
    db.session.commit()

    flask_flash(_("Encrypted vault item saved."), "success")
    return redirect(url_for("vaultwarden.index"))


@vaultwarden_bp.route("/profile", methods=["POST"])
@login_required
def save_vault_profile():
    existing = VaultUserProfile.query.filter_by(user_id=current_user.id).first()
    if existing and not existing.reset_required:
        return jsonify({"error": _("Vault profile is already configured.")}), 409

    payload = request.get_json(silent=True) or {}
    kdf_salt = (payload.get("kdf_salt") or "").strip()
    verification_blob = payload.get("verification_blob")
    if not kdf_salt or not isinstance(verification_blob, dict):
        return jsonify({"error": _("Vault verification data is incomplete.")}), 400
    if not verification_blob.get("iv") or not verification_blob.get("ciphertext"):
        return jsonify({"error": _("Vault verification blob is invalid.")}), 400

    if existing:
        profile = existing
        profile.kdf_salt = kdf_salt
        profile.verification_blob = verification_blob
        profile.reset_required = False
        profile.reset_at = None
        profile.reset_by_user_id = None
        profile.version = (profile.version or 1) + 1
        action = "vault_profile_recreate"
    else:
        profile = VaultUserProfile(
            user_id=current_user.id,
            kdf_salt=kdf_salt,
            verification_blob=verification_blob,
        )
        db.session.add(profile)
        action = "vault_profile_create"
    _record(action)
    db.session.commit()
    return jsonify({"profile": _vault_profile_payload(profile)}), 201


@vaultwarden_bp.route("/folders/create", methods=["POST"])
@login_required
def create_folder():
    organization_memberships, organizations = _load_user_organization_memberships()
    org_choices = _build_org_choices(organizations)
    _collection_entries, accessible_collections, _shared_collection_ids = _get_user_collection_access_data(organization_memberships)
    collection_choices, _collection_options = _build_collection_options(accessible_collections)
    collection_map = {collection.id: collection for collection in accessible_collections}
    form = VaultFolderForm()
    form.organization_id.choices = org_choices
    form.collection_id.choices = collection_choices
    if not form.validate_on_submit():
        flask_flash(_("Folder name cannot be empty."), "danger")
        return _redirect_back()

    selected_org = None
    if form.organization_id.data and form.organization_id.data > 0:
        selected_org = organizations.get(form.organization_id.data)
        if not selected_org:
            flask_flash(_("Selected organization not found."), "danger")
            return _redirect_back()

    selected_collection = None
    if form.collection_id.data and form.collection_id.data > 0:
        selected_collection = collection_map.get(form.collection_id.data)
        if not selected_collection:
            flask_flash(_("Selected collection not found."), "danger")
            return _redirect_back()
        if selected_org and selected_collection.organization_id != selected_org.id:
            flask_flash(
                _("Collection %(name)s is not part of %(org)s.", name=selected_collection.name, org=selected_org.name),
                "danger",
            )
            return _redirect_back()
        if not selected_org:
            selected_org = selected_collection.organization

    folder = VaultFolder(
        name=form.name.data.strip(),
        user_id=current_user.id,
        organization=selected_org,
        collection=selected_collection,
    )
    db.session.add(folder)
    _record("vault_folder_create", metadata={"folder": folder.name})
    db.session.commit()

    flask_flash(_("Folder %(name)s added.", name=folder.name), "success")
    return _redirect_back()


@vaultwarden_bp.route("/folders/<int:folder_id>/delete", methods=["POST"])
@login_required
def delete_folder(folder_id: int):
    folder = VaultFolder.query.filter_by(id=folder_id, user_id=current_user.id).first()
    if not folder:
        flask_flash(_("Folder not found."), "warning")
        return _redirect_back()
    db.session.delete(folder)
    _record("vault_folder_delete", metadata={"folder": folder.name})
    db.session.commit()
    flask_flash(_("Folder %(name)s removed.", name=folder.name), "success")
    return _redirect_back()


@vaultwarden_bp.route("/items/<int:item_id>/favorite", methods=["POST"])
@login_required
def toggle_favorite(item_id: int):
    try:
        item = _item_for_user(item_id, allow_trashed=True, require_modify_access=True)
    except VaultItemAccessError as exc:
        if exc.reason == "missing":
            abort(404)
        abort(404)
    item.favorite = not item.favorite
    _record("vault_item_favorite", item=item, metadata={"favorite": item.favorite})
    db.session.commit()
    flask_flash(
        _("Removed from favorites." if not item.favorite else "Marked as favorite."),
        "success",
    )
    return _redirect_back()


@vaultwarden_bp.route("/items/<int:item_id>/trash", methods=["POST"])
@login_required
def move_to_trash(item_id: int):
    try:
        item = _item_for_user(item_id, require_modify_access=True)
    except VaultItemAccessError as exc:
        if exc.reason == "missing":
            abort(404)
        return _vault_alert_redirect(_("You cannot delete this item."))
    if item.trashed:
        flask_flash(_("Item already in trash."), "info")
        return _redirect_back()
    item.trashed = True
    _record("vault_item_trash", item=item)
    db.session.commit()
    flask_flash(_("Item %(name)s moved to trash.", name=item.name), "warning")
    return _redirect_back()


@vaultwarden_bp.route("/items/<int:item_id>/restore", methods=["POST"])
@login_required
def restore_item(item_id: int):
    try:
        item = _item_for_user(item_id, allow_trashed=True, require_modify_access=True)
    except VaultItemAccessError as exc:
        if exc.reason == "missing":
            abort(404)
        return _vault_alert_redirect(_("You cannot delete this item."))
    if not item.trashed:
        flask_flash(_("Item is not trashed."), "info")
        return _redirect_back()
    item.trashed = False
    _record("vault_item_restore", item=item)
    db.session.commit()
    flask_flash(_("Item %(name)s restored.", name=item.name), "success")
    return _redirect_back()


@vaultwarden_bp.route("/items/<int:item_id>/purge", methods=["POST"])
@login_required
def purge_item(item_id: int):
    try:
        item = _item_for_user(item_id, allow_trashed=True, require_modify_access=True)
    except VaultItemAccessError as exc:
        if exc.reason == "missing":
            abort(404)
        return _vault_alert_redirect(_("You cannot delete this item."))
    if not item.trashed:
        flask_flash(_("Item must be trashed before it can be deleted permanently."), "danger")
        return _redirect_back()
    _record("vault_item_delete", item=item)
    VaultAuditLog.query.filter_by(item_id=item.id).update({VaultAuditLog.item_id: None})
    db.session.delete(item)
    db.session.commit()
    flask_flash(_("Item %(name)s permanently deleted.", name=item.name), "success")
    return _redirect_back()


@vaultwarden_bp.route("/items/<int:item_id>/record-access", methods=["POST"])
@login_required
def record_access(item_id: int):
    try:
        item = _item_for_user(item_id)
    except VaultItemAccessError as exc:
        if exc.reason == "missing":
            abort(404)
        abort(404)
    item.last_accessed = datetime.utcnow()
    _record("vault_item_access", item=item)
    db.session.commit()
    return jsonify({"status": "ok"})


@vaultwarden_bp.route("/organizations/<int:org_id>/key", methods=["GET"])
@login_required
def organization_key(org_id: int):
    membership = VaultOrganizationMembership.query.filter_by(user_id=current_user.id, organization_id=org_id).first()
    if not membership:
        abort(404)
    share = (
        VaultOrganizationKeyShare.query
        .filter_by(organization_id=org_id, user_id=current_user.id)
        .order_by(VaultOrganizationKeyShare.version.desc())
        .first()
    )
    if not share:
        abort(404)
    payload = {
        "key_blob": share.key_blob,
        "version": share.version,
        "expires_at": share.expires_at.isoformat() if share.expires_at else None,
        "organization": membership.organization.name if membership.organization else None,
    }
    return jsonify(payload)


@vaultwarden_bp.route("/api/items")
@login_required
def api_items():
    items = (
        VaultItem.query
        .filter(VaultItem.owner_id == current_user.id)
        .order_by(VaultItem.updated_at.desc())
        .limit(200)
        .all()
    )
    payload = []
    for item in items:
        payload.append(
            {
                "id": item.id,
                "name": item.name,
                "item_type": item.item_type,
                "favorite": item.favorite,
                "trashed": item.trashed,
                "tags": item.tag_list,
                "folder": item.folder.name if item.folder else None,
                "organization_id": item.organization_id,
                "encrypted_blob": item.encrypted_blob,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                "last_accessed": item.last_accessed.isoformat() if item.last_accessed else None,
            }
        )
    return jsonify(
        {
            "items": payload,
            "counts": {
                "total": len(payload),
                "favorites": sum(1 for entry in payload if entry["favorite"]),
            },
        }
    )
