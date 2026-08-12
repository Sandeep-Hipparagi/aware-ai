#!/usr/bin/env pwsh
# Start script for aware.ai local development (Windows PowerShell)

$ErrorActionPreference = "Stop"

Write-Host "Starting aware.ai local development environment..." -ForegroundColor Green

# Check if docker is running
try {
    docker info > $null 2>&1
} catch {
    Write-Host "ERROR: Docker is not running. Please start Docker first." -ForegroundColor Red
    exit 1
}

# Start services
Write-Host "Starting Redis and Ollama..." -ForegroundColor Cyan
docker-compose up -d redis ollama

# Wait for services to be healthy
Write-Host "Waiting for services to be ready..." -ForegroundColor Cyan
docker-compose run --rm model-puller

Write-Host "Starting Gateway..." -ForegroundColor Cyan
docker-compose up -d gateway

Write-Host ""
Write-Host "aware.ai is running!" -ForegroundColor Green
Write-Host "  Gateway: http://localhost:8000" -ForegroundColor Cyan
Write-Host "  Health:  http://localhost:8000/health" -ForegroundColor Cyan
Write-Host "  Ready:   http://localhost:8000/health/ready" -ForegroundColor Cyan
Write-Host "  Agents:  http://localhost:8000/v1/agents" -ForegroundColor Cyan
Write-Host ""
Write-Host "Run tests with: python test_e2e.py" -ForegroundColor Yellow
Write-Host "View logs with: docker-compose logs -f gateway" -ForegroundColor Yellow