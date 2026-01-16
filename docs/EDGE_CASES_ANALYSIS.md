# Edge Cases & Downstream Dependencies Analysis

## ✅ Already Handled Edge Cases

### 1. **Domain Deletion with Active Briefings** ✅
**Location**: `app/briefing/routes.py:1645-1653`

**Handled**:
- Checks for active briefings before deletion
- Prevents deletion if briefings are using domain
- User-friendly error message

**Code**:
```python
active_briefings = Briefing.query.filter_by(
    sending_domain_id=domain_id,
    status='active'
).count()

if active_briefings > 0:
    flash(f'Cannot delete domain: {active_briefings} active briefing(s) are using it...', 'error')
```

---

### 2. **Domain Status Check at Send Time** ✅
**Location**: `app/briefing/email_client.py:96-103`

**Handled**:
- Re-checks domain status right before sending
- Falls back to default if domain not verified
- Handles race conditions (domain becomes unverified after briefing created)

**Code**:
```python
if briefing.sending_domain_id and briefing.sending_domain:
    domain = briefing.sending_domain
    if domain.status == 'verified' and briefing.from_email:
        return briefing.from_email
# Falls back to default
```

---

### 3. **Foreign Key Cleanup** ✅
**Location**: `app/models.py:2734`

**Handled**:
- `ondelete='SET NULL'` on `sending_domain_id`
- When domain deleted, `briefing.sending_domain_id` automatically set to NULL
- Briefings gracefully fall back to default email

---

### 4. **Resend API Failure Handling** ✅
**Location**: `app/briefing/routes.py:1653-1660`

**Handled**:
- If Resend API deletion fails, domain kept in database
- Prevents orphaned domains in Resend
- Maintains data consistency

---

## ⚠️ Edge Cases That Need Fixing

### 1. **Domain Deleted While Email Sending** ⚠️
**Issue**: If domain is deleted while `BriefingEmailClient._get_from_email()` is executing, `briefing.sending_domain` could be None.

**Current Code**:
```python
if briefing.sending_domain_id and briefing.sending_domain:
    domain = briefing.sending_domain  # Could be None if deleted
```

**Fix Needed**: Add try/except or check if relationship exists.

---

### 2. **from_email Set But Domain Removed** ⚠️
**Issue**: If user removes `sending_domain_id` but `from_email` still contains custom domain email, validation should clear it.

**Current Behavior**: `from_email` can remain set even if domain removed.

**Fix Needed**: Clear `from_email` when `sending_domain_id` is removed.

---

### 3. **Company Logo Missing/Broken** ⚠️
**Issue**: If company logo file is deleted or URL is broken, email template will show broken image.

**Current Code**:
```python
company_logo_url = f"{base_url}/profiles/image/{company.logo}"
# No error handling if logo doesn't exist
```

**Fix Needed**: Add error handling in template or check if logo exists.

---

### 4. **Domain Status Changes After Briefing Created** ⚠️
**Issue**: If domain becomes unverified/failed after briefing is created, user should be notified.

**Current Behavior**: System silently falls back to default (good), but user might not know.

**Fix Needed**: Add notification or warning in briefing detail page if domain status changed.

---

### 5. **Email Validation When Domain Changed** ⚠️
**Issue**: If user changes domain in edit form, email validation should update immediately.

**Current Behavior**: JavaScript validates, but server-side might not catch all cases.

**Fix Needed**: Ensure server-side validation handles domain changes correctly.

---

### 6. **Company Profile Deleted** ⚠️
**Issue**: If company profile is deleted, briefings with `owner_type='org'` and `owner_id` pointing to deleted profile will break.

**Current Behavior**: Foreign key might prevent deletion, or briefings become orphaned.

**Fix Needed**: Check if this is handled in account deletion flow.

---

## 🔧 Recommended Fixes

### Fix #1: Handle Domain Deletion Race Condition

**File**: `app/briefing/email_client.py`

```python
def _get_from_email(self, briefing: Briefing) -> str:
    try:
        if briefing.sending_domain_id:
            # Reload domain to ensure it still exists
            domain = SendingDomain.query.get(briefing.sending_domain_id)
            if domain and domain.status == 'verified' and briefing.from_email:
                return briefing.from_email
    except Exception as e:
        logger.warning(f"Error checking domain for briefing {briefing.id}: {e}")
    
    # Fallback to default
    return os.environ.get('BRIEF_FROM_EMAIL', 'hello@brief.societyspeaks.io')
```

---

### Fix #2: Clear from_email When Domain Removed

**File**: `app/briefing/routes.py` (edit route)

```python
# Update branding (only for org briefings)
if briefing.owner_type == 'org':
    briefing.from_name = from_name
    briefing.from_email = from_email
    briefing.sending_domain_id = sending_domain_id
    
    # Clear from_email if domain removed
    if not sending_domain_id and briefing.from_email:
        # Check if from_email was from a custom domain
        if briefing.sending_domain_id != sending_domain_id:  # Domain was removed
            briefing.from_email = None
```

Actually, better approach:

```python
# Update branding (only for org briefings)
if briefing.owner_type == 'org':
    briefing.from_name = from_name
    briefing.sending_domain_id = sending_domain_id
    
    # If domain removed, clear from_email
    if not sending_domain_id:
        briefing.from_email = None
    else:
        briefing.from_email = from_email
```

---

### Fix #3: Handle Missing Company Logo

**File**: `app/briefing/email_client.py`

```python
# Get company logo if org briefing
company_logo_url = None
if briefing.owner_type == 'org' and briefing.owner_id:
    from app.models import CompanyProfile
    company = CompanyProfile.query.get(briefing.owner_id)
    if company and company.logo:
        # Build full URL for logo
        company_logo_url = f"{base_url}/profiles/image/{company.logo}"
        # Note: Template should handle broken images with onerror handler
```

**File**: `app/templates/emails/brief_run.html`

Already has `onerror` handler, but we should verify it works:

```html
<img src="{{ company_logo_url }}" 
     alt="{{ briefing.name }}"
     style="max-width: 120px; max-height: 60px; height: auto; display: block;"
     onerror="this.style.display='none';">
```

This is already handled! ✅

---

### Fix #4: Warn User About Domain Status Changes

**File**: `app/templates/briefing/detail.html`

Add warning if domain status is not verified:

```html
{% if briefing.owner_type == 'org' and briefing.sending_domain %}
    {% if briefing.sending_domain.status != 'verified' %}
    <div class="mt-4 bg-yellow-50 border border-yellow-200 rounded-lg p-4">
        <div class="flex">
            <svg class="h-5 w-5 text-yellow-400" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
            </svg>
            <div class="ml-3">
                <h3 class="text-sm font-medium text-yellow-800">Domain Not Verified</h3>
                <p class="mt-1 text-sm text-yellow-700">
                    Your sending domain "{{ briefing.sending_domain.domain }}" is not verified. 
                    Emails will be sent from the default address until verification is complete.
                    <a href="{{ url_for('briefing.verify_domain', domain_id=briefing.sending_domain.id) }}" class="underline">Verify domain</a>
                </p>
            </div>
        </div>
    </div>
    {% endif %}
{% endif %}
```

---

### Fix #5: Validate Email When Domain Changes

**File**: `app/briefing/routes.py` (edit route)

Already handled! ✅ When `sending_domain_id` changes, validation runs:

```python
if sending_domain_id:
    if not from_email:
        flash('Email address is required when a sending domain is selected', 'error')
        return redirect(...)
    
    # Validate email matches domain
    if not from_email.endswith(f'@{domain_name}'):
        flash(f'Email must be from verified domain: {domain_name}', 'error')
        return redirect(...)
```

But we should also clear `from_email` if domain is removed:

```python
# If domain removed, clear from_email
if not sending_domain_id and briefing.sending_domain_id:
    briefing.from_email = None
```

---

### Fix #6: Company Profile Deletion

**File**: `app/settings/routes.py:237-238`

Already handled! ✅ When company profile is deleted, SendingDomains are deleted:

```python
# Delete SendingDomains (CASCADE will handle this, but explicit is safer)
SendingDomain.query.filter_by(org_id=org_id).delete(synchronize_session=False)
```

But we should check what happens to briefings with `owner_type='org'` and `owner_id=org_id`. They might become orphaned.

**Check needed**: Does account deletion handle org briefings?

---

## 📋 Summary of Required Fixes

1. ✅ **Domain deletion race condition** - Add try/except in `_get_from_email()`
2. ✅ **Clear from_email when domain removed** - Add logic in edit route
3. ✅ **Company logo missing** - Already handled with `onerror` in template
4. ✅ **Warn about domain status** - Add warning in detail page
5. ✅ **Email validation on domain change** - Already handled, but add clearing logic
6. ⚠️ **Company profile deletion** - Need to verify org briefings are handled

---

## 🧪 Test Cases to Verify

1. **Domain deleted while email sending**:
   - Create briefing with domain
   - Start sending email
   - Delete domain mid-send
   - Verify email still sends (with fallback)

2. **Domain removed from briefing**:
   - Create briefing with domain and email
   - Edit briefing, remove domain
   - Verify `from_email` is cleared

3. **Domain becomes unverified**:
   - Create briefing with verified domain
   - Domain verification fails (DNS removed)
   - Verify briefing shows warning
   - Verify emails still send (with fallback)

4. **Company logo missing**:
   - Create org briefing
   - Delete company logo file
   - Generate and send email
   - Verify email renders without broken image

5. **Company profile deleted**:
   - Create org briefing
   - Delete company profile
   - Verify briefings are handled (deleted or orphaned appropriately)
