# Zilliz MCP Server - Testing Guide

This document describes the testing setup and coverage for the Zilliz MCP Server project.

## 📋 Test Overview

We've implemented a comprehensive unit testing suite that covers the core functionality of the Zilliz MCP Server. The tests focus on the most critical components to ensure reliability and correctness.

### ✅ Test Statistics
- **Total Tests**: 118
- **Test Modules**: 5 modules
- **Coverage**: Core functionality (Settings, HTTP Client, API Tools, Billing Tools)
- **Framework**: pytest with asyncio support

## 🧪 Test Structure

```
tests/
├── __init__.py
├── conftest.py              # pytest configuration and shared fixtures
├── pytest.ini              # pytest settings
├── unit/
│   ├── __init__.py
│   ├── test_settings.py     # Configuration validation tests (12 tests)
│   ├── test_openapi_client.py  # HTTP client tests (40 tests)
│   └── tools/
│       ├── __init__.py
│       ├── test_zilliz_tools.py    # Zilliz Cloud API tests (19 tests)
│       ├── test_milvus_tools.py    # Milvus data operations tests (23 tests)
│       └── test_billing_tools.py   # Billing usage and invoice tests (24 tests)
```

## 🎯 Test Coverage

### 1. Configuration Tests (`test_settings.py`)
**Focus**: Environment variable handling and validation

- ✅ Valid configuration loading
- ✅ Default value handling
- ✅ Required field validation (token)
- ✅ URI format validation
- ✅ Port range validation
- ✅ Error handling for invalid inputs
- ✅ Singleton behavior verification

### 2. HTTP Client Tests (`test_openapi_client.py`)
**Focus**: API communication and error handling

- ✅ Request header generation
- ✅ Response parsing (success/error)
- ✅ HTTP methods (GET, POST, DELETE)
- ✅ Query parameter handling
- ✅ Business error code handling
- ✅ JSON parsing error handling
- ✅ URL construction for control/data planes
- ✅ Input validation

### 3. Zilliz Tools Tests (`test_zilliz_tools.py`)
**Focus**: Control plane operations

- ✅ Project listing and management
- ✅ Cluster operations (list, create, describe)
- ✅ Cluster lifecycle (suspend, resume)
- ✅ Error handling and data formatting
- ✅ API parameter validation
- ✅ Response data transformation

### 4. Milvus Tools Tests (`test_milvus_tools.py`)
**Focus**: Data plane operations

- ✅ Database management
- ✅ Collection operations (create, describe, list)
- ✅ Data operations (insert, search, query, delete)
- ✅ Vector search functionality
- ✅ Parameter validation and error handling

### 5. Billing Tools Tests (`test_billing_tools.py`)
**Focus**: Usage and invoice operations

- ✅ Dates sent as midnight-UTC RFC3339, inclusive end day
- ✅ Date format, order and range-cap validation
- ✅ Usage summary grouping (cluster, project, cost type, region, day)
- ✅ Cluster and project filters
- ✅ Rounding applied only after summing
- ✅ Invoice listing and field mapping
- ✅ Error handling

## 🚀 Running Tests

### Quick Start
```bash
# Run all tests
./run_tests.sh

# Or manually:
ZILLIZ_CLOUD_TOKEN=test uv run --extra test pytest tests/unit/ -v
```

> Settings are validated at import time, so `ZILLIZ_CLOUD_TOKEN` must be set (any value) for the tests to load. The tests never call the real API.

### Specific Test Categories
```bash
# Configuration tests only
uv run pytest tests/unit/test_settings.py -v

# HTTP client tests only
uv run pytest tests/unit/test_openapi_client.py -v

# API tools tests only
uv run pytest tests/unit/tools/ -v

# Billing tools tests only
uv run pytest tests/unit/tools/test_billing_tools.py -v

# Run tests with coverage
uv add pytest-cov
uv run pytest tests/unit/ --cov=src/zilliz_mcp_server --cov-report=html
```

## 🔧 Test Configuration

### Dependencies
The testing setup uses these key dependencies:
- `pytest` - Test framework
- `pytest-asyncio` - Async test support
- `pytest-mock` - Mocking utilities
- `responses` - HTTP request mocking

### Async Test Support
All async tests are automatically handled using:
```python
# Enable asyncio for all async tests in a module
pytestmark = pytest.mark.asyncio
```

### Fixtures and Mocking
- **Shared fixtures** in `conftest.py` for common test data
- **HTTP mocking** using `responses` library
- **Module mocking** to isolate units under test
- **Environment variable mocking** for configuration tests

## 🎯 Testing Strategy

### What We Test
1. **Input Validation** - Ensure proper error handling for invalid inputs
2. **Business Logic** - Verify core functionality works as expected
3. **Error Handling** - Test error scenarios and edge cases
4. **Data Transformation** - Validate API response formatting
5. **Configuration** - Ensure settings are loaded and validated correctly

### What We Don't Test (Intentionally)
1. **External API Integration** - We mock all external calls
2. **Complex End-to-End Flows** - Focus on unit-level testing
3. **UI/UX Components** - This is a backend service
4. **Performance Testing** - Out of scope for unit tests

## 📊 Test Quality Metrics

- **Fast Execution**: All 62 tests run in under 1 second
- **Isolated**: Each test is independent and can run alone
- **Deterministic**: Tests produce consistent results
- **Comprehensive**: Cover all critical code paths
- **Maintainable**: Clear test structure and naming

## 🔍 Key Testing Patterns

### 1. Mocking External Dependencies
```python
@patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
async def test_list_projects_success(self, mock_client, sample_project_response):
    mock_client.control_plane_api_request.return_value = sample_project_response
    # Test implementation...
```

### 2. Environment Variable Testing
```python
def test_init_with_valid_env_vars(self, mock_env_vars):
    with patch.dict(os.environ, mock_env_vars, clear=True):
        config = ZillizConfig()
        assert config.token == "test-token-123"
```

### 3. Exception Testing
```python
def test_invalid_port_range(self):
    env_vars = {"ZILLIZ_CLOUD_TOKEN": "test-token", "MCP_SERVER_PORT": "99999"}
    with patch.dict(os.environ, env_vars, clear=True):
        with pytest.raises(ValueError, match="MCP_SERVER_PORT must be between 1 and 65535"):
            ZillizConfig()
```

## 🚀 Next Steps

For further test improvements, consider:

1. **Integration Tests** - Add tests that verify component interactions
2. **Performance Tests** - Benchmark critical operations
3. **End-to-End Tests** - Test complete user workflows
4. **Load Tests** - Verify behavior under concurrent usage
5. **Security Tests** - Validate input sanitization and auth handling

## 📝 Contributing to Tests

When adding new functionality:

1. **Write tests first** (TDD approach)
2. **Follow naming conventions** (`test_<functionality>_<scenario>`)
3. **Use descriptive assertions** with clear error messages
4. **Mock external dependencies** to keep tests isolated
5. **Test both success and error cases**
6. **Keep tests simple and focused** on one thing

---

**Happy Testing! 🧪✨** 