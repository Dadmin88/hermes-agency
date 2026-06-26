---
name: design-system-patterns
description: Component libraries, design tokens, naming conventions, and documentation
tags: [design, design-system, tokens, components, patterns]
---

# Design System Patterns

## When to Use
When building or maintaining a design system, component library, or shared UI toolkit.

## Prerequisites
- Understanding of the product's visual language
- Access to existing components and designs

## Steps

### Step 1: Define design tokens
```json
{
  "color": {
    "primary": { "50": "#...", "500": "#...", "900": "#..." },
    "neutral": { "50": "#...", "500": "#...", "900": "#..." },
    "semantic": {
      "success": "#...",
      "warning": "#...",
      "error": "#..."
    }
  },
  "spacing": {
    "xs": "4px", "sm": "8px", "md": "16px", "lg": "24px", "xl": "32px"
  },
  "typography": {
    "fontFamily": { "sans": "...", "mono": "..." },
    "fontSize": { "xs": "12px", "sm": "14px", "base": "16px", "lg": "20px" }
  }
}
```

### Step 2: Build component primitives
Start with atoms:
- Button (variants: primary, secondary, ghost, danger)
- Input (text, number, search, textarea)
- Typography (heading, body, caption)
- Icon (consistent size, style)
- Badge/Tag

### Step 3: Compose molecules
Combine atoms:
- Search bar = Input + Button
- Card = Typography + Button + Badge
- Form field = Label + Input + Error message
- Navigation item = Icon + Typography

### Step 4: Document components
For each component:
- Name and description
- Props/parameters
- Usage examples
- Do's and don'ts
- Accessibility notes

### Step 5: Establish naming conventions
- Components: PascalCase (`Button`, `CardHeader`)
- Props: camelCase (`onClick`, `isDisabled`)
- CSS classes: kebab-case (`btn-primary`, `card-header`)
- Tokens: camelCase (`colorPrimary`, `spacingMd`)

## Tool Usage
- `write_file` for creating component documentation
- `read_file` for reviewing existing components

## Pitfalls
1. Don't build everything at once — start with the most-used components
2. Don't skip documentation — undocumented systems get misused
3. Don't make components too flexible — constraints enable consistency
4. Don't forget accessibility — build it into the primitives
5. Don't version inconsistently — use semver for the design system

## Quick Reference
Tokens: Colors, spacing, typography, shadows
Primitives: Button, Input, Typography, Icon, Badge
Molecules: Search bar, Card, Form field, Nav item
Naming: PascalCase components, camelCase props, kebab-case classes