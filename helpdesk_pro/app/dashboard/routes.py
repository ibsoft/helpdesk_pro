from flask import Blueprint, render_template
from flask_login import login_required, current_user
from sqlalchemy import func, or_, case
from datetime import datetime, timedelta
from app import db
from app.models.user import User
from app.models.ticket import Ticket

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

    # === 3️⃣ Aggregation helper ===
    def aggregate(period):
        created = (
            db.session.query(
                func.date_trunc(period, func.timezone(
                    tz, Ticket.created_at)).label("p"),
                func.count(Ticket.id).label("c")
            )
            .filter(Ticket.id.in_(tickets_query.with_entities(Ticket.id)))
            .group_by("p")
            .order_by("p")
            .all()
        )
        closed = (
            db.session.query(
                func.date_trunc(period, func.timezone(
                    tz, Ticket.closed_at)).label("p"),
                func.count(Ticket.id).label("c")
            )
            .filter(
                Ticket.closed_at.isnot(None),
                Ticket.id.in_(tickets_query.with_entities(Ticket.id))
            )
            .group_by("p")
            .order_by("p")
            .all()
        )
        return created, closed

    created_day, closed_day = aggregate("day")
    created_week, closed_week = aggregate("week")
    created_month, closed_month = aggregate("month")
    created_year, closed_year = aggregate("year")

    # === 4️⃣ Fill helper ===
    def fill(data, delta, count, fmt):
        m = {}
        for d in data:
            date_val = d[0]
            if hasattr(date_val, "date"):
                date_val = date_val.date()
            m[date_val] = d[1]
        now = datetime.now()
        labels, vals = [], []
        for i in range(count - 1, -1, -1):
            day = (now - i * delta).date()
            labels.append(day.strftime(fmt))
            vals.append(m.get(day, 0))
        return labels, vals

    # === 5️⃣ Charts data ===
    daily_labels, daily_created = fill(
        created_day, timedelta(days=1), 7, "%d %b")
    _, daily_closed = fill(closed_day, timedelta(days=1), 7, "%d %b")

    weekly_labels, weekly_created = fill(
        created_week, timedelta(weeks=1), 8, "W%W")
    _, weekly_closed = fill(closed_week, timedelta(weeks=1), 8, "W%W")

    monthly_labels, monthly_created = fill(
        created_month, timedelta(days=30), 12, "%b %Y")
    _, monthly_closed = fill(closed_month, timedelta(days=30), 12, "%b %Y")

    monthly_rate = [
        round((closed / created * 100) if created else 0, 1)
        for created, closed in zip(monthly_created, monthly_closed)
    ]

    yearly_labels, yearly_closed = fill(
        closed_year, timedelta(days=365), 5, "%Y")

    # === 6️⃣ Department summary table (Managers & Admins) ===
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

    # === 7️⃣ Render ===
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
        dept_summary=dept_summary
    )
