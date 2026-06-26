---
name: accessibility-audit
description: WCAG 2.1 AA compliance audit for web interfaces and applications
tags: [design, accessibility, wcag, aria, keyboard, screen-reader, audit]
---

# Accessibility Audit

## When to Use
When reviewing a web interface, component, or page for accessibility compliance. This applies before launches, after UI changes, when receiving accessibility complaints, or as part of a regular audit cycle. Target: WCAG 2.1 Level AA compliance.

## Prerequisites
- Access to the live application or local dev server
- Browser with developer tools (Chrome/Firefox)
- Understanding of WCAG 2.1 AA requirements
- Terminal for running automated tools

## Steps

### Step 1: Run Automated Accessibility Scanners
Automated tools catch ~30-40% of accessibility issues. Start here for quick wins.

```bash
# Install and run axe-core CLI
npx @axe-core/cli <URL> --tags wcag2a,wcag2aa,wcag21aa

# Install pa11y for CI-friendly scanning
npx pa11y <URL> --standard WCAG2AA --reporter json

# Lighthouse accessibility audit (via Chrome CLI)
npx lighthouse <URL> --only-categories=accessibility --output=json --quiet

# For React projects, add eslint-plugin-jsx-a11y
npx eslint src/ --plugin jsx-a11y --rule 'jsx-a11y/anchor-is-valid: error'
```

Record all automated findings. These are guaranteed issues (high confidence, no false positives for most rules).

### Step 2: Test Keyboard Navigation
Navigate the entire interface using only the keyboard.

**Test sequence:**
1. Press `Tab` to move forward through all interactive elements
2. Press `Shift+Tab` to move backward
3. Press `Enter` to activate links and buttons
4. Press `Space` to toggle checkboxes and activate buttons
5. Press arrow keys in menus, tabs, and radio groups
6. Press `Escape` to close modals and dismiss popups

**Check for:**
- [ ] All interactive elements are reachable via Tab
- [ ] Tab order follows visual layout (left-to-right, top-to-bottom)
- [ ] Focus indicator is visible (not `outline: none` without replacement)
- [ ] No keyboard traps (can always Tab away from any element)
- [ ] Skip-to-content link exists and works
- [ ] Modals trap focus when open, restore focus when closed
- [ ] Custom components follow WAI-ARIA keyboard patterns

### Step 3: Test with a Screen Reader
Verify the experience for screen reader users.

**Tools:** NVDA (Windows), VoiceOver (Mac), Orca (Linux)

**Test sequence:**
1. Navigate by headings (H key in NVDA) — can you understand the page structure?
2. Navigate by landmarks (D key) — are nav, main, complementary regions labeled?
3. Read all form fields — are labels announced correctly?
4. Test all interactive elements — are roles and states announced?
5. Test dynamic content — are live regions announced?

**Check for:**
- [ ] Page has a descriptive `<title>`
- [ ] Headings create a logical outline (H1 → H2 → H3, no skips)
- [ ] All images have appropriate alt text (decorative images: `alt=""`)
- [ ] Form fields have associated labels (`<label for="id">` or `aria-label`)
- [ ] Error messages are announced (via `aria-live` or `role="alert"`)
- [ ] Dynamic content changes are announced (`aria-live` regions)
- [ ] Links and buttons have descriptive text (not "click here" or "read more")

### Step 4: Check Color and Contrast
Verify visual accessibility.

```bash
# Use browser extension: axe DevTools, WAVE, or Colour Contrast Analyser

# Programmatic check with node
npx color-contrast-checker "#333333" "#FFFFFF"  # Should show ratio ≥ 4.5:1
```

**Check for:**
- [ ] Text contrast ratio ≥ 4.5:1 (normal text) or ≥ 3:1 (large text ≥18pt or 14pt bold)
- [ ] UI component contrast ≥ 3:1 against adjacent colors
- [ ] Information is not conveyed by color alone (add icons, patterns, or text)
- [ ] Focus indicators have sufficient contrast
- [ ] Links are distinguishable from body text (not just by color)

### Step 5: Validate Semantic HTML and ARIA
Inspect the DOM for proper structure.

```bash
# In browser console, check for common issues:
# Missing landmarks
document.querySelectorAll('main, nav, aside, header, footer').length

# Images without alt
document.querySelectorAll('img:not([alt])').length

# Buttons without accessible names
document.querySelectorAll('button:not([aria-label]):empty').length

# Inputs without labels
document.querySelectorAll('input:not([aria-label]):not([id])').length
```

**Check for:**
- [ ] Semantic HTML used over divs/spans where possible (`<nav>`, `<main>`, `<button>`)
- [ ] ARIA roles used correctly (not duplicating native HTML semantics)
- [ ] `aria-label` or `aria-labelledby` on landmark regions
- [ ] `aria-expanded` on collapsible elements
- [ ] `aria-current` for current navigation item
- [ ] No `tabindex` > 0 (use 0 or -1 only)

### Step 6: Compile Audit Report
Organize findings by WCAG criterion and severity.

```
## Accessibility Audit Report

**URL:** [audited URL]
**Date:** [date]
**Standard:** WCAG 2.1 AA

### Critical (Blocks users from completing tasks)
1. [WCAG X.X.X] [Element]: [Issue] → [Fix]
2. [WCAG X.X.X] [Element]: [Issue] → [Fix]

### Serious (Significant barrier, workaround possible)
1. [WCAG X.X.X] [Element]: [Issue] → [Fix]

### Moderate (Difficulty but usable)
1. [WCAG X.X.X] [Element]: [Issue] → [Fix]

### Minor (Best practice, not a violation)
1. [Element]: [Suggestion]

### Summary
- Critical: X
- Serious: X
- Moderate: X
- Minor: X
- Automated scan score: X/100
```

## Tool Usage
- **terminal**: Run axe-core CLI, pa11y, Lighthouse, and eslint for automated scanning
- **file read**: Review HTML/JSX source for semantic structure and ARIA usage
- **search_files**: Find instances of `outline: none`, missing `alt`, `tabindex`, etc.
- **web search**: Look up specific WCAG criteria or WAI-ARIA patterns

## Pitfalls
1. **Don't rely on automated tools alone** — they catch only ~30% of issues
2. **Don't add ARIA to fix bad HTML** — use semantic elements first, ARIA as supplement
3. **Don't remove focus outlines** — `outline: none` without replacement is an accessibility violation
4. **Don't use `tabindex` > 0** — it disrupts natural tab order; use DOM order instead
5. **Don't use placeholder text as labels** — placeholders disappear on focus and are not announced by all screen readers
6. **Don't assume color-blindness is rare** — ~8% of men have some form of color vision deficiency

## Verification
- Automated scan shows 0 critical/serious violations
- Complete keyboard navigation test passes
- Screen reader announces all content and interactive elements correctly
- Color contrast meets WCAG AA ratios
- Page heading outline is logical and complete

## Quick Reference
```
AUDIT → Automated scan (axe/pa11y) → Keyboard test → Screen reader test
  → Color/contrast check → Semantic HTML review → Compile report

WCAG AA QUICK CHECKS:
  Contrast: 4.5:1 text, 3:1 large text & UI
  Keyboard: All interactive elements reachable, visible focus
  Labels: Every input has a label, every image has alt
  Headings: Logical H1→H2→H3, one H1
  Live regions: Dynamic content announced
