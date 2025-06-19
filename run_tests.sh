#!/bin/bash

echo "🚀 Running Zilliz MCP Server Unit Tests..."
echo "============================================"

# Run all unit tests
echo "📦 Installing test dependencies..."
uv add --group test pytest pytest-asyncio pytest-mock responses

echo "🧪 Running unit tests..."
uv run pytest tests/unit/ -v --tb=short

echo "✅ Test run completed!"
echo ""
echo "📊 For test coverage report, run:"
echo "   uv add pytest-cov"
echo "   uv run pytest tests/unit/ --cov=src/zilliz_mcp_server --cov-report=html" 