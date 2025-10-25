from flask import Blueprint, render_template
from flask_login import login_required, current_user
from sqlalchemy import func, or_, case, select
from datetime import datetime, timedelta, date
from app import db
from app.models.user import User
from app.models.ticket import Ticket
from app.models.knowledge import KnowledgeArticle
from app.models.inventory import HardwareAsset, SoftwareAsset
from app.models.network import Network, NetworkHost
from app.navigation import is_feature_allowed

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/dashboard")
@login_required
def index():
    tz = "Europe/Athens"

    # === 1️⃣ Scope based on role ===
    if current_user.role == "admin":
        tickets_query = Ticket.query
        dept_users = None
    elif current_user.role == "manager":
        dept_users = User.query.filter_by(
            department=current_user.department).with_entities(User.id)
        tickets_query = Ticket.query.filter(
            or_(
                Ticket.created_by.in_(dept_users),
                Ticket.assigned_to.in_(dept_users)
            )
        )
    else:
        tickets_query = Ticket.query.filter(
            or_(
                Ticket.created_by == current_user.id,
                Ticket.assigned_to == current_user.id
            )
        )
        dept_users = None

    # === 2️⃣ Summary cards ===
    users_count = User.query.count() if current_user.role == "admin" else 1
    open_tickets = tickets_query.filter_by(status="Open").count()
    closed_tickets = tickets_query.filter_by(status="Closed").count()
    in_progress = tickets_query.filter_by(status="In Progress").count()

    ticket_ids_subq = tickets_query.with_entities(Ticket.id).subquery()
    ticket_ids_select = select(ticket_ids_subq.c.id).scalar_subquery()

    # === 3️⃣ Aggregation helper ===
    def aggregate_map(period, column, skip_null=False):
        bucket = func.date_trunc(period, func.timezone(tz, column)).label("bucket")
        query = db.session.query(bucket, func.count()).filter(Ticket.id.in_(ticket_ids_select))
        if skip_null:
            query = query.filter(column.isnot(None))
        rows = query.group_by(bucket).order_by(bucket).all()
        data = {}
        for bucket_value, count in rows:
            if not bucket_value:
                continue
            bucket_date = bucket_value.date() if hasattr(bucket_value, "date") else bucket_value
            data[bucket_date] = count
        return data

    created_day_map = aggregate_map("day", Ticket.created_at)
    closed_day_map = aggregate_map("day", Ticket.closed_at, skip_null=True)
    created_week_map = aggregate_map("week", Ticket.created_at)
    closed_week_map = aggregate_map("week", Ticket.closed_at, skip_null=True)
    created_month_map = aggregate_map("month", Ticket.created_at)
    closed_month_map = aggregate_map("month", Ticket.closed_at, skip_null=True)
    closed_year_map = aggregate_map("year", Ticket.closed_at, skip_null=True)

    # === 4️⃣ Period helpers ===
    def shift_month(base: date, offset: int) -> date:
        year = base.year + ((base.month - 1 + offset) // 12)
        month = (base.month - 1 + offset) % 12 + 1
        return date(year, month, 1)

    def generate_period_keys(period: str, count: int):
        today_date = datetime.now().date()
        if period == "day":
            start = today_date - timedelta(days=count - 1)
            return [start + timedelta(days=i) for i in range(count)]
        if period == "week":
            current_week_start = today_date - timedelta(days=today_date.weekday())
            return [current_week_start - timedelta(weeks=count - 1 - i) for i in range(count)]
        if period == "month":
            current_month_start = today_date.replace(day=1)
            return [shift_month(current_month_start, -(count - 1 - i)) for i in range(count)]
        if period == "year":
            current_year_start = date(today_date.year, 1, 1)
            return [date(today_date.year - (count - 1 - i), 1, 1) for i in range(count)]
        raise ValueError(f"Unsupported period: {period}")

    def build_series(period: str, count: int, data_map: dict, formatter):
        keys = generate_period_keys(period, count)
        labels = [formatter(key) for key in keys]
        values = [data_map.get(key, 0) for key in keys]
        return labels, values

    # === 5️⃣ Charts data ===
    def daily_formatter(d: date) -> str:
        return d.strftime("%d %b")

    def weekly_formatter(d: date) -> str:
        iso = d.isocalendar()
        year = getattr(iso, "year", iso[0])
        week = getattr(iso, "week", iso[1])
        return f"{year} W{week:02d}"

    def monthly_formatter(d: date) -> str:
        return d.strftime("%b %Y")

    def yearly_formatter(d: date) -> str:
        return str(d.year)

    daily_labels, daily_created = build_series("day", 7, created_day_map, daily_formatter)
    _, daily_closed = build_series("day", 7, closed_day_map, daily_formatter)

    weekly_labels, weekly_created = build_series("week", 8, created_week_map, weekly_formatter)
    _, weekly_closed = build_series("week", 8, closed_week_map, weekly_formatter)

    monthly_labels, monthly_created = build_series("month", 12, created_month_map, monthly_formatter)
    _, monthly_closed = build_series("month", 12, closed_month_map, monthly_formatter)

    monthly_rate = [
        round((closed / created * 100) if created else 0, 1)
        for created, closed in zip(monthly_created, monthly_closed)
    ]

    yearly_labels, yearly_closed = build_series("year", 5, closed_year_map, yearly_formatter)

    # === 6️⃣ Additional module metrics ===
    knowledge_enabled = is_feature_allowed("knowledge", current_user)
    knowledge_labels, knowledge_counts = [], []
    if knowledge_enabled:
        knowledge_rows = (
            db.session.query(
                func.date_trunc("month", func.timezone(tz, KnowledgeArticle.created_at)).label("bucket"),
                func.count(KnowledgeArticle.id)
            )
            .filter(KnowledgeArticle.is_published.is_(True))
            .group_by("bucket")
            .order_by("bucket")
            .all()
        )
        knowledge_map = {}
        for bucket_value, count in knowledge_rows:
            if not bucket_value:
                continue
            knowledge_map[bucket_value.date()] = count
        knowledge_labels, knowledge_counts = build_series("month", 12, knowledge_map, monthly_formatter)

    inventory_enabled = is_feature_allowed("inventory", current_user)
    hardware_stats = {"total": 0, "assigned": 0, "available": 0}
    software_stats = {"total": 0, "assigned": 0, "available": 0}
    if inventory_enabled:
        hardware_stats["total"] = db.session.query(func.count(HardwareAsset.id)).scalar() or 0
        hardware_stats["assigned"] = db.session.query(func.count(HardwareAsset.id)).filter(HardwareAsset.assigned_to.isnot(None)).scalar() or 0
        hardware_stats["available"] = max(hardware_stats["total"] - hardware_stats["assigned"], 0)

        software_stats["total"] = db.session.query(func.count(SoftwareAsset.id)).scalar() or 0
        software_stats["assigned"] = db.session.query(func.count(SoftwareAsset.id)).filter(SoftwareAsset.assigned_to.isnot(None)).scalar() or 0
        software_stats["available"] = max(software_stats["total"] - software_stats["assigned"], 0)

    networks_enabled = is_feature_allowed("networks", current_user)
    network_labels, network_used, network_available = [], [], []
    if networks_enabled:
        top_networks = (
            db.session.query(Network, func.count(NetworkHost.id).label("used"))
            .outerjoin(NetworkHost, NetworkHost.network_id == Network.id)
            .group_by(Network.id)
            .order_by(func.count(NetworkHost.id).desc())
            .limit(8)
            .all()
        )
        for network, used in top_networks:
            label = network.name or network.cidr
            capacity = network.host_capacity or 0
            network_labels.append(label)
            network_used.append(int(used or 0))
            network_available.append(max(capacity - int(used or 0), 0))

    # === 7️⃣ Department summary table (Managers & Admins) ===
    dept_summary = []
    if current_user.role in ("admin", "manager"):
        if current_user.role == "admin":
            dept_users_query = User.query
        else:
            dept_users_query = User.query.filter_by(
                department=current_user.department)

        dept_summary = (
            db.session.query(
                User.username,
                func.count(case((Ticket.status == "Open", 1))).label("open"),
                func.count(case((Ticket.status == "In Progress", 1))
                           ).label("in_progress"),
                func.count(case((Ticket.status == "Closed", 1))
                           ).label("closed")
            )
            .join(Ticket, Ticket.assigned_to == User.id, isouter=True)
            .filter(User.id.in_(dept_users_query.with_entities(User.id)))
            .group_by(User.username)
            .order_by(User.username)
            .all()
        )

    # === 8️⃣ Render ===
    return render_template(
        "dashboard/index.html",
        users=users_count,
        open_tickets=open_tickets,
        in_progress=in_progress,
        closed_tickets=closed_tickets,
        daily_labels=daily_labels,
        daily_created=daily_created,
        daily_closed=daily_closed,
        weekly_labels=weekly_labels,
        weekly_created=weekly_created,
        weekly_closed=weekly_closed,
        monthly_labels=monthly_labels,
        monthly_rate=monthly_rate,
        yearly_labels=yearly_labels,
        yearly_closed=yearly_closed,
        dept_summary=dept_summary,
        knowledge_enabled=knowledge_enabled,
        knowledge_labels=knowledge_labels,
        knowledge_counts=knowledge_counts,
        inventory_enabled=inventory_enabled,
        hardware_stats=hardware_stats,
        software_stats=software_stats,
        networks_enabled=networks_enabled,
        network_labels=network_labels,
        network_used=network_used,
        network_available=network_available,
    )
