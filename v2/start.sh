#!/bin/bash

# Anthropic Interviewer - Development Startup Script
# Usage: ./start.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==================================="
echo "  Anthropic Interviewer"
echo "==================================="

# Check for API key
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo ""
    echo "WARNING: ANTHROPIC_API_KEY not set!"
    echo "Set it with: export ANTHROPIC_API_KEY='your-key'"
    echo ""
fi

# Install frontend dependencies if needed
if [ ! -d "$PROJECT_DIR/frontend/node_modules" ]; then
    echo "Installing frontend dependencies..."
    cd "$PROJECT_DIR/frontend"
    npm install
    cd "$PROJECT_DIR"
fi

echo ""
echo "Starting services..."
echo ""

# Start backend in background
echo "[Backend] Starting FastAPI on http://localhost:8000"
cd "$PROJECT_DIR"
python3 -m uvicorn src.api.main:app --reload --port 8000 &
BACKEND_PID=$!

# Wait for backend to start
sleep 2

# Start frontend
echo "[Frontend] Starting Vite on http://localhost:5173"
cd "$PROJECT_DIR/frontend"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "==================================="
echo "  Services Running"
echo "==================================="
echo ""
echo "  Frontend: http://localhost:5173"
echo "  Backend:  http://localhost:8000"
echo "  API Docs: http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop all services"
echo ""

# Handle cleanup on exit
cleanup() {
    echo ""
    echo "Stopping services..."
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    exit 0
}

trap cleanup INT TERM

# Wait for processes
wait
