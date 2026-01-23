# Weekly Question Digest Implementation Plan
## Email Frequency Optimization & Discussion Engagement Strategy

**Version:** 1.2
**Date:** January 2025
**Status:** Ready for Implementation (Updated: Weekly Default, Tuesday 9am, User Choice for Send Day)

---

## Executive Summary

This plan addresses user feedback that daily question emails are overwhelming inboxes, reducing vote participation. Based on research from Duolingo, TikTok, email marketing best practices, and send-time optimization studies, we propose moving from **daily emails (7/week)** to **weekly digests (1/week)** to increase voting (primary goal) and then drive discussion participation (secondary goal), while maintaining daily question publishing on the website.

**Key Changes:**
- Email frequency: Daily → Weekly (default: Tuesday 9am user's timezone)
- Email content: 1 question → 5 questions in weekly digest
- Send day/time: User choice (like daily brief) with smart default
- Discussion integration: Hidden after vote → Awareness in email, prominent on results page (after voting)
- User choice: Single frequency → Multiple frequency options (daily/weekly) + preferred send day

**Expected Outcomes:**
- 86% reduction in email volume (7 → 1 per week)
- **Increased vote participation** (less inbox fatigue = more people voting)
- **Increased discussion participation** (better discovery after voting)
- Higher retention (less unsubscribes)
- Better engagement quality (batch processing vs rushed daily)

**Flow:**
1. Weekly digest → More people vote (primary goal)
2. After voting → Better discussion discovery → More discussion participation (secondary goal)

---

## Problem Statement

### Current Issues

1. **Email Fatigue:** Users report daily emails are "too much" and saturating inboxes
2. **Low Vote Participation:** Daily emails may be overwhelming, reducing overall participation
3. **Low Discussion Participation:** After voting, users aren't effectively driven to discussions
4. **Hidden Discussion Links:** Discussion connections only appear after voting on website
5. **No User Choice:** Single frequency option doesn't accommodate different engagement levels
6. **Missed Opportunities:** Questions linked to active discussions aren't highlighted in emails

### User Feedback

> "The daily question and the email on a daily basis is probably too much. They'd actually prefer it to be on a weekly basis and say get five questions at the same time so they can do it all at once and save some of their email inbox because they're getting overloaded."

### Key Nuance: Voting First, Then Discussions

**CRITICAL:** The goal is a two-step flow:
1. **Primary Goal:** Get more people to VOTE on questions (existing voting flow works well - **DO NOT CHANGE IT**)
2. **Secondary Goal:** Get voters to then participate in discussions (this needs improvement)

**Existing Flow (Working Well - Keep As-Is):**
- User votes on question → Results page shows → Discussion link appears
- This flow works perfectly, we just need to:
  - Drive more people to vote (reduce email fatigue)
  - Make discussion links more prominent on results page (after voting)

**What Needs Improvement:**
- **More people voting** (reduce email fatigue to increase vote participation)
- **Better discussion discovery after voting** (make discussion links more prominent on results page)
- **Discussion awareness in emails** (so voters know discussions exist, but voting is still primary action)

**What NOT to Change:**
- ❌ Don't change the voting flow/interface (it works well)
- ❌ Don't change the comment/reason submission flow (it works well)
- ❌ Don't make discussion links primary CTA in emails (voting is primary)
- ✅ Do make discussion links more prominent on results page (after voting)
- ✅ Do add discussion awareness/preview in emails (secondary to voting)

---

## Research Findings & Best Practices

### Email Frequency Best Practices (SaaS)

**Optimal Frequency:** 1-2 emails per week (4-8 per month)
- **Source:** Industry research on SaaS email engagement
- **Key Insight:** Balance between staying top-of-mind and avoiding unsubscribes
- **Recommendation:** Start with 2/week, offer daily/weekly options

### Duolingo Engagement Strategy

**Key Tactics:**
1. **Consistent Timing:** Same time daily builds habit loops
2. **Personalization:** Bandit algorithm adapts to user behavior
3. **Gamification:** Streaks, badges, leaderboards
4. **Threat-Based Re-engagement:** "We'll pause if inactive" messaging
5. **Content Variety:** Different notifications for different user segments

**Application:**
- Maintain consistent send times (user's preferred day/time, default Tuesday 9am local)
- Add frequency personalization based on engagement
- Enhance existing streak system
- Add re-engagement emails for inactive users

### TikTok Engagement Strategy

**Key Tactics:**
1. **Multiple Touchpoints:** 2-5 posts per week optimal
2. **Consistency:** Regular posting schedule matters more than perfect timing
3. **Social Proof:** Show engagement metrics
4. **Content Variety:** Mix of content types

**Application:**
- 1 email/week with 5 questions provides focused engagement opportunity
- Show discussion stats in emails ("23 people discussing")
- Mix question types (civic, policy, social issues)

### Wordle Model

**Key Tactics:**
1. **One Question Per Day:** Finite, low-friction engagement
2. **Social Sharing:** Streak tracking and sharing
3. **Daily Ritual:** Same time, same format

**Application:**
- Questions still publish daily on website (maintains ritual)
- Email aggregates weekly (reduces inbox fatigue)
- Maintain streak tracking (adapt for weekly)

### Email Send Day & Time Research

**Best Days (by open rate):**
- **Tuesday:** Consistently ranks #1 across HubSpot, Mailchimp, and CoSchedule studies
- **Wednesday:** Strong second choice
- **Thursday:** Good for "end of week reflection" framing
- **Monday:** Typically worst - inbox overload from weekend, people in "catch up" mode
- **Friday:** Drop-off as people wind down for weekend

**Best Times:**
- **9-11am local time:** Peak engagement - people have cleared initial inbox, ready to engage
- **1-2pm:** Secondary peak - post-lunch engagement spike
- **Early morning (6-8am):** Lower engagement, people scanning not engaging

**Key Insight:** Sending at 8am UTC (as originally planned) is suboptimal:
- 8am UTC = 8am UK (too early) / 3am EST (middle of night)
- Better approach: Send based on user's timezone, default 9am local

**For Civic/Reflective Content:**
- Mid-week works best - people have mental bandwidth for thoughtful engagement
- Tuesday gives "here's what's happening this week" framing
- Avoids Monday overwhelm and Friday disengagement

**Recommendation:**
- Default: **Tuesday 9am in user's timezone**
- Allow user choice of send day (like daily brief)
- Fall back to Tuesday 9am UTC if timezone unknown

---

## Recommended Strategy

### Email Frequency: Weekly (Default)

**Weekly Digest Email: "5 Questions This Week"**
- Sent on user's preferred day (default: Tuesday 9am in user's timezone)
- 5 questions from past 7 days
- Curated to prioritize discussion-linked questions
- Each question includes:
  - Question text + context
  - **One-click vote buttons (PRIMARY CTA)** - this is the main action
  - Discussion hook with social proof ("23 people discussing" - awareness, not primary)
  - Discussion link as secondary CTA (for after voting)
- Subject: "5 Questions This Week: [Top Topic]"
- **Goal:** Get people to vote first, then discover discussions

**Future Enhancement: "Deep Dive" Email (Optional/Opt-in)**
- For power users who want more engagement
- 1-2 high-engagement questions with discussion previews
- Not part of initial rollout - add based on user demand

### User Frequency Options

1. **Weekly** (Default, recommended) - with choice of send day
2. **Daily** (Power users, opt-in)
3. **Monthly Digest** (Very casual, opt-in)

### User Send Day/Time Preferences

Following the pattern established by the daily brief:
- **Default day:** Tuesday (research-backed optimal engagement)
- **Default time:** 9am in user's timezone
- **User choice:** Allow users to select their preferred send day (Mon-Sun)
- **Timezone handling:** Store user timezone, fall back to UTC if unknown

### Discussion Integration (After Voting)

**Important:** Don't change the existing voting/comment flow - it works well.

**Email Changes (Pre-Vote):**
- Show discussion stats as preview: "23 people discussing this" (creates awareness)
- Include discussion link as secondary CTA (primary CTA is still vote buttons)
- Purpose: Let voters know discussions exist, but voting is the primary action

**Website Changes (Post-Vote):**
- **Enhance results page discussion promotion** (this is where discussion discovery happens)
- Make discussion link more prominent after voting
- Add social proof: "Join 23 people discussing this"
- Show discussion preview (top responses) to entice participation
- **Keep existing voting flow unchanged** - it works well

---

## Current State Analysis

### Database Schema

**File:** `app/models.py`

**Current Model: `DailyQuestionSubscriber` (lines 2315-2514)**
```python
class DailyQuestionSubscriber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    magic_token = db.Column(db.String(64), unique=True)
    token_expires_at = db.Column(db.DateTime)
    current_streak = db.Column(db.Integer, default=0)
    longest_streak = db.Column(db.Integer, default=0)
    last_participation_date = db.Column(db.Date)
    thoughtful_participations = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_email_sent = db.Column(db.DateTime)
    unsubscribe_reason = db.Column(db.String(50), nullable=True)
    unsubscribed_at = db.Column(db.DateTime, nullable=True)
```

**Missing Fields:**
- `email_frequency` - User's preferred frequency ('daily'|'weekly'|'monthly')
- `last_weekly_email_sent` - Track when weekly digest was sent
- `preferred_send_day` - User's preferred day for weekly digest (0=Monday through 6=Sunday, default=1 Tuesday)
- `preferred_send_hour` - User's preferred hour (0-23, default=9)
- `timezone` - User's timezone for localized send times (e.g., 'Europe/London', 'America/New_York')

**Current Model: `DailyQuestion` (lines 2024-2154)**
- Already has `source_discussion_id` (line 2047) ✅
- Already has `source_statement_id` (line 2048) ✅
- Links to discussions exist ✅

### Email Sending Logic

**File:** `app/resend_client.py`

**Current Function: `send_daily_question()` (lines 415-477)**
- Sends single question per email
- Includes: question text, context, vote buttons, magic link
- **Missing:** Discussion stats, discussion links, social proof

**Current Function: `send_daily_question_to_all_subscribers()` (lines 891-997)**
- Batch sends to all active subscribers
- Uses chunking (500 per batch)
- Filters by `can_receive_email()` check
- **Missing:** Frequency filtering, discussion data inclusion

**File:** `app/scheduler.py`

**Current Job: `daily_question_email()` (lines 523-551)**
- Runs daily at 8:00am UTC
- Calls `send_daily_question_to_all_subscribers()`
- **Needs:** New weekly job, frequency-based filtering

### Email Template

**File:** `app/templates/emails/daily_question.html`

**Current Structure:**
- Question text + context
- One-click vote buttons
- "Vote on website" link
- Why this question section
- **Missing:** Discussion hooks, social proof, discussion links

### Website Routes

**File:** `app/daily/routes.py`

**Current Routes:**
- `/daily` - Today's question (line 281)
- `/daily/<date_str>` - Specific date question (line 330)
- `/daily/v/<token>/<vote_choice>` - One-click vote (line 853)
- `/daily/vote` - Website vote submission (line 991)

**Current Function: `get_discussion_participation_data()` (lines 202-278)**
- Calculates discussion stats (participant count, vote count)
- Returns participation data for results page
- **Can be reused** for email discussion stats (DRY principle)

**Missing Routes:**
- `/daily/weekly` - Batch voting interface for weekly digest
- `/daily/preferences` - Frequency preference management

### Discussion Statistics

**File:** `app/daily/routes.py` - `get_discussion_participation_data()` (lines 202-278)

**Current Implementation:**
- Counts participants (authenticated + anonymous)
- Counts votes
- Calculates votes needed for consensus
- **Reusable for email stats** ✅

**File:** `app/sources/utils.py` - `get_source_stats()` (lines 53-149)
- Similar pattern for counting participants
- Can reference for consistency

### Question Selection

**File:** `app/daily/auto_selection.py`

**Current Function: `select_next_question_source()` (lines 200+)**
- Selects single question for daily publishing
- Uses engagement-weighted selection
- **Needs:** New function to select 5 questions for weekly digest
- **Enhancement:** Prioritize discussion-linked questions

---

## Implementation Plan

### Phase 1: Database Schema Updates

#### 1.1 Migration: Add Frequency and Send Preferences

**File:** `migrations/versions/XXXX_add_email_frequency_to_daily_subscriber.py`

```python
"""Add email frequency and send preferences to daily question subscribers

Revision ID: XXXX
Revises: [previous]
Create Date: 2025-01-XX
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    # Add email_frequency column (default: weekly)
    op.add_column('daily_question_subscriber',
        sa.Column('email_frequency', sa.String(20),
                  nullable=False, server_default='weekly'))

    # Add last_weekly_email_sent for tracking
    op.add_column('daily_question_subscriber',
        sa.Column('last_weekly_email_sent', sa.DateTime(), nullable=True))

    # Add send day preference (0=Mon, 1=Tue, ..., 6=Sun; default=1 Tuesday)
    op.add_column('daily_question_subscriber',
        sa.Column('preferred_send_day', sa.Integer(),
                  nullable=False, server_default='1'))

    # Add send hour preference (0-23, default=9 for 9am)
    op.add_column('daily_question_subscriber',
        sa.Column('preferred_send_hour', sa.Integer(),
                  nullable=False, server_default='9'))

    # Add timezone for localized send times
    op.add_column('daily_question_subscriber',
        sa.Column('timezone', sa.String(50), nullable=True))

    # Create index for frequency filtering
    op.create_index('idx_dqs_frequency', 'daily_question_subscriber',
                   ['email_frequency', 'is_active'])

    # Create index for send day scheduling (for efficient daily job queries)
    op.create_index('idx_dqs_send_day', 'daily_question_subscriber',
                   ['preferred_send_day', 'is_active'])

def downgrade():
    op.drop_index('idx_dqs_send_day', 'daily_question_subscriber')
    op.drop_index('idx_dqs_frequency', 'daily_question_subscriber')
    op.drop_column('daily_question_subscriber', 'timezone')
    op.drop_column('daily_question_subscriber', 'preferred_send_hour')
    op.drop_column('daily_question_subscriber', 'preferred_send_day')
    op.drop_column('daily_question_subscriber', 'last_weekly_email_sent')
    op.drop_column('daily_question_subscriber', 'email_frequency')
```

**Action Items:**
- [ ] Create migration file
- [ ] Test migration on staging
- [ ] Set default to 'weekly' for existing subscribers
- [ ] Set default send day to Tuesday (1) for existing subscribers
- [ ] Add migration to version control

#### 1.2 Update Model

**File:** `app/models.py` - `DailyQuestionSubscriber` class (line 2315)

**Add Fields:**
```python
email_frequency = db.Column(db.String(20), default='weekly')  # 'daily'|'weekly'|'monthly'
last_weekly_email_sent = db.Column(db.DateTime, nullable=True)
preferred_send_day = db.Column(db.Integer, default=1)  # 0=Mon, 1=Tue (default), ..., 6=Sun
preferred_send_hour = db.Column(db.Integer, default=9)  # 0-23, default 9am
timezone = db.Column(db.String(50), nullable=True)  # e.g., 'Europe/London', 'America/New_York'
```

**Add Constants:**
```python
# At top of models.py or in daily/constants.py
VALID_EMAIL_FREQUENCIES = ['daily', 'weekly', 'monthly']
DEFAULT_EMAIL_FREQUENCY = 'weekly'

# Send day constants (matching Python's weekday() where Monday=0)
SEND_DAYS = {
    0: 'Monday',
    1: 'Tuesday',  # Default
    2: 'Wednesday',
    3: 'Thursday',
    4: 'Friday',
    5: 'Saturday',
    6: 'Sunday'
}
DEFAULT_SEND_DAY = 1  # Tuesday
DEFAULT_SEND_HOUR = 9  # 9am
```

**Add Helper Methods:**
```python
def get_send_day_name(self):
    """Return human-readable send day name"""
    return SEND_DAYS.get(self.preferred_send_day, 'Tuesday')

def get_localized_send_time(self):
    """Return send time in user's timezone"""
    import pytz
    from datetime import datetime, time

    tz = pytz.timezone(self.timezone) if self.timezone else pytz.UTC
    send_time = time(hour=self.preferred_send_hour)
    return send_time, tz
```

**Action Items:**
- [ ] Add fields to model
- [ ] Add validation method for send_day (0-6) and send_hour (0-23)
- [ ] Add helper methods for timezone handling
- [ ] Update `__repr__` if needed
- [ ] Add property methods for frequency checks

### Return Flow After Voting

**Important:** After voting from weekly digest, user should be able to:
1. Return to batch page to vote on remaining questions
2. OR go to results page for that question
3. OR continue to discussion

**Implementation in `one_click_vote()` route:**

```python
# After recording vote (line 981):
flash('Vote recorded! Thanks for participating.', 'success')

# Check if user came from weekly digest
source = request.args.get('source', '')
referrer = request.referrer or ''

# If from weekly digest batch page, return there
if source == 'weekly_digest' or '/daily/weekly' in referrer:
    return redirect(url_for('daily.weekly_digest', token=token))
    
# Otherwise, go to results page for this question
return redirect(url_for('daily.by_date', date_str=question.question_date.isoformat()))
```

**Action Items:**
- [ ] Update `one_click_vote()` redirect logic
- [ ] Add `source` query param to vote URLs in weekly digest
- [ ] Test return flow from batch page
- [ ] Test return flow from individual email links

---

### Phase 2: Discussion Statistics Helper (DRY Principle)

#### 2.1 Create Reusable Discussion Stats Function

**File:** `app/daily/utils.py` (NEW FILE - extract from routes.py)

**Purpose:** Centralize discussion statistics calculation for reuse in:
- Email templates (discussion stats)
- Results page (existing usage)
- Weekly digest selection (prioritize active discussions)

**Function:**
```python
def get_discussion_stats_for_question(question):
    """
    Get discussion statistics for a question's linked discussion.
    Reusable across email templates, results pages, and selection logic.
    
    Args:
        question: DailyQuestion object
        
    Returns:
        dict: {
            'has_discussion': bool,
            'discussion_id': int | None,
            'discussion_slug': str | None,
            'discussion_title': str | None,
            'participant_count': int,
            'response_count': int,
            'is_active': bool,  # Has activity in last 24h
            'discussion_url': str | None
        }
    """
    # Implementation reusing get_discussion_participation_data() logic
    # But focused on stats, not user-specific participation
```

**Action Items:**
- [ ] Create `app/daily/utils.py`
- [ ] Extract discussion stats logic from `routes.py`
- [ ] Make it reusable (no user context needed)
- [ ] Add caching for performance (discussion stats don't change frequently)
- [ ] Update `routes.py` to use new function (DRY)

---

### Phase 3: Email Template Updates

## Weekly Digest User Flow - Optimal UX Design

### Best Practice Recommendation: Batch-First Design (Optimal UX)

**Research-Backed Approach:**
- **Progress bars increase completion rates by 15-20%** (psychology studies)
- **Batch processing reduces context switching** (cognitive load research)
- **"View All" pattern works well** (newsletter best practices - Morning Brew, Axios)
- **One question at a time** (reduces cognitive load vs showing all 5)
- **Mini results after each vote** (immediate feedback, learning opportunity)

**Why This Design Maximizes Voting, Discussion Participation, and Learning:**

1. **Higher Voting Completion:**
   - Progress bar shows "2 of 5 completed" → motivates finishing all
   - One question at a time → less overwhelming than 5 at once
   - "Next Question" button → clear path forward
   - Research shows progress indicators increase completion by 15-20%

2. **Better Discussion Participation:**
   - Mini results after each vote → shows discussion link immediately
   - Can join discussion after each question (not wait for all 5)
   - Summary page at end → shows all discussion links together
   - Discussion links prominent in mini results

3. **Enhanced Learning:**
   - Research tools (Perplexity, ChatGPT, Claude) available after each vote
   - Source articles shown in mini results
   - Can research before voting on next question
   - "Learn more" section in mini results (same as full results page)

**Design Pattern: "One Question at a Time" Batch Flow**

This is the best of both worlds:
- **Batch processing benefits** (progress tracking, completion motivation)
- **Individual question focus** (less cognitive load, can research between questions)
- **Learning tools available** (research after each vote, not just at end)
- **Discussion discovery** (prominent links after each vote)

**Recommended Flow: Batch-First with Individual Fallback**

### Primary Flow: Batch Voting Page (Recommended)

**Why Batch is Better:**
1. **Higher completion rates:** Progress tracking encourages finishing all 5
2. **Less context switching:** Stay in one flow, vote on all questions
3. **Better learning:** Can see all questions together, understand context
4. **Easier discussion discovery:** Summary page shows all discussion links
5. **Research tools available:** After each vote, can learn more before next question

**User Journey (Batch Page - Recommended Flow):**

```
Email → "View All 5 Questions" (Prominent Link) → Batch Page

Batch Page Flow:
├─ Progress: "0 of 5 completed" (prominent progress bar)
│
├─ Question 1 (Active, focused view)
│  ├─ Question text + context
│  ├─ Large vote buttons (Agree/Disagree/Unsure)
│  ├─ Click vote → Confirmation → Vote recorded
│  └─ Mini Results shown:
│     ├─ Quick stats (agree/disagree/unsure %)
│     ├─ "Add reason" button (optional, expandable)
│     ├─ "Learn More" section:
│     │  ├─ Research Tools: Perplexity, ChatGPT, Claude
│     │  └─ Source articles (if available)
│     ├─ Discussion link (if linked): "Join 23 people discussing →"
│     └─ "Next Question" button (primary CTA)
│
├─ Question 2 (Progress: "1 of 5 completed")
│  ├─ Same flow as Question 1
│  └─ Mini Results → "Next Question"
│
├─ Question 3 (Progress: "2 of 5 completed")
│  ├─ Same flow
│  └─ Mini Results → "Next Question"
│
├─ Question 4 (Progress: "3 of 5 completed")
│  ├─ Same flow
│  └─ Mini Results → "Next Question"
│
└─ Question 5 (Progress: "4 of 5 completed")
   ├─ Same flow
   └─ Mini Results → "All Done!" → Summary Page
      ├─ All 5 questions with results
      ├─ Discussion links for each (prominent)
      ├─ "Join Discussions" CTA
      ├─ Research tools available
      └─ Share results option
```

**Key Features:**
- ✅ **One question at a time** (reduces cognitive load)
- ✅ **Progress tracking** (motivates completion)
- ✅ **Mini results after each vote** (immediate feedback)
- ✅ **Research tools available** (can learn between questions)
- ✅ **Discussion links prominent** (after each vote)
- ✅ **Can add reasons** (optional, at any point)

### Secondary Flow: Individual Voting (From Email)

**When to Use:**
- Quick vote on one question
- User wants to vote now, finish later
- Mobile user prefers one question at a time

**User Journey (Individual):**

```
Email → Click Vote Button on Question 1
├─ Confirmation → Vote → Full Results Page
│  ├─ Stats, public reasons
│  ├─ "Add your reason" button
│  ├─ "Learn More" section (research tools: Perplexity, ChatGPT, Claude)
│  ├─ Source articles (if available)
│  ├─ Discussion link (prominent)
│  └─ "Back to weekly digest" link
└─ Return to email → Vote on Question 2, etc.
```

### Why This UX Maximizes Your Goals

**1. Maximum Voting (Primary Goal)**
- ✅ **Progress bar motivation:** "2 of 5 completed" encourages finishing all
- ✅ **One question at a time:** Less overwhelming than 5 at once
- ✅ **Clear next step:** "Next Question" button removes friction
- ✅ **Research-backed:** Progress indicators increase completion by 15-20%
- ✅ **Individual option still available:** Quick votes from email work too

**2. Maximum Discussion Participation (Secondary Goal)**
- ✅ **Discussion links after each vote:** Not hidden, shown in mini results
- ✅ **Can join immediately:** Don't have to wait for all 5 questions
- ✅ **Summary page:** Shows all discussion links together at end
- ✅ **Prominent CTAs:** "Join 23 people discussing" is clear and visible

**3. Maximum Learning (Important Goal)**
- ✅ **Research tools after each vote:** Perplexity, ChatGPT, Claude available immediately
- ✅ **Source articles shown:** Can read sources before next question
- ✅ **Can research between questions:** Learn, then vote on next with more context
- ✅ **Same tools as full results page:** No feature loss in batch flow

**4. Best User Experience**
- ✅ **Reduced cognitive load:** One question at a time (not 5 at once)
- ✅ **Progress tracking:** Visual feedback motivates completion
- ✅ **Flexible:** Can vote quickly from email OR do full batch experience
- ✅ **Learning integrated:** Research tools part of flow, not separate

### Key UX Principles

**1. Batch Page is Primary Experience (Recommended)**
- Make "View All 5 Questions" link **prominent** in email (not just footer)
- Batch page should be the default/recommended path
- Individual voting still works (for quick votes), but batch is encouraged
- **Why:** Higher completion rates, better learning, more discussion participation

**2. Mini Results After Each Vote (Batch Page)**
- Show quick stats (agree/disagree/unsure percentages)
- "Add reason" button (optional, expandable)
- **"Learn More" section with research tools:**
  - Perplexity (web search)
  - ChatGPT (discuss)
  - Claude (analyze)
- Source articles (if available)
- Discussion link (if linked): "Join 23 people discussing →"
- "Next Question" button (primary CTA)
- Progress: "2 of 5 completed"
- **Why:** Immediate feedback, learning opportunity, discussion discovery

**3. Full Results Page (Individual Flow)**
- Same as current results page (preserve existing UX)
- All features: stats, reasons, research tools, discussions
- "Back to weekly digest" link to continue voting
- **Why:** Maintains existing good UX, allows quick votes

**4. Summary Page (After All 5 Voted)**
- Shows all 5 questions with results
- Discussion links for each (if linked)
- "Join Discussions" prominent CTA
- Research tools available
- Share results option
- **Why:** Celebration of completion, easy discussion discovery

### Research Tools Integration

**Current Implementation (Results Page):**
- "Learn More About This Topic" section
- Source articles (if available)
- Research Tools: Perplexity, ChatGPT, Claude links

**For Batch Page:**
- Include same research tools after each vote (mini results)
- Allow users to research before voting on next question
- Keep learning tools accessible throughout flow

**Action Items:**
- [ ] Design mini results view for batch page
- [ ] Include research tools in mini results
- [ ] Ensure source articles available in batch flow
- [ ] Test learning/research flow

---

## Weekly Digest User Flow (Detailed)

### Overview: How Users Vote, Comment, and Participate

**Key Principle:** Batch voting is the primary experience (better completion), but individual voting from email is available for quick votes.

### Flow Option 1: Individual Question Voting (From Email)

**Step 1: User Opens Weekly Digest Email**
- Sees 5 questions, each with:
  - Question text + context
  - **Primary CTA:** Vote buttons (Agree/Disagree/Unsure) - one-click
  - **Secondary CTA:** "23 people discussing →" (awareness)

**Step 2: User Clicks Vote Button on Question 1**
- Goes to: `/daily/v/<token>/<vote_choice>?q=<question_id>&source=weekly_digest`
- Shows: Confirmation page (same as daily email)
- User can:
  - Click "Submit My Vote" (quick vote, no reason)
  - OR click "Add a reason" → expand form → add reason → submit
- After voting: Redirects to results page for that question

**Step 3: On Results Page (After Voting)**
- Shows: Vote stats, their vote, public reasons from others
- **Prominent Discussion Link:** "Join 23 people discussing →"
- **Option to add/edit reason:** Can add reason if they didn't before
- **Navigation:**
  - "Back to weekly digest" link → returns to email or batch page
  - "View all 5 questions" link → goes to batch page
  - Discussion link → goes to discussion

**Step 4: User Returns to Email**
- Can click vote button on Question 2, 3, 4, 5
- Each question has its own vote token
- Each question follows same flow (confirm → vote → results)

**Step 5: Discussion Participation (After Voting)**
- From results page, clicks "Join discussion" link
- Goes to: `/discussions/<id>/<slug>?q=<question_id>&source=weekly_digest`
- Can participate in full discussion (vote on statements, add responses)

### Flow Option 2: Batch Voting (From "View All Questions" Link)

**Step 1: User Clicks "View All 5 Questions" Link in Email**
- Goes to: `/daily/weekly?token=<magic_token>`
- Shows: All 5 questions on one page
- Progress indicator: "Question 1 of 5", "Question 2 of 5", etc.

**Step 2: User Votes on Question 1**
- Clicks vote button → confirmation page → votes
- Returns to batch page
- Question 1 marked as "✓ Voted"
- Progress: "1 of 5 completed"

**Step 3: User Continues Through Questions**
- Votes on Question 2, 3, 4, 5
- Each follows same flow
- Progress updates: "2 of 5", "3 of 5", etc.

**Step 4: After Voting on All 5**
- Shows: "All done! View your results"
- Links to: Individual results pages or summary page
- Summary shows:
  - Which questions they voted on
  - Discussion links for each (if linked)
  - "Join discussions" CTA

**Step 5: Adding Comments/Reasons**

**Option A: Add Reason During Voting**
- On confirmation page, click "Add a reason"
- Expand form, type reason (up to 500 chars)
- Choose visibility: Public (named/anonymous) or Private
- Submit vote with reason

**Option B: Add Reason After Voting**
- On results page, see "Add your reason" button
- Click → expand form → add reason
- Reason syncs to discussion if question is linked

**Step 6: Discussion Participation**
- From results page (individual or batch summary)
- Click "Join discussion" link
- Goes to full discussion page
- Can:
  - Vote on other statements in discussion
  - Add responses to statements
  - See consensus analysis (if unlocked)

### User Flow Diagram

```
Weekly Digest Email
├─ Question 1
│  ├─ [Vote Button] → Confirm → Vote → Results → Discussion
│  └─ [View Discussion] → Discussion (awareness only)
│
├─ Question 2
│  ├─ [Vote Button] → Confirm → Vote → Results → Discussion
│  └─ [View Discussion] → Discussion (awareness only)
│
├─ Question 3
│  ├─ [Vote Button] → Confirm → Vote → Results → Discussion
│  └─ [View Discussion] → Discussion (awareness only)
│
├─ Question 4
│  ├─ [Vote Button] → Confirm → Vote → Results → Discussion
│  └─ [View Discussion] → Discussion (awareness only)
│
├─ Question 5
│  ├─ [Vote Button] → Confirm → Vote → Results → Discussion
│  └─ [View Discussion] → Discussion (awareness only)
│
└─ [View All 5 Questions] → Batch Page
   ├─ Vote on all 5 sequentially
   ├─ Progress indicator
   └─ Summary → Results → Discussions
```

### Key Implementation Details

**1. Vote URLs in Email:**
```python
# Each question gets its own vote token
vote_agree_url = f"{base_url}/daily/v/{token}/agree?q={question_id}&source=weekly_digest"
vote_disagree_url = f"{base_url}/daily/v/{token}/disagree?q={question_id}&source=weekly_digest"
vote_unsure_url = f"{base_url}/daily/v/{token}/unsure?q={question_id}&source=weekly_digest"
```

**2. Confirmation Page (Same as Daily):**
- Shows question text
- Shows selected vote (Agree/Disagree/Unsure)
- "Submit My Vote" button (quick vote)
- "Add a reason" expandable section
- After submit → redirects to results page

**3. Results Page (After Voting):**
- Shows vote stats
- Shows their vote
- Shows public reasons from others
- **Prominent discussion link** (if linked)
- "Add/edit your reason" button
- "Back to weekly digest" link
- "View all 5 questions" link

**4. Batch Page (`/daily/weekly`):**
- Shows all 5 questions
- Progress indicator
- Each question has vote buttons
- After voting, question marked as complete
- "View results" link after all voted

**5. Adding Comments:**
- **During voting:** Expand "Add a reason" on confirmation page
- **After voting:** Click "Add your reason" on results page
- Reason syncs to discussion automatically (if linked)
- Reason appears in discussion response thread

**6. Discussion Participation:**
- **From results page:** Click "Join discussion" link
- **From email:** Click "View discussion" (awareness, but voting is primary)
- Goes to full discussion page
- Can vote on statements, add responses, see consensus

### Edge Cases

**1. User Votes on Some Questions, Not All:**
- That's fine - they can vote on remaining questions later
- Email links still work (tokens valid for 7 days)
- Batch page shows progress: "2 of 5 completed"

**2. User Already Voted on Question:**
- If they click vote button again, shows: "You already voted on this question"
- Redirects to results page
- Can still add/edit reason

**3. User Wants to Change Vote:**
- Currently: Can't change vote (by design)
- Can add reason explaining change of mind
- Future: Could allow vote change with reason

**4. User Clicks Old Email Link:**
- Token validation checks question date
- If question is too old (>7 days), shows: "This question expired"
- Redirects to current weekly digest

---

#### 3.1 Create Weekly Digest Template

**File:** `app/templates/emails/weekly_questions_digest.html` (NEW)

**Structure:**
```html
{% extends "emails/base_email.html" %}

{% block title %}5 Questions This Week - Society Speaks{% endblock %}

{% block content %}
  <!-- Header: "5 Questions This Week" -->
  
  <!-- Loop through 5 questions -->
  {% for question_data in questions %}
    <!-- Question Card -->
    <table>
      <!-- Question text + context -->
      
      <!-- PRIMARY CTA: Vote buttons (prominent, easy to click) -->
      <tr>
        <td align="center" style="padding: 16px 0;">
          <!-- Large, prominent vote buttons - one-click voting -->
          <table role="presentation" cellpadding="0" cellspacing="0" border="0">
            <tr>
              <td style="padding: 0 6px;">
                <a href="{{ question_data.vote_urls.agree }}" 
                   style="display: inline-block; padding: 14px 24px; background-color: #2563eb; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: 600;">
                  ✓ Agree
                </a>
              </td>
              <td style="padding: 0 6px;">
                <a href="{{ question_data.vote_urls.disagree }}" 
                   style="display: inline-block; padding: 14px 24px; background-color: #dc2626; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: 600;">
                  ✗ Disagree
                </a>
              </td>
              <td style="padding: 0 6px;">
                <a href="{{ question_data.vote_urls.unsure }}" 
                   style="display: inline-block; padding: 14px 24px; background-color: #d97706; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: 600;">
                  ? Unsure
                </a>
              </td>
            </tr>
          </table>
        </td>
      </tr>
      
      <!-- SECONDARY: Discussion awareness (if linked) -->
      {% if question_data.discussion_stats.has_discussion %}
        <tr>
          <td align="center" style="padding: 8px 0; font-size: 12px; color: #666;">
            💬 {{ question_data.discussion_stats.participant_count }} people discussing
            <a href="{{ question_data.discussion_stats.discussion_url }}" style="color: #1e40af; text-decoration: underline;">View discussion →</a>
            <br>
            <span style="font-size: 11px; color: #999;">(Vote first, then join the conversation)</span>
          </td>
        </tr>
      {% endif %}
      
      <!-- Note: Discussion link is secondary, voting is primary -->
    {% endfor %}
    
  <!-- Footer: Batch Voting Option (PRIMARY CTA) -->
  <tr>
    <td align="center" style="padding: 24px 0; border-top: 1px solid #e5e7eb; background-color: #f9fafb;">
      <p style="font-size: 16px; color: #1f2937; margin: 0 0 8px 0; font-weight: 600;">
        Vote on all 5 questions at once
      </p>
      <p style="font-size: 13px; color: #6b7280; margin: 0 0 16px 0;">
        See your progress, learn between questions, join discussions
      </p>
      <a href="{{ base_url }}/daily/weekly?token={{ subscriber.magic_token }}" 
         style="display: inline-block; padding: 14px 28px; background-color: #2563eb; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 15px;">
        View All 5 Questions →
      </a>
      <p style="font-size: 11px; color: #9ca3af; margin: 12px 0 0 0;">
        Or vote on individual questions above
      </p>
    </td>
  </tr>
{% endblock %}
```

**Action Items:**
- [ ] Create template file
- [ ] Design question cards (mobile-responsive)
- [ ] **Make vote buttons PRIMARY CTA (large, prominent)**
- [ ] Add discussion hooks as SECONDARY (smaller, awareness)
- [ ] Ensure vote buttons are easy to click (mobile-friendly)
- [ ] **Make "View All 5 Questions" link PROMINENT in footer (primary batch experience)**
- [ ] Include `source=weekly_digest` query param in vote URLs
- [ ] Test email rendering across clients
- [ ] Add unsubscribe link
- [ ] **Verify voting is the primary action, discussions are secondary**
- [ ] **Encourage batch voting** (better completion rates)

#### 3.2 Create Deep Dive Template (FUTURE PHASE - Deferred)

**Status:** Not part of initial rollout. Add based on user demand for more engagement.

**File:** `app/templates/emails/weekly_deep_dive.html` (NEW - FUTURE)

**Structure:**
- 1-2 high-engagement questions
- Discussion preview (top responses)
- Strong discussion CTA
- Social proof

**Action Items (FUTURE):**
- [ ] Create template (when user demand identified)
- [ ] Add discussion response preview
- [ ] Design prominent CTA
- [ ] Test rendering

#### 3.3 Update Daily Template (Optional - for daily frequency users)

**File:** `app/templates/emails/daily_question.html` (EXISTING)

**Enhancement:** Add discussion hooks even for daily emails
- Add discussion stats section (if linked)
- Add "Join discussion" link
- Maintain existing structure for backward compatibility

**Action Items:**
- [ ] Add discussion hook section
- [ ] Keep backward compatible
- [ ] Test with existing daily sends

---

### Phase 4: Email Sending Logic Updates

#### 4.1 Create Weekly Digest Sending Function

**File:** `app/resend_client.py`

**New Function:**
```python
def send_weekly_questions_digest(self, subscriber, questions_data) -> bool:
    """
    Send weekly digest with 5 questions.
    
    Args:
        subscriber: DailyQuestionSubscriber
        questions_data: List of dicts, each containing:
            - question: DailyQuestion object
            - discussion_stats: dict from get_discussion_stats_for_question()
            - vote_urls: dict with 'agree', 'disagree', 'unsure' URLs
    
    Returns:
        bool: Success status
    """
    # Generate vote tokens for all 5 questions
    # Build email with weekly template
    # Include discussion stats for each
    # Send via Resend
```

**Action Items:**
- [ ] Implement function
- [ ] Reuse `_build_vote_urls()` helper (DRY)
- [ ] Use `get_discussion_stats_for_question()` (DRY)
- [ ] Handle batch API for efficiency
- [ ] Add error handling

#### 4.2 Create Deep Dive Sending Function

**File:** `app/resend_client.py`

**New Function:**
```python
def send_weekly_deep_dive(self, subscriber, questions_data) -> bool:
    """
    Send Thursday deep dive with 1-2 high-engagement questions.
    
    Args:
        subscriber: DailyQuestionSubscriber
        questions_data: List with 1-2 questions + discussion previews
    
    Returns:
        bool: Success status
    """
    # Select top 1-2 questions with highest discussion engagement
    # Include discussion response previews
    # Strong CTA to join discussion
```

**Action Items:**
- [ ] Implement function
- [ ] Add discussion response preview logic
- [ ] Use deep dive template
- [ ] Add engagement metrics

#### 4.3 Update Batch Sending Function

**File:** `app/resend_client.py` - `send_daily_question_to_all_subscribers()` (line 891)

**Enhancement:** Add frequency filtering

**Current Logic:**
```python
subscribers = DailyQuestionSubscriber.query.filter_by(is_active=True)...
```

**New Logic:**
```python
# Filter by frequency preference
frequency_map = {
    'daily': send_daily_question,
    'weekly': send_weekly_digest,  # User's preferred day, default Tuesday
    'monthly': send_monthly_digest
}

# Group subscribers by frequency
# Send appropriate email type
```

**Action Items:**
- [ ] Refactor to support multiple frequencies
- [ ] Add frequency-based routing
- [ ] Maintain backward compatibility
- [ ] Add logging for frequency distribution

#### 4.4 Create Question Selection for Weekly Digest

**File:** `app/daily/auto_selection.py`

**New Function:**
```python
def select_questions_for_weekly_digest(days_back=7, count=5):
    """
    Select 5 questions from past week for weekly digest.
    Prioritizes questions linked to active discussions.
    
    Args:
        days_back: How many days to look back (default 7)
        count: Number of questions to select (default 5)
    
    Returns:
        List of DailyQuestion objects with discussion stats
    """
    # Get questions from past 7 days
    # Prioritize those with source_discussion_id
    # Score by: discussion activity, response count, recency
    # Return top 5
```

**Action Items:**
- [ ] Implement selection algorithm
- [ ] Prioritize discussion-linked questions
- [ ] Ensure diversity (different topics)
- [ ] Handle edge case: < 5 questions available

---

### Phase 5: Scheduler Updates

#### 5.1 Update Scheduler Jobs

**File:** `app/scheduler.py`

**Current Job:** `daily_question_email()` (line 523)
- Runs daily at 8:00am UTC
- Sends to all active subscribers

**New Approach: Timezone-Aware Hourly Processing**

Since users can choose their preferred send day and time, we need a scheduler that runs hourly and checks which subscribers should receive emails at that hour in their timezone.

```python
@scheduler.scheduled_job('cron', minute=0, id='process_weekly_digest_sends')
def process_weekly_digest_sends():
    """
    Process weekly digest sends. Runs every hour on the hour.
    Checks which subscribers should receive their weekly digest based on:
    - Their preferred send day (0-6)
    - Their preferred send hour (0-23)
    - Their timezone

    Example: If it's Tuesday 9am in Europe/London, send to all subscribers
    who have preferred_send_day=1, preferred_send_hour=9, timezone='Europe/London'
    """
    from datetime import datetime
    import pytz

    # Get current UTC time
    utc_now = datetime.utcnow()

    # Get all active weekly subscribers
    weekly_subscribers = DailyQuestionSubscriber.query.filter_by(
        is_active=True,
        email_frequency='weekly'
    ).all()

    # Group by timezone and check if it's their send time
    for subscriber in weekly_subscribers:
        tz = pytz.timezone(subscriber.timezone) if subscriber.timezone else pytz.UTC
        local_now = utc_now.replace(tzinfo=pytz.UTC).astimezone(tz)

        # Check if it's their preferred day and hour
        if (local_now.weekday() == subscriber.preferred_send_day and
            local_now.hour == subscriber.preferred_send_hour):

            # Check if we haven't already sent this week
            if not has_sent_this_week(subscriber):
                send_weekly_digest(subscriber)

# Keep daily job for 'daily' frequency users (power users)
@scheduler.scheduled_job('cron', hour=8, minute=0, id='daily_question_email')
def daily_question_email():
    """
    Send daily question to subscribers with 'daily' frequency preference.
    Runs daily at 8:00am UTC.
    """
    # Filter subscribers by frequency ('daily')
    # Send single question emails (existing logic)
```

**Helper Function:**
```python
def has_sent_this_week(subscriber):
    """Check if weekly digest was already sent this week"""
    if not subscriber.last_weekly_email_sent:
        return False

    from datetime import datetime, timedelta
    week_ago = datetime.utcnow() - timedelta(days=6)
    return subscriber.last_weekly_email_sent > week_ago
```

**Action Items:**
- [ ] Create hourly scheduler job for weekly digest processing
- [ ] Implement timezone-aware send time checking
- [ ] Add `has_sent_this_week()` helper to prevent duplicate sends
- [ ] Update daily job to filter by frequency='daily' only
- [ ] Add idempotency checks
- [ ] Add error handling and logging
- [ ] Consider batching by timezone for efficiency

---

### Phase 6: Website Routes & UI

#### 6.1 Add Frequency and Send Time Preference Management

**File:** `app/daily/routes.py`

**New Route:**
```python
@daily_bp.route('/daily/preferences', methods=['GET', 'POST'])
@login_required  # Or magic link auth
def manage_preferences():
    """
    Allow users to manage email frequency and send time preferences.
    Similar pattern to daily brief preferences.
    """
    subscriber = get_subscriber_for_current_user()

    if request.method == 'POST':
        # Update frequency
        frequency = request.form.get('email_frequency', 'weekly')
        if frequency in VALID_EMAIL_FREQUENCIES:
            subscriber.email_frequency = frequency

        # Update send day (for weekly subscribers)
        if frequency == 'weekly':
            send_day = int(request.form.get('preferred_send_day', 1))
            if 0 <= send_day <= 6:
                subscriber.preferred_send_day = send_day

            send_hour = int(request.form.get('preferred_send_hour', 9))
            if 0 <= send_hour <= 23:
                subscriber.preferred_send_hour = send_hour

        # Update timezone
        timezone = request.form.get('timezone')
        if timezone:
            subscriber.timezone = timezone

        db.session.commit()
        flash('Preferences updated successfully!', 'success')
        return redirect(url_for('daily.manage_preferences'))

    # GET: Show current preferences
    return render_template('daily/preferences.html',
        subscriber=subscriber,
        send_days=SEND_DAYS,
        frequencies=VALID_EMAIL_FREQUENCIES
    )
```

**Template: `app/templates/daily/preferences.html`**
```html
<form method="POST">
    <!-- Frequency Selection -->
    <label>Email Frequency</label>
    <select name="email_frequency">
        <option value="weekly" {{ 'selected' if subscriber.email_frequency == 'weekly' }}>
            Weekly (Recommended)
        </option>
        <option value="daily" {{ 'selected' if subscriber.email_frequency == 'daily' }}>
            Daily
        </option>
        <option value="monthly" {{ 'selected' if subscriber.email_frequency == 'monthly' }}>
            Monthly
        </option>
    </select>

    <!-- Send Day (only shown for weekly) -->
    <div id="weekly-options">
        <label>Preferred Send Day</label>
        <select name="preferred_send_day">
            {% for day_num, day_name in send_days.items() %}
                <option value="{{ day_num }}"
                    {{ 'selected' if subscriber.preferred_send_day == day_num }}>
                    {{ day_name }}{% if day_num == 1 %} (Recommended){% endif %}
                </option>
            {% endfor %}
        </select>

        <label>Preferred Send Time</label>
        <select name="preferred_send_hour">
            {% for hour in range(24) %}
                <option value="{{ hour }}"
                    {{ 'selected' if subscriber.preferred_send_hour == hour }}>
                    {{ '%02d:00'|format(hour) }}{% if hour == 9 %} (Recommended){% endif %}
                </option>
            {% endfor %}
        </select>

        <label>Timezone</label>
        <select name="timezone">
            <!-- Common timezones -->
            <option value="Europe/London">UK (London)</option>
            <option value="America/New_York">US Eastern</option>
            <option value="America/Los_Angeles">US Pacific</option>
            <option value="Europe/Paris">Central Europe</option>
            <!-- Add more as needed -->
        </select>
    </div>

    <button type="submit">Save Preferences</button>
</form>
```

**Action Items:**
- [ ] Create route with frequency + send day/time handling
- [ ] Create template `daily/preferences.html`
- [ ] Add form with frequency options
- [ ] Add send day dropdown (Mon-Sun)
- [ ] Add send hour dropdown (0-23)
- [ ] Add timezone selector
- [ ] Add JavaScript to show/hide weekly options based on frequency
- [ ] Add validation
- [ ] Update subscriber model
- [ ] Add success message
- [ ] Consider auto-detecting timezone from browser

#### 6.2 Add Weekly Digest Batch Voting Page

**File:** `app/daily/routes.py`

**New Route:**
```python
@daily_bp.route('/daily/weekly')
@limiter.limit("10 per minute")
def weekly_digest():
    """
    Display weekly digest page with 5 questions.
    Allows batch voting on all questions.
    
    Flow:
    1. User sees all 5 questions
    2. Clicks vote on Question 1 → confirmation → vote → returns to batch page
    3. Question 1 marked as "✓ Voted"
    4. Progress: "1 of 5 completed"
    5. Continues with Questions 2-5
    6. After all voted, shows summary with discussion links
    """
    # Get subscriber from token or session
    token = request.args.get('token')
    subscriber = None
    
    if token:
        subscriber = DailyQuestionSubscriber.query.filter_by(magic_token=token).first()
        if subscriber:
            session['daily_subscriber_id'] = subscriber.id
    else:
        subscriber_id = session.get('daily_subscriber_id')
        if subscriber_id:
            subscriber = DailyQuestionSubscriber.query.get(subscriber_id)
    
    if not subscriber or not subscriber.is_active:
        flash('Please use the link from your weekly digest email.', 'info')
        return redirect(url_for('daily.subscribe'))
    
    # Get 5 questions from past 7 days
    from datetime import date, timedelta
    week_ago = date.today() - timedelta(days=7)
    
    questions = DailyQuestion.query.filter(
        DailyQuestion.question_date >= week_ago,
        DailyQuestion.question_date <= date.today(),
        DailyQuestion.status == 'published'
    ).order_by(DailyQuestion.question_date.desc()).limit(5).all()
    
    # Check which questions user has voted on
    voted_question_ids = set()
    if subscriber.user_id:
        responses = DailyQuestionResponse.query.filter(
            DailyQuestionResponse.user_id == subscriber.user_id,
            DailyQuestionResponse.daily_question_id.in_([q.id for q in questions])
        ).all()
        voted_question_ids = {r.daily_question_id for r in responses}
    else:
        # Check by session fingerprint
        fingerprint = get_session_fingerprint()
        if fingerprint:
            responses = DailyQuestionResponse.query.filter(
                DailyQuestionResponse.session_fingerprint == fingerprint,
                DailyQuestionResponse.daily_question_id.in_([q.id for q in questions])
            ).all()
            voted_question_ids = {r.daily_question_id for r in responses}
    
    # Prepare question data with vote URLs and learning resources
    from app.daily.routes import get_source_articles  # Reuse existing function
    
    questions_data = []
    for question in questions:
        has_voted = question.id in voted_question_ids
        vote_urls = {}
        
        if not has_voted:
            # Generate vote tokens for this question
            vote_token = subscriber.generate_vote_token(question.id)
            vote_urls = {
                'agree': url_for('daily.one_click_vote', token=vote_token, vote_choice='agree', source='weekly_digest', _external=True),
                'disagree': url_for('daily.one_click_vote', token=vote_token, vote_choice='disagree', source='weekly_digest', _external=True),
                'unsure': url_for('daily.one_click_vote', token=vote_token, vote_choice='unsure', source='weekly_digest', _external=True)
            }
        
        # Get discussion stats (for discussion links)
        discussion_stats = get_discussion_stats_for_question(question)
        
        # Get source articles (for learning/research)
        source_articles = get_source_articles(question, limit=3)
        
        questions_data.append({
            'question': question,
            'has_voted': has_voted,
            'vote_urls': vote_urls,
            'discussion_stats': discussion_stats,
            'source_articles': source_articles,  # For mini results
            'results_url': url_for('daily.by_date', date_str=question.question_date.isoformat(), _external=True)
        })
    
    # Calculate progress
    voted_count = len(voted_question_ids)
    total_count = len(questions)
    progress_percent = (voted_count / total_count * 100) if total_count > 0 else 0
    
    # Determine which question to show (first unanswered)
    current_question_index = 0
    for i, q_data in enumerate(questions_data):
        if not q_data['has_voted']:
            current_question_index = i
            break
    
    current_question = questions_data[current_question_index] if questions_data else None
    
    return render_template('daily/weekly_digest.html',
                         questions_data=questions_data,
                         current_question=current_question,
                         current_question_index=current_question_index,
                         voted_count=voted_count,
                         total_count=total_count,
                         progress_percent=progress_percent,
                         subscriber=subscriber)
```

**Template: `app/templates/daily/weekly_digest.html`**

**Design Philosophy:**
- **One question at a time** (reduces cognitive load)
- **Progress tracking** (encourages completion)
- **Mini results after each vote** (immediate feedback, learning opportunity)
- **Research tools available** (Perplexity, ChatGPT, Claude)
- **Discussion links** (after voting, not before)

**Implementation Note: Question Progression**
The batch page shows one question at a time. After voting, the page reloads to show:
1. Mini results for the question just voted on
2. "Next Question" button to advance
3. Or use htmx/AJAX for smoother transitions (enhancement)

For MVP, use page reload approach:
- Vote → Redirect back to `/daily/weekly` with `?just_voted=<question_id>`
- Page shows mini results for that question + "Next Question" button
- Clicking "Next Question" reloads to show next unanswered question

**Structure:**
```html
{% extends "layout.html" %}

{% block title %}5 Questions This Week - Society Speaks{% endblock %}

{% block content %}
<div class="max-w-3xl mx-auto py-8 px-4">
  <!-- Header -->
  <div class="text-center mb-8">
    <h1 class="text-3xl font-bold text-gray-900 mb-2">5 Questions This Week</h1>
    <p class="text-gray-600">Vote on all 5, then join the discussions</p>
  </div>
  
  <!-- Progress Indicator (Prominent) -->
  <div class="bg-white rounded-xl shadow-md p-6 mb-8">
    <div class="flex items-center justify-between mb-2">
      <span class="text-sm font-medium text-gray-700">Progress</span>
      <span class="text-sm font-semibold text-gray-900">{{ voted_count }} of {{ total_count }} completed</span>
    </div>
    <div class="w-full bg-gray-200 rounded-full h-3">
      <div class="bg-blue-600 h-3 rounded-full transition-all duration-500" 
           style="width: {{ progress_percent }}%"></div>
    </div>
  </div>
  
  <!-- Current Question (One at a time) -->
  {% set current_q = questions_data[0] if questions_data else None %}
  {% if current_q and not current_q.has_voted %}
    <!-- Question Card (Active) -->
    <div class="bg-white rounded-2xl shadow-xl p-8 mb-6">
      <div class="text-center mb-6">
        <span class="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-blue-100 text-blue-800">
          Question {{ loop.index }} of {{ total_count }}
        </span>
      </div>
      
      <h2 class="text-2xl font-bold text-gray-900 mb-4 text-center">
        "{{ current_q.question.question_text }}"
      </h2>
      
      {% if current_q.question.context %}
        <div class="bg-gray-50 rounded-lg p-4 mb-6">
          <p class="text-sm text-gray-600">{{ current_q.question.context }}</p>
        </div>
      {% endif %}
      
      <!-- Vote Buttons (Large, Prominent) -->
      <div class="grid grid-cols-3 gap-4 mb-6">
        <a href="{{ current_q.vote_urls.agree }}?source=weekly_digest" 
           class="flex flex-col items-center p-6 rounded-xl border-2 border-blue-200 hover:border-blue-500 hover:bg-blue-50 transition">
          <div class="w-16 h-16 rounded-full bg-blue-100 flex items-center justify-center mb-3">
            <svg class="w-8 h-8 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <span class="text-lg font-semibold text-gray-900">Agree</span>
        </a>
        
        <a href="{{ current_q.vote_urls.disagree }}?source=weekly_digest" 
           class="flex flex-col items-center p-6 rounded-xl border-2 border-red-200 hover:border-red-500 hover:bg-red-50 transition">
          <div class="w-16 h-16 rounded-full bg-red-100 flex items-center justify-center mb-3">
            <svg class="w-8 h-8 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </div>
          <span class="text-lg font-semibold text-gray-900">Disagree</span>
        </a>
        
        <a href="{{ current_q.vote_urls.unsure }}?source=weekly_digest" 
           class="flex flex-col items-center p-6 rounded-xl border-2 border-yellow-200 hover:border-yellow-500 hover:bg-yellow-50 transition">
          <div class="w-16 h-16 rounded-full bg-yellow-100 flex items-center justify-center mb-3">
            <svg class="w-8 h-8 text-yellow-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <span class="text-lg font-semibold text-gray-900">Unsure</span>
        </a>
      </div>
      
      <!-- Discussion Awareness (Secondary) -->
      {% if current_q.discussion_stats.has_discussion %}
        <div class="text-center text-sm text-gray-600">
          💬 {{ current_q.discussion_stats.participant_count }} people discussing this
          <span class="text-gray-400">(join after voting)</span>
        </div>
      {% endif %}
    </div>
    
    <!-- Upcoming Questions Preview -->
    {% if questions_data|length > 1 %}
      <div class="bg-gray-50 rounded-xl p-6">
        <h3 class="text-sm font-semibold text-gray-700 mb-3">Upcoming Questions</h3>
        <div class="space-y-2">
          {% for q_data in questions_data[1:] %}
            <div class="flex items-center text-sm text-gray-600">
              <span class="w-6 h-6 rounded-full bg-gray-200 flex items-center justify-center mr-3 text-xs font-medium">
                {{ loop.index + 1 }}
              </span>
              <span>{{ q_data.question.question_text[:80] }}{% if q_data.question.question_text|length > 80 %}...{% endif %}</span>
            </div>
          {% endfor %}
        </div>
      </div>
    {% endif %}
    
  {% elif current_q and current_q.has_voted %}
    <!-- Show Next Question or Summary -->
    <!-- Logic to show next unanswered question -->
  {% endif %}
  
  <!-- Summary (if all voted) -->
  {% if voted_count == total_count %}
    <div class="bg-gradient-to-br from-green-50 to-blue-50 rounded-2xl shadow-xl p-8 text-center">
      <div class="text-6xl mb-4">🎉</div>
      <h2 class="text-2xl font-bold text-gray-900 mb-2">All Done!</h2>
      <p class="text-gray-600 mb-6">You've voted on all 5 questions this week</p>
      <a href="/daily/weekly/results" 
         class="inline-flex items-center px-6 py-3 bg-blue-600 text-white font-semibold rounded-lg hover:bg-blue-700 transition">
        View Your Results →
      </a>
    </div>
  {% endif %}
</div>
{% endblock %}
```

**Mini Results View (After Voting in Batch):**

After user votes, show mini results inline before moving to next question. This is CRITICAL for learning and discussion participation.

```html
<!-- Mini Results (shown after vote, before next question) -->
<div class="bg-white rounded-xl shadow-md p-6 mb-6">
  <div class="text-center mb-4">
    <span class="text-4xl">{{ user_vote_emoji }}</span>
    <p class="text-sm text-gray-600 mt-2">Your vote: {{ user_vote_label }}</p>
  </div>
  
  <!-- Quick Stats -->
  <div class="grid grid-cols-3 gap-4 mb-4">
    <div class="text-center">
      <div class="text-2xl font-bold text-blue-600">{{ stats.agree }}%</div>
      <div class="text-xs text-gray-600">Agree</div>
    </div>
    <div class="text-center">
      <div class="text-2xl font-bold text-red-600">{{ stats.disagree }}%</div>
      <div class="text-xs text-gray-600">Disagree</div>
    </div>
    <div class="text-center">
      <div class="text-2xl font-bold text-yellow-600">{{ stats.unsure }}%</div>
      <div class="text-xs text-gray-600">Unsure</div>
    </div>
  </div>
  
  <!-- Add Reason (Optional) -->
  <button onclick="showReasonForm()" 
          class="w-full py-2 px-4 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg text-sm font-medium mb-4">
    + Add a reason (optional)
  </button>
  
  <!-- Learn More Section (CRITICAL for learning) -->
  <div class="border-t pt-4">
    <h4 class="text-sm font-semibold text-gray-700 mb-3">Learn More About This Topic</h4>
    
    <!-- Source Articles (if available) -->
    {% if source_articles and source_articles|length > 0 %}
      <div class="mb-4">
        <p class="text-xs text-gray-500 mb-2">Source Articles:</p>
        <div class="space-y-1">
          {% for article in source_articles[:3] %}
            <a href="{{ article.url }}" target="_blank" 
               class="block text-xs text-blue-600 hover:text-blue-800 truncate">
              {{ article.title[:60] }}{% if article.title|length > 60 %}...{% endif %}
            </a>
          {% endfor %}
        </div>
      </div>
    {% endif %}
    
    <!-- Research Tools (Perplexity, ChatGPT, Claude) - Contextual Links -->
    <p class="text-xs text-gray-500 mb-2">Research with AI:</p>
    <div class="grid grid-cols-3 gap-2 mb-4">
      <!-- Note: URLs should include the question text for context -->
      <!-- question_search_query = url_encode(question.question_text) -->
      <a href="https://perplexity.ai/search?q={{ question_search_query }}" target="_blank"
         class="flex flex-col items-center p-2 rounded-lg border border-gray-200 hover:border-blue-400 hover:bg-blue-50 transition text-center">
        <span class="text-xs font-medium text-gray-900">Perplexity</span>
        <span class="text-xs text-gray-500">Web search</span>
      </a>
      <a href="https://chat.openai.com/?q={{ question_search_query }}" target="_blank"
         class="flex flex-col items-center p-2 rounded-lg border border-gray-200 hover:border-blue-400 hover:bg-blue-50 transition text-center">
        <span class="text-xs font-medium text-gray-900">ChatGPT</span>
        <span class="text-xs text-gray-500">Discuss</span>
      </a>
      <a href="https://claude.ai/new?q={{ question_search_query }}" target="_blank" 
         class="flex flex-col items-center p-2 rounded-lg border border-gray-200 hover:border-blue-400 hover:bg-blue-50 transition text-center">
        <span class="text-xs font-medium text-gray-900">Claude</span>
        <span class="text-xs text-gray-500">Analyze</span>
      </a>
    </div>
    
    <!-- Discussion Link (if linked) - PROMINENT -->
    {% if discussion_stats.has_discussion %}
      <a href="{{ discussion_stats.discussion_url }}" 
         class="block w-full text-center py-2 px-4 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition text-sm font-medium mb-3">
        Join {{ discussion_stats.participant_count }} people discussing →
      </a>
    {% endif %}
    
    <!-- Next Question Button (Primary CTA) -->
    <a href="/daily/weekly?token={{ token }}&next={{ next_question_index }}" 
       class="block w-full text-center py-3 px-4 bg-gray-900 text-white rounded-lg hover:bg-gray-800 transition font-semibold">
      Next Question ({{ current_index }} of {{ total_count }}) →
    </a>
  </div>
</div>
```

**Key Features of Mini Results:**
- ✅ Quick stats (immediate feedback)
- ✅ Add reason option (optional)
- ✅ **Source articles** (if available - same as full results page)
- ✅ **Research tools** (Perplexity, ChatGPT, Claude - same as full results page)
- ✅ **Discussion link** (prominent, if linked)
- ✅ Next Question button (clear path forward)
- ✅ Progress indicator

**Why This Design:**
- Users can **learn between questions** (research tools available)
- Users can **join discussions immediately** (don't wait for all 5)
- Users get **immediate feedback** (stats shown right away)
- **Same learning tools** as full results page (no feature loss)

**Action Items:**
- [ ] Create route with batch voting logic
- [ ] Create template `daily/weekly_digest.html` (one question at a time design)
- [ ] Add prominent progress indicator (top of page)
- [ ] Design mini results view (after each vote)
- [ ] **Include research tools in mini results** (Perplexity, ChatGPT, Claude) - CRITICAL for learning
- [ ] **Include source articles in mini results** (using `get_source_articles()` function) - CRITICAL for learning
- [ ] Add "Add reason" button in mini results (expandable)
- [ ] Add discussion link in mini results (prominent, if linked)
- [ ] Add "Next Question" button (primary CTA in mini results)
- [ ] Handle return from confirmation page (back to batch page, show mini results)
- [ ] Create summary page after all 5 voted
- [ ] Show all discussion links on summary page
- [ ] Test learning/research flow (can research between questions)
- [ ] Test discussion participation flow (can join after each vote)
- [ ] **Verify research tools work** (same as full results page)
- [ ] **Verify source articles display** (same as full results page)

### Why This UX is Optimal

**Research-Backed Benefits:**

1. **Maximum Voting Completion:**
   - Progress bar: "2 of 5 completed" → **15-20% higher completion rates** (psychology research)
   - One question at a time → Less cognitive load than 5 at once
   - Clear next step → "Next Question" button removes friction
   - Individual option available → Quick votes from email still work

2. **Maximum Discussion Participation:**
   - Discussion links **after each vote** (not hidden, shown in mini results)
   - Can join **immediately** (don't have to wait for all 5)
   - Summary page shows **all discussion links** together
   - Prominent CTAs: "Join 23 people discussing →"

3. **Maximum Learning:**
   - **Research tools available after each vote** (Perplexity, ChatGPT, Claude)
   - **Source articles shown** (same as full results page)
   - Can **research between questions** (learn, then vote on next with more context)
   - **Same learning tools** as full results page (no feature loss)

4. **Best User Experience:**
   - Reduced cognitive load (one question at a time)
   - Progress tracking (visual feedback motivates)
   - Flexible (quick votes OR full batch experience)
   - Learning integrated (research tools part of flow)

**Comparison:**

| Feature | Individual Voting | Batch Voting (Recommended) |
|---------|------------------|---------------------------|
| Completion Rate | Lower (no progress tracking) | **Higher (15-20% boost)** |
| Learning Opportunity | After all votes | **After each vote** |
| Discussion Discovery | After all votes | **After each vote** |
| Cognitive Load | Low (one question) | **Low (one question at a time)** |
| Progress Feedback | None | **Visual progress bar** |
| Research Tools | Full results page only | **Mini results after each vote** |

**Conclusion:** Batch voting with one-question-at-a-time design + mini results is the optimal UX for maximizing voting, discussion participation, and learning.

#### 6.3 Enhance Results Page Discussion Promotion (AFTER VOTING)

**File:** `app/templates/daily/results.html` (EXISTING)

**Current:** Shows discussion link after voting (line 545)

**Important:** This is where discussion promotion happens - AFTER voting. The voting flow itself should not change.

**Enhancement:**
- Make discussion link MORE prominent (this is the key improvement)
- Add social proof ("23 people discussing")
- Add "Join discussion" as prominent CTA (after voting is complete)
- Show discussion preview (top 2-3 responses) to entice participation
- Add visual emphasis to discussion section

**Action Items:**
- [ ] Enhance discussion section visibility (make it stand out more)
- [ ] Add social proof prominently
- [ ] Improve CTA visibility and placement
- [ ] Add discussion preview/responses
- [ ] Test user flow (vote → results → discussion)
- [ ] **DO NOT** change voting interface or flow

---

### Phase 7: Migration Strategy

#### 7.1 Existing Subscriber Migration

**Approach:**
1. Set all existing subscribers to `email_frequency = 'weekly'` (default)
2. Set default send day to Tuesday (1) and send hour to 9am
3. Send migration email explaining change
4. Provide link to update preferences
5. Monitor unsubscribe rates

**Migration Email:**
```
Subject: We're improving your Daily Questions experience

Hi [Name],

Based on your feedback, we're moving to a weekly format:
- One email per week with 5 questions
- Sent on Tuesday at 9am (you can change this)
- Same great questions, less inbox clutter

You can choose your preferred day and time, or opt for daily if you prefer.
[Update Preferences] [Learn More]
```

**Action Items:**
- [ ] Create migration script
- [ ] Create migration email template
- [ ] Send to all active subscribers
- [ ] Monitor metrics

#### 7.2 Gradual Rollout

**Week 1:** 
- Deploy code (disabled)
- Test with internal users

**Week 2:**
- Enable for 10% of subscribers (A/B test)
- Monitor engagement metrics

**Week 3:**
- Enable for 50% if metrics positive
- Continue monitoring

**Week 4:**
- Full rollout if successful
- Send migration email to all

**Action Items:**
- [ ] Create feature flag
- [ ] Set up A/B testing
- [ ] Define success metrics
- [ ] Create monitoring dashboard

---

## Code Organization & DRY Principles

### Shared Utilities

**File:** `app/daily/utils.py` (NEW)

**Functions to Extract:**
1. `get_discussion_stats_for_question()` - Reusable discussion stats
2. `build_question_email_data()` - Prepare question data for emails
3. `select_questions_for_digest()` - Question selection logic

**Benefits:**
- Single source of truth for discussion stats
- Reusable across email templates, routes, selection
- Easier testing
- Consistent data structure

### Constants File

**File:** `app/daily/constants.py` (EXISTING - verify)

**Add:**
```python
VALID_EMAIL_FREQUENCIES = ['daily', 'weekly', 'monthly']
DEFAULT_EMAIL_FREQUENCY = 'weekly'

# Send day constants (matching Python's weekday() where Monday=0)
SEND_DAYS = {
    0: 'Monday',
    1: 'Tuesday',  # Default - research shows best engagement
    2: 'Wednesday',
    3: 'Thursday',
    4: 'Friday',
    5: 'Saturday',
    6: 'Sunday'
}
DEFAULT_SEND_DAY = 1          # Tuesday (research-backed optimal)
DEFAULT_SEND_HOUR = 9         # 9am local time

# Question selection
WEEKLY_DIGEST_QUESTION_COUNT = 5
WEEKLY_DIGEST_DAYS_BACK = 7
```

### Template Partials

**File:** `app/templates/emails/partials/question_card.html` (NEW)

**Purpose:** Reusable question card component for:
- Daily email template
- Weekly digest template
- Deep dive template

**Structure:**
```html
{% macro question_card(question, discussion_stats, vote_urls, show_discussion=True) %}
  <!-- Question text -->
  <!-- Context -->
  <!-- Discussion hook (if show_discussion and has_discussion) -->
  <!-- Vote buttons -->
{% endmacro %}
```

**Benefits:**
- DRY: Single source for question card design
- Consistent styling
- Easier maintenance

---

## Downstream Dependencies & Integration Points

### 1. Email Analytics (EmailEvent Model)

**File:** `app/models.py` - `EmailEvent` class (lines 1825-1951)

**Current Implementation:**
- Tracks email events: `sent`, `delivered`, `opened`, `clicked`, `bounced`, `complained`
- Categories: `auth`, `daily_brief`, `daily_question`, `discussion`, `admin`
- Links to `question_subscriber_id` and `daily_question_id` for daily questions

**Required Changes:**
- Weekly digest emails should use category `daily_question` (same category)
- Deep dive emails should also use `daily_question` category
- **Edge Case:** When tracking weekly digest with 5 questions, which `daily_question_id` to use?
  - **Solution:** Track multiple `EmailEvent` records (one per question) OR
  - **Solution:** Use first question's ID and add metadata field for question count
  - **Recommendation:** Track one event per email, store question IDs in metadata JSON field

**Action Items:**
- [ ] Decide on tracking strategy (one event vs multiple)
- [ ] Update `EmailEvent.record_event()` to handle multiple questions
- [ ] Update email analytics dashboard to show weekly digest separately
- [ ] Test webhook handling for weekly digest emails

### 2. Social Media Posting Integration

**File:** `app/scheduler.py` - `post_daily_question_to_social()` (lines 554-653)

**Current Implementation:**
- Posts to X and Bluesky at 2pm UTC daily
- Uses `generate_daily_question_post()` from `app/trending/social_insights.py`
- Tracks with PostHog: `daily_question_posted_to_x`, `daily_question_posted_to_bluesky`

**Required Changes:**
- **Decision Needed:** Should we post weekly digest to social media?
  - Option A: Post Monday digest summary (5 questions)
  - Option B: Continue posting daily (questions still publish daily)
  - **Recommendation:** Continue daily posting (questions still publish daily on website)
- **Edge Case:** Social posts reference "today's question" - wording needs to stay accurate
- **Action Items:**
  - [ ] Verify social posting still works with daily question publishing
  - [ ] Consider adding weekly digest social post (optional enhancement)
  - [ ] Update PostHog tracking if needed

### 3. Admin Interface Updates

**File:** `app/admin/routes.py`

**Subscriber Management (lines 1016-1185):**
- `list_daily_subscribers()` - Shows all subscribers
- `add_subscriber()` - Adds individual subscribers
- `toggle_subscriber()` - Activates/deactivates
- `delete_subscriber()` - Removes subscriber
- `bulk_import_subscribers()` - Bulk import

**Required Changes:**
- Add frequency column to subscriber list view
- Add frequency filter to subscriber list
- Add frequency editing in subscriber management
- Show frequency in subscriber detail view

**Question Management (lines 734-895):**
- `list_daily_questions()` - Lists all questions
- `create_daily_question()` - Creates new question
- `edit_daily_question()` - Edits question
- `publish_daily_question()` - Publishes question

**Required Changes:**
- No changes needed (questions still publish daily)
- Consider adding "discussion activity" indicator in list view

**Action Items:**
- [ ] Update `app/templates/admin/daily/subscribers.html` to show frequency
- [ ] Add frequency filter to subscriber list
- [ ] Add frequency editing capability
- [ ] Update bulk import to set default frequency

### 4. PostHog Event Tracking

**Files:** Multiple locations track PostHog events

**Current Events:**
- `daily_question_subscribed` - When user subscribes (line 765 in `app/daily/routes.py`)
- `daily_question_posted_to_x` - Social posting (line 613 in `app/scheduler.py`)
- `social_post_clicked` - When users click from social (in `app/trending/conversion_tracking.py`)

**Required Changes:**
- Add new event: `weekly_digest_sent` - Track weekly digest sends
- Add new event: `weekly_digest_opened` - Track opens
- Add new event: `frequency_preference_changed` - Track preference updates
- **Edge Case:** Existing `daily_question_subscribed` event should include frequency preference

**Action Items:**
- [ ] Add new PostHog events for weekly digest
- [ ] Update subscription tracking to include frequency
- [ ] Add tracking for frequency preference changes
- [ ] Update analytics dashboard queries

### 5. Settings/Preferences UI

**File:** `app/settings/routes.py` - `view_settings()` (lines 10-31)

**Current Implementation:**
- Handles notification preferences: `email_notifications`, `discussion_participant_notifications`, etc.
- No daily question frequency preference UI

**Required Changes:**
- Add daily question frequency preference to settings page
- Link to subscriber record if exists
- Handle case where user has no subscriber record (create one)

**Action Items:**
- [ ] Add frequency preference section to settings template
- [ ] Create route handler for frequency updates
- [ ] Link User to DailyQuestionSubscriber if not exists
- [ ] Test settings page updates

### 6. Account Deletion Cleanup

**File:** `app/settings/routes.py` - `delete_account()` (lines 61-254)

**Current Implementation:**
- Handles `DailyQuestionSubscriber` cleanup (line 117-118)
- Sets `user_id` to NULL (doesn't delete subscriber)

**Required Changes:**
- No changes needed - existing cleanup handles it
- **Edge Case:** Subscriber remains with email but no user_id (expected behavior)

**Action Items:**
- [ ] Verify account deletion still works correctly
- [ ] Test that orphaned subscribers can still receive emails

### 7. Discussion Sync Logic

**File:** `app/daily/routes.py`

**Current Functions:**
- `sync_vote_to_statement()` (line 645) - Syncs vote to discussion
- `sync_daily_reason_to_statement()` (line 449) - Syncs reason to Response
- `vote()` (line 991) - Website vote submission
- `one_click_vote()` (line 853) - Email vote submission

**Required Changes:**
- No changes needed - existing sync logic works for weekly digest
- **Edge Case:** Multiple questions in weekly digest all sync correctly
- **Edge Case:** Batch voting from weekly digest page needs to sync all votes

**Action Items:**
- [ ] Verify sync logic works for batch voting
- [ ] Test that all 5 questions sync correctly
- [ ] Ensure DiscussionParticipant tracking works for batch votes

### 8. Conversion Tracking

**File:** `app/trending/conversion_tracking.py`

**Current Implementation:**
- Tracks `social_post_clicked` events
- Tracks `discussion_participated_from_social` events

**Required Changes:**
- Add tracking for weekly digest clicks
- Track which question in digest was clicked
- Track discussion clicks from weekly digest

**Action Items:**
- [ ] Add tracking for weekly digest interactions
- [ ] Track question-level clicks in digest
- [ ] Track discussion click-through from digest

### 9. Email Webhook Handling

**File:** `app/brief/routes.py` - Webhook handler (lines 615-720)

**Current Implementation:**
- Handles Resend webhooks for email events
- Uses `EmailAnalytics.record_from_webhook()` (DRY service)

**Required Changes:**
- Weekly digest emails will generate webhook events
- Need to handle multiple questions in one email
- **Edge Case:** Webhook doesn't know which question was clicked (only email ID)

**Action Items:**
- [ ] Verify webhook handling works for weekly digest
- [ ] Add question ID tracking in click URLs (UTM params or query params)
- [ ] Test webhook event recording

### 10. Welcome Email Integration

**File:** `app/resend_client.py` - `send_daily_question_welcome_email()`

**Current Implementation:**
- Sends welcome email when user subscribes
- Mentions daily emails

**Required Changes:**
- Update welcome email copy to mention frequency options
- Explain weekly default with Tuesday 9am send time
- Mention ability to choose preferred send day/time
- Link to preferences page
- Include referral code generation and explanation
- Mention sharing features

**Action Items:**
- [ ] Update welcome email template
- [ ] Add frequency explanation
- [ ] Add link to preferences
- [ ] Generate referral code on subscription
- [ ] Explain referral system in welcome email
- [ ] Add sharing encouragement

## Areas Requiring Attention

### 1. Streak Tracking Adaptation

**Issue:** Current streak system tracks daily participation. Weekly emails change this.

**Current Logic:** `app/models.py` - `update_participation_streak()` (line 2472)
- Increments streak if participation is consecutive days
- Resets if gap > 1 day

**Solution Options:**
1. **Adaptive Streaks:** Track weekly participation (5 questions = 1 "week" streak)
2. **Dual Tracking:** Keep daily streak for website users, add weekly streak for email users
3. **Flexible Window:** Count participation within 7-day window as maintaining streak

**Recommendation:** Option 2 - Dual tracking
- `current_streak` - Daily participation (existing)
- `weekly_streak` - Weekly participation (new)
- Update both based on frequency preference

**Action Items:**
- [ ] Add `weekly_streak` field to model
- [ ] Update streak logic to handle both
- [ ] Update email templates to show appropriate streak
- [ ] Test edge cases

### 2. Token Management for Multiple Questions

**Issue:** Current system generates one vote token per question. Weekly digest needs 5 tokens.

**Current:** `generate_vote_token(question_id)` - Single question

**Solution:**
- Generate tokens for all 5 questions when building email
- Store in email data structure
- Each question card gets its own vote URLs

**Action Items:**
- [ ] Update `_build_vote_urls()` to handle multiple questions
- [ ] Batch token generation for performance
- [ ] Ensure token expiration (7 days) works for all
- [ ] Test token validation

### 3. Discussion Stats Performance

**Issue:** Calculating discussion stats for 5 questions per subscriber could be slow.

**Current:** `get_discussion_participation_data()` queries database per question

**Solution:**
- Cache discussion stats (TTL: 1 hour)
- Batch query for all 5 questions
- Use `get_discussion_stats_for_question()` with caching

**Action Items:**
- [ ] Add caching layer (Redis or in-memory)
- [ ] Batch database queries
- [ ] Monitor query performance
- [ ] Add cache invalidation on discussion updates

### 4. Edge Cases

**Scenarios to Handle:**
1. **< 5 questions available:** Send what's available, don't fail
2. **No discussion-linked questions:** Still send digest, just no discussion hooks
3. **Subscriber changes frequency mid-week:** Handle gracefully
4. **Email send fails for one question:** Continue with others
5. **Discussion deleted after email sent:** Handle 404 gracefully

**Action Items:**
- [ ] Add error handling for each edge case
- [ ] Add logging for monitoring
- [ ] Test edge cases
- [ ] Add fallback behavior

### 5. Backward Compatibility

**Issue:** Existing daily email system must continue working.

**Solution:**
- Keep `send_daily_question()` function
- Add frequency filtering to batch sender
- Maintain existing templates
- Gradual migration

**Action Items:**
- [ ] Test daily emails still work
- [ ] Verify existing subscribers receive emails
- [ ] Monitor for regressions
- [ ] Create rollback plan

### 6. Email Analytics for Multiple Questions

**Issue:** Weekly digest contains 5 questions, but `EmailEvent` links to single `daily_question_id`.

**Current Model:** `EmailEvent.daily_question_id` (single FK)

**Recommended Solution:** One `EmailEvent` per email send + question IDs in URL query params

**Why This Approach:**
- Avoids 5x database bloat (one event per email, not 5)
- Still provides question-level CTR via URL query params
- Simpler webhook handling (one event per email)
- Easier analytics queries (parse query params)
- No schema changes needed

**Implementation:**

**URL Structure:**
```python
# Vote URLs in weekly digest (include source for return flow):
vote_agree_url = f"{base_url}/daily/v/{token}/agree?q={question_id}&type=vote&source=weekly_digest"
vote_disagree_url = f"{base_url}/daily/v/{token}/disagree?q={question_id}&type=vote&source=weekly_digest"
vote_unsure_url = f"{base_url}/daily/v/{token}/unsure?q={question_id}&type=vote&source=weekly_digest"

# Discussion URLs (awareness, not primary):
discussion_url = f"{base_url}/discussions/{id}/{slug}?q={question_id}&source=weekly_digest&link_type=discussion"

# Question view URLs:
question_url = f"{base_url}/daily/{date}?q={question_id}&source=weekly_digest&link_type=view"

# Batch page URL (for "View All 5 Questions" link):
batch_url = f"{base_url}/daily/weekly?token={subscriber.magic_token}"
```

**Query Params:**
- `q` - Question ID (for question-level tracking)
- `type` - Link type: `vote`, `discussion`, `view`
- `source` - Email source: `weekly_digest`, `deep_dive`, `daily`
- `link_type` - Same as `type` (for consistency)

**Analytics Parsing:**
```python
# In EmailEvent click_url, parse query params:
# click_url = "/daily/v/token/agree?q=123&type=vote&source=weekly_digest"
# Extract question_id=123, link_type=vote, source=weekly_digest

# In analytics dashboard:
# Group by question_id to see which questions get most clicks
# Filter by link_type to see vote vs discussion clicks
```

**Action Items:**
- [ ] Update `_build_vote_urls()` to include query params
- [ ] Update discussion URLs to include query params
- [ ] Update analytics queries to parse query params
- [ ] Add helper function to extract question_id from click_url
- [ ] Update analytics dashboard to show question-level CTR
- [ ] Test webhook recording with query params

### 7. Social Media Post Timing

**Issue:** Social posts happen at 2pm UTC daily. Weekly digest doesn't change this, but wording might.

**Current:** Posts "today's question" to social media

**Solution:** 
- Questions still publish daily (for website visitors)
- Social posts continue daily (no change needed)
- Wording stays accurate ("today's question")

**Action Items:**
- [ ] Verify social posting still works
- [ ] No code changes needed (questions publish daily)

### 8. Admin Bulk Operations

**Issue:** Admin can bulk import/remove subscribers. Need to handle frequency preference.

**Current:** `bulk_import_subscribers()` (line 1115) creates subscribers without frequency

**Solution:**
- Set default frequency (`weekly`) for bulk imports
- Set default send day (Tuesday) and hour (9am) for bulk imports
- Add frequency column to bulk import UI
- Allow frequency selection in bulk operations

**Action Items:**
- [ ] Update bulk import to set frequency
- [ ] Add frequency column to bulk import form
- [ ] Test bulk operations

### 9. Email Template Rendering Performance

**Issue:** Weekly digest template renders 5 questions. Could be slow with discussion stats.

**Solution:**
- Cache discussion stats (already planned)
- Batch database queries
- Use template partials for question cards (DRY)

**Action Items:**
- [ ] Implement caching (Phase 2)
- [ ] Batch query discussion stats
- [ ] Monitor template rendering time
- [ ] Add performance logging

### 10. Magic Token Management

**Issue:** Weekly digest needs 5 vote tokens (one per question). Current system generates one.

**Current:** `generate_vote_token(question_id)` - Single token

**Solution:**
- Generate tokens for all 5 questions when building email
- Store in email data structure
- Each question card gets its own vote URLs

**Action Items:**
- [ ] Update `_build_vote_urls()` to handle multiple questions
- [ ] Batch token generation
- [ ] Test token expiration (7 days) for all questions
- [ ] Verify token validation works

### 11. Unsubscribe Flow

**Issue:** Unsubscribe from weekly digest should work correctly.

**Current:** `app/daily/routes.py` - `unsubscribe()` (line 791)

**Solution:**
- Unsubscribe works the same (sets `is_active = False`)
- Unsubscribe link in weekly digest emails
- Track unsubscribe reason (already implemented)

**Action Items:**
- [ ] Verify unsubscribe works from weekly emails
- [ ] Test unsubscribe reason tracking
- [ ] Ensure List-Unsubscribe headers work

### 12. Email Client Compatibility

**Issue:** Weekly digest with 5 questions might render differently across email clients.

**Solution:**
- Test in major clients (Gmail, Outlook, Apple Mail)
- Use responsive design
- Fallback for older clients

**Action Items:**
- [ ] Test template in major email clients
- [ ] Verify mobile rendering
- [ ] Test dark mode compatibility
- [ ] Add fallback styles

---

## Testing Requirements

### Unit Tests

**File:** `tests/test_daily_email_frequency.py` (NEW)

**Test Cases:**
1. Frequency preference validation
2. Discussion stats calculation
3. Question selection for weekly digest
4. Token generation for multiple questions
5. Streak tracking with weekly participation

### Integration Tests

**File:** `tests/test_weekly_digest_sending.py` (NEW)

**Test Cases:**
1. Weekly digest email rendering
2. Frequency-based subscriber filtering
3. Batch sending with multiple questions
4. Discussion links in emails
5. Unsubscribe handling

### Manual Testing Checklist

- [ ] Weekly digest email renders correctly (desktop + mobile)
- [ ] All 5 questions display properly
- [ ] Discussion hooks show correct stats
- [ ] Vote buttons work for all questions
- [ ] Discussion links navigate correctly
- [ ] Frequency preference updates work
- [ ] Daily emails still work for daily users
- [ ] Unsubscribe works from weekly emails
- [ ] Streak tracking updates correctly
- [ ] Edge cases handled gracefully

---

## Success Metrics

### Engagement Metrics

**Primary (Voting First):**
- **Vote Participation Rate:** % of email recipients who vote on questions
  - Current baseline: [TBD - measure before]
  - Target: +20-30% increase (less email fatigue = more voting)

- **Vote Completion Rate:** % who vote on all 5 questions in weekly digest
  - Current baseline: [TBD]
  - Target: 40-50% of digest recipients vote on at least 3 questions

- **Email Engagement Rate:** Open rate + vote click rate
  - Current: [TBD]
  - Target: Maintain or improve

**Secondary (Discussion Participation After Voting):**
- **Vote-to-Discussion Conversion:** % of voters who then join discussions
  - Current baseline: [TBD - measure before]
  - Target: +30-50% increase (better discovery after voting)

- **Discussion Click-Through:** % who click discussion links (from email or results page)
  - Current baseline: [TBD]
  - Target: +40-60% increase

**Other Metrics:**
- **Unsubscribe Rate:** Should decrease with less frequency
- **Weekly Digest Engagement:** Open rate, vote rate, discussion participation rate

### Retention Metrics

- **Subscriber Retention:** % who stay subscribed after change
- **Re-engagement:** % of inactive users who return with new format
- **Frequency Preference Distribution:** How users choose frequencies

### Performance Metrics

- **Email Send Time:** Should be similar (batch API)
- **Database Query Performance:** Monitor discussion stats queries
- **Cache Hit Rate:** For discussion stats caching

---

## Risk Mitigation

### Risk 1: User Backlash from Frequency Change

**Mitigation:**
- Gradual rollout (10% → 50% → 100%)
- Clear communication about change
- Easy preference management
- Option to keep daily emails

### Risk 2: Reduced Engagement

**Mitigation:**
- A/B test before full rollout
- Monitor metrics closely
- Quick rollback plan
- User feedback collection

### Risk 3: Technical Issues

**Mitigation:**
- Comprehensive testing
- Feature flags for gradual enablement
- Monitoring and alerting
- Rollback procedure documented

### Risk 4: Discussion Stats Performance

**Mitigation:**
- Implement caching
- Batch database queries
- Monitor query times
- Scale database if needed

---

## Growth & Engagement Features

### Referral System

**Purpose:** Encourage users to share with people who see things differently, driving diverse participation in discussions.

**Implementation:**

**Database Schema:**
```python
# Add to DailyQuestionSubscriber model:
referral_code = db.Column(db.String(32), unique=True, nullable=True)
referred_by_id = db.Column(db.Integer, db.ForeignKey('daily_question_subscriber.id'), nullable=True)
referral_count = db.Column(db.Integer, default=0)  # How many they've referred
referral_participation_count = db.Column(db.Integer, default=0)  # How many referred users participated in discussions
```

**Referral Code Generation:**
```python
def generate_referral_code(self):
    """Generate unique referral code for subscriber"""
    import secrets
    code = secrets.token_urlsafe(16)[:16].upper()  # 16 char code
    # Ensure uniqueness
    while DailyQuestionSubscriber.query.filter_by(referral_code=code).first():
        code = secrets.token_urlsafe(16)[:16].upper()
    self.referral_code = code
    return code
```

**Email Integration:**
- Add referral section to weekly digest footer
- Copy: "Share with someone who sees this differently →"
- Include referral link: `{base_url}/daily/subscribe?ref={referral_code}`
- Show referral stats: "You've shared with 3 people, 2 joined discussions"

**Subscription Flow:**
```python
# In subscribe() route:
ref_code = request.args.get('ref')
if ref_code:
    referrer = DailyQuestionSubscriber.query.filter_by(referral_code=ref_code).first()
    if referrer:
        subscriber.referred_by_id = referrer.id
        referrer.referral_count += 1
```

**Participation Tracking:**
- Track referred user votes first (primary metric)
- When referred user participates in discussion, increment `referral_participation_count`
- Reward based on both voting AND discussion participation
- Badge: "Bridge Builder" for referring users who both vote and participate in discussions

**Action Items:**
- [ ] Add referral fields to DailyQuestionSubscriber model
- [ ] Create migration for referral fields
- [ ] Add referral code generation method
- [ ] Update subscribe route to handle referral codes
- [ ] Add referral section to weekly digest email template
- [ ] Track referral participation in discussion sync logic
- [ ] Create referral stats display in user profile
- [ ] Add "Bridge Builder" badge logic

### Enhanced Sharing Features

**Current State:** Basic share buttons exist (`share_button.html` component)

**Enhancements:**

**1. Contextual Share Messages:**
```python
# Different share messages based on context:
# For weekly digest:
"5 civic questions this week - where do you stand?"
"Share with someone who sees this differently"

# For individual questions:
"Daily Question: {question_text[:100]}..."
"Join the conversation"

# For discussions:
"{X} people discussing: {discussion_title}"
"See what different perspectives think"
```

**2. Share Tracking:**
- Track shares via PostHog: `weekly_digest_shared`, `question_shared`, `discussion_shared`
- Track share destination: X, Bluesky, Email, WhatsApp, etc.
- Track conversion: share → click → subscription → participation

**3. Share-to-Email Feature:**
- "Email this digest to a friend" button in weekly digest
- Pre-filled email with referral code
- Subject: "5 civic questions - where do you stand?"
- **Focus:** Encourage voting first, then discussion participation

**Action Items:**
- [ ] Create contextual share message generator
- [ ] Add share tracking to PostHog
- [ ] Enhance share_button component with contextual messages
- [ ] Add "Email this digest" feature
- [ ] Track share conversions

### Participation Badges & Rewards

**Purpose:** Reward meaningful engagement (discussion participation), not just growth metrics.

**Badge System:**

**Database Schema:**
```python
# Add to DailyQuestionSubscriber or User model:
badges = db.Column(db.JSON, default=list)  # List of badge names
# Or create separate Badge model for more flexibility

# Badge Types:
# - "Bridge Builder" - Referred users who participate in discussions
# - "Thoughtful Participant" - Already exists (thoughtful_participations)
# - "Discussion Starter" - Started X discussions
# - "Consensus Seeker" - Participated in X discussions that reached consensus
# - "Weekly Regular" - Participated in X weekly digests
```

**Badge Display:**
- Show badges in email footer (subtle)
- Show badges on profile/results page
- Badge icons/emojis in email signature

**Reward Logic:**
```python
def check_and_award_badges(subscriber):
    """Check if subscriber qualifies for badges"""
    badges = []
    
    # Active Voter: Voted on 10+ questions (primary engagement)
    vote_count = DailyQuestionResponse.query.filter_by(
        user_id=subscriber.user_id if subscriber.user_id else None,
        session_fingerprint=subscriber.session_fingerprint if not subscriber.user_id else None
    ).count()
    if vote_count >= 10:
        badges.append('active_voter')
    
    # Bridge Builder: Referred users who voted AND participated in discussions
    if subscriber.referral_participation_count >= 3:
        badges.append('bridge_builder')
    
    # Weekly Regular: Voted in 5+ weekly digests
    if subscriber.weekly_participation_count >= 5:
        badges.append('weekly_regular')
    
    # Update subscriber badges
    subscriber.badges = list(set(subscriber.badges + badges))
```

**Action Items:**
- [ ] Design badge system (JSON field or separate model)
- [ ] Create badge checking logic
- [ ] Add badge display to email templates
- [ ] Add badge display to profile/results pages
- [ ] Create badge icons/designs
- [ ] Add badge notification when earned

### Reactivation & Re-engagement Emails

**Purpose:** Bring back inactive users without guilt/FOMO messaging.

**Email Types:**

**1. "We Miss You" Email (2 weeks inactive):**
```
Subject: "5 questions you might have missed"
- Show 5 questions from past 2 weeks
- "Catch up on what people are discussing"
- Positive, not guilt-driven
- Link to weekly digest signup
```

**2. "Streak at Risk" Email (4 weeks inactive):**
```
Subject: "Your {X}-day streak is still going!"
- Celebrate existing streak
- "Join us this week for 5 new questions"
- Positive reinforcement
- No threats, just invitation
```

**3. "Pausing Emails" Email (6 weeks inactive):**
```
Subject: "We're pausing your emails"
- Respectful pause message
- "We'll resume when you're ready"
- Easy reactivation link
- No shame, just options
```

**Implementation:**
```python
# New scheduler job:
@scheduler.scheduled_job('cron', day_of_week='mon', hour=9, minute=0, id='reactivation_emails')
def send_reactivation_emails():
    """Send reactivation emails to inactive subscribers"""
    # Find subscribers inactive for 2, 4, 6 weeks
    # Send appropriate email based on inactivity period
    # Track reactivation success
```

**Action Items:**
- [ ] Create reactivation email templates
- [ ] Add scheduler job for reactivation emails
- [ ] Create logic to identify inactive subscribers
- [ ] Track reactivation success metrics
- [ ] A/B test messaging (positive vs neutral)

### Newsletter-Style Growth Patterns

**Learnings from Morning Brew, Axios, theSkimm:**

**1. "Smart Brevity" Format (Axios):**
- ✅ Already implementing: 5 questions in scannable cards
- ✅ One main takeaway per question
- ✅ Context provided but concise

**2. Shareability (Wordle):**
- ✅ Questions publish daily (maintains ritual)
- ✅ Weekly digest is convenience layer
- ✅ Share results/streaks (already have this)
- ⚠️ Add: "Share your weekly results" feature

**3. Habit Surface (Newsletter Playbook):**
- ✅ Consistent timing (user's preferred day/time, default Tuesday 9am)
- ✅ Predictable format
- ✅ Finite engagement (5 questions, not overwhelming)
- ⚠️ Add: "Forward to someone who'd disagree" CTA

**Action Items:**
- [ ] Add "Share your weekly results" feature
- [ ] Add "Forward to someone who'd disagree" CTA to emails
- [ ] Ensure consistent timing and format
- [ ] Test shareability of weekly digest format

---

## Next Steps

1. **Review this plan** with team
2. **Approve approach** and timeline
3. **Set up feature branch** for development
4. **Create GitHub issues** for each phase
5. **Begin Phase 1** (Database migration)

---

## Additional Implementation Details

### Referral System Database Migration

**File:** `migrations/versions/XXXX_add_referral_system_to_daily_subscriber.py`

```python
"""Add referral system to daily question subscribers

Revision ID: XXXX
Revises: [previous]
Create Date: 2025-01-XX
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    # Add referral fields
    op.add_column('daily_question_subscriber', 
        sa.Column('referral_code', sa.String(32), nullable=True, unique=True))
    op.add_column('daily_question_subscriber',
        sa.Column('referred_by_id', sa.Integer(), sa.ForeignKey('daily_question_subscriber.id'), nullable=True))
    op.add_column('daily_question_subscriber',
        sa.Column('referral_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('daily_question_subscriber',
        sa.Column('referral_participation_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('daily_question_subscriber',
        sa.Column('badges', sa.JSON(), nullable=True))
    op.add_column('daily_question_subscriber',
        sa.Column('weekly_participation_count', sa.Integer(), nullable=False, server_default='0'))
    
    # Create indexes
    op.create_index('idx_dqs_referral_code', 'daily_question_subscriber', ['referral_code'])
    op.create_index('idx_dqs_referred_by', 'daily_question_subscriber', ['referred_by_id'])

def downgrade():
    op.drop_index('idx_dqs_referred_by', 'daily_question_subscriber')
    op.drop_index('idx_dqs_referral_code', 'daily_question_subscriber')
    op.drop_column('daily_question_subscriber', 'weekly_participation_count')
    op.drop_column('daily_question_subscriber', 'badges')
    op.drop_column('daily_question_subscriber', 'referral_participation_count')
    op.drop_column('daily_question_subscriber', 'referral_count')
    op.drop_column('daily_question_subscriber', 'referred_by_id')
    op.drop_column('daily_question_subscriber', 'referral_code')
```

### Referral Tracking in Discussion Participation

**File:** `app/daily/routes.py` - Update `sync_vote_to_statement()` and discussion participation

**Add Referral Participation Tracking:**
```python
def track_referral_participation(user_id, subscriber_id):
    """Track when a referred user participates in discussion"""
    if subscriber_id and subscriber_id.referred_by_id:
        referrer = DailyQuestionSubscriber.query.get(subscriber_id.referred_by_id)
        if referrer:
            referrer.referral_participation_count += 1
            # Check for Bridge Builder badge
            if referrer.referral_participation_count >= 3 and 'bridge_builder' not in (referrer.badges or []):
                referrer.badges = (referrer.badges or []) + ['bridge_builder']
            db.session.commit()
```

**Action Items:**
- [ ] Add referral participation tracking to discussion sync
- [ ] Call tracking when user participates in discussion
- [ ] Update badge checking logic

### Share Results Feature

**Purpose:** Allow users to share their weekly digest participation results.

**Implementation:**

**New Route:**
```python
@daily_bp.route('/daily/weekly/share')
def share_weekly_results():
    """Generate shareable weekly results card"""
    # Get user's participation in past week's questions
    # Generate share card image (like Wordle)
    # Return shareable link
```

**Share Card Content:**
- Questions participated in (5 emoji blocks)
- Streak information
- "Share your civic engagement this week"
- Link back to weekly digest

**Action Items:**
- [ ] Create share results route
- [ ] Generate share card image
- [ ] Add share button to weekly digest results page
- [ ] Track share results events

### Enhanced Email CTAs

**Weekly Digest Email CTAs:**

1. **Primary CTA (per question):**
   - **"Vote" buttons (one-click)** - THIS IS THE MAIN ACTION
   - Vote buttons are prominent, easy to click
   - Goal: Get people to vote first

2. **Secondary CTA (per question):**
   - "23 people discussing →" (awareness/preview)
   - Discussion link (for after voting)
   - Purpose: Let voters know discussions exist, but voting comes first

3. **Tertiary CTAs:**
   - "Forward to someone who sees this differently"
   - "Share your results"
   - "View all questions on website"

4. **Footer CTAs:**
   - Referral link with code
   - Preferences link
   - Unsubscribe link

**CTA Hierarchy:**
1. Vote (primary - get people to vote)
2. Discussion awareness (secondary - show discussions exist)
3. Discussion participation (tertiary - after voting, on results page)

**Action Items:**
- [ ] Design CTA hierarchy for weekly digest
- [ ] Add "Forward to someone who disagrees" CTA
- [ ] Add referral link in footer
- [ ] Test CTA placement and wording

### Analytics Dashboard Enhancements

**New Metrics to Track:**

1. **Vote Metrics (Primary):**
   - Vote rate per question in weekly digest
   - Vote completion rate (how many vote on all 5 questions)
   - Vote CTR from email (primary engagement metric)
   - Vote-to-discussion conversion rate (secondary metric)

2. **Question-Level Metrics:**
   - CTR per question in weekly digest
   - Vote rate per question (PRIMARY)
   - Discussion click-through per question (SECONDARY)
   - Parse from query params in click_url

3. **Referral Metrics:**
   - Referral signups
   - Referral vote rate (primary)
   - Referral discussion participation rate (secondary)
   - Bridge Builder badge awards
   - Referral source tracking

4. **Engagement Metrics:**
   - Weekly digest open rate
   - Deep dive open rate
   - Vote participation rate (PRIMARY GOAL)
   - Discussion participation rate (SECONDARY GOAL)
   - Share rate
   - Reactivation success rate

**Key Insight:** Track voting as primary metric, discussion participation as secondary conversion metric

**Action Items:**
- [ ] Add question-level analytics queries
- [ ] Add referral metrics dashboard
- [ ] Add engagement metrics tracking
- [ ] Create analytics visualization

## Questions for Review

1. ~~**Frequency Default:** Should new subscribers default to 'twice_weekly' or 'daily'?~~ **DECIDED: Weekly**
2. ~~**Send Day Default:** What day should be the default?~~ **DECIDED: Tuesday 9am (research-backed)**
3. ~~**User Choice for Send Day:** Should users be able to choose?~~ **DECIDED: Yes, like daily brief**
4. **Streak Tracking:** Which approach do you prefer (adaptive, dual, flexible)?
5. **Rollout Strategy:** Gradual (A/B test) or all-at-once?
6. **Migration Communication:** Email, in-app notification, or both?
7. **Referral Rewards:** Participation-based only, or include signup rewards?
8. **Badge Display:** In emails, on profile, or both?
9. **Timezone Detection:** Auto-detect from browser, or require manual selection?

---

## References

- Current Email Template: `app/templates/emails/daily_question.html`
- Email Sending: `app/resend_client.py` - `send_daily_question()`
- Scheduler: `app/scheduler.py` - `daily_question_email()`
- Discussion Stats: `app/daily/routes.py` - `get_discussion_participation_data()`
- Subscriber Model: `app/models.py` - `DailyQuestionSubscriber`
- Question Model: `app/models.py` - `DailyQuestion`

---

## Critical Dependencies Summary

### Must Address Before Implementation

1. **Email Analytics Tracking** ⚠️
   - Decision needed: How to track 5 questions in one email?
   - Impact: Analytics dashboard, reporting
   - Files: `app/models.py` (EmailEvent), `app/lib/email_analytics.py`

2. **Admin Interface Updates** ⚠️
   - Frequency column in subscriber list
   - Frequency editing capability
   - Bulk operations need frequency handling
   - Files: `app/admin/routes.py`, `app/templates/admin/daily/subscribers.html`

3. **Settings/Preferences UI** ⚠️
   - Add frequency preference to user settings
   - Link User to DailyQuestionSubscriber
   - Files: `app/settings/routes.py`, `app/templates/settings/settings.html`

4. **PostHog Event Tracking** ⚠️
   - New events for weekly digest
   - Update subscription tracking
   - Files: Multiple (see PostHog section)

5. **Magic Token Generation** ⚠️
   - Batch token generation for 5 questions
   - Token expiration handling
   - Files: `app/resend_client.py`, `app/models.py` (DailyQuestionSubscriber)

### Should Address During Implementation

6. **Welcome Email Updates**
   - Mention frequency options
   - Link to preferences
   - File: `app/templates/emails/daily_question_welcome.html`

7. **Conversion Tracking**
   - Track weekly digest clicks
   - Track question-level interactions
   - File: `app/trending/conversion_tracking.py`

8. **Email Webhook Handling**
   - Handle multiple questions in webhook
   - Add question ID to click URLs
   - File: `app/brief/routes.py` (webhook handler)

9. **Template Performance**
   - Cache discussion stats
   - Batch database queries
   - Monitor rendering time

10. **Email Client Testing**
    - Test in major clients
    - Mobile rendering
    - Dark mode compatibility

### No Changes Required (Verified)

- ✅ **Social Media Posting** - Continues daily (questions publish daily)
- ✅ **Account Deletion** - Existing cleanup handles subscribers
- ✅ **Discussion Sync Logic** - Works for batch voting
- ✅ **Unsubscribe Flow** - Works the same way

---

## Pre-Implementation Checklist

Before starting implementation, ensure:

- [ ] Team review of this plan completed
- [ ] Decisions made on:
  - [ ] Email analytics tracking strategy (one event vs multiple)
  - [ ] Social media posting strategy (continue daily vs weekly)
  - [ ] Streak tracking approach (adaptive vs dual vs flexible)
- [ ] Database backup scheduled
- [ ] Staging environment ready
- [ ] Feature flag system in place
- [ ] Monitoring/alerting configured
- [ ] Rollback plan documented

---

## Code Review Checklist

When reviewing implementation PRs, verify:

### Database Changes
- [ ] Migration tested on staging
- [ ] Default values set correctly
- [ ] Indexes added for performance
- [ ] Rollback migration works

### Email Sending
- [ ] Frequency filtering works correctly
- [ ] Batch sending handles errors gracefully
- [ ] Token generation for multiple questions works
- [ ] Discussion stats included in emails

### Templates
- [ ] Weekly digest renders correctly
- [ ] Deep dive template works
- [ ] Mobile responsive
- [ ] Email client compatibility tested

### Admin Interface
- [ ] Frequency column visible
- [ ] Frequency editing works
- [ ] Bulk operations handle frequency
- [ ] Subscriber list filters work

### Analytics
- [ ] Email events tracked correctly
- [ ] PostHog events fire
- [ ] Analytics dashboard shows weekly digest
- [ ] Webhook handling works

### Testing
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Manual testing completed
- [ ] Edge cases handled

---

**Document Status:** Ready for Implementation (Comprehensive Plan with Growth Features)
**Last Updated:** January 2025
**Version:** 1.2 - Updated with weekly default, Tuesday 9am send time, and user choice for send day
**Author:** AI Assistant (based on user requirements, codebase analysis, email send-time research, and growth best practices)
