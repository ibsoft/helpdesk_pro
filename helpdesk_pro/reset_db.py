#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reset_db.py — Safely reset and rebuild the Helpdesk Pro PostgreSQL database.
Drops, recreates, migrates, and seeds an admin user.
"""

import os
import subprocess
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# ───────────── Configuration ───────────── #
DB_NAME = os.getenv("POSTGRES_DB", "helpdesk_pro")
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "superpass")
DB_HOST = os.getenv("POSTGRES_HOST", "192.168.7.10")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")

APP_CONTEXT = "app:create_app"  # Flask app factory

# ───────────── Helper Functions ───────────── #


def run(cmd):
    print(f"→ {cmd}")
    subprocess.run(cmd, shell=True, check=True)


def drop_and_create_db():
    print(f"\n🧹 Dropping and recreating database '{DB_NAME}'…")

    conn = psycopg2.connect(
        dbname="postgres",
        user=DB_USER,
        password=DB_PASS,
        host=DB_HOST,
        port=DB_PORT,
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()

    # Terminate active sessions
    cur.execute(f"""
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE datname = '{DB_NAME}' AND pid <> pg_backend_pid();
    """)

    # Drop and recreate
    cur.execute(f"DROP DATABASE IF EXISTS {DB_NAME};")
    cur.execute(f"CREATE DATABASE {DB_NAME};")

    cur.close()
    conn.close()
    print("✅ Database recreated successfully.\n")


def reset_migrations():
    if os.path.exists("migrations"):
        print("🗑️ Removing old migrations directory…")
        import shutil
        shutil.rmtree("migrations")
    run("flask db init")
    run('flask db migrate -m "Reset schema"')
    run("flask db upgrade")
    print("✅ Database schema rebuilt successfully.\n")


def create_admin_user():
    print("👤 Creating default admin user…")
    from app import create_app, db
    from app.models.user import User

    app = create_app()
    with app.app_context():
        if not User.query.filter_by(username="admin").first():
            admin = User(
                username="admin",
                email="admin@example.com",
                role="admin",
                department="IT",
                active=True,
            )
            admin.set_password("Admin123!")
            db.session.add(admin)
            db.session.commit()
            print("✅ Admin user created (username=admin, password=Admin123!).")
        else:
            print("ℹ️ Admin user already exists.")


def main():
    print("🚀 Starting full database reset for Helpdesk Pro…")
    try:
        drop_and_create_db()
        reset_migrations()
        create_admin_user()
        print("\n🎉 All done! Database is clean and ready.\n")
    except Exception as e:
        print(f"❌ ERROR: {e}")
        raise


if __name__ == "__main__":
    main()
