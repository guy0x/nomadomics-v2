#!/bin/bash
# scripts/setup-strapi.sh — Local Strapi development environment for Nomadomics

set -e

echo "=== Nomadomics Strapi Local Setup ==="

# Check for Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker not found. Install Docker Desktop first."
    exit 1
fi

# Create directories
mkdir -p uploads strapi-app

echo "📦 Starting PostgreSQL..."
docker-compose up -d postgres

echo "⏳ Waiting for PostgreSQL to be ready..."
sleep 5

echo "🚀 Starting Strapi..."
docker-compose up -d strapi

echo ""
echo "✅ Strapi is starting at http://localhost:1337/admin"
echo ""
echo "To manage:"
echo "  docker-compose logs -f strapi    # View logs"
echo "  docker-compose stop             # Stop services"
echo "  docker-compose down -v          # Remove volumes (destructive)"
echo ""
echo "After first run, create admin account at /admin"
echo "Then configure content types per Phase 1.4 in superplan"