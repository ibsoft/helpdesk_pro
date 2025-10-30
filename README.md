# helpdesk_pro
IT Helpdesk Ticketing System

## Overview

Helpdesk Pro is a Flask-based IT helpdesk platform that provides ticketing, inventory, knowledge base, collaboration tools, and administrative utilities for small to mid-sized teams.

## Backup Monitor (New)

The Backup Monitor module adds LTO tape lifecycle management, backup job tracking, storage logistics, and auditing to Helpdesk Pro.

- Catalogue cartridges with capacity, generation, tags, and status.
- Log backup jobs with retention policies, spanning support for multiple tapes, and verification results.
- Record vault locations, chain of custody, and view detailed audit trails.
- Delete jobs or tapes through confirmation modals that surface the impact of each action.

👉 Read the full guide here: [`docs/backup_monitor.md`](docs/backup_monitor.md)

### Quick Start

1. Apply the latest migrations:
   ```bash
   source helpdesk_pro/.venv/bin/activate
   FLASK_APP=helpdesk_pro/wsgi.py flask db upgrade
   ```
2. Sign in as an admin and visit **Manage → Backup Monitor**.
3. Use the summary actions to register tapes or log backup jobs.
4. Manage access rights via **Manage → Access** (look for the `Backup Monitor` module toggle).

## Network Host Import Script

Use `scripts/import_network_hosts.py` to bulk load hosts into an existing network (or create one on the fly). Example:

```bash
python scripts/import_network_hosts.py \
  --csv data/lan_hosts.csv \
  --network 192.168.1.0/24 \
  --create-if-missing \
  --network-name "HQ LAN"
```

- The CSV must contain an `ip_address` column; optional fields are `hostname`, `mac_address`, `device_type`, `assigned_to`, `description`, and `is_reserved`.
- Hosts are updated when they already exist; new rows are inserted automatically.
- Add `--dry-run` to preview changes without committing.
