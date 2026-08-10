---
name: prioritization-frameworks
description: Frameworks and methods for evaluating, ranking, and prioritizing work items
tags: [product, prioritization, framework, rice, impact, decision-making]
---

# Prioritization Frameworks

## When to Use
When facing a backlog of features, bugs, or improvements and needing to decide what to work on first. This applies during sprint planning, roadmap creation, feature selection, and any situation where limited resources must be allocated across competing demands.

## Prerequisites
- A list of candidate items (features, bugs, improvements) to prioritize
- Understanding of business goals and user needs
- Access to relevant data (usage metrics, user feedback, revenue data)

## Steps

### Step 1: Define Evaluation Criteria
Establish what matters before scoring anything.

**Standard criteria (adapt weights to context):**

| Criterion | Weight | Description |
|-----------|--------|-------------|
| User Impact | 30% | How many users affected × how much it matters to them |
| Business Value | 25% | Revenue impact, strategic alignment, competitive advantage |
| Effort | 20% | Engineering time + design + QA (inverse: lower effort = higher score) |
| Confidence | 15% | How sure are we about the impact estimates? |
| Risk | 10% | Technical risk, market risk, dependency risk (inverse) |

### Step 2: Apply RICE Scoring
The RICE framework provides a quantitative starting point.

```
RICE Score = (Reach × Impact × Confidence) / Effort

Reach:    Number of users/items affected per time period (e.g., 500 users/quarter)
Impact:   Scale of impact per user (3=massive, 2=high, 1=medium, 0.5=low, 0.25=minimal)
Confidence: How sure are you? (100%=high, 80%=medium, 50%=low)
Effort:   Person-months to complete (e.g., 0.5 = 2 weeks, 2 = 2 months)
```

**RICE scoring template:**

| Feature | Reach | Impact | Confidence | Effort | RICE Score |
|---------|-------|--------|------------|--------|------------|
| SSO login | 2000 | 2 | 80% | 3 | 1067 |
| Dark mode | 5000 | 0.5 | 100% | 1 | 2500 |
| Export CSV | 500 | 1 | 100% | 0.5 | 1000 |
| API v2 | 100 | 3 | 50% | 5 | 30 |

Higher RICE score = higher priority.

### Step 3: Apply Impact × Effort Matrix
For quick visual prioritization when detailed scoring isn't needed.

```
         HIGH IMPACT
              │
    QUICK     │    BIG
    WINS      │    BETS
   (Do First) │  (Plan Carefully)
              │
──────────────┼──────────────
              │
    FILL      │    MONEY
    INS       │    PIT
   (Do Last)  │  (Avoid/Deprioritize)
              │
         LOW IMPACT

    LOW EFFORT ──────── HIGH EFFORT
```

**How to use:**
1. Plot each item on the 2×2 grid
2. Quick Wins (high impact, low effort) → do immediately
3. Big Bets (high impact, high effort) → plan and resource properly
4. Fill Ins (low impact, low effort) → do when spare capacity exists
5. Money Pits (low impact, high effort) → don't do (or radically simplify)

### Step 4: Apply Weighted Scoring for Complex Decisions
When RICE alone doesn't capture all factors, use a weighted matrix.

**Step-by-step:**
1. List items as rows
2. List criteria as columns
3. Score each item on each criterion (1-5 scale)
4. Multiply by criterion weight
5. Sum weighted scores

```
## Weighted Scoring Example

Criteria weights: User Impact (30%), Business Value (25%), Effort (20%), 
                  Confidence (15%), Risk (10%)

| Item          | User Impact (×0.30) | Business (×0.25) | Effort (×0.20) | Confidence (×0.15) | Risk (×0.10) | TOTAL |
|---------------|--------------------|-----------------|--------------|-------------------|-------------|-------|
| SSO Login     | 4 × 0.30 = 1.20   | 5 × 0.25 = 1.25 | 3 × 0.20 = 0.60 | 4 × 0.15 = 0.60 | 4 × 0.10 = 0.40 | 4.05 |
| Dark Mode     | 3 × 0.30 = 0.90   | 2 × 0.25 = 0.50 | 5 × 0.20 = 1.00 | 5 × 0.15 = 0.75 | 5 × 0.10 = 0.50 | 3.65 |
| Export CSV    | 2 × 0.30 = 0.60   | 3 × 0.25 = 0.75 | 4 × 0.20 = 0.80 | 5 × 0.15 = 0.75 | 5 × 0.10 = 0.50 | 3.40 |
```

### Step 5: Validate with Stakeholders
Prioritization is a social process, not just a math exercise.

- **Share the scored list** with product, engineering, and business stakeholders
- **Identify disagreements** — where do scores diverge? Discuss why.
- **Check for non-negotiables** — compliance deadlines, contractual obligations, critical bugs
- **Apply strategic overrides** — leadership may have context that changes priorities

**Validation checklist:**
- [ ] Engineering confirms effort estimates are realistic
- [ ] Product confirms user impact estimates
- [ ] Business confirms value alignment
- [ ] No compliance/legal deadlines are missed
- [ ] Dependencies between items are accounted for

### Step 6: Create the Prioritized Backlog
Convert scores into an ordered backlog with rationale.

```
## Prioritized Backlog — Q1 2025

### Priority 1: SSO Login (RICE: 1067, Weighted: 4.05)
- Rationale: Enterprise customers require SSO; blocking 3 deals worth $180K ARR
- Dependencies: Identity provider integration
- Timeline: 6 weeks

### Priority 2: Dark Mode (RICE: 2500, Weighted: 3.65)
- Rationale: Most requested feature (top of feedback board), quick win
- Dependencies: Design system token update
- Timeline: 2 weeks

### Priority 3: Export CSV (RICE: 1000, Weighted: 3.40)
- Rationale: Power users need data export for reporting
- Dependencies: None
- Timeline: 1 week

### Deferred
- API v2: Low confidence, high effort. Needs research spike first.
```

## Tool Usage
- **file read**: Review existing backlogs, feature requests, and user feedback
- **file write**: Create prioritization matrices, scoring spreadsheets, and backlog documents
- **web search**: Research RICE framework variations, industry benchmarks, or competitor analysis
- **search_files**: Find existing feature specs, effort estimates, and usage data

## Pitfalls
1. **Don't prioritize by loudest voice** — use data and frameworks, not who asks loudest
2. **Don't ignore effort** — a high-impact feature that takes 6 months may not beat three quick wins
3. **Don't score in isolation** — involve engineering for effort, product for impact, business for value
4. **Don't treat scores as absolute** — frameworks are tools for structured discussion, not oracle answers
5. **Don't forget dependencies** — Item A might be high priority but blocked by Item B
6. **Don't re-prioritize constantly** — change priorities weekly and nothing gets done; review monthly or per sprint

## Verification
- All candidate items have been scored using at least one framework
- Scoring was validated with cross-functional stakeholders
- Prioritized list accounts for dependencies and deadlines
- Rationale for each priority level is documented
- The list is achievable within the planning period

## Quick Reference
```
RICE: (Reach × Impact × Confidence) / Effort
2×2:  Quick Wins → Big Bets → Fill Ins → Money Pits
WEIGHTED: Score 1-5 per criterion × weight → sum → rank

PROCESS:
  1. Define criteria + weights
  2. Score items (RICE or weighted)
  3. Plot on impact/effort matrix
  4. Validate with stakeholders
  5. Create ordered backlog with rationale
```
