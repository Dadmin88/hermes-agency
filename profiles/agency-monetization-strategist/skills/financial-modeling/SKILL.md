---
name: financial-modeling
description: Budget templates, forecasting, unit economics, and cost analysis
tags: [operations, finance, budget, forecasting, unit-economics]
---

# Financial Modeling

## When to Use
When creating budgets, forecasting revenue/expenses, analyzing unit economics, or evaluating business decisions.

## Prerequisites
- Historical financial data (if available)
- Understanding of revenue model

## Steps

### Step 1: Build a budget template
```markdown
## Monthly Budget

### Revenue
- Product sales: $X
- Subscriptions: $X
- Services: $X
- **Total Revenue: $X**

### Expenses
- Personnel (salaries + benefits): $X
- Infrastructure (hosting, tools): $X
- Marketing: $X
- Operations (office, legal, insurance): $X
- **Total Expenses: $X**

### Net
- **Profit/Loss: $X**
- **Margin: X%**
```

### Step 2: Calculate unit economics
```
Customer Acquisition Cost (CAC) = Marketing Spend / New Customers
Lifetime Value (LTV) = Average Revenue per Customer × Average Lifespan
LTV:CAC Ratio = LTV / CAC (target: >3:1)
Payback Period = CAC / Monthly Revenue per Customer
```

### Step 3: Build revenue forecast
```
Month 1: Starting Users × Growth Rate × ARPU
Month 2: (Starting + New - Churned) × ARPU
...
Month 12: Projected Users × ARPU
```

### Step 4: Analyze costs
- Fixed costs: Same regardless of volume (rent, salaries)
- Variable costs: Scale with volume (hosting, support)
- Break-even: Fixed Costs / (Price - Variable Cost per Unit)

### Step 5: Create scenarios
- **Base case**: Most likely outcome
- **Optimistic**: Best realistic case
- **Pessimistic**: Worst realistic case
- Document assumptions for each scenario

## Tool Usage
- `write_file` for creating financial documents
- `read_file` for reviewing existing financials

## Pitfalls
1. Don't confuse revenue with profit — always show both
2. Don't ignore churn — it compounds over time
3. Don't use round numbers without justification
4. Don't forget to document assumptions
5. Don't present one scenario — show base, optimistic, pessimistic

## Quick Reference
CAC = Marketing Spend / New Customers
LTV = ARPU × Average Lifespan
LTV:CAC target: >3:1
Break-even = Fixed Costs / (Price - Variable Cost)
Scenarios: Base, Optimistic, Pessimistic