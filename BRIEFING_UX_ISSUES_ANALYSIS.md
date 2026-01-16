# Briefing System UX Issues Analysis

## Issues Identified

### 1. Company/Organization Briefings Not Working
**Status**: Code exists but may have UI/form issues
- Route logic checks for `company_profile` correctly
- Form shows option but may not be working properly
- Need to verify form submission and validation

### 2. System Sources Not Available
**Status**: Missing - NewsSource not included in available sources
- Current code only queries `InputSource` (user/org created)
- `NewsSource` (60+ curated system sources) should be available
- Need to bridge NewsSource to InputSource or allow direct selection
- Users should be able to select from existing curated sources

### 3. DRY Violation - Recipient Management
**Status**: Basic implementation doesn't match admin UI
- Admin has: bulk import, toggle pause/active, bulk remove, better table UI
- Briefing recipients page: only single add/remove
- Missing: bulk operations, status management, better UX

### 4. Missing Breadcrumbs & Navigation
**Status**: No breadcrumbs, confusing UX
- No breadcrumbs on any briefing pages
- No clear navigation path
- No step indicators for multi-step processes
- Should follow pattern from discussions pages

### 5. Responsive Design & Best Practices
**Status**: Need verification
- Should ensure all pages are fully responsive
- Follow same patterns as working pages (brief/landing.html, admin pages)

## Solutions

### Fix 1: Company Briefings
- Verify form properly shows/handles org option
- Ensure validation works correctly
- Test with company profile

### Fix 2: System Sources
- Create helper function to get all available sources (InputSource + NewsSource)
- Convert NewsSource to InputSource-like objects for selection
- Or create InputSource entries on-the-fly when NewsSource is selected
- Show in source selection UI

### Fix 3: Recipient Management
- Refactor to match admin UI patterns
- Add bulk import functionality
- Add toggle pause/active buttons
- Add bulk remove with checkboxes
- Better table layout

### Fix 4: Breadcrumbs
- Add breadcrumb component
- Add to all briefing pages:
  - List → Create
  - List → Detail
  - Detail → Edit
  - Detail → Sources
  - Detail → Recipients
  - Detail → Run View

### Fix 5: UX Improvements
- Add step indicators where appropriate
- Ensure responsive design
- Follow best practices from other pages
