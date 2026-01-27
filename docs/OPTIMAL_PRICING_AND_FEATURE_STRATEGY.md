# Optimal Pricing & Feature Strategy - Cost vs. Value Analysis

**Date:** January 26, 2026  
**Status:** Strategic Analysis

## The Core Problem

**Challenge:** You want to provide amazing features, but can't afford to pay for everything until you have more paid subscribers. Paid users expect features to be included, not "bring your own key."

**Question:** What's the optimal balance between included features, add-ons, and user experience?

---

## Cost Reality Check

### Current Costs (If You Provide Everything)

**Per Brief Generation:**
- Deeper analysis: ~$0.01 per item
- TTS audio: ~$0.15 per brief (if enabled)
- Typical brief: 5 items = $0.05 deeper analysis + $0.15 TTS = **$0.20 per brief**

**Monthly Costs (Example Scenarios):**

| Users | Briefs/Month | Items/Month | Deeper Analysis | TTS | Total |
|-------|--------------|-------------|-----------------|-----|-------|
| 10 Professional | 100 | 500 | $5 | $15 | **$20/mo** |
| 50 Professional | 500 | 2,500 | $25 | $75 | **$100/mo** |
| 5 Team | 50 | 250 | $2.50 | $7.50 | **$10/mo** |
| 20 Team | 200 | 1,000 | $10 | $30 | **$40/mo** |

**At Scale (100 Professional users):**
- 1,000 briefs/month = **$200/month** in LLM costs
- This is 8% of revenue (£25 × 100 = £2,500 = ~$3,125, costs = $200 = 6.4%)

**Verdict:** Costs are manageable at scale, but painful when you have few subscribers.

---

## Competitive Analysis

### What Do Competitors Do?

**Morning Brew / The Hustle:**
- Free tier: Basic newsletter
- Paid tier: Premium content, but no AI features
- **No TTS, no deeper analysis**

**Briefing Services (Politico, Axios):**
- Premium subscriptions: $300-500/year
- Include deeper analysis (human-written)
- **No TTS**

**AI-Powered News (The Browser, Perplexity):**
- Free tier: Limited AI queries
- Paid tier: Unlimited AI, but you pay for API usage
- **Hybrid model: Included with limits, then pay-per-use**

**Key Insight:** Most competitors either:
1. Don't offer these features at all
2. Include them but charge premium prices
3. Use hybrid models (included with limits)

---

## Optimal Strategy: Tiered Inclusion with Smart Limits

### Strategy Overview

**Core Principle:** Include features that add value, but use smart limits to control costs. Offer unlimited via BYOK for power users.

### Tier Breakdown

#### **Starter (£12/month) - "Essential"**
**Included:**
- ✅ Basic briefs (no deeper analysis)
- ❌ No TTS
- ❌ No deeper analysis
- **Why:** Keep costs low, focus on core value

**Cost to You:** $0 (no LLM usage)

#### **Professional (£25/month) - "Enhanced"**
**Included:**
- ✅ Deeper analysis: **10 briefs/month included** (~$0.50 cost)
- ✅ TTS: **5 briefs/month included** (~$0.75 cost)
- 🔄 **Unlimited via BYOK** (bring your own OpenAI key)

**Cost to You:** ~$1.25/month per user (5% of revenue)
**User Experience:** "10 enhanced briefs included, unlimited with your own key"

#### **Team (£300/month) - "Premium"**
**Included:**
- ✅ Deeper analysis: **50 briefs/month included** (~$2.50 cost)
- ✅ TTS: **20 briefs/month included** (~$3 cost)
- 🔄 **Unlimited via BYOK**

**Cost to You:** ~$5.50/month per team (1.8% of revenue)
**User Experience:** "50 enhanced briefs included, unlimited with your own key"

#### **Enterprise (£2,000/month) - "Unlimited"**
**Included:**
- ✅ Deeper analysis: **Unlimited** (you pay)
- ✅ TTS: **Unlimited** (you pay)
- ✅ Priority processing
- ✅ Custom models/voices

**Cost to You:** Variable (but at £2k/month, you can afford it)
**User Experience:** "Everything included, no limits"

---

## Why This Works

### 1. **Psychological Pricing**
- Users see "10 included" and think "that's generous"
- Most users won't use 10/month (80/20 rule)
- Power users can bring their own key (they're happy to)

### 2. **Cost Control**
- Starter: $0 cost (no features)
- Professional: $1.25/user (5% of revenue, manageable)
- Team: $5.50/team (1.8% of revenue, very manageable)
- Enterprise: Variable but justified by price

### 3. **User Experience**
- **Not "bring your own key"** - that's confusing
- **"10 included, unlimited with your key"** - clear value prop
- Most users use included, power users bring keys
- Everyone gets amazing experience

### 4. **Business Model**
- Low-cost features included (builds value)
- High-cost features limited (controls costs)
- Power users self-serve (no support burden)
- Scales with revenue (costs stay at 5-10% of revenue)

---

## Implementation Details

### Feature Flags & Limits

```python
# In models.py
class BriefingSubscription(db.Model):
    tier = db.Column(db.String(20))  # starter, professional, team, enterprise
    deeper_analysis_used = db.Column(db.Integer, default=0)  # Track usage
    tts_used = db.Column(db.Integer, default=0)
    deeper_analysis_limit = db.Column(db.Integer)  # Based on tier
    tts_limit = db.Column(db.Integer)  # Based on tier

# Limits by tier
TIER_LIMITS = {
    'starter': {'deeper_analysis': 0, 'tts': 0},
    'professional': {'deeper_analysis': 10, 'tts': 5},
    'team': {'deeper_analysis': 50, 'tts': 20},
    'enterprise': {'deeper_analysis': -1, 'tts': -1}  # -1 = unlimited
}
```

### Usage Tracking

```python
# When generating deeper analysis
def _generate_deeper_context(self, topic, articles, existing_content, user_id=None):
    # Check if user has subscription
    subscription = get_active_subscription(user_id)
    
    if subscription:
        # Check if within limits
        if subscription.deeper_analysis_used < subscription.deeper_analysis_limit:
            # Use system key (you pay)
            subscription.deeper_analysis_used += 1
            db.session.commit()
            return self._call_llm(prompt)  # System key
        
        # Over limit - check for user key
        user_key = get_user_api_key(user_id, 'openai')
        if user_key:
            # Use user key (they pay)
            return self._call_llm(prompt, api_key=user_key)
        else:
            # Over limit, no user key - show upgrade prompt
            return None  # Or show "upgrade or add API key" message
    
    # No subscription - check for user key
    user_key = get_user_api_key(user_id, 'openai')
    if user_key:
        return self._call_llm(prompt, api_key=user_key)
    
    return None  # No access
```

### UI Messaging

**For Professional Users:**
```
"Enhanced Briefs: 8 of 10 included used this month"
"Unlimited with your OpenAI key → Add Key"
```

**When Over Limit:**
```
"You've used all 10 enhanced briefs this month.
Add your OpenAI key for unlimited access, or upgrade to Team."
```

**For Starter Users:**
```
"Upgrade to Professional for deeper analysis (10/month included)"
"Or add your OpenAI key to enable now"
```

---

## Alternative: Usage-Based Add-On

### Option B: Pay-Per-Use Add-On

**Instead of included limits, offer:**
- Base subscription: No AI features
- Add-on: "AI Enhancement Pack" - £5/month for 20 enhanced briefs
- Or: Pay-per-use at cost ($0.20 per brief)

**Pros:**
- Clear pricing
- Users only pay for what they use
- You break even on costs

**Cons:**
- More complex pricing
- Users might feel nickel-and-dimed
- Less "premium" feeling

**Verdict:** Tiered inclusion (Option A) feels more premium and is simpler.

---

## Recommended Approach

### Phase 1: Start Conservative (Now)

**Professional Tier:**
- ✅ Deeper analysis: **5 briefs/month included** (~$0.25 cost)
- ❌ TTS: Not included (BYOK only)
- **Cost:** $0.25/user (1% of revenue)

**Rationale:**
- Low cost to you
- Tests demand
- Easy to increase later
- TTS is expensive, make it BYOK-only

### Phase 2: Increase as Revenue Grows

**When you have 20+ Professional subscribers:**
- Increase to 10 briefs/month
- Add TTS: 5 briefs/month included

**When you have 50+ Professional subscribers:**
- Increase to 20 briefs/month
- Increase TTS to 10 briefs/month

**Rationale:**
- Costs scale with revenue
- You can afford more as you grow
- Users see value increasing over time

### Phase 3: Enterprise Unlimited

**Enterprise tier:**
- Everything unlimited
- You pay for it (but at £2k/month, it's justified)
- Premium positioning

---

## Cost Projections

### Scenario: 20 Professional Users

**Monthly Revenue:** £25 × 20 = £500 = ~$625
**Monthly Costs:**
- Deeper analysis: 5 briefs × 20 users = 100 briefs × $0.01 = $1
- TTS: 0 (BYOK only)
- **Total: $1/month (0.16% of revenue)**

### Scenario: 50 Professional Users

**Monthly Revenue:** £25 × 50 = £1,250 = ~$1,563
**Monthly Costs:**
- Deeper analysis: 10 briefs × 50 users = 500 briefs × $0.01 = $5
- TTS: 5 briefs × 50 users = 250 briefs × $0.15 = $37.50
- **Total: $42.50/month (2.7% of revenue)**

### Scenario: 100 Professional Users

**Monthly Revenue:** £25 × 100 = £2,500 = ~$3,125
**Monthly Costs:**
- Deeper analysis: 10 briefs × 100 users = 1,000 briefs × $0.01 = $10
- TTS: 5 briefs × 100 users = 500 briefs × $0.15 = $75
- **Total: $85/month (2.7% of revenue)**

**Verdict:** Costs stay at 2-3% of revenue, very manageable.

---

## Final Recommendation

### ✅ **Tiered Inclusion with Smart Limits**

**Starter (£12):**
- No AI features (keep it simple, zero cost)

**Professional (£25):**
- 5-10 deeper analysis briefs/month included
- TTS: BYOK only (too expensive to include)
- Unlimited with user's OpenAI key
- **Cost to you: $0.25-1.25/user (1-5% of revenue)**

**Team (£300):**
- 20-50 deeper analysis briefs/month included
- 10-20 TTS briefs/month included
- Unlimited with user's OpenAI key
- **Cost to you: $5.50-11/user (1.8-3.7% of revenue)**

**Enterprise (£2,000):**
- Everything unlimited (you pay)
- Premium positioning

### Why This Works

1. **Users get value** - "10 included" feels generous
2. **You control costs** - Limits keep costs at 2-5% of revenue
3. **Power users happy** - BYOK for unlimited
4. **Scales with growth** - Increase limits as revenue grows
5. **Premium feel** - Not "bring your own key," but "10 included, unlimited with key"

### Implementation Priority

1. **Start with Professional tier:** 5 deeper analysis/month (quick win, low cost)
2. **Add BYOK option:** For unlimited (power users)
3. **Add TTS later:** When you have 20+ subscribers (BYOK only initially)
4. **Increase limits:** As revenue grows

---

## Key Takeaways

1. **Don't make everything BYOK** - Users expect features included
2. **Use smart limits** - Most users won't hit them (80/20 rule)
3. **Start conservative** - Increase limits as you grow
4. **TTS is expensive** - Make it BYOK-only initially, or very limited
5. **Costs stay manageable** - 2-5% of revenue is sustainable
6. **Premium positioning** - "10 included" feels better than "bring your own key"

**Bottom Line:** Include features with limits, offer BYOK for unlimited. This gives users amazing experience while keeping your costs under control.
