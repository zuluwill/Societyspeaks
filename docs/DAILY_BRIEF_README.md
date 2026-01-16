# Daily Sense-Making Brief System

## Overview

The Daily Brief is an evening news summary (6pm UTC) that provides 3-5 curated stories with:
- **Coverage analysis** across political perspectives (left/center/right)
- **Sensationalism scoring** (low/medium/high language analysis)
- **Verification links** to primary sources
- **Discussion integration** for lightweight participation

**Key Principles**:
- Fully automated selection (admin can override)
- Calm, neutral framing (no sensationalism)
- Transparent methodology
- Timezone-aware delivery
- Paid subscription model (with 14-day trial)

---

## Architecture

### Components

```
app/brief/
├── __init__.py              # Blueprint registration
├── routes.py                # Public routes (/brief, /subscribe, /archive)
├── admin.py                 # Admin interface (/admin/brief)
├── generator.py             # LLM-powered content generation
├── topic_selector.py        # Automated topic selection algorithm
├── coverage_analyzer.py     # Political leaning analysis
├── email_client.py          # Resend integration + timezone delivery
└── underreported.py         # "Blindspot" feature for underreported stories
```

### Database Models

**DailyBrief** - One brief per day
- `date` (unique)
- `title`, `intro_text`
- `status`: draft → ready → published
- `auto_selected` flag (false if admin edited)

**BriefItem** - 3-5 items per brief
- References `TrendingTopic` (DRY principle)
- `headline`, `summary_bullets` (LLM-generated)
- `coverage_distribution`, `sensationalism_score`
- `verification_links` (JSON array)

**DailyBriefSubscriber** - Subscription management
- `tier`: trial | individual | team
- `timezone`, `preferred_send_hour` (6am, 8am, 6pm)
- `status`: active | unsubscribed | payment_failed
- Magic link authentication

**BriefTeam** - Multi-seat team subscriptions
- `seat_limit` (default 5)
- `base_price` ($40/month for 5 seats)
- Stripe integration

**NewsSource** (extended)
- `political_leaning` (-2 to +2: left to right)
- `leaning_source` (allsides | manual | llm_inferred)
- Seeded from AllSides.com ratings

---

## Environment Variables

### Required

```bash
# LLM (choose one)
OPENAI_API_KEY=sk-...              # For brief generation
ANTHROPIC_API_KEY=sk-ant-...       # Alternative to OpenAI

# Email
RESEND_API_KEY=re_...              # Get from resend.com
BRIEF_FROM_EMAIL=Daily Brief <brief@societyspeaks.com>

# Existing (you should have these)
RESEND_API_KEY=...                 # For all transactional emails
DATABASE_URL=postgresql://...
REDIS_URL=redis://...
```

### Optional

```bash
# Billing
BILLING_ENFORCEMENT_ENABLED=false  # Set 'true' when ready to charge
STRIPE_SECRET_KEY=sk_test_...      # For paid subscriptions
STRIPE_WEBHOOK_SECRET=whsec_...    # For payment webhooks

# Testing
BRIEF_ADMIN_REVIEW_WINDOW=60       # Minutes between generation and auto-publish (default: 60)
```

---

## Setup & Installation

### 1. Database Migration

```bash
# Apply migration
flask db upgrade

# Verify tables created
flask shell
>>> from app.models import DailyBrief, BriefItem, DailyBriefSubscriber
>>> DailyBrief.query.count()
0
```

### 2. Seed AllSides Ratings

```bash
flask seed-allsides
```

This populates `political_leaning` for all 21 news sources based on AllSides.com + manual assessments.

### 3. Test Brief Generation

```bash
# Generate a test brief manually
flask generate-brief

# This will:
# - Select 3-5 topics from recent TrendingTopics
# - Generate headlines and bullet summaries
# - Calculate coverage distribution
# - Extract verification links
# - Save as DailyBrief with status='ready'
```

### 4. Test Email Sending

```bash
# Send test email to yourself
flask test-brief-email your.email@example.com

# Check your inbox for:
# - Professional HTML email
# - Coverage visualizations
# - Sensationalism badges
# - Discussion CTAs
```

---

## Scheduled Jobs

The system runs fully automated via APScheduler:

| Time (UTC) | Job | Description |
|------------|-----|-------------|
| 5:00pm | `generate_daily_brief` | Auto-select topics, generate content, set status='ready' |
| 6:00pm | `auto_publish_brief` | If status still 'ready', publish (admin had 1-hour review window) |
| Every hour | `send_brief_emails` | Send to subscribers in that timezone hour |
| 2am (1st of month) | `update_allsides_ratings` | Refresh political leaning data |

**Admin Review Window**: 5:00pm - 6:00pm UTC
- Check `/admin/brief/preview`
- Edit items, change headlines, add verification links
- Click "Publish Now" to override auto-publish
- Click "Skip Today" to prevent sending

**Timezone Delivery Example**:
- 18:00 UTC → Sends to:
  - UK users (6pm UK time, UTC+0)
  - EST users who want 1pm delivery (1pm EST = 18:00 UTC)
  - PST users who want 10am delivery (10am PST = 18:00 UTC)

---

## Topic Selection Algorithm

Automated selection ensures quality and diversity:

**Criteria** (all must pass):
- Published in last 24 hours
- Civic score >= 0.6 (public importance)
- Source count >= 2 (multiple perspectives)
- Coverage imbalance <= 0.8 (not too skewed)
- Not featured in brief in last 30 days

**Scoring Formula**:
- 40% civic importance
- 30% quality/factuality
- 20% source diversity
- 10% coverage balance

**Diversity Enforcement**:
- Max 1 topic per category (Healthcare, Tech, Climate, etc.)
- Geographic mix (global, national, local)
- Perspective balance preferred

**Result**: 3-5 topics ranked by priority

---

## Coverage Analysis Methodology

**Data Source**: AllSides.com media bias ratings

**Scale**: -2 (Left) to +2 (Right)
- **Left** (-2): New Yorker
- **Lean Left** (-1): Guardian, Atlantic, Independent
- **Center** (0): BBC, FT, Economist, Axios
- **Lean Right** (+1): Telegraph, UnHerd
- **Right** (+2): (none in current source list)

**Calculation**:
1. Count sources by leaning for each story cluster
2. Calculate percentages: {left: 0.25, center: 0.50, right: 0.25}
3. Compute imbalance: (max_pct - 0.33) / 0.67
4. Display: "Coverage from 8 sources (2L, 4C, 2R)"

**Language Guidelines**:
- ✅ "Coverage distributed across perspectives"
- ✅ "Primarily covered by center outlets"
- ❌ "This story is biased"
- ❌ "Objectively unbalanced"

**Transparency**:
- Link to `/brief/methodology` in every email
- Show source names grouped by leaning
- Cite AllSides as data source

---

## Admin Interface

### Dashboard (`/admin/brief`)

- Today's brief status
- Subscriber counts (trial, paid, total)
- Recent briefs list
- Candidate topics for next brief

### Preview (`/admin/brief/preview`)

- View generated brief before publish
- Edit headlines and summaries
- Add/remove verification links
- Remove items from brief
- Publish, unpublish, or skip

### Actions

```python
# Publish now (override auto-publish)
POST /admin/brief/publish/<brief_id>

# Skip today (no brief sent)
POST /admin/brief/skip/<brief_id>

# Edit item
GET/POST /admin/brief/item/<item_id>/edit

# Remove item
POST /admin/brief/item/<item_id>/remove

# Send test email
POST /admin/brief/test-send
  brief_id=<id>
  email=<test_email>
```

###Subscribers (`/admin/brief/subscribers`)

- View all subscribers
- Filter by tier (trial, individual, team)
- Export list (CSV)
- View subscription details

---

## Subscription Tiers

### Trial (14 days)
- Full brief access
- Automatic on signup
- Email reminder 2 days before expiry

### Individual ($6/month or $60/year)
- Unlimited briefs
- Full archive access
- Priority support

### Team ($40/month for 5 seats)
- Shared billing
- $5/seat for additional members
- Admin dashboard for seat management

**Billing Enforcement**:
- Initially: `BILLING_ENFORCEMENT_ENABLED=false` (everyone gets access)
- Launch: Set to `true`, trial starts from first email sent
- Stripe webhooks handle payment failures, cancellations

---

## CLI Commands

### Brief Management

```bash
# Generate today's brief manually
flask generate-brief

# Generate for specific date
flask generate-brief --date 2026-01-15

# Force regenerate (replaces existing)
flask generate-brief --force

# Publish a draft brief
flask publish-brief <brief_id>

# Skip today's brief
flask skip-brief --reason "Holiday"
```

### Testing

```bash
# Send test email
flask test-brief-email your.email@example.com

# Test with specific brief
flask test-brief-email your.email@example.com --date 2026-01-15

# Test topic selection only (no generation)
flask test-topic-selection

# Test coverage analysis for a topic
flask test-coverage <topic_id>
```

### Subscriber Management

```bash
# Create test subscriber
flask create-brief-subscriber test@example.com --timezone America/New_York --hour 8

# List all subscribers
flask list-brief-subscribers

# Export subscribers to CSV
flask export-brief-subscribers > subscribers.csv
```

### Data Management

```bash
# Seed AllSides ratings
flask seed-allsides

# Update AllSides ratings (re-run seed)
flask seed-allsides --update

# View underreported stories
flask show-underreported --days 7 --limit 10
```

---

## Underreported Stories ("Blindspot" Feature)

Identifies stories with high civic importance but low media coverage:

**Criteria**:
- Civic score >= 0.7 (very important)
- Source count <= 3 (underreported)
- Not featured in brief (last 7 days)

**Categorization**:
- **Left Blindspot**: Only covered by right/center outlets
- **Right Blindspot**: Only covered by left/center outlets
- **Center Blindspot**: Only covered by left/right outlets
- **Uncovered**: Very few sources overall (< 2)

**Access**:
- `/brief/underreported` - Web view
- Could add to weekly digest email (future)

---

## Monitoring & Debugging

### Logs

```bash
# Watch scheduler logs
tail -f logs/scheduler.log

# Watch brief generation
tail -f logs/brief.log

# Watch email sending
tail -f logs/email.log
```

### Key Metrics

```python
# In Flask shell
from app.models import DailyBrief, DailyBriefSubscriber

# Brief health
DailyBrief.query.filter_by(status='published').count()  # Published briefs
DailyBrief.query.filter_by(status='skipped').count()   # Skipped days

# Subscriber health
DailyBriefSubscriber.query.filter_by(status='active').count()
DailyBriefSubscriber.query.filter_by(tier='trial').count()
DailyBriefSubscriber.query.filter_by(tier='individual').count()

# Email delivery
from sqlalchemy import func
db.session.query(func.avg(DailyBriefSubscriber.total_briefs_received)).scalar()
```

### Common Issues

**No topics selected**:
- Check: `TrendingTopic.query.filter_by(status='published').count()`
- Ensure trending pipeline is running (4x daily)
- Lower `MIN_CIVIC_SCORE` in `topic_selector.py` if needed

**Emails not sending**:
- Verify `RESEND_API_KEY` is set
- Check subscriber timezone/preferred_hour
- Check hourly job running: `flask shell` → `from app.scheduler import scheduler` → `scheduler.get_jobs()`

**Coverage analysis missing**:
- Run `flask seed-allsides` to populate leaning data
- Check `NewsSource.query.filter(NewsSource.political_leaning.isnot(None)).count()`

---

## Testing Checklist

Before launch:

- [ ] Database migration applied
- [ ] AllSides ratings seeded (21 sources)
- [ ] Generated test brief successfully
- [ ] Sent test email to yourself
- [ ] Verified email rendering (mobile + desktop)
- [ ] Subscribed with test email
- [ ] Received magic link
- [ ] Viewed brief in browser
- [ ] Unsubscribed successfully
- [ ] Admin interface accessible
- [ ] Edited brief item
- [ ] Published brief manually
- [ ] Skipped brief
- [ ] Checked scheduler jobs running
- [ ] Reviewed logs for errors
- [ ] Tested with 5+ subscribers in different timezones

---

## Rollout Plan

### Phase 1: Internal Beta (Week 1)
- Set `BILLING_ENFORCEMENT_ENABLED=false`
- Invite 10-20 internal testers
- Monitor logs daily
- Fix any issues

### Phase 2: Public Launch (Week 2)
- Set `BILLING_ENFORCEMENT_ENABLED=true`
- All new signups get 14-day trial
- Enable Stripe webhooks
- Launch announcement

### Phase 3: Growth (Week 3+)
- Add Stripe Checkout for subscriptions
- Build team management UI
- Add weekly digest option
- Implement "Blindspot" weekly email

---

## Future Enhancements

**Short-term**:
- [ ] Slack webhook for admin notifications (brief ready for review)
- [ ] Weekly digest email (best of week + underreported)
- [ ] Mobile app push notifications
- [ ] RSS feed for brief

**Medium-term**:
- [ ] Team admin dashboard (manage seats)
- [ ] Stripe Billing Portal integration
- [ ] A/B test email subject lines
- [ ] Personalized briefing (topic preferences)

**Long-term**:
- [ ] Community notes system (like Twitter/X)
- [ ] Podcast audio version of brief
- [ ] API for third-party integrations
- [ ] Automated fact-check integration (ClaimReview API)

---

## Support & Maintenance

**Weekly Tasks**:
- Review skipped briefs (identify patterns)
- Check subscriber growth
- Monitor unsubscribe rate
- Review underreported stories

**Monthly Tasks**:
- Update AllSides ratings (manual or automated)
- Review top performing items (most clicks)
- Analyze coverage balance trends
- Update pricing if needed

**Quarterly Tasks**:
- Review LLM costs (optimize if high)
- A/B test email template changes
- Survey subscribers for feedback
- Review source quality (add/remove outlets)

---

## Contact & Questions

For issues or questions:
1. Check logs first (`tail -f logs/*.log`)
2. Review this README
3. Check `/admin/brief` dashboard
4. Flask shell debugging: `flask shell`

**Critical Issues**:
- Emails not sending → Check Resend dashboard
- Brief generation failing → Check LLM API keys/limits
- Database errors → Check PostgreSQL connection

**Non-Critical**:
- Low open rates → Test subject lines
- High unsubscribe → Review content quality
- Low clicks → Improve CTAs

---

## License & Credits

Built for Society Speaks platform.

**Data Sources**:
- AllSides.com (media bias ratings)
- Guardian API, RSS feeds (news content)
- OpenAI/Anthropic (content generation)

**Inspiration**:
- Ground News (coverage analysis)
- Tortoise Media (Sensemaker)
- Axios (concise bulletins)
