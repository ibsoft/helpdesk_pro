# Helpdesk Pro — Flask + PostgreSQL Ticketing System

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate   # ή .venv\Scripts\activate στα Windows
pip install -r requirements.txt
flask db upgrade
flask run
```

## Default admin
username: admin
password: change_me

## PostgreSQL connection
postgresql+psycopg2://itdesk:superpass@192.168.7.10:5432/itdesk

## Multilingual
English / Greek (switch via Accept-Language header)

## Notes
- Secure headers (CSP, HSTS, X-Frame-Options)
- Email notifications (SMTP TLS)
- JWT REST API
- Bootstrap 5 + FontAwesome + Light/Dark Mode Switch
- Logging in logs/helpdesk.log
