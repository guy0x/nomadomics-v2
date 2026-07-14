#!/usr/bin/env python3
"""setup-strapi.py — Initialize Strapi v5 backend for Nomadomics (local dev mode).

Creates Strapi app with PostgreSQL config. Run from nomadomics-v2 directory.

Usage:
    python3 scripts/setup-strapi.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

def main():
    root = Path(__file__).parent.parent
    
    # Check Node.js
    try:
        node_version = subprocess.run(["node", "--version"], capture_output=True, text=True)
        print(f"Node.js: {node_version.stdout.strip()}")
    except Exception:
        print("ERROR: Node.js not found. Install Node.js 20+ first.")
        sys.exit(1)
    
    # Create .env.strapi if missing
    env_path = root / ".env.strapi"
    if not env_path.exists():
        env_content = """# Strapi environment (LOCAL DEVELOPMENT ONLY)
HOST=0.0.0.0
PORT=1337
APP_KEYS=key1,key2,key3,key4
API_TOKEN_SALT=dev_salt_change_me
ADMIN_JWT_SECRET=dev_admin_jwt_change_me
TRANSFER_TOKEN_SALT=dev_transfer_salt_change_me
JWT_SECRET=dev_jwt_change_me
DATABASE_CLIENT=postgres
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=nomadomics
DATABASE_USERNAME=nomadomics
DATABASE_PASSWORD=nomadomics_dev_password
MCP_SERVER=true
"""
        env_path.write_text(env_content)
        print(f"Created {env_path}")
    
    # Create uploads directory
    uploads = root / "uploads"
    uploads.mkdir(exist_ok=True)
    
    print("""
=== Nomadomics Strapi Setup ===

Prerequisites (manual):
1. PostgreSQL 16 running on localhost:5432
2. Database 'nomadomics' exists:
   createdb nomadomics -U postgres
   Or via Docker: docker run --name pg -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16

Next steps:
    npm create strapi@latest . -- --quickstart --no-run
    npm install
    npm run dev

After setup, create admin account at http://localhost:1337/admin
""")

if __name__ == "__main__":
    main()