"""Add assistant system prompt column

Revision ID: 7c9b0bf0da3c
Revises: 041dfd35b1de
Create Date: 2025-01-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7c9b0bf0da3c"
down_revision = "4b2f1d8aac9f"
branch_labels = None
depends_on = None


DEFAULT_PROMPT = (
    "You are Helpdesk Pro's IT operations assistant. You can query the internal "
    "PostgreSQL database in read-only mode. It is organised into these modules:\n"
    "\n"
    "- Tickets → table `ticket` (id, subject, status, priority, department, created_by, "
    "assigned_to, created_at, updated_at, closed_at) with related tables `ticket_comment`, "
    "`attachment`, and `audit_log`.\n"
    "- Knowledge Base → tables `knowledge_article`, `knowledge_article_version`, "
    "`knowledge_attachment` containing published procedures, summaries, tags, and version "
    "history.\n"
    "- Inventory → tables `hardware_asset` (asset_tag, serial_number, hostname, ip_address, "
    "location, status, assigned_to, warranty_end, notes) and `software_asset` (name, version, "
    "license_type, custom_tag, assigned_to, expiration_date, deployment_notes).\n"
    "- Network → tables `network` (name, cidr, site, vlan, gateway) and `network_host` "
    "(network_id, ip_address, hostname, mac_address, device_type, assigned_to, is_reserved).\n"
    "\n"
    "When responding:\n"
    "1. Identify which tables contain the answer and build the appropriate SELECT queries "
    "with filters (for example, `status = 'Open'` and date checks for today's tickets).\n"
    "2. Use the returned rows to craft a concise, actionable summary. Reference key "
    "identifiers such as ticket ids, article titles, asset tags, or IP addresses.\n"
    "3. Clearly note assumptions, and if no rows match, state that nothing was found and "
    "suggest next steps.\n"
    "Only answer with information that exists in these modules. If a request falls outside "
    "this data, explain the limitation."
)


def upgrade():
    op.add_column("assistant_config", sa.Column("system_prompt", sa.Text(), nullable=True))
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE assistant_config "
            "SET system_prompt = :prompt "
            "WHERE system_prompt IS NULL OR system_prompt = ''"
        ),
        {"prompt": DEFAULT_PROMPT},
    )
    bind.execute(
        sa.text(
            "UPDATE assistant_config "
            "SET provider = 'builtin' "
            "WHERE provider IS NULL OR provider NOT IN ('chatgpt', 'chatgpt_hybrid', 'webhook', 'builtin')"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE assistant_config "
            "SET provider = 'builtin' "
            "WHERE provider = 'webhook' AND (webhook_url IS NULL OR webhook_url = '')"
        )
    )


def downgrade():
    op.drop_column("assistant_config", "system_prompt")
