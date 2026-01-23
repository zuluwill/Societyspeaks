# Question Selection Engagement Improvements
## Future Enhancements for Maximizing Voting & Discussion Participation

**Date:** January 2025  
**Status:** Future Enhancements (Not Yet Implemented)  
**Related:** Weekly Digest Implementation, Daily Question Selection

---

## Executive Summary

This document outlines strategic improvements to the question/statement selection system to maximize engagement. The current system uses engagement-weighted scoring, but there are opportunities to enhance it with better metrics, personalization, and data-driven optimization.

**Current System:**
- Engagement-weighted scoring (civic, timeliness, clarity, controversy, historical)
- Prioritizes discussion-linked questions for digests
- Uses weighted random selection from top candidates

**Goal:** Increase both voting (primary) and discussion participation (secondary) through smarter question selection.

---

## Current Selection System

### Daily Question Selection

**Function:** `select_next_question_source()` in `app/daily/auto_selection.py`

**Scoring Factors (Weighted):**
- **Civic Relevance (25%):** How important for civic discourse
- **Timeliness (25%):** Recency (exponential decay over 14 days)
- **Clarity (20%):** Statement length (optimal: 50-100 chars)
- **Controversy Potential (15%):** Likelihood of divided opinions
- **Historical Performance (15%):** Past performance by topic category

**Selection Process:**
1. Get eligible discussions (not used in last 30 days)
2. Score all seed statements from top 15 discussions
3. Take top 10 candidates by score
4. Weighted random selection from top 10
5. Fallback to trending topics → direct statements

### Weekly Digest Selection

**Function:** `select_questions_for_weekly_digest()` in `app/daily/auto_selection.py`

**Scoring:**
- +0.4 if linked to discussion
- +0.2 if discussion has recent activity (24 hours)
- +0.2 for recency
- +0.2 for response count (capped)

**Returns:** Top 5 questions from past 7 days

### Monthly Digest Selection

**Function:** `select_questions_for_monthly_digest()` in `app/daily/auto_selection.py`

**Scoring:**
- +0.3 if linked to discussion
- +0.2 if discussion has recent activity (7 days)
- +0.15 for recency
- +0.25 for response count (higher threshold: 100+)
- +0.1 for high engagement (20+ votes)

**Returns:** Top 10 questions from past 30 days

---

## Recommended Improvements

### 1. Enhanced Historical Performance Tracking ⭐ **HIGH PRIORITY**

**Current Limitation:**
- Only tracks response count by topic category
- Doesn't measure engagement quality or discussion conversion

**Proposed Enhancements:**

#### Track Discussion Participation Rate
```python
# New metric: % of voters who join discussions
discussion_conversion_rate = (
    voters_who_joined_discussion / total_voters
) * 100
```

**Implementation:**
- Query `DailyQuestionResponse` + `DiscussionParticipant` join
- Calculate conversion rate per question
- Use in historical performance scoring
- Boost questions with high conversion rates

**Impact:** Prioritize questions that drive both voting AND discussion participation

#### Track Reason Submission Rate
```python
# New metric: % of voters who provide thoughtful reasons
reason_submission_rate = (
    responses_with_reason / total_responses
) * 100
```

**Implementation:**
- Query `DailyQuestionResponse` where `reason IS NOT NULL`
- Calculate rate per question/topic
- Boost questions that inspire thoughtful participation

**Impact:** Select questions that drive deeper engagement

#### Track Vote Distribution Balance
```python
# New metric: How balanced are the votes?
# Balanced (40/40/20) = more engaging than lopsided (90/5/5)
balance_score = 1.0 - abs(agree_pct - 50) / 50
# 50/50 split = 1.0, 90/10 split = 0.2
```

**Implementation:**
- Calculate agree/disagree/unsure percentages
- Score based on balance (closer to 50/50 = higher)
- Boost balanced questions in selection

**Impact:** More engaging questions that spark discussion

#### Track Time-to-Vote
```python
# New metric: How quickly do users vote after seeing question?
# Faster = higher engagement
avg_time_to_vote = average(time_voted - time_question_seen)
```

**Implementation:**
- Track when question is first viewed (email open, page view)
- Track when vote is submitted
- Calculate average time difference
- Boost questions with faster voting

**Impact:** Prioritize questions that capture attention immediately

#### Track Return Rate
```python
# New metric: Do users come back to see results?
return_rate = (
    users_who_viewed_results / total_voters
) * 100
```

**Implementation:**
- Track page views on results page
- Calculate return rate per question
- Boost questions with high return rates

**Impact:** Select questions that maintain interest

**Files to Modify:**
- `app/daily/auto_selection.py` - `get_historical_performance()`
- `app/models.py` - Add helper methods to `DailyQuestion`
- New: `app/daily/engagement_metrics.py` - Centralized metrics calculation

---

### 2. Discussion Engagement Quality Score ⭐ **HIGH PRIORITY**

**Current Limitation:**
- Weekly/monthly digests boost for "has discussion" (+0.4)
- Doesn't consider discussion health, activity, or quality

**Proposed Enhancements:**

#### Active Discussion Boost
```python
# Boost for discussions with recent activity
recent_votes = StatementVote.query.filter(
    StatementVote.discussion_id == discussion.id,
    StatementVote.created_at >= 24_hours_ago
).count()

if recent_votes > 5:
    score += 0.2  # Active discussion
elif recent_votes > 0:
    score += 0.1  # Some activity
```

**Implementation:**
- Check for votes in last 24 hours (weekly) or 7 days (monthly)
- Boost based on activity level
- Already partially implemented, but could be enhanced

**Impact:** Prioritize questions linked to active discussions

#### Balanced Discussion Boost
```python
# Boost for discussions with participation from both sides
agree_votes = votes where position == 'agree'
disagree_votes = votes where position == 'disagree'

balance_ratio = min(agree_votes, disagree_votes) / max(agree_votes, disagree_votes)
# 1.0 = perfectly balanced, 0.0 = one-sided

if balance_ratio > 0.6:
    score += 0.15  # Balanced discussion
```

**Implementation:**
- Query `StatementVote` to get vote distribution
- Calculate balance ratio
- Boost balanced discussions

**Impact:** Prioritize questions that lead to genuine debate, not echo chambers

#### Bridge Statement Boost
```python
# Boost for questions linked to bridge statements (unite opposing groups)
if question.source_statement.is_bridge_statement:
    score += 0.2
```

**Implementation:**
- Check if linked statement is a bridge statement (from consensus analysis)
- Boost bridge-linked questions

**Impact:** Prioritize questions that reveal common ground

#### Discussion Growth Boost
```python
# Boost for discussions with growing participation
participants_last_week = count(participants where joined >= 7_days_ago)
participants_this_week = count(participants where joined >= today)

growth_rate = participants_this_week / participants_last_week
if growth_rate > 1.2:  # 20% growth
    score += 0.1
```

**Implementation:**
- Track participant growth over time
- Boost growing discussions

**Impact:** Prioritize questions linked to trending discussions

#### Stale Discussion Penalty
```python
# Penalize questions from inactive discussions
last_activity = max(StatementVote.created_at for discussion)
days_since_activity = (now - last_activity).days

if days_since_activity > 7:
    score -= 0.1  # Stale discussion
```

**Implementation:**
- Check last activity date
- Penalize stale discussions

**Impact:** Avoid questions from dead discussions

**Files to Modify:**
- `app/daily/auto_selection.py` - `select_questions_for_weekly_digest()`
- `app/daily/auto_selection.py` - `select_questions_for_monthly_digest()`
- New: `app/daily/discussion_quality.py` - Discussion health metrics

---

### 3. Vote Distribution Balance Factor ⭐ **HIGH PRIORITY**

**Insight:**
- Balanced questions (40% agree, 40% disagree, 20% unsure) drive more engagement
- Lopsided questions (90% agree) get less discussion

**Proposed Implementation:**

```python
def calculate_vote_balance_score(question):
    """
    Score based on vote distribution balance.
    Balanced = more engaging, lopsided = less engaging.
    """
    percentages = question.vote_percentages
    agree_pct = percentages['agree']
    disagree_pct = percentages['disagree']
    unsure_pct = percentages['unsure']
    
    # Calculate how balanced the distribution is
    # Perfect balance (50/50) = 1.0, completely lopsided (100/0) = 0.0
    main_split_balance = 1.0 - abs(agree_pct - disagree_pct) / 100.0
    
    # Boost for having some "unsure" (shows complexity)
    unsure_bonus = min(unsure_pct / 30.0, 0.2)  # Cap at 0.2
    
    # Penalize extreme lopsidedness
    if agree_pct > 80 or disagree_pct > 80:
        main_split_balance *= 0.5  # Heavy penalty
    
    return main_split_balance + unsure_bonus
```

**Usage:**
- For existing questions: Use actual vote percentages
- For new questions: Estimate based on similar statements
- Add to engagement score calculation

**Impact:** Select questions that spark genuine debate

**Files to Modify:**
- `app/daily/auto_selection.py` - Add `calculate_vote_balance_score()`
- `app/daily/auto_selection.py` - Integrate into scoring

---

### 4. Social Proof & Momentum Signals

**Current Limitation:**
- Doesn't consider existing engagement signals or momentum

**Proposed Enhancements:**

#### Recent Activity Boost
```python
# Boost questions with votes in last 24 hours
recent_votes = DailyQuestionResponse.query.filter(
    DailyQuestionResponse.daily_question_id == question.id,
    DailyQuestionResponse.created_at >= 24_hours_ago
).count()

if recent_votes > 10:
    score += 0.15  # High momentum
elif recent_votes > 5:
    score += 0.1   # Some momentum
elif recent_votes > 0:
    score += 0.05  # Recent activity
```

**Implementation:**
- Query recent votes (last 24 hours)
- Boost based on activity level
- Use in weekly/monthly digest selection

**Impact:** Prioritize questions with current momentum

#### Growing Participation Boost
```python
# Boost questions with increasing vote rate
votes_yesterday = count(votes where date = yesterday)
votes_today = count(votes where date = today)

if votes_today > votes_yesterday * 1.2:  # 20% growth
    score += 0.1
```

**Implementation:**
- Track daily vote counts
- Calculate growth rate
- Boost growing questions

**Impact:** Prioritize questions that are gaining traction

#### Discussion Momentum Boost
```python
# Boost for discussions with recent new participants
new_participants_today = DiscussionParticipant.query.filter(
    DiscussionParticipant.discussion_id == discussion.id,
    DiscussionParticipant.joined_at >= today
).count()

if new_participants_today > 3:
    score += 0.1
```

**Implementation:**
- Track new discussion participants
- Boost questions linked to growing discussions

**Impact:** Prioritize questions that drive discussion growth

**Files to Modify:**
- `app/daily/auto_selection.py` - Add momentum calculations
- `app/daily/auto_selection.py` - Integrate into scoring

---

### 5. Personalization Engine (Long-term)

**Current Limitation:**
- Same questions for everyone
- No user preference learning

**Proposed Approach:**

#### Track User Engagement Patterns
```python
# Track which topics users engage with most
user_topic_engagement = {
    'policy': 0.8,  # High engagement
    'social': 0.6,  # Medium engagement
    'economic': 0.3  # Low engagement
}
```

**Implementation:**
- Track user votes by topic category
- Calculate engagement scores per topic
- Store in user profile or session

#### Personalized Weekly Digests
```python
# Select questions based on user's engagement history
def select_personalized_questions(user, days_back=7, count=5):
    # Get all eligible questions
    questions = get_questions_from_past_week()
    
    # Score based on user's historical engagement
    for question in questions:
        user_topic_score = user.engagement_by_topic.get(
            question.topic_category, 0.5
        )
        score += user_topic_score * 0.3  # 30% weight for personalization
    
    # Return top N personalized questions
    return sorted(questions, key=lambda q: q.score, reverse=True)[:count]
```

**Implementation:**
- Store user engagement preferences
- Calculate personalized scores
- A/B test: Personalized vs. universal digests

**Impact:** Higher engagement through relevance

**Files to Create:**
- New: `app/daily/personalization.py` - User preference tracking
- New: `app/models.py` - Add `user_engagement_preferences` to User model

---

### 6. Improved Controversy Detection

**Current Limitation:**
- Simple keyword matching for controversy
- Doesn't detect nuanced divisive topics

**Proposed Enhancements:**

#### Use Actual Vote Distribution
```python
# Learn from similar statements' actual vote distributions
similar_statements = find_similar_statements(statement_text)
vote_distributions = [s.vote_percentages for s in similar_statements]

# High controversy = balanced distribution (40/40/20)
# Low controversy = lopsided distribution (90/5/5)
controversy_score = calculate_balance_from_distributions(vote_distributions)
```

**Implementation:**
- Find similar statements (text similarity, topic match)
- Get their actual vote distributions
- Calculate controversy based on balance

**Impact:** More accurate controversy detection

#### Learn from Discussion Data
```python
# Use discussion participation patterns
if discussion.has_bridge_statements:
    controversy_score += 0.2  # Divisive but with common ground

if discussion.has_consensus_statements:
    controversy_score -= 0.1  # More agreement than disagreement
```

**Implementation:**
- Check for bridge/consensus statements in discussion
- Adjust controversy score accordingly

**Impact:** Better identification of engaging, debatable questions

#### Sentiment Analysis (Advanced)
```python
# Use NLP to detect controversial language patterns
from textblob import TextBlob

blob = TextBlob(statement_text)
polarity = blob.sentiment.polarity  # -1 to 1
subjectivity = blob.sentiment.subjectivity  # 0 to 1

# High subjectivity + moderate polarity = controversial
controversy_score = abs(polarity) * subjectivity
```

**Implementation:**
- Use sentiment analysis library
- Detect controversial language patterns
- Combine with existing keyword approach

**Impact:** More sophisticated controversy detection

**Files to Modify:**
- `app/daily/auto_selection.py` - `calculate_controversy_potential()`
- New: `app/daily/controversy_analysis.py` - Advanced controversy detection

---

### 7. Time-Based Optimization

**Current Limitation:**
- No time-of-day or day-of-week optimization

**Proposed Enhancements:**

#### Track Performance by Day/Time
```python
# Track which topics perform better on which days
topic_performance_by_day = {
    'Monday': {'policy': 0.8, 'social': 0.6},
    'Tuesday': {'policy': 0.9, 'social': 0.7},
    # ...
}
```

**Implementation:**
- Track question performance by day of week
- Track performance by send time
- Adjust selection based on send day/time

**Impact:** Better alignment with user behavior patterns

#### Day-Specific Selection
```python
# Select questions optimized for send day
if send_day == 'Tuesday':  # Default weekly send day
    # Boost policy questions (perform better mid-week)
    policy_boost = 0.1
elif send_day == 'Friday':
    # Boost lighter social questions (weekend engagement)
    social_boost = 0.1
```

**Implementation:**
- Learn which topics perform best on which days
- Adjust selection weights accordingly

**Impact:** Optimize for day-specific engagement patterns

**Files to Modify:**
- `app/daily/auto_selection.py` - Add day/time awareness
- New: `app/daily/time_optimization.py` - Time-based selection logic

---

### 8. Improved Clarity Scoring

**Current Limitation:**
- Only considers length (50-100 chars optimal)
- Doesn't consider readability or complexity

**Proposed Enhancements:**

#### Readability Score
```python
# Use Flesch-Kincaid or similar readability metric
from textstat import flesch_reading_ease

readability = flesch_reading_ease(statement_text)
# 90-100 = very easy, 0-30 = very difficult

# Optimal: 60-80 (accessible but not dumbed down)
if 60 <= readability <= 80:
    clarity_score = 1.0
else:
    clarity_score = 1.0 - abs(readability - 70) / 70
```

**Implementation:**
- Add readability library (textstat)
- Calculate readability score
- Combine with length score

**Impact:** More accessible, engaging questions

#### Jargon Detection
```python
# Penalize jargon-heavy statements
jargon_words = ['paradigm', 'synergy', 'leverage', 'optimize', ...]
jargon_count = sum(1 for word in statement_text if word in jargon_words)

if jargon_count > 3:
    clarity_score *= 0.7  # Penalty for jargon
```

**Implementation:**
- Maintain jargon word list
- Count jargon words
- Penalize jargon-heavy statements

**Impact:** More accessible language

#### Question vs. Statement Structure
```python
# Questions often work better than statements for engagement
if statement_text.endswith('?'):
    clarity_score += 0.1  # Questions are more engaging
```

**Implementation:**
- Detect question format
- Boost questions over statements

**Impact:** Better engagement through format

**Files to Modify:**
- `app/daily/auto_selection.py` - `calculate_clarity_score()`

---

### 9. Diversity Factors

**Current Limitation:**
- No explicit diversity tracking

**Proposed Enhancements:**

#### Topic Diversity
```python
# Ensure topic diversity in weekly digest
selected_topics = []
for question in candidate_questions:
    if question.topic_category not in selected_topics:
        score += 0.1  # Boost for new topic
        selected_topics.append(question.topic_category)
```

**Implementation:**
- Track topics already selected
- Boost questions from different topics
- Ensure mix of policy, social, economic, etc.

**Impact:** Prevents fatigue, maintains interest

#### Position Diversity
```python
# Ensure position diversity (pro/con/neutral)
selected_positions = []
for question in candidate_questions:
    estimated_position = estimate_statement_position(question.question_text)
    if estimated_position not in selected_positions:
        score += 0.05  # Boost for position diversity
```

**Implementation:**
- Estimate statement position (pro/con/neutral)
- Track positions already selected
- Boost diverse positions

**Impact:** Balanced perspective in digests

#### Geographic Diversity
```python
# Mix of global vs. local questions
if discussion.geographic_scope == 'global' and not has_global_question:
    score += 0.05  # Boost for geographic diversity
```

**Implementation:**
- Track geographic scope of selected questions
- Ensure mix of global and local

**Impact:** Broader appeal

**Files to Modify:**
- `app/daily/auto_selection.py` - Add diversity tracking to digest selection

---

### 10. A/B Testing Framework

**Proposed Approach:**

#### Test Different Selection Strategies
```python
# A/B test: Engagement-weighted vs. Discussion-optimized
if user.in_test_group('selection_strategy_v2'):
    # New strategy: Prioritize discussion conversion
    questions = select_questions_optimized_for_discussion_conversion()
else:
    # Current strategy: Engagement-weighted
    questions = select_questions_engagement_weighted()
```

**Implementation:**
- Create test groups
- Implement alternative selection strategies
- Track performance metrics
- Roll out best-performing strategy

**Impact:** Data-driven optimization

#### Test Different Scoring Weights
```python
# A/B test: Different weight combinations
weights_variant_a = {
    'civic': 0.25,
    'timeliness': 0.25,
    'clarity': 0.20,
    'controversy': 0.15,
    'historical': 0.15
}

weights_variant_b = {
    'civic': 0.20,
    'timeliness': 0.20,
    'clarity': 0.20,
    'controversy': 0.20,  # Higher controversy weight
    'historical': 0.20
}
```

**Implementation:**
- Test different weight combinations
- Measure engagement outcomes
- Optimize weights based on results

**Impact:** Continuous improvement

**Files to Create:**
- New: `app/daily/ab_testing.py` - A/B test framework
- New: `app/daily/selection_variants.py` - Alternative selection strategies

---

## Implementation Priority

### Phase 1: Quick Wins (1-2 weeks)
1. ✅ **Recent Activity Boost** - Already partially implemented, enhance it
2. ✅ **Discussion Activity Boost** - Already implemented, verify it's working
3. ✅ **Vote Distribution Balance** - Add balance scoring to digest selection

### Phase 2: High Impact (2-4 weeks)
1. ⭐ **Enhanced Historical Performance** - Track discussion conversion, reason submission
2. ⭐ **Discussion Quality Score** - Balanced discussions, bridge statements, growth
3. ⭐ **Social Proof Signals** - Momentum, recent activity, growing participation

### Phase 3: Advanced Features (1-2 months)
1. 🔮 **Personalization Engine** - User preference learning
2. 🔮 **Improved Controversy Detection** - Actual vote data, sentiment analysis
3. 🔮 **Time-Based Optimization** - Day/time-specific selection

### Phase 4: Long-term (3+ months)
1. 🚀 **A/B Testing Framework** - Test different strategies
2. 🚀 **Machine Learning Model** - Train on engagement outcomes
3. 🚀 **Real-time Engagement Signals** - Live data integration

---

## Metrics to Track

### Primary Metrics (Voting)
- **Vote Rate:** % of email recipients who vote
- **Vote Completion Rate:** % who vote on all questions in digest
- **Time-to-Vote:** Average time from email open to vote
- **Return Rate:** % who return to see results

### Secondary Metrics (Discussion)
- **Discussion Conversion Rate:** % of voters who join discussions
- **Discussion Participation Rate:** % who actively participate (not just join)
- **Reason Submission Rate:** % who provide thoughtful reasons
- **Discussion Growth:** New participants per question

### Quality Metrics
- **Vote Balance:** Distribution of agree/disagree/unsure
- **Discussion Balance:** Participation from both sides
- **Engagement Depth:** Time spent, return visits, reason length

---

## Data Requirements

### New Data to Collect
1. **Discussion Conversion Tracking:**
   - Link `DailyQuestionResponse` to `DiscussionParticipant`
   - Track: voter → discussion participant conversion

2. **Engagement Timing:**
   - Track email open time
   - Track vote submission time
   - Calculate time-to-vote

3. **User Engagement Preferences:**
   - Track votes by topic category per user
   - Track discussion participation by topic
   - Build user preference profile

4. **Discussion Health Metrics:**
   - Track participant growth over time
   - Track vote distribution in discussions
   - Track bridge/consensus statements

### Database Changes Needed
- Add `discussion_conversion_rate` to `DailyQuestion` (cached)
- Add `reason_submission_rate` to `DailyQuestion` (cached)
- Add `vote_balance_score` to `DailyQuestion` (cached)
- Add `user_engagement_preferences` JSON field to `User` model
- Add indexes for performance queries

---

## Success Criteria

### Short-term (3 months)
- **+20% discussion conversion rate** (voters → discussion participants)
- **+15% reason submission rate** (thoughtful participation)
- **+10% vote completion rate** (all questions in digest)

### Medium-term (6 months)
- **+30% discussion conversion rate**
- **Personalization showing +15% engagement** (A/B test)
- **Better topic diversity** (measured by user feedback)

### Long-term (12 months)
- **Self-optimizing selection** (ML model)
- **Real-time engagement signals** integrated
- **Continuous A/B testing** showing improvements

---

## Risks & Mitigation

### Risk 1: Over-optimization
**Risk:** Selection becomes too narrow, missing diverse topics  
**Mitigation:** Maintain diversity factors, ensure topic variety

### Risk 2: Personalization Bias
**Risk:** Users only see topics they already like  
**Mitigation:** Balance personalization with exploration (80/20 rule)

### Risk 3: Performance Impact
**Risk:** Additional queries slow down selection  
**Mitigation:** Cache metrics, batch queries, optimize database

### Risk 4: Data Quality
**Risk:** Poor data leads to poor decisions  
**Mitigation:** Validate data, handle edge cases, monitor metrics

---

## Questions to Answer Before Implementation

1. **Do we have data on discussion participation rates by question type?**
   - Need to query: `DailyQuestionResponse` → `DiscussionParticipant` join
   - Calculate conversion rates

2. **Are there topics that consistently drive more discussion participation?**
   - Analyze historical data
   - Identify high-conversion topics

3. **Do we track vote distribution (agree/disagree/unsure ratios)?**
   - `DailyQuestion.vote_percentages` property exists
   - Need to use in selection scoring

4. **Are there patterns in which questions get the most "reason" submissions?**
   - Query `DailyQuestionResponse` where `reason IS NOT NULL`
   - Analyze by topic, clarity, controversy

5. **What's our current discussion conversion rate?**
   - Baseline metric needed
   - Track before/after improvements

---

## References

- Current Selection: `app/daily/auto_selection.py`
- Engagement Scoring: `calculate_statement_engagement_score()`
- Historical Performance: `get_historical_performance()`
- Weekly Digest Selection: `select_questions_for_weekly_digest()`
- Monthly Digest Selection: `select_questions_for_monthly_digest()`

---

## Next Steps

1. **Analyze Current Data:**
   - Calculate baseline discussion conversion rates
   - Identify high-performing question patterns
   - Analyze vote distribution patterns

2. **Implement Phase 1 Quick Wins:**
   - Enhance recent activity boost
   - Add vote balance scoring
   - Verify discussion activity boost

3. **Set Up Metrics Tracking:**
   - Add discussion conversion tracking
   - Add reason submission tracking
   - Create metrics dashboard

4. **A/B Test Improvements:**
   - Test enhanced selection vs. current
   - Measure impact on engagement
   - Iterate based on results

---

**Status:** Ready for implementation planning  
**Last Updated:** January 2025
