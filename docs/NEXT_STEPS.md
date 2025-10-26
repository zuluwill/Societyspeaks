# Next Steps to Complete Phase 1 Setup

## ✅ What's Been Completed

1. ✅ **All code implementation** (7 models, 9 routes, 5 forms, templates)
2. ✅ **Database migration created** (`migrations/versions/c1a2b3c4d5e6_*.py`)
3. ✅ **Blueprint registered** in `app/__init__.py`
4. ✅ **Dependencies defined** in `requirements.txt`
5. ✅ **Local Python packages installed** (Flask-Migrate, APScheduler, Flask extensions)
6. ✅ **No linting errors**
7. ✅ **Comprehensive documentation** created

**Status:** Ready for database migration and testing!

---

## 🚀 Action Required: Database Setup

### Step 1: Set DATABASE_URL Environment Variable

You need to configure your database connection. Choose one of these options:

#### Option A: Using `.env` file (Development)

Create or update `.env` file in your project root:

```bash
# For local PostgreSQL
DATABASE_URL=postgresql://username:password@localhost:5432/societyspeaks

# For Replit PostgreSQL
DATABASE_URL=postgresql://neondb_owner:YOURPASSWORD@...
```

#### Option B: Export in current shell (Temporary)

```bash
export DATABASE_URL="postgresql://username:password@localhost:5432/societyspeaks"
```

#### Option C: Replit Secrets (Production)

If deploying on Replit:

1. Go to Replit Secrets (🔒 icon in left sidebar)
2. Add `DATABASE_URL` with your PostgreSQL connection string

---

### Step 2: Apply the Database Migration

Once `DATABASE_URL` is set:

```bash
# Navigate to project directory
cd /Users/williamroberts/Code/personal/Societyspeaks

# Apply migration
python3 -m flask db upgrade

# You should see output like:
# INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
# INFO  [alembic.runtime.migration] Will assume transactional DDL.
# INFO  [alembic.runtime.migration] Running upgrade 294c806bafa6 -> c1a2b3c4d5e6, add native statement system phase 1
```

**What this does:**

- Creates 7 new tables: `statement`, `statement_vote`, `response`, `evidence`, `consensus_analysis`, `statement_flag`, `user_api_key`
- Adds `has_native_statements` column to `discussion` table
- Makes `embed_code` nullable in `discussion` table
- Creates all necessary indexes and constraints

---

### Step 3: Verify Tables Created

```bash
# Connect to your database
psql $DATABASE_URL

# List all tables
\dt

# You should see:
# statement
# statement_vote
# response
# evidence
# consensus_analysis
# statement_flag
# user_api_key

# Exit psql
\q
```

---

### Step 4: Create a Test Discussion

#### Option A: Via Flask Shell

```bash
python3 -m flask shell
```

```python
from app import db
from app.models import Discussion, User

# Get or create a user
user = User.query.first()  # Or create one if needed

# Create a native discussion
test_disc = Discussion(
    title="Test Native Discussion System",
    description="Testing the new pol.is-inspired statement system",
    has_native_statements=True,  # 🔑 KEY FLAG
    embed_code=None,  # No pol.is embed needed
    topic="Technology",
    geographic_scope="global",
    creator_id=user.id,
    individual_profile_id=user.individual_profile.id if user.profile_type == 'individual' else None
)

db.session.add(test_disc)
db.session.commit()

print(f"Created discussion at: /discussions/{test_disc.id}/{test_disc.slug}")
exit()
```

#### Option B: Via Web UI

1. Start your Flask app: `python3 run.py`
2. Navigate to `/discussions/create`
3. Currently the form doesn't have a `has_native_statements` checkbox yet
4. You'll need to manually update a discussion in the database or add the checkbox to the form

---

### Step 5: Test the System

Once you have a native discussion created, visit:

```
http://localhost:5000/discussions/{discussion_id}/{discussion-slug}
```

**Test Checklist:**

- [ ] Page loads without errors
- [ ] You see the statement input form (if logged in)
- [ ] Character counter works (0/500)
- [ ] Can post a statement (10-500 chars)
- [ ] Can vote on a statement (Agree/Disagree/Unsure)
- [ ] Vote counts update immediately (AJAX)
- [ ] Sorting dropdown works (Progressive/Best/Recent/Controversial/Most Voted)
- [ ] Try to create duplicate statement (should show error)
- [ ] Edit a statement within 10 minutes
- [ ] Try to edit after 10 minutes (should fail)

---

## 🔧 Optional: Update Create Discussion Form

To allow users to choose native vs pol.is when creating discussions:

### Update Form (`app/discussions/forms.py`):

```python
class CreateDiscussionForm(FlaskForm):
    # ... existing fields ...

    use_native_statements = BooleanField(
        'Use Native Statement System',
        default=False,
        description='Enable the new native debate system (pol.is-style) instead of embedding'
    )

    # Update validation to make embed_code optional when use_native_statements is True
    def validate_embed_code(self, field):
        if not self.use_native_statements.data and not field.data:
            raise ValidationError('Either provide a pol.is embed code or enable native statements')
```

### Update Route (`app/discussions/routes.py`):

```python
@discussions_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_discussion():
    form = CreateDiscussionForm()
    if form.validate_on_submit():
        discussion = Discussion(
            embed_code=form.embed_code.data if not form.use_native_statements.data else None,
            has_native_statements=form.use_native_statements.data,  # 🆕 NEW FIELD
            title=form.title.data,
            # ... rest of fields ...
        )
        db.session.add(discussion)
        db.session.commit()
        flash("Discussion created successfully!", "success")
        return redirect(url_for('discussions.view_discussion', discussion_id=discussion.id, slug=discussion.slug))

    return render_template('discussions/create_discussion.html', form=form)
```

### Update Template (`app/templates/discussions/create_discussion.html`):

Add this field to your form:

```html
<div class="mb-4">
  {{ form.use_native_statements.label(class="block text-sm font-medium
  text-gray-700 mb-2") }} {{ form.use_native_statements(class="h-4 w-4
  text-blue-600 focus:ring-blue-500 border-gray-300 rounded") }}
  <p class="mt-1 text-sm text-gray-500">
    Enable the new native statement system with voting and consensus clustering
    (experimental)
  </p>
</div>

<!-- Make embed_code conditional -->
<div id="embed-code-section" class="mb-4">
  {{ form.embed_code.label(class="block text-sm font-medium text-gray-700 mb-2")
  }} {{ form.embed_code(class="w-full px-3 py-2 border border-gray-300
  rounded-md", rows="4") }}
  <p class="mt-1 text-sm text-gray-500">
    If using pol.is, paste the embed code here
  </p>
</div>

<script>
  // Toggle embed code visibility
  document
    .getElementById("use_native_statements")
    .addEventListener("change", function () {
      document.getElementById("embed-code-section").style.display = this.checked
        ? "none"
        : "block";
    });
</script>
```

---

## 📊 What Happens Next

### Immediate (Phase 1 Complete)

- Users can create statements
- Users can vote (agree/disagree/unsure)
- Vote counts display in real-time
- Statements can be sorted 5 different ways
- Basic moderation (flagging)

### Soon (Phase 2 - Rich Debate)

- Threaded responses (pro/con)
- Evidence linking
- Moderation queue
- Statement quality scoring

### Later (Phase 3 - Consensus Clustering)

- User clustering based on voting patterns
- Consensus statement identification (≥70% overall, ≥60% per cluster)
- Bridge statement identification (high agreement, low variance)
- Divisive statement identification
- Interactive visualizations (Chart.js/D3.js)
- Automated analysis snapshots

### Future (Phase 4 - LLM Features)

- AI-powered summaries
- Semantic clustering
- Automatic deduplication
- Quality moderation assistance

---

## 🐛 Troubleshooting

### Migration Fails

```bash
# Check current migration status
python3 -m flask db current

# If stuck, try:
python3 -m flask db stamp head  # Mark as up-to-date
python3 -m flask db upgrade     # Try again
```

### "Table already exists" Error

```bash
# Drop and recreate (⚠️ WARNING: DATA LOSS)
psql $DATABASE_URL -c "DROP TABLE IF EXISTS statement, statement_vote, response, evidence, consensus_analysis, statement_flag, user_api_key CASCADE;"

# Then apply migration
python3 -m flask db upgrade
```

### Import Errors

```bash
# Install missing dependencies
python3 -m pip install -r requirements.txt --user

# Or install specific package
python3 -m pip install package-name --user
```

### Can't See Native UI

1. Verify `discussion.has_native_statements = True` in database:
   ```sql
   SELECT id, title, has_native_statements FROM discussion WHERE id = YOUR_ID;
   ```
2. Check browser console for JavaScript errors
3. Verify `view_native.html` template exists
4. Check Flask logs for template rendering errors

---

## ✅ Success Criteria

You'll know Phase 1 is fully working when:

1. ✅ Migration applies without errors
2. ✅ 7 new tables exist in database
3. ✅ Can create a native discussion
4. ✅ Can post statements (10-500 chars)
5. ✅ Can vote on statements
6. ✅ Vote counts update instantly
7. ✅ Different sorting options work
8. ✅ Duplicate detection works
9. ✅ Edit window enforced (10 min)
10. ✅ No errors in browser console or Flask logs

---

## 📞 Need Help?

1. Check `docs/IMPLEMENTATION_COMPLETE.md` for full technical details
2. Check `docs/polis-analysis.md` for pol.is patterns
3. Review code comments (comprehensive docstrings)
4. Check Flask logs: `tail -f flask.log`
5. Check browser console (F12) for JavaScript errors
6. Verify database schema: `psql $DATABASE_URL -c "\d statement"`

---

## 🎉 Once Complete

When Phase 1 is tested and working:

1. **Deploy to Replit**:

   - Push code to GitHub
   - Replit auto-deploys
   - Add `ENCRYPTION_KEY` to Replit Secrets (for Phase 4)
   - Run migration on production DB

2. **Create First Real Discussion**:

   - Choose a timely, engaging topic
   - Add 3-5 seed statements to start
   - Share with beta testers
   - Gather feedback

3. **Monitor**:

   - Check Sentry for errors
   - Review rate limit logs
   - Gather user feedback
   - Iterate on UX

4. **Start Phase 2**:
   - Threaded responses
   - Evidence system
   - Pro/con structure
   - Moderation queue

---

**You're 95% complete! Just need to set `DATABASE_URL` and run the migration. 🚀**
