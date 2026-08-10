---
name: user-story-writing
description: Write clear, actionable user stories with acceptance criteria
tags: [product, user-stories, requirements, agile, acceptance-criteria, backlog]
---

# User Story Writing

## When to Use
When translating product requirements, feature requests, or user needs into structured backlog items. This applies during sprint planning, backlog grooming, feature specification, and whenever a team needs to define what to build in a way that's testable and estimable.

## Prerequisites
- Understanding of the target users and their goals
- Access to user research, feedback, or analytics data
- Knowledge of the current product capabilities

## Steps

### Step 1: Identify the User and Their Goal
Every story starts with who wants what and why.

**User persona template:**
```
As a [specific user role],
I want to [perform an action],
So that [I achieve this outcome].
```

**Good examples:**
```
As a team admin,
I want to invite new members by email,
So that I can quickly onboard collaborators without sharing credentials.

As a mobile user,
I want to save articles for offline reading,
So that I can read content during my commute without connectivity.

As a support agent,
I want to see a customer's recent ticket history,
So that I can provide context-aware help without asking them to repeat themselves.
```

**Bad examples (and why):**
```
❌ "As a user, I want a dashboard." — Who? What dashboard? Why?
❌ "As a developer, I want to refactor the auth module." — This is a task, not a user story.
❌ "As a user, I want everything to be fast." — Not specific or testable.
```

### Step 2: Write Acceptance Criteria
Define the conditions that must be met for the story to be "done."

**Format: Given/When/Then (Gherkin-style)**
```
## Acceptance Criteria

### Scenario 1: Successful invitation
Given I am a team admin on the members page
When I enter a valid email address and click "Invite"
Then an invitation email is sent to that address
And the new member appears in the pending invitations list
And I see a success toast "Invitation sent to email@example.com"

### Scenario 2: Duplicate invitation
Given I am a team admin on the members page
And "alice@example.com" is already a team member
When I enter "alice@example.com" and click "Invite"
Then I see an error message "This person is already a team member"
And no invitation is sent

### Scenario 3: Invalid email format
Given I am a team admin on the members page
When I enter "not-an-email" and click "Invite"
Then the invite button remains disabled
And I see inline validation "Please enter a valid email address"
```

**Checklist format (simpler stories):**
```
## Acceptance Criteria
- [ ] Admin can enter an email address in the invite field
- [ ] Valid email sends an invitation email within 30 seconds
- [ ] Pending invitation appears in the members list immediately
- [ ] Duplicate email shows an error without sending a new invite
- [ ] Invalid email shows inline validation error
- [ ] Non-admin users cannot see the invite button
```

### Step 3: Add Edge Cases and Constraints
Think beyond the happy path.

```
## Edge Cases
- What happens with very long email addresses (254 chars)?
- What if the email service is down? Retry? Queue?
- What about international email addresses (unicode)?
- What if the team is at its member limit?
- What about inviting someone with an existing account vs. new user?
- Rate limiting: how many invitations per minute/hour?

## Constraints
- Must work on mobile browsers (iOS Safari, Android Chrome)
- Invitation emails must comply with CAN-SPAM
- Must support SSO-only teams (invite flow differs)
```

### Step 4: Define the Definition of Done
What must be true beyond the acceptance criteria for the story to ship?

```
## Definition of Done
- [ ] All acceptance criteria pass
- [ ] Unit tests written and passing
- [ ] Integration tests for email sending
- [ ] UI matches design spec (link to Figma)
- [ ] Accessibility: screen reader announces success/error states
- [ ] Performance: invitation sends in <2 seconds
- [ ] Error handling: graceful failure with user-friendly message
- [ ] Documentation: API docs updated if applicable
- [ ] Code reviewed and approved
- [ ] Deployed to staging and verified
```

### Step 5: Estimate and Split if Needed
Stories should be completable within a single sprint (1-2 weeks).

**Story too big if:**
- More than 5 acceptance criteria
- More than 3 days of engineering effort
- Multiple user roles involved
- Requires changes to 5+ files
- Involves significant design work

**Splitting strategies:**
| Strategy | Example |
|----------|---------|
| By workflow step | "Invite by email" → "View pending invites" → "Accept invitation" |
| By input type | "Upload images" → "Upload PDFs" → "Upload videos" |
| By complexity | "Basic search" → "Advanced filters" → "Saved searches" |
| By platform | "Web implementation" → "Mobile implementation" |
| By data type | "Support text posts" → "Support image posts" |

### Step 6: Write the Complete Story Document
Combine all elements into a single, self-contained story.

```markdown
## US-421: Team Invitation by Email

**Priority:** P1 (Sprint 14)
**Points:** 5
**Owner:** [Product Designer]

### User Story
As a team admin,
I want to invite new members by email address,
So that I can onboard collaborators quickly without manual account creation.

### Acceptance Criteria
[Given/When/Then scenarios from Step 2]

### Edge Cases
[From Step 3]

### Design
- Figma: [link]
- Flow: Admin enters email → system sends invite → recipient accepts → added to team

### Technical Notes
- Use existing email service (SendGrid)
- Store pending invitations in `team_invitations` table
- Invitation tokens expire after 7 days
- Rate limit: 50 invitations per team per day

### Definition of Done
[From Step 4]

### Dependencies
- Email service integration (already exists)
- Team member limits feature (US-418, in progress)
```

## Tool Usage
- **file read**: Review existing user stories for format and style consistency
- **file write**: Create story documents in the project's backlog or docs folder
- **search_files**: Find related stories, acceptance criteria patterns, and existing feature specs
- **web search**: Look up user story best practices, INVEST criteria, or domain-specific patterns

## Pitfalls
1. **Don't write implementation details in the story** — "As a user, I want a REST endpoint" is a task, not a story
2. **Don't use vague acceptance criteria** — "should work well" is not testable; "loads in <2 seconds" is
3. **Don't combine multiple user goals** — one story, one goal; split if you see "and" in the goal
4. **Don't forget non-functional requirements** — performance, accessibility, security are part of "done"
5. **Don't write stories for developers** — write for the user; technical tasks are sub-tasks
6. **Don't skip edge cases** — the happy path is 20% of the work; edge cases are the other 80%

## Verification
- Story follows "As a [who], I want [what], so that [why]" format
- Acceptance criteria are specific, measurable, and testable
- Edge cases are identified and addressed
- Story is estimable (fits within one sprint)
- All stakeholders understand the story the same way
- Definition of Done includes testing, accessibility, and documentation

## Quick Reference
```
FORMAT: As a [role], I want [action], so that [outcome]
CRITERIA: Given/When/Then scenarios + checklist
EDGE CASES: Error states, limits, permissions, platforms
DONE: Criteria pass + tests + docs + reviewed + deployed

INVEST: Independent, Negotiable, Valuable, Estimable, Small, Testable
SPLIT BY: Workflow step | Input type | Complexity | Platform | Data type
```
