# Sentry Error Fixes

## ✅ FIXED IN THIS COMMIT

### 1. ValueError: Confidence must be between 1 and 5
**Root cause**: Confidence parameter not properly validated
**Fix**: Added robust validation with try/except and range checking
- Default confidence = 3 if invalid
- Handles None, out-of-range, and non-integer values

### 2. TypeError: dict.get() takes no keyword arguments
**Root cause**: Using `request.form.get('vote', type=int)` which might fail
**Fix**: Changed to `int(request.form.get('vote', 0))` for safer handling

---

## 🔧 TO FIX IN REPLIT

### 3. BuildError: Could not build url for endpoint 'discussions.list_discussions'
**File**: `app/templates/discussions/create_statement.html` (line 8)
**Error**: Route name doesn't exist
**Fix**: Change `discussions.list_discussions` to `discussions.search_discussions`

```html
<!-- WRONG -->
<a href="{{ url_for('discussions.list_discussions') }}">Discussions</a>

<!-- CORRECT -->
<a href="{{ url_for('discussions.search_discussions') }}">Discussions</a>
```

---

### 4. BuildError: Could not build url for endpoint 'discussions.index'
**File**: `app/templates/help/native_system.html` (line 443)
**Error**: Route name doesn't exist
**Fix**: Change `discussions.index` to `discussions.search_discussions`

```html
<!-- WRONG -->
<a href="{{ url_for('discussions.index') }}">Browse Active Discussions</a>

<!-- CORRECT -->
<a href="{{ url_for('discussions.search_discussions') }}">Browse Active Discussions</a>
```

---

### 5. UndefinedError: 'csrf_token' is undefined
**File**: `app/templates/discussions/view_statement.html`
**Error**: Missing CSRF token in form
**Fix**: Add CSRF token to any forms that don't have it

```html
<form method="POST" action="...">
    {{ form.hidden_tag() }}  <!-- Add this line -->
    <!-- OR if not using Flask-WTF form: -->
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
    <!-- ... rest of form ... -->
</form>
```

---

### 6. UndefinedError: ResponseForm has no attribute 'parent_response_id'
**File**: `app/templates/discussions/create_response.html` (line 87)
**Error**: Form missing field
**Fix**: Add HiddenField to ResponseForm OR remove from template

**Option A - Add field to form** (`app/discussions/statement_forms.py`):
```python
class ResponseForm(FlaskForm):
    # ... existing fields ...
    parent_response_id = HiddenField('Parent Response ID')
```

**Option B - Remove from template**:
```html
<!-- Remove this line from create_response.html line 87: -->
{{ form.parent_response_id() }}
```

---

## 🔍 HOW TO FIND & FIX IN REPLIT

1. **Open Replit Shell**
2. **Search for wrong route names:**
   ```bash
   grep -rn "discussions.list_discussions\|discussions.index" app/templates/
   ```

3. **Search for csrf_token issues:**
   ```bash
   grep -rn "<form" app/templates/discussions/view_statement.html
   ```

4. **Fix each file** as outlined above

5. **Test in browser** - errors should disappear!

---

## ✅ VERIFICATION CHECKLIST

After applying fixes in Replit:

- [ ] No more BuildError for `discussions.list_discussions`
- [ ] No more BuildError for `discussions.index`
- [ ] No more UndefinedError for `csrf_token`
- [ ] No more UndefinedError for `parent_response_id`
- [ ] No more ValueError for confidence
- [ ] No more TypeError for dict.get()

Check Sentry dashboard - all 6 errors should be resolved!
