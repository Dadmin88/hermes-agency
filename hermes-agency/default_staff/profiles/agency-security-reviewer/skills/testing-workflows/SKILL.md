---
name: testing-workflows
description: Write and run tests systematically using pytest, jest, and TDD patterns
tags: [engineering, testing, pytest, jest, tdd, coverage]
---

# Testing Workflows

## When to Use
When writing tests for new code, fixing failing tests, improving test coverage, or following test-driven development.

## Prerequisites
- Project test framework identified (pytest, jest, etc.)
- Test files located in the project

## Steps

### Step 1: Identify the test framework
```bash
# Python
cat pyproject.toml | grep -A5 "\[tool.pytest"
ls tests/ test/ 2>/dev/null

# JavaScript/TypeScript
cat package.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('scripts',{}).get('test',''))"
ls __tests__/ tests/ *.spec.* *.test.* 2>/dev/null
```

### Step 2: Run existing tests first
```bash
# Python (pytest)
python3 -m pytest -x -v 2>&1 | tail -20

# JavaScript (jest/npm)
npm test 2>&1 | tail -20

# Makefile
make test 2>&1 | tail -20
```

### Step 3: Write tests following project conventions
- Match existing test file naming (`test_*.py`, `*_test.py`, `*.spec.ts`)
- Match existing test structure (fixtures, mocks, assertions)
- Test one behavior per test function
- Use descriptive test names that explain the expected behavior

### Step 4: Run targeted tests
```bash
# Run single test file
python3 -m pytest tests/test_feature.py -v

# Run single test function
python3 -m pytest tests/test_feature.py::test_specific_case -v

# Run with coverage
python3 -m pytest --cov=src --cov-report=term-missing
```

### Step 5: Follow TDD when appropriate
1. RED: Write a failing test that defines the desired behavior
2. GREEN: Write the minimum code to make the test pass
3. REFACTOR: Clean up the code while keeping tests green

## Tool Usage
- `terminal` for running tests
- `write_file` for creating test files
- `read_file` for reading existing tests

## Pitfalls
1. Don't skip running existing tests first — know the baseline
2. Don't write tests that depend on external services without mocking
3. Don't test implementation details — test behavior
4. Don't leave failing tests — fix them or mark them as expected failures
5. Don't ignore test coverage — aim for >80% on new code

## Verification
- All existing tests still pass
- New tests pass
- Coverage increased or maintained
- Test names clearly describe what is being tested

## Quick Reference
```bash
# Run all tests
python3 -m pytest -x -v

# Run with coverage
python3 -m pytest --cov=src --cov-report=term-missing

# Run specific test
python3 -m pytest tests/test_file.py::test_name -v

# Run tests matching pattern
python3 -m pytest -k "pattern" -v
```