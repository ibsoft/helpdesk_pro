# -*- coding: utf-8 -*-
"""
Networks blueprint routes.
Provides management pages for IP network maps and networking tools.
"""

import ipaddress
from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    abort,
    flash,
    redirect,
    url_for,
)
from flask_login import login_required, current_user

from app import db
from app.models import Network, NetworkHost


networks_bp = Blueprint("networks", __name__, url_prefix="/networks")


def _require_roles(*roles):
    if not current_user.is_authenticated:
        abort(403)
    user_role = (current_user.role or "").lower()
    allowed = {role.lower() for role in roles}
    if user_role not in allowed:
        abort(403)


def _require_admin():
    _require_roles("admin")


def _json_response(success, message, category="info", status=200, **extra):
    payload = {"success": success, "message": message, "category": category}
    payload.update(extra)
    return jsonify(payload), status


@networks_bp.route("/maps")
@login_required
def network_maps():
    _require_roles("admin", "technician")
    networks = Network.query.order_by(Network.name.asc()).all()
    total_hosts = sum(n.host_capacity for n in networks)
    return render_template(
        "networks/maps.html",
        networks=networks,
        total_hosts=total_hosts,
    )


def _generate_hosts_for_network(network: Network):
    """Generate host entries for a network if none exist."""
    ip_net = network.ip_network
    if not ip_net:
        return 0
    created = 0
    existing_ips = {host.ip_address for host in network.hosts}
    hosts_to_create = []

    if isinstance(ip_net, ipaddress.IPv4Network):
        if ip_net.prefixlen >= 31:
            iterable = ip_net.hosts() if ip_net.prefixlen == 32 else ip_net
        else:
            iterable = ip_net.hosts()
        for ip in iterable:
            ip_str = str(ip)
            if ip_str in existing_ips:
                continue
            hosts_to_create.append(NetworkHost(network_id=network.id, ip_address=ip_str))
    else:
        for ip in ip_net.hosts():
            ip_str = str(ip)
            if ip_str in existing_ips:
                continue
            hosts_to_create.append(NetworkHost(network_id=network.id, ip_address=ip_str))
            if len(hosts_to_create) >= 1024:
                break

    if hosts_to_create:
        db.session.bulk_save_objects(hosts_to_create)
        db.session.commit()
        created = len(hosts_to_create)
    return created


@networks_bp.route("/maps/<int:network_id>")
@login_required
def network_hosts(network_id):
    _require_roles("admin", "technician")
    network = Network.query.get_or_404(network_id)
    hosts = NetworkHost.query.filter_by(network_id=network.id).order_by(NetworkHost.ip_address.asc()).all()
    can_generate = len(hosts) == 0
    total_hosts = len(hosts)
    return render_template(
        "networks/hosts.html",
        network=network,
        hosts=hosts,
        can_generate=can_generate,
        total_hosts=total_hosts,
    )

@networks_bp.route("/maps/<int:network_id>/hosts.json", methods=["GET"])
@login_required
def network_hosts_json(network_id):
    _require_roles("admin", "technician")
    network = Network.query.get_or_404(network_id)

    hosts = (
        NetworkHost.query.filter_by(network_id=network.id)
        .order_by(NetworkHost.ip_address.asc())
        .all()
    )
    host_entries = []
    truncated = False

    if hosts:
        host_entries = [
            {"ip": host.ip_address, "reserved": bool(host.is_reserved)}
            for host in hosts
        ]
    else:
        ip_net = network.ip_network
        if not ip_net:
            return _json_response(False, "Invalid network definition.", "danger", 400)

        limit = 1024 if ip_net.version == 4 else 512
        produced = 0

        if isinstance(ip_net, ipaddress.IPv4Network):
            iterable = ip_net.hosts() if ip_net.prefixlen <= 30 else ip_net
        else:
            iterable = ip_net.hosts()

        for ip in iterable:
            host_entries.append({"ip": str(ip), "reserved": False})
            produced += 1
            if produced >= limit:
                truncated = ip_net.num_addresses > limit
                break

        if not host_entries and ip_net.prefixlen >= 31:
            host_entries = [{"ip": str(ip), "reserved": False} for ip in ip_net][:limit]
            truncated = len(host_entries) == limit and ip_net.num_addresses > limit

    if not hosts and network.host_capacity and len(host_entries) < network.host_capacity:
        truncated = True

    return jsonify(
        success=True,
        hosts=host_entries,
        truncated=truncated,
        host_count=len(host_entries),
        capacity=network.host_capacity,
        network=network.as_dict(),
    )


@networks_bp.route("/maps/<int:network_id>/generate-hosts", methods=["POST"])
@login_required
def generate_hosts(network_id):
    _require_admin()
    network = Network.query.get_or_404(network_id)
    if network.hosts:
        flash("Hosts already exist for this network.", "warning")
        return redirect(request.referrer or url_for("networks.network_hosts", network_id=network.id))
    created = _generate_hosts_for_network(network)
    if created == 0:
        flash("No hosts generated. Verify the network definition.", "warning")
    else:
        flash(f"Generated {created} hosts.", "success")
    return redirect(request.referrer or url_for("networks.network_hosts", network_id=network.id))


@networks_bp.route("/maps/create", methods=["POST"])
@login_required
def create_network():
    _require_admin()
    name = (request.form.get("name") or "").strip()
    cidr = (request.form.get("cidr") or "").strip()
    if not name or not cidr:
        return _json_response(False, "Name and network (CIDR) are required.", "warning", 400)

    try:
        ip_net = ipaddress.ip_network(cidr, strict=False)
        cidr = str(ip_net)
    except ValueError:
        return _json_response(False, "Invalid network CIDR.", "danger", 400)

    if Network.query.filter_by(cidr=cidr).first():
        return _json_response(False, "Network already exists.", "warning", 400)

    network = Network(
        name=name,
        cidr=cidr,
        description=request.form.get("description"),
        site=request.form.get("site"),
        vlan=request.form.get("vlan"),
        gateway=request.form.get("gateway"),
        notes=request.form.get("notes"),
    )
    db.session.add(network)
    db.session.commit()
    return _json_response(True, "Network added successfully.", "success")


@networks_bp.route("/maps/<int:network_id>/update", methods=["POST"])
@login_required
def update_network(network_id):
    _require_admin()
    network = Network.query.get_or_404(network_id)

    name = (request.form.get("name") or "").strip()
    cidr = (request.form.get("cidr") or "").strip()
    if not name or not cidr:
        return _json_response(False, "Name and network (CIDR) are required.", "warning", 400)

    try:
        ip_net = ipaddress.ip_network(cidr, strict=False)
        cidr = str(ip_net)
    except ValueError:
        return _json_response(False, "Invalid network CIDR.", "danger", 400)

    existing = Network.query.filter(Network.cidr == cidr, Network.id != network.id).first()
    if existing:
        return _json_response(False, "Another network already uses that CIDR.", "warning", 400)

    network.name = name
    network.cidr = cidr
    network.description = request.form.get("description")
    network.site = request.form.get("site")
    network.vlan = request.form.get("vlan")
    network.gateway = request.form.get("gateway")
    network.notes = request.form.get("notes")

    db.session.commit()
    return _json_response(True, "Network updated successfully.", "success")


@networks_bp.route("/maps/<int:network_id>/delete", methods=["POST"])
@login_required
def delete_network(network_id):
    _require_admin()
    network = Network.query.get_or_404(network_id)
    db.session.delete(network)
    db.session.commit()
    return _json_response(True, "Network removed.", "warning")


@networks_bp.route("/maps/<int:network_id>/hosts/<int:host_id>/update", methods=["POST"])
@login_required
def update_host(network_id, host_id):
    _require_admin()
    network = Network.query.get_or_404(network_id)
    host = NetworkHost.query.filter_by(id=host_id, network_id=network.id).first_or_404()

    ip_address = (request.form.get("ip_address") or "").strip()
    if not ip_address:
        return _json_response(False, "IP address is required.", "warning", 400)
    try:
        ip_obj = ipaddress.ip_address(ip_address)
    except ValueError:
        return _json_response(False, "Invalid IP address.", "danger", 400)

    ip_net = network.ip_network
    if ip_net and ip_obj not in ip_net:
        return _json_response(False, "IP address is outside network range.", "warning", 400)

    existing = NetworkHost.query.filter(NetworkHost.network_id == network.id, NetworkHost.ip_address == str(ip_obj), NetworkHost.id != host.id).first()
    if existing:
        return _json_response(False, "Another host already uses this IP.", "warning", 400)

    host.ip_address = str(ip_obj)
    host.hostname = (request.form.get("hostname") or "").strip() or None
    host.mac_address = (request.form.get("mac_address") or "").strip() or None
    host.device_type = (request.form.get("device_type") or "").strip() or None
    host.assigned_to = (request.form.get("assigned_to") or "").strip() or None
    host.description = (request.form.get("description") or "").strip() or None
    host.is_reserved = bool(request.form.get("is_reserved"))

    db.session.commit()
    return _json_response(True, "Host updated successfully.", "success")


@networks_bp.route("/maps/<int:network_id>/hosts/<int:host_id>/delete", methods=["POST"])
@login_required
def delete_host(network_id, host_id):
    _require_admin()
    host = NetworkHost.query.filter_by(id=host_id, network_id=network_id).first_or_404()
    db.session.delete(host)
    db.session.commit()
    return _json_response(True, "Host removed.", "warning")


@networks_bp.route("/tools")
@login_required
def network_tools():
    _require_roles("admin", "technician")
    return render_template("networks/tools.html")
