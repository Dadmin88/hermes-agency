---
name: adversarial-testing
description: Threat modeling, exploit analysis, fuzz testing, and penetration testing
tags: [qa, security, red-team, threat-modeling, penetration-testing]
---

# Adversarial Testing

## When to Use
When performing security testing, threat modeling, or adversarial analysis of a system.

## Prerequisites
- Access to the target system
- Understanding of the system architecture

## Steps

### Step 1: Threat modeling
Identify:
- **Assets**: What's valuable? (data, access, reputation)
- **Threats**: Who might attack? (external, internal, automated)
- **Vulnerabilities**: Where are the weaknesses? (input validation, auth, encryption)
- **Impact**: What's the worst case? (data breach, downtime, financial loss)

### Step 2: OWASP Top 10 testing
```bash
# SQL Injection
' OR 1=1 --
'; DROP TABLE users; --

# XSS
<script>alert('xss')</script>
<img src=x onerror=alert('xss')>

# CSRF
# Check for anti-CSRF tokens on state-changing requests

# Insecure Direct Object Reference
# Change IDs in URLs: /user/123 → /user/124

# Security Misconfiguration
# Check default credentials, exposed debug info, verbose errors
```

### Step 3: Fuzz testing
```bash
# Send random/malformed inputs
for i in $(seq 1 1000); do
  curl -X POST "$URL" -d "input=$(head -c 100 /dev/urandom | base64)"
done

# Use tools
# ffuf - web fuzzer
# AFL - binary fuzzer
# radamsa - test case generator
```

### Step 4: Authentication testing
- Test brute force protection
- Test session management (timeout, fixation, hijacking)
- Test password policies
- Test multi-factor authentication bypass
- Test account enumeration

### Step 5: Report findings
```
## Finding: [Title]
Severity: Critical/High/Medium/Low
Description: [What was found]
Impact: [What could happen]
Reproduction: [Steps to reproduce]
Remediation: [How to fix]
```

## Tool Usage
- `terminal` for running security tools
- `write_file` for creating reports
- `web_search` for researching vulnerabilities

## Pitfalls
1. Don't test production without authorization
2. Don't ignore low-severity findings — they chain into critical ones
3. Don't assume the system is secure because it hasn't been attacked
4. Don't forget to test error handling — it often leaks information
5. Don't report without remediation — every finding needs a fix

## Quick Reference
OWASP Top 10: Injection, Broken Auth, XSS, IDOR, Misconfiguration
Fuzz: Random inputs, malformed data, boundary values
Auth: Brute force, session management, password policy
Report: Severity, Description, Impact, Reproduction, Remediation