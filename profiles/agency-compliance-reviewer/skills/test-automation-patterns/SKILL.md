---
name: test-automation-patterns
description: Playwright and Selenium test automation patterns, page objects, fixtures
tags: [qa, testing, automation, playwright, selenium, page-objects]
---

# Test Automation Patterns

## When to Use
When writing automated UI/integration tests, setting up test infrastructure, or improving test reliability.

## Prerequisites
- Test framework installed (Playwright, Selenium, Cypress)
- Application under test accessible

## Steps

### Step 1: Set up the test framework
```bash
# Playwright
npm init playwright@latest
npx playwright install

# Selenium
pip install selenium webdriver-manager
```

### Step 2: Use the Page Object pattern
```python
# page_objects/login_page.py
class LoginPage:
    def __init__(self, page):
        self.page = page
        self.email_input = page.locator('#email')
        self.password_input = page.locator('#password')
        self.submit_button = page.locator('button[type="submit"]')

    async def login(self, email, password):
        await self.email_input.fill(email)
        await self.password_input.fill(password)
        await self.submit_button.click()

    async def get_error_message(self):
        return await self.page.locator('.error-message').text_content()
```

### Step 3: Write test fixtures
```python
# conftest.py
import pytest

@pytest.fixture
async def logged_in_page(page):
    login_page = LoginPage(page)
    await login_page.login('test@example.com', 'password')
    return page
```

### Step 4: Write reliable tests
```python
# tests/test_login.py
async def test_successful_login(page):
    login_page = LoginPage(page)
    await login_page.login('test@example.com', 'correct-password')
    await page.wait_for_url('/dashboard')
    assert await page.title() == 'Dashboard'

async def test_failed_login(page):
    login_page = LoginPage(page)
    await login_page.login('test@example.com', 'wrong-password')
    error = await login_page.get_error_message()
    assert 'Invalid credentials' in error
```

### Step 5: Handle flaky tests
- Use explicit waits, not `sleep()`
- Wait for elements to be visible/enabled before interacting
- Use test IDs (`data-testid`) instead of CSS selectors
- Retry on transient failures (network, animation)
- Isolate tests — each test should be independent

## Tool Usage
- `terminal` for running tests
- `write_file` for creating test files
- `read_file` for reviewing existing tests

## Pitfalls
1. Don't use `sleep()` — use explicit waits
2. Don't rely on CSS selectors — use test IDs
3. Don't write dependent tests — each should be independent
4. Don't skip error paths — test failure scenarios too
5. Don't ignore flaky tests — fix them or mark them as known issues

## Quick Reference
Page Object: Encapsulate page interactions in classes
Fixtures: Set up test preconditions
Selectors: data-testid > aria > CSS
Waits: wait_for_selector > wait_for_url > sleep
Independence: Each test sets up and tears down its own state