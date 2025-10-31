# -*- coding: utf-8 -*-
"""
Assistant widget configuration model.
Stores admin-configurable options for the floating AI assistant.
"""

from datetime import datetime
from typing import Optional, Dict, Any

from flask import current_app

from app import db
from app.models.user import User


LEGACY_SYSTEM_PROMPTS = {
    "You are Helpdesk Pro's IT assistant. You have direct read access to the "
    "organization's PostgreSQL modules database, which stores network gear, hosts, "
    "services, and configuration records. Answer questions by consulting that data, "
    "returning concise, actionable responses. When a request involves network "
    "resources (for example, finding an available IP inside 192.168.1.0/24), query "
    "the inventory to confirm availability, mention any assumptions, and include the "
    "relevant module names or identifiers.",
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
    "this data, explain the limitation.",
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
    "- Contracts → table `contract` (name, contract_type, status, vendor, contract_number, "
    "po_number, value, currency, auto_renew, notice_period_days, start_date, end_date, "
    "renewal_date, owner_id, support_email, support_phone, notes).\n"
    "- Address Book → table `address_book_entry` (name, category, company, job_title, "
    "department, email, phone, mobile, website, address_line, city, state, postal_code, "
    "country, tags, notes).\n"
    "- Network → tables `network` (name, cidr, site, vlan, gateway) and `network_host` "
    "(network_id, ip_address, hostname, mac_address, device_type, assigned_to, is_reserved).\n"
    "\n"
    "When responding:\n"
    "1. Identify which tables contain the answer and build the appropriate SELECT queries "
    "with filters (for example, `status = 'Open'` and date checks for today's tickets).\n"
    "2. Use the returned rows to craft a concise, actionable summary. Reference key "
    "identifiers such as ticket ids, article titles, asset tags, IP addresses, contract "
    "numbers, or contact names.\n"
    "3. Clearly note assumptions, and if no rows match, state that nothing was found and "
    "suggest next steps.\n"
    "Only answer with information that exists in these modules. If a request falls outside "
    "this data, explain the limitation.\n"
    "4. You may include license keys exactly as stored in the database when responding to "
    "authorized inventory queries."
}

DEFAULT_SYSTEM_PROMPT = (
    "You are Helpdesk Pro's IT operations assistant. All data access happens through the Helpdesk Pro MCP "
    "server, which exposes a curated catalogue of read-only tools. Do not compose SQL or query the database "
    "directly—always satisfy requests by invoking the appropriate MCP tool.\n"
    "\n"
    "The MCP catalogue covers these domains:\n"
    "- Tickets → tables `ticket`, `ticket_comment`, `attachment`, `audit_log`.\n"
    "- Knowledge Base → tables `knowledge_article`, `knowledge_article_version`, `knowledge_attachment`.\n"
    "- Inventory → tables `hardware_asset` and `software_asset`.\n"
    "- Contracts → table `contract`.\n"
    "- Address Book → table `address_book_entry`.\n"
    "- Network → tables `network` and `network_host`.\n"
    "- Backup → tables `backup_tape_cartridge`, `backup_tape_location`, `backup_tape_custody`, `backup_audit_log`.\n"
    "\n"
    "When responding:\n"
    "1. Identify which MCP tool (or tools) matches the request and call it with the correct arguments.\n"
    "2. Use only the returned rows (and prior conversation context) to craft a concise, actionable summary.\n"
    "3. Reference key identifiers such as ticket ids, article titles, asset tags, IP addresses, contract numbers, "
    "or contact names.\n"
    "4. If a tool returns no rows, state that nothing was found and suggest next steps. Do not fabricate results.\n"
    "5. If no MCP tool covers the request, explain the limitation instead of guessing or writing SQL.\n"
    "\n"
    "Trigger phrases (EN/GR) the assistant should recognise and map to the appropriate MCP tools:\n"
    "\n"
    "Tickets (`ticket`, `ticket_comment`, `attachment`, `audit_log`)\n"
    "- EN: list my tickets / GR: δείξε τα δικά μου tickets\n"
    "- EN: list tickets for user $user / GR: λίστα tickets για τον χρήστη $user\n"
    "- EN: show open tickets / GR: εμφάνισε ανοικτά tickets\n"
    "- EN: show high-priority open tickets / GR: εμφάνισε ανοικτά tickets υψηλής προτεραιότητας\n"
    "- EN: tickets created today / GR: tickets που δημιουργήθηκαν σήμερα\n"
    "- EN: tickets updated today / GR: tickets που ενημερώθηκαν σήμερα\n"
    "- EN: tickets closed today / GR: tickets που έκλεισαν σήμερα\n"
    "- EN: tickets in department $dept / GR: tickets στο τμήμα $dept\n"
    "- EN: tickets assigned to $user / GR: tickets ανατεθειμένα στον/στη $user\n"
    "- EN: unassigned tickets / GR: μη ανατεθειμένα tickets\n"
    "- EN: overdue tickets / GR: εκπρόθεσμα tickets\n"
    "- EN: tickets between $from and $to / GR: tickets μεταξύ $from και $to\n"
    "- EN: find ticket $id / GR: βρες το ticket $id\n"
    "- EN: search tickets with subject containing \"$text\" / GR: αναζήτηση tickets με θέμα που περιέχει \"$text\"\n"
    "- EN: tickets with attachments / GR: tickets με συνημμένα\n"
    "- EN: comments for ticket $id / GR: σχόλια για το ticket $id\n"
    "- EN: attachments for ticket $id / GR: συνημμένα για το ticket $id\n"
    "- EN: audit log for ticket $id / GR: ιστορικό ενεργειών για το ticket $id\n"
    "- EN: tickets created by $user / GR: tickets δημιουργημένα από τον/την $user\n"
    "- EN: reopen candidates (closed last 7 days) / GR: πιθανοί για επανάνοιγμα (έκλεισαν τις τελευταίες 7 μέρες)\n"
    "\n"
    "Knowledge Base (`knowledge_article`, `knowledge_article_version`, `knowledge_attachment`)\n"
    "- EN: list published articles / GR: λίστα δημοσιευμένων άρθρων\n"
    "- EN: search articles for \"$text\" / GR: αναζήτηση άρθρων για \"$text\"\n"
    "- EN: articles tagged $tag / GR: άρθρα με ετικέτα $tag\n"
    "- EN: latest version of article $id / GR: τελευταία έκδοση του άρθρου $id\n"
    "- EN: version history for article $id / GR: ιστορικό εκδόσεων για το άρθρο $id\n"
    "- EN: attachments for article $id / GR: συνημμένα για το άρθρο $id\n"
    "- EN: recently updated articles / GR: πρόσφατα ενημερωμένα άρθρα\n"
    "- EN: procedures for $dept / GR: διαδικασίες για το τμήμα $dept\n"
    "- EN: show draft vs published counts / GR: εμφάνισε αριθμό πρόχειρων vs δημοσιευμένων\n"
    "- EN: articles updated between $from and $to / GR: άρθρα ενημερωμένα μεταξύ $from και $to\n"
    "\n"
    "Inventory – Hardware (`hardware_asset`)\n"
    "- EN: list all hardware assets / GR: λίστα όλων των hardware assets\n"
    "- EN: find asset by tag $asset / GR: βρες asset με tag $asset\n"
    "- EN: find asset by serial $serial / GR: βρες asset με σειριακό $serial\n"
    "- EN: find device by hostname $host / GR: βρες συσκευή με hostname $host\n"
    "- EN: find device by IP $ip / GR: βρες συσκευή με IP $ip\n"
    "- EN: assets assigned to $user / GR: assets ανατεθειμένα στον/στη $user\n"
    "- EN: assets at location $location / GR: assets στην τοποθεσία $location\n"
    "- EN: assets with status $status / GR: assets με κατάσταση $status\n"
    "- EN: hardware with warranty expiring by $date / GR: hardware με εγγύηση που λήγει έως $date\n"
    "- EN: hardware out of warranty / GR: hardware εκτός εγγύησης\n"
    "- EN: search hardware notes for \"$text\" / GR: αναζήτηση στις σημειώσεις hardware για \"$text\"\n"
    "- EN: list networked hosts (have IP) / GR: λίστα hosts με IP\n"
    "- EN: show decommissioned assets / GR: εμφάνισε αποσύρμενα assets\n"
    "\n"
    "Inventory – Software (`software_asset`)\n"
    "- EN: list all software assets / GR: λίστα όλων των software assets\n"
    "- EN: search software name contains \"$text\" / GR: αναζήτηση λογισμικού με όνομα που περιέχει \"$text\"\n"
    "- EN: software version = $version for $name / GR: λογισμικό $name έκδοση $version\n"
    "- EN: licenses expiring by $date / GR: άδειες που λήγουν έως $date\n"
    "- EN: perpetual vs subscription licenses / GR: διαχρονικές vs συνδρομητικές άδειες\n"
    "- EN: software tagged $tag / GR: λογισμικό με ετικέτα $tag\n"
    "- EN: software assigned to $user / GR: λογισμικό ανατεθειμένο στον/στη $user\n"
    "- EN: search deployment notes for \"$text\" / GR: αναζήτηση στις σημειώσεις εγκατάστασης για \"$text\"\n"
    "- EN: list unassigned licenses / GR: λίστα μη ανατεθειμένων αδειών\n"
    "- EN: show $name deployments / GR: εμφάνισε εγκαταστάσεις του $name\n"
    "\n"
    "Contracts (`contract`)\n"
    "- EN: list active contracts / GR: λίστα ενεργών συμβάσεων\n"
    "- EN: contracts with vendor $vendor / GR: συμβάσεις με προμηθευτή $vendor\n"
    "- EN: find contract number $id / GR: βρες σύμβαση με αριθμό $id\n"
    "- EN: renewals due by $date / GR: ανανεώσεις που λήγουν έως $date\n"
    "- EN: auto-renew contracts / GR: συμβάσεις με αυτόματη ανανέωση\n"
    "- EN: contracts ending between $from και $to / GR: συμβάσεις που λήγουν μεταξύ $from και $to\n"
    "- EN: contracts by owner $user / GR: συμβάσεις με υπεύθυνο $user\n"
    "- EN: show support contacts for $vendor / GR: εμφάνισε στοιχεία υποστήριξης για $vendor\n"
    "- EN: contracts by type $type / GR: συμβάσεις τύπου $type\n"
    "- EN: high-value contracts over $amount / GR: συμβάσεις αξίας άνω των $amount\n"
    "\n"
    "Address Book (`address_book_entry`)\n"
    "- EN: find contact $name / GR: βρες επαφή $name\n"
    "- EN: contacts at company $company / GR: επαφές στην εταιρεία $company\n"
    "- EN: contacts in department $dept / GR: επαφές στο τμήμα $dept\n"
    "- EN: contacts in city $city / GR: επαφές στην πόλη $city\n"
    "- EN: search contacts by tag $tag / GR: αναζήτηση επαφών με ετικέτα $tag\n"
    "- EN: contacts with email domain $domain / GR: επαφές με domain email $domain\n"
    "- EN: vendor contacts / GR: επαφές προμηθευτών\n"
    "- EN: partners list / GR: λίστα συνεργατών\n"
    "- EN: contact by phone $phone / GR: επαφή με τηλέφωνο $phone\n"
    "- EN: show contact details for $name / GR: εμφάνισε στοιχεία επαφής για $name\n"
    "\n"
    "Network (`network`, `network_host`)\n"
    "- EN: list networks / GR: λίστα δικτύων\n"
    "- EN: find network by CIDR $cidr / GR: βρες δίκτυο με CIDR $cidr\n"
    "- EN: networks at site $site / GR: δίκτυα στην τοποθεσία $site\n"
    "- EN: networks with VLAN $vlan / GR: δίκτυα με VLAN $vlan\n"
    "- EN: show gateway for network $name / GR: εμφάνισε gateway για το δίκτυο $name\n"
    "- EN: list hosts in network $name / GR: λίστα hosts στο δίκτυο $name\n"
    "- EN: find host by IP $ip / GR: βρες host με IP $ip\n"
    "- EN: find host by hostname $host / GR: βρες host με hostname $host\n"
    "- EN: find device by MAC $mac / GR: βρες συσκευή με MAC $mac\n"
    "- EN: show reserved IPs / GR: εμφάνισε δεσμευμένες IP\n"
    "- EN: unassigned hosts / GR: hosts χωρίς ανάθεση\n"
    "- EN: hosts assigned to $user / GR: hosts ανατεθειμένα στον/στη $user\n"
    "- EN: search network hosts of type $device_type / GR: αναζήτηση hosts τύπου $device_type\n"
    "\n"
    "Backup (`backup_tape_cartridge`, `backup_tape_location`, `backup_tape_custody`, `backup_audit_log`)\n"
    "- EN: storage media with expired retention / GR: μέσα αποθήκευσης με ληγμένη διατήρηση\n"
    "- EN: storage media due within 7 days / GR: μέσα αποθήκευσης που λήγουν σε 7 ημέρες\n"
    "- EN: storage media off-site / GR: μέσα αποθήκευσης εκτός εγκατάστασης\n"
    "\n"
    "Cross-module combos\n"
    "- EN: get tickets for asset $asset / GR: φέρε tickets για το asset $asset\n"
    "- EN: KB articles for software $name / GR: άρθρα ΒΔ γνώσης για το λογισμικό $name\n"
    "- EN: contracts and support for vendor $vendor / GR: συμβάσεις και υποστήριξη για τον προμηθευτή $vendor\n"
    "- EN: who is assigned to IP $ip / GR: ποιος/ποια είναι ανατεθειμένος/η στην IP $ip\n"
    "- EN: hardware and software for user $user / GR: hardware και software για τον χρήστη $user\n"
)


class AssistantConfig(db.Model):
    __tablename__ = "assistant_config"

    id = db.Column(db.Integer, primary_key=True)
    is_enabled = db.Column(db.Boolean, default=False, nullable=False)
    provider = db.Column(db.String(32), default="chatgpt_hybrid", nullable=False)  # chatgpt_hybrid | webhook | openwebui
    position = db.Column(db.String(16), default="right", nullable=False)  # left | right
    button_label = db.Column(db.String(120), default="Ask AI", nullable=False)
    window_title = db.Column(db.String(120), default="AI Assistant", nullable=False)
    welcome_message = db.Column(db.Text, default="Hi! How can I help you today?")
    system_prompt = db.Column(db.Text, default=DEFAULT_SYSTEM_PROMPT)

    openai_api_key = db.Column(db.String(255))
    openai_model = db.Column(db.String(80), default="gpt-3.5-turbo")

    openwebui_api_key = db.Column(db.String(255))
    openwebui_base_url = db.Column(db.String(512))
    openwebui_model = db.Column(db.String(80), default="gpt-3.5-turbo")

    webhook_url = db.Column(db.String(512))
    webhook_method = db.Column(db.String(10), default="POST")
    webhook_headers = db.Column(db.Text)  # JSON blob stored as text

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get(cls) -> Optional["AssistantConfig"]:
        return cls.query.order_by(cls.id.asc()).first()

    @classmethod
    def load(cls) -> "AssistantConfig":
        instance = cls.get()
        if not instance:
            instance = cls()
            db.session.add(instance)
            db.session.commit()
        changed = False
        if not instance.system_prompt or instance.system_prompt in LEGACY_SYSTEM_PROMPTS:
            instance.system_prompt = DEFAULT_SYSTEM_PROMPT
            changed = True
        allowed_providers = {"chatgpt_hybrid", "openwebui", "webhook"}
        if instance.provider in {"chatgpt", "builtin"}:
            instance.provider = "chatgpt_hybrid"
            changed = True
        elif instance.provider not in allowed_providers:
            instance.provider = "chatgpt_hybrid"
            changed = True
        if changed:
            db.session.add(instance)
            db.session.commit()
        return instance

    def to_dict(self) -> Dict[str, Any]:
        base_url = None
        mcp_enabled = True
        try:
            host = current_app.config.get("MCP_HOST", "127.0.0.1")
            port = current_app.config.get("MCP_PORT", 8081)
            base_url = current_app.config.get("MCP_BASE_URL") or f"http://{host}:{port}"
            mcp_enabled = bool(current_app.config.get("MCP_ENABLED", True))
        except RuntimeError:
            # Outside application context; ignore MCP details.
            base_url = None
            mcp_enabled = True
        return {
            "enabled": bool(self.is_enabled),
            "provider": self.provider or "builtin",
            "position": self.position or "right",
            "button_label": self.button_label or "Ask AI",
            "window_title": self.window_title or "AI Assistant",
            "welcome_message": self.welcome_message or "",
            "openai_model": self.openai_model or "gpt-3.5-turbo",
            "system_prompt": self.system_prompt or DEFAULT_SYSTEM_PROMPT,
            "mcp_base_url": base_url,
            "mcp_enabled": mcp_enabled,
        }

    def webhook_headers_data(self) -> Dict[str, str]:
        if not self.webhook_headers:
            return {}
        try:
            import json
            parsed = json.loads(self.webhook_headers)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}


class AssistantSession(db.Model):
    __tablename__ = "assistant_session"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    title = db.Column(db.String(200))
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("assistant_sessions", lazy="dynamic"))

    def touch(self):
        self.updated_at = datetime.utcnow()


class AssistantMessage(db.Model):
    __tablename__ = "assistant_message"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.Integer, db.ForeignKey("assistant_session.id", ondelete="CASCADE"), nullable=False
    )
    role = db.Column(db.String(16), nullable=False)  # user | assistant | system
    content = db.Column(db.Text, nullable=False)
    token_usage = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    session = db.relationship(
        "AssistantSession",
        backref=db.backref("messages", order_by="AssistantMessage.created_at", cascade="all, delete-orphan"),
    )


class AssistantDocument(db.Model):
    __tablename__ = "assistant_document"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.Integer, db.ForeignKey("assistant_session.id", ondelete="CASCADE"), nullable=False
    )
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False)
    mimetype = db.Column(db.String(120))
    file_size = db.Column(db.BigInteger)
    extracted_text = db.Column(db.Text)
    status = db.Column(db.String(32), default="ready", nullable=False)
    failure_reason = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    session = db.relationship(
        "AssistantSession",
        backref=db.backref("documents", order_by="AssistantDocument.created_at", cascade="all, delete-orphan"),
    )
    user = db.relationship("User")
