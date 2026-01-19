# Pricing Update - Edge Cases & Dependencies Audit

**Date:** January 19, 2026  
**Status:** ⚠️ CRITICAL ISSUES IDENTIFIED & FIXED  

---

## ✅ **What Was Updated**

### Landing Page Pricing (`app/templates/briefing/landing.html`)
- **Individual Pricing:**
  - Starter: £12/month (was £8)
  - Professional: £25/month (was £15)
  - Removed confusing "3 briefs" limit
  - Added "Unlimited briefs (fair use: 10)" for Professional

- **Organization Pricing:**
  - Simplified from 3 tiers to 2
  - Team: £300/month (replaces Starter £250 + Pro £750)
  - Enterprise: £2,000/month (replaces Institutional £1,500)

- **Trial Period:**
  - Standardized to 30-day free trial
  - No credit card required

---

## 🚨 **CRITICAL ISSUES FOUND**

### ❌ Issue #1: Trial Length Mismatch (FIXED ✅)

**Problem:**  
Landing page promised 30-day trial, but backend code defaulted to 14 days.

**Location:** `app/models.py` - `DailyBriefSubscriber.start_trial()`

**Impact:**
- Users would expect 30 days but only receive 14
- Major trust issue and poor conversion
- Could lead to refund requests and complaints

**Fix Applied:**
```python
# BEFORE
def start_trial(self, days=14):
    """Start free trial with specified duration"""

# AFTER
def start_trial(self, days=30):
    """Start free trial with specified duration (default 30 days)"""
```

**Files Modified:**
- `app/models.py` lines 1533, 1540, 1469, 1598

---

## ⚠️ **CRITICAL ISSUE #2: No Billing Implementation**

**Problem:**  
The Briefing system has **NO subscription enforcement or billing integration**.

**What's Missing:**

### 1. **No Tier Tracking on Briefing Model**
The `Briefing` model doesn't track subscription tier:
```python
class Briefing(db.Model):
    owner_type = db.Column(db.String(20))  # 'user' | 'org'
    owner_id = db.Column(db.Integer)
    # ❌ NO tier field
    # ❌ NO subscription_id field
    # ❌ NO briefing count limits
```

### 2. **No Briefing Limits Enforced**
Routes don't check tier before allowing briefing creation:
```python
# app/briefing/routes.py
@briefing_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_briefing():
    # ❌ NO check: "Does user have Starter (1 brief) or Professional (unlimited)?"
    # ❌ Anyone can create unlimited briefings
    briefing = Briefing(...)
    db.session.add(briefing)
```

### 3. **No Stripe Integration**
```python
# app/briefing/routes.py - Lines searched: 0 results for "stripe"
# ❌ No payment gateway
# ❌ No subscription webhooks
# ❌ No trial expiration handling
```

### 4. **No Feature Gates**
No enforcement of tier-specific features:
- ❌ Source limits (20 for Starter, unlimited for Pro)
- ❌ Recipient limits (individuals vs teams)
- ❌ Document uploads (Pro only)
- ❌ Custom branding (Team only)
- ❌ Analytics access (Team only)

---

## 🔍 **WHAT THIS MEANS**

### Current State
**Right now, anyone can:**
- Create unlimited briefings (even on "Starter")
- Add unlimited sources (even on free tier)
- Add unlimited recipients
- Use all "Pro" features for free

**The landing page is essentially marketing vapor** - there's no enforcement.

### Why This Isn't Necessarily Bad for MVP
**Pros:**
1. You can get users on the platform now
2. Test features without billing complexity
3. Build social proof and testimonials
4. Learn what users actually value
5. Manually manage early customers (invoice them via email)

**Cons:**
1. Can't scale revenue without automation
2. Risk of abuse (unlimited usage)
3. Hard to enforce "fair use" manually
4. Can't A/B test pricing or tiers

---

## ✅ **SYSTEMS THAT ARE SEPARATE** (No Changes Needed)

### 1. **DailyBriefSubscriber Model**
This is a DIFFERENT system (free daily brief for everyone).
- Has tier logic (`trial`, `free`, `individual`, `team`)
- Trial logic updated to 30 days ✅
- Not related to Briefing system

### 2. **Landing Pages**
- `app/templates/briefing/landing.html` ✅ Updated
- `app/templates/index.html` - Generic homepage, no briefing pricing
- `app/templates/news/landing.html` - News dashboard (free product)

### 3. **Documentation**
- `docs/BRIEFING_V2_COMPLETE.md` - Technical docs, no pricing mentioned
- `docs/FEATURE_COMPLETENESS_FINAL.md` - Feature checklist, not user-facing

---

## 📋 **IMPLEMENTATION ROADMAP**

### When You Need Billing (Priority Order)

#### **Phase 1: Manual Revenue (Now - Month 1)** ✅ CURRENT STATE
**Strategy:** Manually manage first 10-20 customers
- Landing page shows pricing (done ✅)
- Users sign up via "Request Access" for Team/Enterprise
- You email them Stripe invoices manually
- Manually grant access (no code changes needed)

**Pros:**
- No dev time required
- Can iterate pricing quickly
- Learn what customers actually want
- Build case studies

**Cons:**
- Doesn't scale past ~20 customers
- Manual work (15 min per customer/month)

---

#### **Phase 2: Stripe Self-Service (Month 2-3)** 🔨 RECOMMENDED NEXT
**What to Build:**

1. **Add Tier to User/Org Models**
   ```python
   # app/models.py
   class User(db.Model):
       briefing_tier = db.Column(db.String(20), default='trial')  # trial|starter|professional
       briefing_tier_expires_at = db.Column(db.DateTime)
       stripe_customer_id = db.Column(db.String(255))
       stripe_subscription_id = db.Column(db.String(255))
   
   class CompanyProfile(db.Model):
       briefing_tier = db.Column(db.String(20), default='trial')  # trial|team|enterprise
       briefing_tier_expires_at = db.Column(db.DateTime)
       stripe_customer_id = db.Column(db.String(255))
   ```

2. **Add Tier Checks to Routes**
   ```python
   # app/briefing/routes.py
   def can_create_briefing(user):
       """Check if user can create more briefings based on tier"""
       existing_count = Briefing.query.filter_by(
           owner_type='user',
           owner_id=user.id
       ).count()
       
       if user.briefing_tier == 'starter':
           return existing_count < 1
       elif user.briefing_tier == 'professional':
           return existing_count < 10  # Fair use limit
       
       return False  # Trial expired or no tier
   
   @briefing_bp.route('/create', methods=['GET', 'POST'])
   @login_required
   def create_briefing():
       if not can_create_briefing(current_user):
           flash("Upgrade to create more briefings", "warning")
           return redirect(url_for('briefing.pricing'))
   ```

3. **Stripe Checkout Integration**
   ```python
   # app/billing/routes.py (new file)
   @billing_bp.route('/checkout/<tier>')
   @login_required
   def checkout(tier):
       # Create Stripe checkout session
       session = stripe.checkout.Session.create(
           customer_email=current_user.email,
           payment_method_types=['card'],
           line_items=[{
               'price': STRIPE_PRICE_IDS[tier],
               'quantity': 1,
           }],
           mode='subscription',
           success_url=url_for('briefing.dashboard', _external=True),
           cancel_url=url_for('briefing.pricing', _external=True),
       )
       return redirect(session.url)
   ```

4. **Stripe Webhook Handler**
   ```python
   @billing_bp.route('/webhooks/stripe', methods=['POST'])
   def stripe_webhook():
       # Handle subscription events:
       # - checkout.session.completed → Grant access
       # - customer.subscription.updated → Update tier
       # - customer.subscription.deleted → Revoke access
       # - invoice.payment_failed → Grace period warning
   ```

5. **Trial Expiration Job**
   ```python
   # app/scheduler.py
   @scheduler.scheduled_job('cron', hour=10, minute=0)
   def check_trial_expirations():
       """Check for expired trials and send upgrade reminders"""
       expired_users = User.query.filter(
           User.briefing_tier == 'trial',
           User.briefing_tier_expires_at < datetime.utcnow()
       ).all()
       
       for user in expired_users:
           send_trial_expired_email(user)
           # Optionally: disable briefing generation
   ```

**Estimated Dev Time:** 2-3 days

---

#### **Phase 3: Advanced Billing (Month 4+)** 🚀 GROWTH STAGE
Only implement when you have 50+ paying customers:

1. **Usage-Based Add-ons**
   - Extra recipients: £0.10 per recipient over limit
   - Extra briefings: £5/month per brief over limit
   - Premium integrations: £20/month for Slack, API access

2. **Downgrade Prevention Flow**
   - "About to cancel? Try Starter instead"
   - Recovers 20-30% of churns

3. **Team Member Management**
   - Invite editors (Team tier)
   - Role-based permissions
   - Seat-based billing

4. **Metered Billing**
   - Track AI generation costs per customer
   - Adjust pricing based on usage patterns

---

## 🛡️ **RECOMMENDED APPROACH FOR NOW**

### What to Do This Week:

1. **✅ Keep Current Setup** (Manual Management)
   - Landing page is live with pricing
   - Users can "Request Access" for Team/Enterprise
   - You manually invoice early customers
   - No code changes needed

2. **✅ Monitor for Abuse**
   - Check weekly: Are any users creating 50+ briefings?
   - If yes, politely reach out and offer Team tier
   - Add basic rate limits if needed

3. **✅ Collect Customer Feedback**
   - Ask first 10 customers: "Is this pricing fair?"
   - Learn: What features matter most?
   - Iterate: Adjust pricing before building billing

### When to Build Billing:

**Don't build until:**
- You have 10+ customers manually paying
- You've validated pricing (customers are happy to pay)
- Manual management becomes painful (30+ customers)

**Then build:**
- Phase 2 Stripe integration (2-3 days dev time)
- Tier checks and feature gates
- Trial expiration handling

---

## 📊 **RISK ASSESSMENT**

### Low Risk (Acceptable for MVP)
✅ No billing enforcement (manual management works)  
✅ Anyone can create briefings (abuse is unlikely at small scale)  
✅ No feature gates (helps user testing)  

### Medium Risk (Monitor)
⚠️ Unlimited usage could attract abusers  
⚠️ Manual invoicing doesn't scale past ~30 customers  
⚠️ Can't A/B test pricing without code  

### High Risk (Must Fix Before Scale)
🚨 ~~Trial length mismatch~~ ✅ FIXED  
🚨 No Stripe integration blocks self-service revenue  
🚨 No tier checks means can't enforce "Starter = 1 brief"  

---

## ✅ **WHAT'S BEEN FIXED**

### Files Modified:
1. **`app/models.py`** (4 changes)
   - Line 1469: Comment "14-day trial" → "30-day trial"
   - Line 1533: `start_trial(days=14)` → `start_trial(days=30)`
   - Line 1540: `extend_trial(additional_days=14)` → `extend_trial(additional_days=30)`
   - Line 1598: Docstring "14-day free trial" → "30-day free trial"

2. **`app/templates/briefing/landing.html`** (committed earlier)
   - Updated all pricing tiers
   - Changed trial messaging to 30 days
   - Simplified organization pricing

---

## 🎯 **ACTION ITEMS**

### Immediate (This Week)
- [x] Fix trial length mismatch ✅
- [ ] Commit model.py changes ✅ (doing next)
- [ ] Test landing page displays correctly
- [ ] Set up basic monitoring (check for abuse weekly)

### Short-term (Month 1-2)
- [ ] Manually manage first 10 customers via email invoices
- [ ] Collect feedback on pricing
- [ ] Create Stripe account and price IDs
- [ ] Document manual customer onboarding process

### Medium-term (Month 2-3)
- [ ] Implement Phase 2 billing (Stripe self-service)
- [ ] Add tier tracking to User/CompanyProfile models
- [ ] Build feature gates and limits
- [ ] Set up Stripe webhook handlers
- [ ] Create trial expiration job

### Long-term (Month 4+)
- [ ] Advanced billing features (metered, usage-based)
- [ ] Team management and SSO
- [ ] Downgrade prevention flow
- [ ] A/B test pricing variations

---

## 📚 **RELATED DOCUMENTATION**

- [BRIEFING_V2_COMPLETE.md](./BRIEFING_V2_COMPLETE.md) - Technical implementation
- [TODAYS_WORK_SUMMARY.md](./TODAYS_WORK_SUMMARY.md) - Recent improvements
- [FEATURE_COMPLETENESS_FINAL.md](./FEATURE_COMPLETENESS_FINAL.md) - Feature checklist

---

## 🤝 **QUESTIONS FOR USER**

1. **Do you want to implement Stripe billing now or wait?**
   - Recommendation: Wait until you have 10 manually-managed customers

2. **How will you handle "Request Access" for Team/Enterprise?**
   - Email them a Stripe invoice link?
   - Or schedule a sales call first?

3. **What's your abuse prevention strategy for MVP?**
   - Monitor weekly?
   - Add rate limits (max 10 briefings per user)?
   - Require email verification?

4. **Do you want to enforce trial expiration?**
   - Disable briefing generation after 30 days?
   - Or keep it open for early growth?

---

**Status:** ✅ Landing page pricing updated  
**Blocker:** ⚠️ No billing enforcement (acceptable for MVP)  
**Next Step:** Commit model.py changes, then monitor for feedback
