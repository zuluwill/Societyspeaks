# Stripe + Manual Subscription Integration Analysis

**Date:** January 21, 2026  
**Status:** ⚠️ POTENTIAL CONFLICTS IDENTIFIED

---

## 🎯 **Executive Summary**

**Current Status:** The manual subscription system works alongside Stripe, but there are **3 edge cases** that need handling to prevent conflicts.

**Risk Level:** MEDIUM (won't break the system, but could cause confusion)

---

## ✅ **What Works Correctly**

### **1. Webhook Isolation** ✅

Stripe webhooks **only affect Stripe-managed subscriptions**:

```python
# billing/routes.py:254-259
def handle_subscription_deleted(subscription_data):
    sub = Subscription.query.filter_by(stripe_subscription_id=subscription_data['id']).first()
    # ✅ Only finds Stripe subscriptions (manual ones have stripe_subscription_id=None)
```

**Result:** Manual subscriptions are completely isolated from Stripe webhooks.

---

### **2. Admin-Only Manual Subscriptions** ✅

Manual subscriptions can only be created by admins:
- Users cannot self-grant free access
- No UI for users to create manual subscriptions
- Admin logs all manual subscription actions

---

### **3. Webhook Handlers Don't Touch Manual Subs** ✅

All webhook handlers filter by `stripe_subscription_id`:
- `handle_subscription_created` - Only syncs Stripe subs
- `handle_subscription_updated` - Only updates Stripe subs
- `handle_subscription_deleted` - Only cancels Stripe subs
- `handle_payment_failed` - Only marks Stripe subs past_due

**Manual subscriptions are safe from webhook interference.**

---

## ⚠️ **Edge Cases That Need Handling**

### **Edge Case 1: Multiple Active Subscriptions** ⚠️

**Scenario:** User has BOTH a manual free subscription AND a Stripe subscription active simultaneously.

**How It Happens:**
1. Admin grants user free Professional plan (manual, lifetime)
2. User signs up for Stripe Team plan
3. Now user has TWO active subscriptions

**Current Behavior:**
```python
# billing/service.py:181-184
sub = Subscription.query.filter(
    Subscription.user_id == user.id,
    Subscription.status.in_(['trialing', 'active'])
).first()  # ⚠️ Returns FIRST match (order undefined)
```

**Problem:** `.first()` without `ORDER BY` means **unpredictable** which subscription is returned.

**Impact:**
- User might get limits from Professional (manual) instead of Team (Stripe, paid)
- Or vice versa
- Inconsistent behavior between requests

**Risk Level:** MEDIUM - Won't break, but confusing

---

### **Edge Case 2: Stripe Checkout with Existing Manual Sub** ⚠️

**Scenario:** User has manual free subscription, clicks "Upgrade" in UI.

**Current Flow:**
```python
# billing/routes.py:39-56 (checkout creation)
existing_sub = get_active_subscription(current_user)
if existing_sub:
    # ⚠️ This will find the manual subscription
    # Code tries to cancel it via Stripe
    s.Subscription.modify(existing_sub.stripe_subscription_id, ...)
    # 💥 PROBLEM: existing_sub.stripe_subscription_id is None for manual subs
```

**Problem:** Code assumes all subscriptions have Stripe IDs and tries to cancel via Stripe API.

**Impact:**
- AttributeError or API error when trying to cancel manual subscription
- User cannot checkout for paid plan
- Payment flow broken

**Risk Level:** HIGH - Breaks checkout flow

---

### **Edge Case 3: Admin Grants While Stripe Active** ⚠️

**Scenario:** User has active Stripe subscription, admin grants free access.

**Current Flow:**
```python
# admin/routes.py:554-557 (grant action)
if active_sub:
    active_sub.status = 'canceled'
    active_sub.canceled_at = datetime.utcnow()
# ⚠️ Cancels the subscription in DB, but NOT in Stripe
```

**Problem:** 
- Cancels Stripe subscription in local DB
- Stripe keeps charging user (not canceled on Stripe side)
- User gets double-charged but subscription shows as canceled

**Impact:**
- User keeps getting billed by Stripe
- Support nightmare (user complains about charges)
- Refunds required

**Risk Level:** HIGH - Financial impact

---

## 🔧 **Recommended Fixes**

### **Fix 1: Deterministic Subscription Priority**

**Goal:** Always return the "best" subscription when multiple exist.

**Implementation:**
```python
# billing/service.py - Enhanced get_active_subscription
def get_active_subscription(user):
    """
    Get the user's active subscription, if any.
    
    Priority order when multiple active subscriptions exist:
    1. Stripe subscriptions (user is paying)
    2. Manual subscriptions (admin-granted free access)
    
    This ensures paying customers always get their paid plan limits.
    """
    # Check user's direct subscription (Stripe first, then manual)
    stripe_sub = Subscription.query.filter(
        Subscription.user_id == user.id,
        Subscription.status.in_(['trialing', 'active']),
        Subscription.stripe_subscription_id.isnot(None)  # Stripe only
    ).order_by(Subscription.created_at.desc()).first()
    
    if stripe_sub:
        return stripe_sub
    
    # Fall back to manual subscription if no Stripe
    manual_sub = Subscription.query.filter(
        Subscription.user_id == user.id,
        Subscription.status.in_(['trialing', 'active']),
        Subscription.stripe_subscription_id.is_(None)  # Manual only
    ).order_by(Subscription.created_at.desc()).first()
    
    if manual_sub:
        return manual_sub
    
    # Check organization subscriptions (same priority logic)...
```

**Why This Works:**
- Stripe subscriptions always win (user is paying, they should get what they paid for)
- Manual subscriptions only apply if no Stripe subscription exists
- Order is deterministic (newest first within each category)

---

### **Fix 2: Handle Manual Subs in Checkout**

**Goal:** Detect manual subscriptions and handle gracefully.

**Implementation:**
```python
# billing/routes.py - Enhanced create_checkout_session route
@billing_bp.route('/checkout/<plan_code>/<billing_interval>')
@login_required
@require_subscription  # ⚠️ This should be removed or modified
def create_checkout_session(plan_code, billing_interval):
    existing_sub = get_active_subscription(current_user)
    
    if existing_sub:
        # NEW: Check if it's a manual subscription
        if existing_sub.stripe_subscription_id is None:
            # Manual subscription exists - just switch to Stripe
            current_app.logger.info(
                f"User {current_user.id} upgrading from manual to Stripe subscription"
            )
            # Mark manual subscription as superseded (don't cancel, just note it)
            existing_sub.status = 'superseded'
            existing_sub.canceled_at = datetime.utcnow()
            db.session.commit()
            # Continue to checkout
        else:
            # Stripe subscription exists - handle as before
            plan = PricingPlan.query.filter_by(code=plan_code).first_or_404()
            if plan.price_monthly > existing_sub.plan.price_monthly:
                # Upgrade path...
```

**Why This Works:**
- Detects manual subscriptions via `stripe_subscription_id is None`
- Marks them as 'superseded' instead of trying to cancel via Stripe
- User can proceed to checkout
- Stripe subscription takes over once created

---

### **Fix 3: Warn Admin About Stripe Subscriptions**

**Goal:** Prevent admin from accidentally overriding paid Stripe subscriptions.

**Implementation:**
```python
# admin/routes.py - Enhanced manage_user_subscription
@admin_bp.route('/users/<int:user_id>/subscription', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_user_subscription(user_id):
    # ... existing code ...
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'grant':
            # NEW: Check if user has active Stripe subscription
            if active_sub and active_sub.stripe_subscription_id:
                flash(
                    f'⚠️ WARNING: User has ACTIVE STRIPE SUBSCRIPTION ({active_sub.plan.name}). '
                    f'Granting manual access will not cancel Stripe billing. '
                    f'User will continue to be charged. '
                    f'Cancel their Stripe subscription first via Stripe Dashboard.',
                    'warning'
                )
                # Optionally: Require confirmation checkbox
                confirm = request.form.get('confirm_override')
                if not confirm:
                    return redirect(url_for('admin.manage_user_subscription', user_id=user_id))
            
            # Proceed with grant...
```

**Why This Works:**
- Admin sees clear warning before overriding Stripe subscription
- Suggests correct action (cancel via Stripe first)
- Prevents accidental double-billing
- Optional confirmation checkbox for intentional overrides

---

## 📊 **Complete Edge Case Matrix**

| Scenario | Current Behavior | Risk | Fix Needed? |
|----------|------------------|------|-------------|
| User has manual sub only | ✅ Works correctly | None | No |
| User has Stripe sub only | ✅ Works correctly | None | No |
| User has BOTH active | ⚠️ Unpredictable which is returned | Medium | **Yes - Fix 1** |
| User with manual tries Stripe checkout | ❌ Checkout fails (tries to cancel via Stripe) | High | **Yes - Fix 2** |
| Admin grants while Stripe active | ❌ DB cancels, Stripe keeps billing | High | **Yes - Fix 3** |
| Stripe webhook, user has manual | ✅ Webhook ignores manual sub | None | No |
| Admin revokes manual, Stripe exists | ✅ Stripe takes over | None | No |
| User cancels Stripe, manual exists | ✅ Manual takes over | None | No |

---

## 🔍 **Testing Scenarios**

### **Scenario 1: Manual → Stripe Upgrade**
```
1. Admin grants free Professional to user@test.com
2. User logs in, sees Professional features
3. User clicks "Upgrade to Team"
4. ✅ With Fix 2: Checkout works, manual marked 'superseded', Stripe takes over
   ❌ Without Fix 2: Error, checkout fails
```

### **Scenario 2: Stripe User Gets Manual Grant**
```
1. User has active Stripe Team subscription ($50/mo)
2. Admin grants free Professional (trying to help)
3. ✅ With Fix 3: Warning shown, admin stops
   ❌ Without Fix 3: User keeps getting charged but DB shows canceled
```

### **Scenario 3: Both Active, Which Wins?**
```
1. User has manual Professional (10 briefs)
2. User also has Stripe Team (unlimited briefs)
3. User tries to create 11th briefing
4. ✅ With Fix 1: Stripe wins, user has unlimited (correct)
   ❌ Without Fix 1: Random - might get manual limits (wrong)
```

---

## 🛠️ **Implementation Priority**

| Fix | Priority | Effort | Risk if Not Fixed |
|-----|----------|--------|-------------------|
| **Fix 1: Subscription Priority** | HIGH | 30 min | Users with both subs get wrong limits |
| **Fix 2: Checkout Handling** | CRITICAL | 45 min | Users cannot upgrade from manual to Stripe |
| **Fix 3: Admin Warning** | HIGH | 20 min | Admin accidentally creates double-billing |

**Total Effort:** ~2 hours

---

## ✅ **Current Strengths**

1. **Webhook Isolation** - Webhooks don't touch manual subscriptions ✅
2. **Admin-Only Creation** - Users can't self-grant ✅
3. **Audit Logging** - All admin actions logged ✅
4. **Data Preservation** - Revoking doesn't delete user's briefings ✅
5. **Separate Namespace** - Manual subs use `billing_interval='lifetime'` for easy identification ✅

---

## 📋 **Recommended Changes Summary**

### **Immediate (Critical):**
1. Add subscription priority to `get_active_subscription()` (Stripe > Manual)
2. Handle manual subscriptions in checkout flow
3. Add warning to admin panel about Stripe subscriptions

### **Short-term (Nice to Have):**
1. Add "superseded" status for manual subs replaced by Stripe
2. Show Stripe subscription status in admin panel
3. Link to Stripe dashboard from admin panel for easy cancellation
4. Add filter to see manual vs Stripe subscriptions

### **Long-term (Future):**
1. Auto-detect Stripe subscription conflicts and alert admin
2. Sync manual subscription grants back to Stripe as comped subscriptions
3. Admin tool to bulk-cancel Stripe subscriptions

---

## 🚨 **Critical Questions to Answer**

### **Q1: What happens if user has both subscriptions?**
**Current:** Unpredictable - `.first()` returns random one  
**Should Be:** Stripe wins (user is paying, give them what they paid for)  
**Fix:** Implement Fix 1

### **Q2: Can user with manual sub sign up for Stripe?**
**Current:** No - checkout fails  
**Should Be:** Yes - Stripe subscription takes over  
**Fix:** Implement Fix 2

### **Q3: What if admin grants while Stripe active?**
**Current:** User keeps getting billed but DB shows canceled  
**Should Be:** Admin sees warning, cancels Stripe first  
**Fix:** Implement Fix 3

---

## 🎯 **Bottom Line**

### **Without Fixes:**
- ⚠️ Users with manual subs **cannot upgrade to paid Stripe** (checkout fails)
- ⚠️ Admin can accidentally create **double-billing scenarios**
- ⚠️ Users with both subs get **unpredictable limits**

### **With Fixes:**
- ✅ Users can seamlessly upgrade from manual to Stripe
- ✅ Admin gets warnings before creating conflicts
- ✅ Subscription priority is deterministic (Stripe > Manual)
- ✅ System works correctly for all edge cases

**Recommendation:** Implement all 3 fixes before production launch. Total effort is ~2 hours and prevents significant support issues.

---

**Status:** ⚠️ FIXES NEEDED - System works for simple cases but has edge case issues  
**Confidence After Fixes:** 9.5/10 - Excellent  
**Confidence Without Fixes:** 6/10 - Risky for production

---

**Last Updated:** January 21, 2026  
**Next Steps:** Implement Fixes 1-3 (est. 2 hours)
