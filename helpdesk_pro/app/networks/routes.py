# -*- coding: utf-8 -*-
"""
Networks blueprint routes.
Provides management pages for IP network maps and networking tools.
"""

import ipaddress
import platform
import re
import socket
import subprocess
from typing import List
from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    abort,
    flash,
    redirect,
    url_for,
    current_app,
)
from flask_login import login_required, current_user

from app import db
from app.models import Network, NetworkHost
from app.permissions import get_module_access, require_module_write


networks_bp = Blueprint("networks", __name__, url_prefix="/networks")


def _require_roles(*roles):
    if not current_user.is_authenticated:
        abort(403)
    user_role = (current_user.role or "").strip().lower()
    allowed = {role.strip().lower() for role in roles}
    if user_role not in allowed:
        abort(403)


def _json_response(success, message, category="info", status=200, **extra):
    payload = {"success": success, "message": message, "category": category}
    payload.update(extra)
    return jsonify(payload), status


_HOST_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")


def _validate_host(value: str) -> bool:
    if not value or len(value) > 253:
        return False
    return bool(_HOST_PATTERN.fullmatch(value))


def _parse_ports(raw_ports: List[str]) -> List[int]:
    ports: List[int] = []
    for item in raw_ports:
        item = str(item).strip()
        if not item:
            continue
        try:
            port = int(item)
        except ValueError:
            raise ValueError(f"Invalid port '{item}'")
        if port < 1 or port > 65535:
            raise ValueError(f"Port {port} out of range (1-65535)")
        ports.append(port)
    if not ports:
        raise ValueError("No valid ports provided")
    if len(ports) > 25:
        raise ValueError("Maximum 25 ports per scan")
    return ports


def _run_ping_command(target: str) -> subprocess.CompletedProcess:
    system = platform.system().lower()
    if system == "windows":
        command = ["ping", "-n", "3", "-w", "2000", target]
    else:
        command = ["ping", "-c", "3", "-W", "2", target]
    return subprocess.run(command, capture_output=True, text=True, timeout=10)


def _scan_tcp_port(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, OSError):
        return False


@networks_bp.route("/maps")
@login_required
def network_maps():
    _require_roles("admin", "technician")
    networks = Network.query.order_by(Network.name.asc()).all()
    total_hosts = sum(n.host_capacity for n in networks)
    module_access = get_module_access(current_user, "networks")
    can_manage = module_access == "write"
    return render_template(
        "networks/maps.html",
        networks=networks,
        total_hosts=total_hosts,
        module_access=module_access,
        can_manage_networks=can_manage,
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
    module_access = get_module_access(current_user, "networks")
    can_manage = module_access == "write"
    return render_template(
        "networks/hosts.html",
        network=network,
        hosts=hosts,
        can_generate=can_generate,
        total_hosts=total_hosts,
        module_access=module_access,
        can_manage_networks=can_manage,
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
    require_module_write("networks")
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
    require_module_write("networks")
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
    require_module_write("networks")
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
    require_module_write("networks")
    network = Network.query.get_or_404(network_id)
    db.session.delete(network)
    db.session.commit()
    return _json_response(True, "Network removed.", "warning")


@networks_bp.route("/maps/<int:network_id>/hosts/<int:host_id>/update", methods=["POST"])
@login_required
def update_host(network_id, host_id):
    require_module_write("networks")
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
    require_module_write("networks")
    host = NetworkHost.query.filter_by(id=host_id, network_id=network_id).first_or_404()
    db.session.delete(host)
    db.session.commit()
    return _json_response(True, "Host removed.", "warning")


@networks_bp.route("/tools")
@login_required
def network_tools():
    _require_roles("admin", "technician")
    module_access = get_module_access(current_user, "networks")
    return render_template("networks/tools.html", module_access=module_access)


@networks_bp.route("/tools/ping", methods=["POST"])
@login_required
def run_ping():
    _require_roles("admin", "technician")
    data = request.get_json(silent=True) or request.form
    target = (data.get("target") or "").strip()
    if not target:
        return _json_response(False, "Target host is required.", "warning", 400)
    if not _validate_host(target):
        return _json_response(False, "Target contains invalid characters.", "danger", 400)

    try:
        socket.getaddrinfo(target, None)
    except socket.gaierror:
        return _json_response(False, "Unable to resolve host.", "danger", 400)

    try:
        result = _run_ping_command(target)
    except FileNotFoundError:
        return _json_response(False, "Ping utility is not available on this server.", "danger", 500)
    except subprocess.TimeoutExpired:
        return _json_response(False, "Ping command timed out.", "warning", 504)

    output = (result.stdout or result.stderr or "").strip()
    if not output:
        output = "Ping completed with no output."
    return jsonify(
        success=result.returncode == 0,
        output=output,
        return_code=result.returncode,
        target=target,
    )


@networks_bp.route("/tools/scan-ports", methods=["POST"])
@login_required
def run_port_scan():
    _require_roles("admin", "technician")
    data = request.get_json(silent=True) or request.form
    target = (data.get("target") or "").strip()
    protocol = (data.get("protocol") or "tcp").strip().lower()
    ports_raw = data.get("ports")

    if not target:
        return _json_response(False, "Target host is required.", "warning", 400)
    if not _validate_host(target):
        return _json_response(False, "Target contains invalid characters.", "danger", 400)
    if protocol not in {"tcp", "udp"}:
        return _json_response(False, "Unsupported protocol.", "danger", 400)

    if isinstance(ports_raw, str):
        raw_list = [p for p in ports_raw.split(",")]
    elif isinstance(ports_raw, list):
        raw_list = ports_raw
    else:
        raw_list = []

    try:
        ports = _parse_ports(raw_list) if raw_list else _parse_ports(["22", "80", "443"])
    except ValueError as exc:
        return _json_response(False, str(exc), "danger", 400)

    try:
        socket.getaddrinfo(target, None)
    except socket.gaierror:
        return _json_response(False, "Unable to resolve host.", "danger", 400)

    results = []
    for port in ports:
        if protocol == "tcp":
            is_open = _scan_tcp_port(target, port)
            status = "open" if is_open else "closed"
        else:
            status = "unsupported"
        results.append({"port": port, "protocol": protocol, "status": status})

    summary = {
        "open": sum(1 for r in results if r["status"] == "open"),
        "closed": sum(1 for r in results if r["status"] == "closed"),
        "unsupported": sum(1 for r in results if r["status"] == "unsupported"),
    }

    return jsonify(success=True, target=target, protocol=protocol, results=results, summary=summary)
