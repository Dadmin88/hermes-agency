---
name: design-review-checklist
description: Systematic design review covering visual hierarchy, consistency, and usability
tags: [design, review, checklist, usability, visual, hierarchy]
---

# Design Review Checklist

## When to Use
When reviewing a design, UI component, page layout, or visual deliverable before shipping.

## Prerequisites
- Access to the design file or rendered output
- Understanding of the target audience and use case

## Steps

### Step 1: Visual hierarchy check
- [ ] Primary action is visually dominant (size, color, position)
- [ ] Headings create clear information hierarchy
- [ ] Whitespace separates logical sections
- [ ] Eye flow follows the intended reading path
- [ ] No more than 3 visual weights (primary, secondary, tertiary)

### Step 2: Consistency check
- [ ] Colors match the brand palette
- [ ] Typography uses consistent scale (e.g., 12, 14, 16, 20, 24, 32)
- [ ] Spacing follows a consistent system (4px, 8px, 16px, 24px, 32px)
- [ ] Similar elements look similar (buttons, inputs, cards)
- [ ] Icon style is consistent (filled vs outlined, size)

### Step 3: Accessibility check
- [ ] Text contrast ratio >= 4.5:1 (AA) or >= 7:1 (AAA)
- [ ] Interactive elements have visible focus states
- [ ] Touch targets >= 44x44px
- [ ] Color is not the only way to convey information
- [ ] Images have alt text

### Step 4: Responsiveness check
- [ ] Works at mobile (320px), tablet (768px), desktop (1024px+)
- [ ] No horizontal scrolling at any breakpoint
- [ ] Text remains readable at all sizes
- [ ] Images/media scale appropriately
- [ ] Navigation adapts to screen size

### Step 5: Usability check
- [ ] Primary task is obvious within 3 seconds
- [ ] Form labels are clear and persistent
- [ ] Error messages are helpful and specific
- [ ] Loading states are clear
- [ ] Empty states guide the user

## Tool Usage
- `read_file` for reading design specs
- `write_file` for writing review notes

## Pitfalls
1. Don't review without a checklist — you'll miss things
2. Don't focus only on aesthetics — usability matters more
3. Don't skip accessibility — it's not optional
4. Don't assume the desktop view — check mobile first
5. Don't approve without testing interactions — static mockups hide issues

## Quick Reference
1. Visual hierarchy: Is the most important thing the most visible?
2. Consistency: Do similar things look similar?
3. Accessibility: Can everyone use it?
4. Responsiveness: Does it work on all screens?
5. Usability: Is the task obvious and easy?