#!/bin/bash
# Start script for aware.ai local development

set -e

echo "Starting aware.ai local development environment..."

# Check if docker is running
if ! docker info > /dev/null 2>&1; then
    echo "ERROR: Docker is not running. Please start Docker first."
    exit 1
fi

# Start services
echo "Starting Redis and Ollama..."
docker-compose up -d redis ollama

# Wait for services to be healthy
echo "Waiting for services to be ready..."
docker-compose run --rm model-puller

echo "Starting Gateway..."
docker-compose up -d gateway

echo ""
echo "aware.ai is running!"
echo "  Gateway: http://localhost:8000"
echo "  Health:  http://localhost:8000/health"
echo "  Ready:   http://localhost:8000/health/ready"
echo "  Agents:  http://localhost:8000/v1/agents"
echo ""
echo "Run tests with: python test_e2e.py"
echo "View logs with: docker-compose logs -f gateway"