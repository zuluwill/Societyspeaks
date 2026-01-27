# User API Keys for TTS and Deeper Analysis - Feasibility Analysis

**Date:** January 26, 2026  
**Status:** Analysis Complete - Recommendation Provided

## Executive Summary

**Recommendation:** ✅ **YES, but only for paid briefing tiers** (Professional, Team, Enterprise)

The infrastructure already exists (80% complete), but UX complexity makes it unsuitable for free users. Paid users are more likely to understand API keys and have budgets for them.

---

## Current State

### ✅ What Already Exists

1. **User API Key Infrastructure** (Complete)
   - `UserAPIKey` model with encrypted storage
   - Full UI at `/settings/api-keys` (add/delete/validate/toggle)
   - Supports OpenAI and Anthropic
   - Currently used for discussion summaries
   - Validation, encryption, error handling all in place

2. **Deeper Analysis Features** (Exists, uses system keys)
   - "Deeper context" generation for brief items
   - 3-4 paragraphs of extended analysis
   - Historical context, implications, key players
   - Currently uses system LLM keys (not user keys)

3. **TTS System** (Architecture ready, package removed)
   - `XTTSClient` class with availability checking
   - `AudioGenerator` with job queue
   - Storage abstraction (S3-ready)
   - Currently disabled in production (package removed)

---

## What Would Be Needed

### 1. TTS with User API Keys

**Effort:** ~3-4 hours

**Changes Required:**
- Create `OpenAITTSClient` class (similar interface to `XTTSClient`)
- Modify `AudioGenerator` to check for user API keys
- Add `user_id` to `AudioGenerationJob` model (migration needed)
- Update routes to pass `user_id` when creating jobs
- Update UI to show "Use your OpenAI key" option

**Code Example:**
```python
# In audio_generator.py
def create_generation_job(self, brief_id, user_id=None, voice_id=None, ...):
    # Store user_id in job
    job.user_id = user_id
    
# In process_job
def process_job(self, job_id):
    job = AudioGenerationJob.query.get(job_id)
    user_id = job.user_id
    
    # Get user's OpenAI key
    if user_id:
        user_key = UserAPIKey.query.filter_by(
            user_id=user_id,
            provider='openai',
            is_active=True
        ).first()
        
        if user_key:
            from app.lib.llm_utils import decrypt_api_key
            api_key = decrypt_api_key(user_key.encrypted_api_key)
            # Use OpenAI TTS instead of XTTS
            audio_path = openai_tts_client.generate_audio(text, api_key)
```

**Cost to Users:**
- OpenAI TTS: $15 per 1M characters (~$0.015 per 1K chars)
- Example: 5-minute brief (~2,000 words ≈ 10,000 chars) = **$0.15 per brief**

### 2. Deeper Analysis with User API Keys

**Effort:** ~2-3 hours

**Changes Required:**
- Modify `BriefGenerator._generate_deeper_context()` to check for user API keys
- Modify `BriefingGenerator._generate_deeper_context()` to check for user API keys
- Pass `user_id` through generation pipeline
- Fall back to system keys if user key not available

**Code Example:**
```python
# In brief/generator.py
def _generate_deeper_context(self, topic, articles, existing_content, user_id=None):
    # Try user key first
    if user_id:
        user_key = UserAPIKey.query.filter_by(
            user_id=user_id,
            provider__in=['openai', 'anthropic'],
            is_active=True
        ).first()
        
        if user_key:
            from app.lib.llm_utils import decrypt_api_key
            api_key = decrypt_api_key(user_key.encrypted_api_key)
            # Use user's key
            return self._call_llm(prompt, api_key=api_key, provider=user_key.provider)
    
    # Fall back to system key
    return self._call_llm(prompt)
```

**Cost to Users:**
- Current system cost: ~$0.01 per item
- User cost: Same (~$0.01 per item with gpt-4o-mini)

---

## UX Complexity Analysis

### ❌ Problems for Free Users

1. **Cognitive Load:**
   - "What's an API key?" (most users don't know)
   - "Where do I get one?" (requires external signup)
   - "How much will this cost me?" (unclear pricing)
   - "Is it safe to give you my key?" (security concerns)

2. **Friction:**
   - Extra steps: Sign up → Get API key → Add to settings → Use feature
   - Many users will abandon at "get API key" step
   - Support burden: "How do I get an OpenAI key?"

3. **Value Mismatch:**
   - Free users expect free features
   - Asking them to pay for API usage feels like a bait-and-switch
   - Better to just disable the feature

### ✅ Benefits for Paid Users

1. **Higher Technical Literacy:**
   - Professional/Team/Enterprise users more likely to understand API keys
   - Often already have OpenAI/Anthropic accounts
   - Budget for API usage

2. **Value Alignment:**
   - Paying customers expect premium features
   - "Bring your own key" is a common enterprise pattern
   - Reduces your costs while giving them control

3. **Flexibility:**
   - Users can choose their provider (OpenAI vs Anthropic)
   - Users control their own costs
   - Users can use higher-tier models if they want

---

## Implementation Strategy

### Phase 1: Paid Briefing Tiers Only (Recommended)

**Target:** Professional (£25/mo), Team (£300/mo), Enterprise (£2,000/mo)

**Why:**
- Higher technical literacy
- Budget for API costs
- Expect premium features
- Lower support burden

**Implementation:**
1. Add tier check to API key UI: "Available for Professional+ plans"
2. Gate deeper analysis behind tier check
3. Gate TTS behind tier check
4. Show clear messaging: "Use your OpenAI key for enhanced features"

**Code Changes:**
```python
# In routes, check tier before showing features
@briefing_bp.route('/<int:briefing_id>/runs/<int:run_id>')
def view_run(...):
    # Check if user has paid tier
    subscription = get_active_subscription(current_user.id)
    has_paid_tier = subscription and subscription.tier in ['professional', 'team', 'enterprise']
    
    return render_template(
        'briefing/run_view.html',
        ...
        allow_user_api_keys=has_paid_tier,
        tts_available=is_tts_available() or (has_paid_tier and user_has_api_key)
    )
```

### Phase 2: Daily Brief (Free) - Skip for Now

**Recommendation:** Don't add user API keys to free daily brief

**Why:**
- Free users expect free features
- Too much friction
- Support burden too high
- Only 2 users requested audio (not worth the complexity)

**Alternative:** If demand grows, consider:
- Adding audio as a paid add-on (£5/month for audio generation)
- Using system keys with usage limits
- Partnering with TTS provider for bulk pricing

---

## Cost Analysis

### Current System Costs (You Pay)

**Deeper Analysis:**
- ~$0.01 per brief item
- If 100 briefs/day with 5 items each = 500 items/day
- Cost: $5/day = $150/month

**TTS:**
- Currently disabled (removed from production)
- Would cost ~$0.15 per brief if re-enabled
- 100 briefs/day = $15/day = $450/month

### With User API Keys (Users Pay)

**Deeper Analysis:**
- Users pay ~$0.01 per item (same as you)
- Your cost: $0
- User cost: Minimal (most users generate <10 briefs/month)

**TTS:**
- Users pay ~$0.15 per brief
- Your cost: $0
- User cost: $1.50/month for 10 briefs (reasonable)

---

## Recommendation

### ✅ **DO IT - But Only for Paid Briefing Tiers**

**Rationale:**
1. **Infrastructure exists** (80% done, just needs wiring)
2. **Paid users can handle it** (technical literacy, budgets)
3. **Reduces your costs** (shift LLM costs to users)
4. **Adds value** (premium feature for paying customers)
5. **Common pattern** (BYOK is standard in enterprise SaaS)

### ❌ **DON'T DO IT - For Free Daily Brief**

**Rationale:**
1. **Too much friction** (most users won't understand)
2. **Support burden** (endless "how do I get a key?" questions)
3. **Value mismatch** (free users expect free features)
4. **Low demand** (only 2 users requested audio)

### Implementation Priority

1. **High Priority:** Deeper analysis for paid briefings (2-3 hours)
   - High value, low complexity
   - Users already understand LLM costs
   - Clear ROI

2. **Medium Priority:** TTS for paid briefings (3-4 hours)
   - Good value, but lower demand
   - Only if audio demand grows
   - Can wait until 10+ users request it

3. **Low Priority:** Daily brief features (skip for now)
   - Too much friction for free users
   - Revisit if demand grows significantly

---

## Alternative: Hybrid Approach

**Option:** Offer both system-provided and user-provided options

1. **System-provided (default):**
   - Free tier: No deeper analysis, no audio
   - Paid tier: System provides deeper analysis (you pay)
   - Limited usage to control costs

2. **User-provided (optional):**
   - Paid tier: Users can bring their own keys
   - Unlimited usage (they pay)
   - Premium models available (GPT-4, Claude Opus)

**Benefits:**
- Best of both worlds
- Users who want more control can bring keys
- Users who want simplicity use system keys
- You control costs while offering flexibility

---

## Technical Implementation Checklist

### For Deeper Analysis (2-3 hours)

- [ ] Modify `BriefGenerator._generate_deeper_context()` to accept `user_id`
- [ ] Modify `BriefingGenerator._generate_deeper_context()` to accept `user_id`
- [ ] Add helper function to get user API key for LLM calls
- [ ] Update generation routes to pass `user_id`
- [ ] Add tier check to UI (show only for paid users)
- [ ] Update documentation

### For TTS (3-4 hours)

- [ ] Create `OpenAITTSClient` class
- [ ] Add `user_id` field to `AudioGenerationJob` (migration)
- [ ] Modify `AudioGenerator` to check for user keys
- [ ] Update audio generation routes to pass `user_id`
- [ ] Add tier check to UI
- [ ] Test with user-provided keys

---

## Conclusion

**Yes, it's worth doing - but only for paid briefing tiers.**

The infrastructure is 80% there, the implementation is straightforward, and paid users are the right audience. Free users would find it too complex, and the support burden isn't worth it.

**Next Steps:**
1. Start with deeper analysis for paid briefings (quick win)
2. Monitor demand for TTS
3. Add TTS if 10+ paid users request it
4. Skip daily brief features for now
