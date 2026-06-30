---
name: lead-finder-web-agency
description: >
  Discover, score, and produce actionable call sheets for businesses whose websites
  are weak enough to need a redesign but whose businesses are healthy enough to pay
  for one. Designed for web agencies selling website redesigns, landing pages, and
  conversion improvements to local/small businesses. Covers ICP definition, candidate
  discovery, website evaluation, lead scoring, mockup triggers, and deliverable production.
  Use when building lead lists, prospecting for web design clients, evaluating business
  websites at scale, or producing ranked call sheets.
tags: [lead-generation, sales, prospecting, web-design, small-business, website-audit, call-sheet]
support_files:
  - references/scoring-rubric.md  — Detailed scoring breakdown for each of the 4 categories (A–D) with score ranges and indicators
  - references/output-templates.md  — CSV column spec, Markdown report template, and daily call sheet template
  - references/discovery-techniques.md  — Search query patterns, suburb hunting strategy, big-company filtering, visual evaluation batching, and redesign opportunity signals
triggers:
  - "find leads"
  - "prospect for web design clients"
  - "lead generation"
  - "website audit"
  - "who needs a website redesign"
  - "build a call sheet"
  - "score businesses"
---

# Lead Finder for Web Agencies

## When To Use This Skill

Use this skill when the task involves:
- Finding businesses that would benefit from a website redesign
- Scoring prospects by business health vs. website weakness
- Producing ranked call sheets or lead databases for sales outreach
- Evaluating websites at scale for design/UX/technical problems
- Building a repeatable lead discovery pipeline

This skill is designed for **web agencies selling to local/small businesses** — not SaaS companies, not enterprise, not e-commerce-only. The sweet spot is service businesses where one extra customer is worth hundreds or thousands of dollars (contractors, lawyers, dentists, med spas, etc.).

---

## Core Workflow (10 Phases)

### Phase 1: Define the Ideal Client Profile (ICP)

Before searching, define:
- **Target country/region** (default: United States)
- **Target business types** (local service businesses where LTV justifies $1,500–$5,000 website spend)
- **Starting niches** — score each by:

| Factor | What To Evaluate |
|--------|-----------------|
| Ability to pay | Average job value vs. website cost; can they afford $1.5K–$5K? |
| Trust/first impressions | Do customers research them online before calling? |
| LTV | Repeat business, referrals, seasonal work |
| Local competition | Does website quality differentiate them? |
| Clear conversion action | "Call for quote", "Book appointment", "Request estimate" |
| Likelihood of outdated sites | Industry norms, tech adoption, company age |

**Recommend best 3 niches** for first experiment. Roofing, HVAC, plumbing, electrical, landscaping, dentists, personal injury lawyers, estate planning lawyers, med spas, and home inspection are strong starting points.

### Phase 2: Build the Lead Scoring Model

Score each candidate **out of 100**:

| Category | Weight | What To Evaluate |
|----------|--------|-----------------|
| **A. Business Health** | 0–30 | Reviews/trust indicators, active presence, physical location, clear services, currently operating, revenue potential |
| **B. Website Weakness** | 0–35 | Outdated design, poor mobile, weak above-fold, no clear CTA, hard-to-find contact, bad service pages, poor trust signals, technical issues, weak local SEO |
| **C. Sales Opportunity** | 0–20 | Website-business quality mismatch, conversion path improvement, competitors look better, clear pitch angle, easy one-sentence improvement |
| **D. Contactability** | 0–15 | Published phone, email/contact form, owner name public, not franchise/corporate, not large agency managed |

**Tier Classifications:**
- **85–100:** Hot Lead — Mockup before calling
- **70–84:** Good Lead — Call sheet
- **55–69:** Maybe — Save for later
- **<55:** Reject

**⚠️ PITFALL: Website weakness ≠ "how bad is the site."** It means "how much redesign opportunity exists." A 3/10 broken site and a 5/10 template site might both score high on weakness because both represent clear redesign opportunities. But a 7/10 decent-but-not-great site may score LOWER on weakness because the opportunity is smaller. Frame the score as **redesign value**, not just site quality.

### Phase 3: Choose Compliant Data Sources

**Allowed:**
- Official websites of businesses
- Public search engine results (manual or compliant API/tools)
- Business/license directories where terms allow research use
- Chamber/trade association member directories (terms permitting)
- Public social profiles
- Public business directories with permitted access
- Manually supplied lists from the client

**Disallowed unless reviewed/approved:**
- Scraping Google Maps or bulk-saving Google Maps/GBP data
- Bypassing rate limits, bot protections, captchas, login walls
- Sketchy lead lists or personal numbers unless clearly business contact
- Automated cold email without compliance review
- SMS outreach

**MVP workflow:** Generate search queries → find candidate websites → visit websites → evaluate → save only needed sales prep info → produce call sheet → client manually calls.

### Phase 4: Build the Discovery Workflow

**Inputs:** Target niche, target state/metro, max leads, minimum lead score, mockups yes/no, output format.

**For each candidate collect:**
- Business name, niche/category, city/state
- Official website URL
- Published business phone
- Published business email or contact form URL
- Owner/manager name if easily found publicly
- Short description of business
- Visible trust signals
- Website problems observed
- Recommended redesign angle
- One-sentence call opener (casual, honest, low-pressure)
- Lead score breakdown and total
- Priority tier
- Source URLs
- Date researched
- Status (default: `researched` or `call-ready`)
- Notes

**Do NOT collect** unnecessary/private data or infer sensitive attributes.

### Phase 5: Website Audit Checklist

Evaluate each website across these dimensions:

**Visual/Brand:**
- Modern, trustworthy, premium enough?
- Clean logo/header?
- Readable typography?
- Real/relevant/high-quality images (not generic stock)?

**Mobile/Conversion:**
- Phone visible on mobile?
- Sticky call / clear CTA?
- Easy quote request?
- Hero clear in 5 seconds?
- Short usable contact form?

**Technical:**
- Load speed acceptable?
- Layout problems?
- HTTPS?
- Broken links?
- Tech stack (WordPress/Wix/Squarespace/custom/unknown)?

**SEO/Local:**
- Clear service pages?
- Location/service area visible?
- Title/meta basics?
- Sensible headings?
- Schema/local business markup?

**Trust:**
- Testimonials/gallery/before-after?
- Licenses/certifications?
- Guarantees/warranties?
- Years in business?
- Team/about page?
- Financing/payment info?
- Emergency service if relevant?

**Technique: Use parallel evaluation.**
1. `web_extract` batches of 3–5 URLs for content analysis
2. `browser_navigate` + `browser_vision` screenshots for visual quality scoring
3. Content extraction alone misses broken layouts, placeholder blocks, and visual problems — always do at least one visual pass on top candidates

**Technique: Visual scoring with browser_vision.**
For each candidate in the shortlist, navigate to their homepage and call `browser_vision` with a specific question:
> "Evaluate this roofing company website for visual design quality. Is it modern or outdated? Rate modernity 1-10, mobile-friendliness 1-10, CTA clarity 1-10, and overall professional appearance 1-10."

Calibration from real runs:
- **3/10** = clearly 2010s template, heavy gradients, beveled buttons, textured backgrounds, brown/orange palettes
- **4/10** = functional but dated, 2012-2015 aesthetic, desktop-first layout, generic typography
- **5/10** = mixed — some modern elements but overall template feel, uninspired palette
- **6/10** = adequate corporate template, safe design, some dated elements but functional
- **7/10** = solid modern-ish design, good CTA, professional — lower redesign opportunity
- **8/10** = modern, well-designed, strong conversion — NOT a redesign candidate

**Sweet spot for redesign leads: 3–5/10 modernity.** These have clear, visible problems that make the pitch obvious. A 6/10 site is harder to pitch because the owner may not see the problem.

### Phase 6: Output Format

Produce **three deliverables:**

1. **Markdown Report** — Summary, chosen niche/geography, research method, scoring rubric, Top 10 leads with detail, rejected leads with reasons, next-run recommendations, risks/compliance notes, future automation plan.

2. **CSV File** — All candidates with columns: `business_name, niche, city, state, website_url, phone, email_or_contact_url, owner_or_manager, business_health_score, website_weakness_score, sales_opportunity_score, contactability_score, total_score, priority_tier, website_problem_summary, recommended_pitch_angle, call_opener, source_urls, date_researched, status, notes`

3. **Daily Call Sheet** — For each call-ready lead: business name, phone, website, why worth calling, biggest website issue, first 15 seconds of the call, what to offer, suggested next step.

**Call opener style:** Casual, honest, low-pressure. Example:
> "Hey, is this [Business Name]? My name is [Name]. I'm a web developer and I was looking at local [niche] companies in [City]. You guys seem to have a strong business, but your website looks like it may not be doing you any favors. I put together a few notes on what I'd improve. Would it be alright if I sent them over?"

**Do NOT** be manipulative, pretend to be a customer, imply a relationship, claim a full audit unless actually done, or claim a mockup unless built.

### Phase 7: Mockup Trigger

**Do NOT generate mockups automatically.** Mark `Mockup recommended: yes/no`.

**Yes only if:**
- Total score 85+
- Website clearly weak or broken
- Business is healthy
- Pitch angle is obvious
- Enough content exists for a credible homepage redesign
- Quick build is possible

For mockup-recommended leads, generate a **creative brief:**
- Current site problem
- Proposed homepage structure
- Brand direction
- Hero headline + CTA
- Sections and trust elements
- Service pages to add
- Assets needed from the client
- Estimated build time
- Suggested price range

### Phase 8: CRM/Status Flow

Every lead must have a status:

| Status | Meaning | When |
|--------|---------|------|
| `researched` | Info gathered, not yet scored/called | After initial discovery |
| `call-ready` | Scored 70+, ready to call | After scoring |
| `mockup-recommended` | Scored 85+, mockup before calling | After scoring |
| `called-no-answer` | Called, no answer | After call attempt |
| `called-not-interested` | Called, not interested | After call |
| `asked-to-email` | Prospect asked for email/follow-up | After call |
| `meeting-booked` | Meeting/call scheduled | After call |
| `proposal-sent` | Proposal/pricing sent | After meeting |
| `won` | Deal closed | After close |
| `lost` | Deal lost | After close |
| `do-not-contact` | Asked not to be contacted — permanent | At any point |

If a business asks not to be contacted, mark `do-not-contact` permanently.

### Phase 9: First Run

Run a **dry first pass** with no outreach:
- Target a specific niche + geography (e.g., 25 roofing contractors in Texas)
- Produce at least 10 scored call-ready leads if possible
- Identify top 3 mockup-recommended leads
- No automated contact
- Report: candidates reviewed, rejected, call-sheet count, top 3 opportunities, data quality issues, compliance concerns, improvements before scaling

### Phase 10: Future Automation Plan

After the MVP works manually, propose (but do not build) a second phase:
- Lead database with duplicate detection
- Dashboard / Kanban view
- Niche/state batch processing
- Automated screenshots
- Lighthouse/PageSpeed scores
- Compliant tech detection (Wappalyzer/BuiltWith-style)
- CRM status tracking
- Mockup queue and proposal queue
- Email draft templates
- Call logging
- Daily call sheet auto-generation

**Do not build Phase 2 until the client has called at least 10 leads and confirmed the scoring model works.**

---

## Pitfalls

1. **Website weakness ≠ site quality.** It means redesign opportunity. A broken 3/10 site and a functional but template-heavy 6/10 site may both represent high opportunity. Frame the score around "how much value can we add" not "how bad is this."

2. **Text extraction misses visual problems.** A site can look fine in text but have broken layouts, placeholder blocks, or empty sections visible only in screenshots. Always do at least one browser screenshot pass on top candidates.

3. **Big established companies rarely need you.** Focus discovery on smaller local operators — they're more likely to have template sites, broken sites, or outdated designs, AND more likely to be reachable by phone.

4. **Suburbs > city centers.** Smaller suburbs yield more weak-site candidates because competition hasn't driven everyone to upgrade yet.

5. **GoDaddy/Wix/Weebly template sites are easy wins.** Look for "Powered by GoDaddy," Weebly URLs, or Wix badges — these are almost always redesign candidates.

6. **Broken sites are highest urgency.** If a site times out, has placeholder content, or shows broken layouts, these are the easiest pitches because the problem is obvious and undeniable.

7. **Owner name matters.** A call that starts "Is this the owner?" is weaker than "Is this Erik?" Always try to find the owner's name from public sources (About page, public reviews, BBB, LinkedIn).

8. **Don't over-collect data.** Only collect what's needed for the sales prep. Don't save private info, scrape reviews, or infer sensitive attributes.

9. **Compliance is non-negotiable.** No Google Maps scraping, no automated outreach, no fake audits, no deceptive claims. Research and prepare only.

10. **Score calibration is iterative.** The first batch will need recalibration. After Kyle (or the client) calls 10+ leads, ask which scores felt right and adjust the model.

11. **Initial searches return the big fish.** Generic "[niche] [city] TX" searches surface large, polished companies (Lon Smith Roofing, CentiMark, Kidd Roofing) that have professional websites and don't need a redesign. Add filters: `small`, `local`, `family owned`, search suburbs instead of city centers, or look for companies on contractor lists (PDF lists from municipalities, chamber member directories) that are harder to find.

12. **Suburb hunting yields better leads.** Instead of "roofing contractors Austin TX," search "roofing contractor Round Rock Cedar Park Pflugerville Georgetown TX" or "roofing company Katy Cypress Sugar Land Pearland TX." Smaller suburbs have more operators with outdated sites because competition hasn't forced everyone to upgrade.

13. **The quality-mismatch pattern is the strongest signal.** The best leads aren't just "bad websites" — they're "good businesses with bad websites." A 30-year-old company with BBB A+, GAF certification, and a 2012-era template website is the perfect pitch because the business quality makes the website weakness more glaring. Always cross-reference business health against website quality.

14. **Gmail/email domain mismatch is a quick win.** Companies using `companyname@gmail.com` instead of `name@companydomain.com` are easy to pitch — it's a visible, undeniable signal that their digital presence needs professionalizing. Mention it in the call opener.

15. **Owner names: check About pages and reviews.** Website About pages sometimes list the owner. If not, customer reviews often mention names ("Allen picked up the phone," "Caleb at Burch Roofing was great"). BBB profiles also list principals. A call that starts "Is this Erik?" is dramatically more effective than "Is this the owner?"

16. **Copyright year is a quick visual proxy.** A footer saying "Copyright 2015-2022" or "© 2020" immediately signals the site hasn't been updated. It's not definitive (some sites auto-update the year), but when paired with other dated elements, it confirms the opportunity.

17. **Don't visit every site visually — batch filter first.** Use `web_extract` on 5-10 candidates at once to get content summaries. Only use `browser_navigate` + `browser_vision` on the 8-12 most promising candidates. This saves significant time while still catching visual issues on the leads that matter.

---

## Verification

After producing deliverables:
- [ ] All URLs in the CSV are valid and load
- [ ] All phone numbers are from official business websites (not third-party)
- [ ] No personal/private data collected beyond what businesses publish
- [ ] No automated outreach performed
- [ ] Score distribution makes sense (not all 80+, not all 40)
- [ ] At least 3 leads scored 70+ (if target geography is large enough)
- [ ] Call openers are honest, casual, and low-pressure
- [ ] Mockup recommendations only for 85+ scores with clearly weak sites
- [ ] All leads have a status assigned
- [ ] CSV columns match the spec
