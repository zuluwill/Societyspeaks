# Admin Subscription Management Guide

**Date:** January 21, 2026  
**Admin User:** will@societyspeaks.io

---

## 🎯 **Overview**

As an admin user, you have **complete control** over the system and can:
1. ✅ **Use all features without a subscription** (admin bypass)
2. ✅ **Manually assign subscriptions to any user** 
3. ✅ **Grant free lifetime access** to selected users
4. ✅ **Change user plans** without Stripe involvement
5. ✅ **Revoke subscriptions** at any time

---

## 🔑 **Admin Bypass: How It Works**

### **What is Admin Bypass?**

Admin users (`is_admin=True`) automatically **bypass ALL subscription checks**. This means:
- ✅ No subscription required
- ✅ Unlimited briefings, sources, recipients
- ✅ All premium features unlocked (document uploads, custom branding, etc.)
- ✅ No Stripe payment required
- ✅ Works throughout the entire application

### **Where Admin Bypass is Active**

```python
# billing/enforcement.py - Lines 21-22
if current_user.is_admin:
    return f(*args, **kwargs)  # ✅ Bypass all checks
```

**Protected Operations:**
1. **Briefing Creation** - Unlimited briefings (no plan limits)
2. **Source Addition** - Unlimited sources per briefing
3. **Recipient Addition** - Unlimited email recipients
4. **Document Uploads** - Always allowed (no feature gate)
5. **Custom Domains** - Always allowed (no feature gate)
6. **Team Management** - Always allowed
7. **Manual Email Sending** - Always allowed
8. **Scheduled Jobs** - Admins' briefings always process

### **Confirming Admin Status**

Your admin user: **will@societyspeaks.io**

To verify in database:
```sql
SELECT username, email, is_admin 
FROM user 
WHERE email = 'will@societyspeaks.io';
```

Or check in admin dashboard:
1. Go to `/admin/users`
2. Look for your username - should show "Yes" under Admin column
3. Purple "ADMIN" badge will appear next to your name

---

## 🛠️ **Managing User Subscriptions**

### **Access the Subscription Manager**

1. Log in as admin
2. Go to `/admin/users`
3. Click "Subscription" link next to any user
4. You'll see the subscription management page

### **Grant Free Lifetime Access** 🎁

**Use Case:** Give someone permanent free access to any plan (no billing, no expiry)

**Steps:**
1. Go to user's subscription page
2. In "Grant Free Access" section (green box)
3. Select a plan from dropdown:
   - **Starter** - 1 brief, 10 sources, 10 recipients
   - **Professional** - 10 briefs, 20 sources, 50 recipients, document uploads
   - **Team** - Unlimited, custom branding, team seats
   - **Enterprise** - Unlimited everything
4. Click "Grant Free Access"
5. Confirm the action

**Result:**
- User gets immediate access
- `billing_interval = 'lifetime'`
- `status = 'active'`
- No Stripe involvement
- Never expires
- Shows as "FREE ACCESS" in admin panel

**Example:**
```
User: john@example.com
Plan: Professional (Lifetime)
Status: 🎁 FREE ACCESS
Limits: 10 briefs, 20 sources, 50 recipients
Features: Document uploads ✓
```

---

### **Grant 30-Day Trial** 🔄

**Use Case:** Give temporary trial access to test features

**Steps:**
1. Go to user's subscription page
2. In "Grant Trial" section (blue box)
3. Select a plan
4. Click "Grant 30-Day Trial"
5. Confirm the action

**Result:**
- User gets 30 days of access
- `current_period_end = now + 30 days`
- `status = 'active'`
- No Stripe involvement
- Expires after 30 days (user loses access)

---

### **Change User's Plan** 🔄

**Use Case:** Upgrade or downgrade existing subscription

**Steps:**
1. Go to user's subscription page
2. In "Change Plan" section (yellow box)
3. Select new plan from dropdown
4. Click "Change Plan"
5. Confirm the action

**Result:**
- User immediately gets new plan limits
- Billing type preserved (free access stays free, Stripe stays Stripe)
- All child data preserved (briefings, sources, recipients)

**Important:**
- If changing from Professional → Starter:
  - User keeps existing 10 briefings (grandfathered)
  - Cannot create NEW briefings beyond limit (1)
  - Existing data preserved (good UX)

---

### **Revoke Subscription** ⚠️

**Use Case:** Remove user's access immediately

**Steps:**
1. Go to user's subscription page
2. In "Revoke Subscription" section (red box)
3. Click "Revoke Subscription"
4. Confirm the action (double-check!)

**Result:**
- `status = 'canceled'`
- `canceled_at = now`
- User immediately loses access
- Cannot create briefings, add sources/recipients, send emails
- Existing data preserved (can still view)

**⚠️ Warning:** This is immediate and cannot be undone without manually granting a new subscription.

---

## 📊 **Subscription Status Reference**

### **Status Colors in Admin Panel**

| Status | Color | Meaning |
|--------|-------|---------|
| 🎁 FREE ACCESS | Green | Lifetime free access (manually granted) |
| ✓ ACTIVE | Green | Paid subscription via Stripe |
| 🔄 TRIALING | Blue | Trial period (30 days) |
| ⚠️ PAST DUE | Yellow | Payment failed, grace period |
| CANCELED | Gray | Subscription ended |

### **Billing Type Indicators**

| Type | Icon | Meaning |
|------|------|---------|
| Free Access | 🎁 | Manually granted, never expires |
| Stripe | 💳 | Via Stripe, managed by webhooks |
| Manual | 🛠️ | Manually created trial (30 days) |

---

## 🧪 **Common Use Cases**

### **Use Case 1: Give Friend Free Access**

**Scenario:** Friend wants to try the product, give them Professional plan forever.

```
1. Admin → Users → Find friend's email
2. Click "Subscription"
3. Grant Free Access → Select "Professional"
4. Confirm
5. ✅ Friend has lifetime Professional access
```

---

### **Use Case 2: Test User Needs Trial**

**Scenario:** Tester needs temporary access for 30 days.

```
1. Admin → Users → Find tester
2. Click "Subscription"
3. Grant 30-Day Trial → Select "Team"
4. Confirm
5. ✅ Tester has 30 days of Team plan access
```

---

### **Use Case 3: User Complains, Upgrade Them**

**Scenario:** Paying Starter user complains limits are too low, upgrade to Professional.

```
1. Admin → Users → Find user
2. Click "Subscription"
3. Change Plan → Select "Professional"
4. Confirm
5. ✅ User immediately gets Professional limits
```

**Note:** If they're on Stripe, they'll STILL be billed for Starter. You'd need to handle Stripe separately via customer portal or Stripe dashboard.

---

### **Use Case 4: Beta Testers Get Free Enterprise**

**Scenario:** 10 beta testers get free Enterprise access during beta.

```
For each tester:
1. Admin → Users → Find email
2. Click "Subscription"
3. Grant Free Access → Select "Enterprise"
4. Confirm
5. ✅ Unlimited access, never expires
```

---

## 🔒 **Security Considerations**

### **Who Can Do This?**

Only users with `is_admin=True` in the database.

**Your admin user:** will@societyspeaks.io

### **Audit Trail**

All actions are logged:
```python
current_app.logger.info(
    f"Admin {current_user.username} granted FREE ACCESS - {plan.name} to user {user.username}"
)
```

Check logs to see who granted what to whom.

### **Cannot Modify Own Status**

Admins **cannot** remove their own admin status (safety feature):
```python
if user == current_user:
    flash('You cannot modify your own admin status.', 'error')
```

---

## 📋 **Subscription Management Page Layout**

```
┌─────────────────────────────────────────────────────────┐
│ Manage Subscription: username                           │
│ email@example.com                                       │
│ [⚡ ADMIN USER badge if admin]                         │
└─────────────────────────────────────────────────────────┘

┌──────────────────────────┬──────────────────────────────┐
│ CURRENT SUBSCRIPTION     │ ADMIN ACTIONS                │
│                          │                              │
│ Plan: Professional       │ 🎁 Grant Free Access         │
│ Status: ✓ ACTIVE         │   [Dropdown: Select Plan]    │
│ Billing: Via Stripe      │   [Grant Free Access Button] │
│ Period: Jan 1 - Jan 31   │                              │
│                          │ 🔄 Grant Trial               │
│ Plan Limits:             │   [Dropdown: Select Plan]    │
│ • Briefings: 10          │   [Grant 30-Day Trial]       │
│ • Sources: 20            │                              │
│ • Recipients: 50         │ 🔄 Change Plan               │
│ • Editors: 10            │   [Dropdown: New Plan]       │
│ • Document Uploads: ✓    │   [Change Plan Button]       │
│ • Custom Branding: ✗     │                              │
│                          │ ⚠️ Revoke Subscription        │
│                          │   [Revoke Button]            │
└──────────────────────────┴──────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ SUBSCRIPTION HISTORY                                    │
│ [Table showing all past subscriptions]                  │
└─────────────────────────────────────────────────────────┘
```

---

## ✅ **Verification Checklist**

After granting a subscription, verify:

### **In Admin Panel:**
- [ ] User shows subscription in `/admin/users` list
- [ ] Status badge shows correct color
- [ ] Subscription page shows active subscription

### **For User:**
- [ ] User can create briefings (check their limit)
- [ ] User can add sources (check their limit)
- [ ] User can add recipients (check their limit)
- [ ] Premium features work if applicable

### **In Code:**
```python
# Test in Flask shell
from app.billing.service import get_active_subscription
sub = get_active_subscription(user)
print(f"Plan: {sub.plan.name}")
print(f"Status: {sub.status}")
print(f"Max Briefs: {sub.plan.max_briefs}")
```

---

## 🚨 **Important Notes**

### **Manual Subscriptions vs Stripe**

| Feature | Manual (Free/Trial) | Stripe |
|---------|---------------------|--------|
| Billing | None | Automatic |
| Expiry | Never (free) or 30 days (trial) | Managed by Stripe |
| Webhooks | No | Yes |
| Renewal | Manual only | Automatic |
| Cancellation | Admin only | User or Admin |

### **Free Access is Forever**

When you grant "Free Access":
- ✅ Never expires
- ✅ No payment required
- ✅ No Stripe involvement
- ✅ Full plan features
- ⚠️ Can only be revoked manually by admin

### **Grandfathering on Downgrades**

When changing from higher → lower plan:
- User keeps existing data (briefings, sources, recipients)
- Cannot CREATE new items beyond new limit
- This is intentional (good UX, prevents data loss)

---

## 📞 **Quick Reference**

| Task | URL | Action |
|------|-----|--------|
| List all users | `/admin/users` | View all users with subscription status |
| Manage user subscription | `/admin/users` → "Subscription" | Full subscription control |
| Grant free access | User subscription page → Green box | Select plan, grant |
| Grant trial | User subscription page → Blue box | Select plan, 30 days |
| Change plan | User subscription page → Yellow box | Select new plan |
| Revoke | User subscription page → Red box | Cancel immediately |

---

## 🎉 **Summary**

As **will@societyspeaks.io** (admin user):

1. ✅ **You can do everything without a subscription** - Admin bypass is active
2. ✅ **You can grant free access** - Give lifetime subscriptions to anyone
3. ✅ **You can manage all users** - Change plans, revoke access, etc.
4. ✅ **No Stripe required** - Manual subscriptions work independently
5. ✅ **Everything is logged** - Audit trail for all actions

**Next Steps:**
1. Log in to `/admin/users`
2. Test granting free access to a test user
3. Verify the user can create briefings
4. Check subscription history shows correctly

---

**Last Updated:** January 21, 2026  
**Created By:** Claude Sonnet 4.5  
**Admin User:** will@societyspeaks.io
