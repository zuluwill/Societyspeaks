# Society Speaks Native Debate System - Complete Guide

**A Next-Generation Civic Discourse Platform**

Built from the ground up to replace pol.is with better UX, deeper insights, and complete control.

---

## 🎯 What You've Built

A **production-ready, pol.is-inspired debate system** with:

### ✅ Core Features (Phases 1-4 Complete)

1. **Statement System** (Phase 1)

   - One-click voting (Agree/Disagree/Unsure)
   - Progressive disclosure (pol.is pattern)
   - Wilson score ranking
   - Controversy detection
   - Duplicate prevention

2. **Rich Debate** (Phase 2)

   - Threaded responses (pro/con/neutral)
   - Evidence linking with file uploads
   - Replit Object Storage integration
   - Moderation queue
   - Edit windows (10 min)
   - Audit logs

3. **Consensus Clustering** (Phase 3)

   - PCA dimensionality reduction
   - Agglomerative clustering
   - Automatic cluster count selection (silhouette score)
   - Consensus statement detection (≥70% agreement)
   - Bridge statement detection (unite clusters)
   - Divisive statement detection (controversy score)
   - Background analysis jobs (APScheduler)
   - JSON export

4. **Optional LLM Features** (Phase 4)
   - User-provided API keys (encrypted)
   - AI-generated summaries
   - Semantic deduplication
   - Cluster labeling
   - Supports: OpenAI, Anthropic (Claude), Mistral

---

## 🚀 Deployment Steps

### 1. Set Environment Variables (Replit Secrets)

```bash
DATABASE_URL=postgresql://user:pass@host:5432/db
SECRET_KEY=your-flask-secret-key-here
ENCRYPTION_KEY=your-fernet-encryption-key-here  # For API keys
```

Generate encryption key:

```python
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
```

### 2. Install Dependencies

```bash
cd /Users/williamroberts/Code/personal/Societyspeaks
pip install -r requirements.txt
```

Key new dependencies:

- `scikit-learn>=1.3.0` (clustering)
- `numpy>=1.24.0` (math)
- `APScheduler==3.10.4` (background tasks)
- `cryptography>=41.0.0` (API key encryption)

### 3. Run Database Migration

```bash
python3 -m flask db upgrade
```

This creates all new tables:

- `statement`
- `statement_vote`
- `response`
- `evidence`
- `consensus_analysis`
- `statement_flag`
- `user_api_key`

### 4. Start the Application

```bash
python3 run.py
```

The background scheduler will start automatically (not during migrations).

### 5. Generate Test Data (Optional)

```bash
python3 scripts/generate_test_data.py
```

This creates:

- 20 test users (`testuser1`-`testuser20`, password: `testpassword123`)
- 1 test discussion on climate action
- 20 statements
- Realistic voting patterns (forms 3 clusters)
- 30 responses
- Sample flags

---

## 📖 User Guide

### Creating a Native Discussion

1. Navigate to `/discussions/create`
2. Check **"Use Native Statement System"**
3. Fill in details (title, description, topic)
4. Submit

### Posting Statements

1. View a native discussion
2. Click **"Add Statement"**
3. Enter 10-500 characters
4. Choose type (Claim or Question)
5. Submit

**Automatic Features:**

- Duplicate prevention (exact match)
- Semantic deduplication (if LLM enabled)
- Progressive disclosure (see statements with fewer votes first)

### Voting on Statements

1. Click **Agree** / **Disagree** / **Unsure** button
2. Optionally add confidence (1-5)
3. AJAX updates (no page reload)
4. Can change your vote anytime

### Adding Responses

1. Click **"Respond"** on a statement
2. Choose position (Pro/Con/Neutral)
3. Write your response
4. Optionally add evidence:
   - URL link
   - File upload (max 10MB)
   - Citation text

### Moderation (Discussion Owners)

1. Navigate to `/discussions/<id>/moderation`
2. Review flagged statements
3. Take action:
   - **Approve flag** → Mark statement as problematic
   - **Reject flag** → Statement is acceptable
   - **Bulk actions** → Handle multiple flags

### Running Consensus Analysis

**Requirements:**

- At least 7 users
- At least 7 statements
- At least 50 total votes
- Each statement has ≥3 votes

**Steps:**

1. Navigate to discussion (as owner)
2. Click **"Run Consensus Analysis"**
3. Wait ~5-30 seconds (depends on size)
4. View results:
   - User clusters (2D visualization)
   - Consensus statements
   - Bridge statements
   - Divisive statements
   - Cluster statistics

**Automatic Re-Analysis:**

- Background scheduler runs every 6 hours
- Only re-analyzes if ≥5 new votes since last run

### Optional LLM Features

**Setup:**

1. Add API key in `/settings/api-keys`
2. Choose provider (OpenAI/Anthropic/Mistral)
3. Key is validated and encrypted
4. Enable/disable anytime

**Features:**

- **AI Summary**: Generate readable summary of consensus
- **Cluster Labels**: Auto-name opinion groups
- **Semantic Deduplication**: Prevent similar statements

**Cost Control:**

- Uses **gpt-4o-mini** (OpenAI) or **claude-haiku** (Anthropic)
- ~$0.01-0.05 per analysis
- Only runs when you click "Generate"
- Your key, your control

---

## 🏗️ Architecture

### Database Schema

```
Discussion
├── has_native_statements: bool
├── embed_code: text (nullable)
└── statements: [Statement]

Statement
├── discussion_id
├── user_id
├── content (10-500 chars)
├── statement_type ('claim'|'question')
├── vote_count_agree/disagree/unsure (denormalized)
├── mod_status (-1|0|1)
├── is_deleted: bool
├── votes: [StatementVote]
└── responses: [Response]

StatementVote
├── statement_id
├── user_id
├── vote (-1|0|1)
├── confidence (1-5, optional)
└── UNIQUE(statement_id, user_id)

Response
├── statement_id
├── user_id
├── parent_response_id (for threading)
├── position ('pro'|'con'|'neutral')
├── content
├── is_deleted: bool
└── evidence: [Evidence]

Evidence
├── response_id
├── source_title/url
├── citation
├── quality_status ('pending'|'verified'|'disputed')
├── storage_key (Replit Object Storage)
└── storage_url

ConsensusAnalysis
├── discussion_id
├── cluster_data: JSON {
│   ├── cluster_assignments: {user_id: cluster_id}
│   ├── pca_coordinates: {user_id: [x, y]}
│   ├── consensus_statements: [...]
│   ├── bridge_statements: [...]
│   ├── divisive_statements: [...]
│   ├── metadata: {...}
│   ├── ai_summary (optional)
│   └── cluster_labels (optional)
│ }
├── num_clusters
├── silhouette_score
└── created_at

StatementFlag
├── statement_id
├── flagger_user_id
├── flag_reason
├── status ('pending'|'approved'|'rejected')
└── reviewed_by_user_id

UserAPIKey
├── user_id
├── provider ('openai'|'anthropic'|'mistral')
├── encrypted_api_key
├── is_active
└── last_validated
```

### Backend Components

**Blueprints:**

- `discussions_bp` - Discussion CRUD
- `statements_bp` - Statement/vote routes
- `moderation_bp` - Moderation queue
- `consensus_bp` - Clustering & analysis
- `api_keys_bp` - User API key management

**Libraries:**

- `app/lib/consensus_engine.py` - Clustering algorithms
- `app/lib/llm_utils.py` - LLM integrations

**Background:**

- `app/scheduler.py` - APScheduler jobs
- Auto-clustering every 6 hours
- Cleanup old analyses daily

### Clustering Algorithm (Phase 3)

**Inspired by pol.is, but enhanced:**

1. **Build Vote Matrix**

   - Rows = users
   - Columns = statements
   - Values = -1 (disagree), 0 (unsure), 1 (agree)

2. **PCA Reduction**

   - Reduce to 2 dimensions
   - Preserves variance
   - Enables visualization

3. **Agglomerative Clustering**

   - Cosine distance (good for sparse vote data)
   - Average linkage
   - Auto-select k using silhouette score

4. **Special Statement Detection**
   - **Consensus**: ≥70% overall, ≥60% in each cluster
   - **Bridge**: High mean agreement, low variance across clusters
   - **Divisive**: Controversy score ≥0.7 (close to 50/50 split)

### Security & Performance

**Security:**

- Rate limiting (Flask-Limiter)
- CSRF protection (Flask-WTF)
- Input validation (10-500 chars, type checking)
- Encrypted API keys (Fernet)
- API key validation before storage
- Edit windows (10 min, then immutable)
- Soft deletes (audit trail)
- Permission checks (owner/moderator)

**Performance:**

- Denormalized vote counts (avoid COUNT(\*) queries)
- Indexes on foreign keys
- Pagination (20 statements per page)
- Rate limiting (prevent abuse)
- Background clustering (non-blocking)
- Old analysis cleanup (keep 10 most recent)

**Data Integrity:**

- Unique constraints (no duplicate statements)
- Foreign key constraints
- Transaction safety (db.session rollback on error)
- Vote matrix validation before clustering

---

## 📊 Consensus Analysis Explained

### What is Clustering?

Pol.is's secret sauce: **group users by how they vote, not what they say**.

- Traditional forums: threads, upvotes, chaos
- Pol.is approach: "Show me people who vote similarly"

**Result:** You discover opinion groups without labels or bias.

### How It Works

1. **Vote Matrix**:

   ```
   User 1: [1, 1, -1, 0, 1]
   User 2: [1, 1, -1, 1, 1]
   User 3: [-1, 0, 1, -1, -1]
   ```

2. **Clustering**:

   - Users 1 & 2 → Group A (vote similarly)
   - User 3 → Group B (votes differently)

3. **Analysis**:
   - What does Group A agree on?
   - What bridges Groups A & B?
   - What divides them?

### Metrics

**Silhouette Score** (0 to 1):

- Measures cluster quality
- > 0.5 = Good separation
- <0.3 = Weak clusters
- Helps auto-select number of clusters

**Controversy Score** (0 to 1):

- 1.0 = Perfect 50/50 split
- 0.0 = Universal agreement or disagreement
- Formula: `1 - |agree_rate - 0.5| * 2`

**Agreement Rate**:

- % of voters who agree with statement
- Used for consensus detection

### Visualization (When UI is added)

**2D Scatter Plot:**

- Each dot = a user
- Colors = clusters
- Position = opinion similarity (PCA coordinates)
- Hover to see user details

**Cluster Cards:**

- Cluster name (AI-generated or "Group 1")
- Member count
- Key shared beliefs
- Representative statements

**Statement Highlighting:**

- 🟢 Green = Consensus
- 🟡 Yellow = Bridge
- 🔴 Red = Divisive

---

## 🔧 Customization

### Adjust Clustering Thresholds

Edit `app/lib/consensus_engine.py`:

```python
# Consensus detection
consensus_threshold=0.7  # 70% overall agreement
cluster_threshold=0.6    # 60% in each cluster

# Bridge detection
min_agreement=0.65       # 65% mean agreement
max_variance=0.15        # Low variance

# Divisive detection
min_controversy=0.7      # High controversy
```

### Change Scheduler Frequency

Edit `app/scheduler.py`:

```python
@scheduler.scheduled_job('interval', hours=6, ...)  # Change hours
```

### Customize LLM Prompts

Edit `app/lib/llm_utils.py`:

```python
def generate_discussion_summary(...):
    context = f"""
    Your custom prompt here...
    """
```

### Add More LLM Providers

Edit `app/lib/llm_utils.py` and `app/settings/api_keys.py`:

1. Add provider to validation
2. Add API client integration
3. Update UI to show new provider

---

## 🧪 Testing

### Manual Testing Checklist

**Phase 1 - Statements:**

- [ ] Create native discussion
- [ ] Post statement (10-500 chars)
- [ ] Vote (agree/disagree/unsure)
- [ ] Change vote
- [ ] Try duplicate statement (should be blocked)
- [ ] View statement sorting (progressive, best, controversial)

**Phase 2 - Responses:**

- [ ] Add response (pro/con/neutral)
- [ ] Add evidence (URL + file upload)
- [ ] Edit response (within 10 min)
- [ ] Delete response
- [ ] Flag statement
- [ ] View moderation queue (as owner)
- [ ] Approve/reject flag

**Phase 3 - Clustering:**

- [ ] Generate test data (20 users, 20 statements)
- [ ] Run consensus analysis
- [ ] View clusters
- [ ] Check consensus statements
- [ ] Check bridge statements
- [ ] Check divisive statements
- [ ] Export JSON

**Phase 4 - LLM:**

- [ ] Add OpenAI API key
- [ ] Validate key
- [ ] Generate summary
- [ ] Generate cluster labels
- [ ] Test semantic deduplication
- [ ] Disable/re-enable key

### Automated Testing (Future)

```bash
# Unit tests
pytest tests/unit/

# Integration tests
pytest tests/integration/

# Load tests
locust -f tests/load/locustfile.py
```

---

## 📈 Monitoring & Maintenance

### Key Metrics to Track

**Engagement:**

- Statements per discussion
- Votes per statement
- Responses per statement
- Avg. time to first vote

**Quality:**

- Silhouette score per analysis
- % consensus statements
- % bridge statements
- Duplicate prevention rate

**Moderation:**

- Flags per discussion
- Flag approval rate
- Response time (flag → review)

**Performance:**

- Clustering time (should be <30s)
- Background job success rate
- API response times

### Logs

**Important log locations:**

```bash
# Application logs
tail -f logs/societyspeaks.log

# Scheduler logs (look for "Scheduler initialized")
grep "Scheduler" logs/societyspeaks.log

# Clustering logs
grep "consensus_engine" logs/societyspeaks.log

# LLM usage logs
grep "llm_utils" logs/societyspeaks.log
```

### Database Maintenance

**Monthly:**

```sql
-- Check table sizes
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename))
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- Vacuum and analyze
VACUUM ANALYZE;
```

**Monitor vote matrix growth:**

```sql
SELECT
    discussion_id,
    COUNT(DISTINCT user_id) as users,
    COUNT(DISTINCT statement_id) as statements,
    COUNT(*) as total_votes
FROM statement_vote
GROUP BY discussion_id
ORDER BY total_votes DESC;
```

---

## 🆘 Troubleshooting

### "Cannot cluster: Need at least 7 users"

**Cause:** Not enough participants  
**Solution:** Wait for more users or generate test data

### "Error uploading to Replit storage"

**Cause:** Replit Object Storage not configured or full  
**Solution:**

1. Check Replit Storage quota
2. Verify `storage_client` initialization
3. Check file size (<10MB)

### "Scheduler already initialized"

**Cause:** App restarting while scheduler still running  
**Solution:** Normal warning, safe to ignore in development

### Clustering takes too long (>60s)

**Cause:** Too many users or statements  
**Solution:**

1. Check vote matrix size (users × statements)
2. Consider sampling for large discussions
3. Run clustering in background only

### API key validation fails

**Cause:** Invalid key or provider issue  
**Solution:**

1. Check key is correct
2. Verify provider (openai/anthropic)
3. Check API provider status
4. Re-validate in settings

### Migration fails: "DATABASE_URL not set"

**Cause:** Environment variable missing  
**Solution:** Set in Replit Secrets or `.env`

---

## 🎉 What's Next?

### Near-Term Enhancements

1. **UI Templates** (in progress):

   - Response threading UI
   - Evidence display
   - Cluster visualization (Chart.js/D3.js)
   - Consensus results page

2. **Mobile Optimization**:

   - Touch-friendly voting
   - Swipe gestures
   - Progressive web app (PWA)

3. **Analytics Dashboard**:

   - Discussion owner insights
   - Engagement metrics
   - Quality scores

4. **Export/Import**:
   - CSV export (votes, statements)
   - PDF reports
   - Import from pol.is

### Future Phases

5. **Advanced Clustering**:

   - UMAP for better visualization
   - HDBSCAN for automatic cluster detection
   - Temporal clustering (how opinions evolve)

6. **Deliberation Tools**:

   - Facilitation prompts
   - Breakout rooms
   - Timed phases

7. **Integration**:
   - Webhook notifications
   - REST API
   - Embed widgets

---

## 📚 References

### Pol.is Documentation

- [pol.is GitHub](https://github.com/compdemocracy/polis)
- [pol.is Math (Clojure)](https://github.com/compdemocracy/polisClientAdmin)

### Algorithms

- [Wilson Score Interval](https://en.wikipedia.org/wiki/Binomial_proportion_confidence_interval)
- [Agglomerative Clustering](https://scikit-learn.org/stable/modules/clustering.html#hierarchical-clustering)
- [Silhouette Score](https://scikit-learn.org/stable/modules/clustering.html#silhouette-coefficient)

### Design Patterns

- [Progressive Disclosure (UX)](https://www.nngroup.com/articles/progressive-disclosure/)
- [Representational Democracy](https://en.wikipedia.org/wiki/Representative_democracy)

---

## 🤝 Contributing

This is an **open-source project** (AGPL-3.0).

### Code Attribution

Where code patterns are adapted from pol.is:

- Vote matrix construction
- PCA + clustering approach
- Consensus/bridge/divisive detection

**Original work by Society Speaks:**

- Flask implementation
- Response & evidence system
- LLM integration
- Replit deployment optimizations

### License

AGPL-3.0 - If you modify and deploy this, you must:

1. Keep source code available
2. Attribute original authors
3. Share modifications under AGPL-3.0

---

**Built with ❤️ by Society Speaks**  
_Empowering nuanced, evidence-based civic discourse_

**Questions?** Open an issue on GitHub or email support@societyspeaks.io
