<!-- cc8e25cf-415b-43da-877a-dd3f0cdd780b 787b10fb-4c4f-45c9-a7bf-931c99a90c14 -->
# Build Native Debate & Consensus System

## Overview

Replace pol.is embeds with a fully native system featuring threaded arguments, pro/con structure, evidence linking, consensus clustering, and optional LLM features using user-provided API keys.

## Architecture Strategy

### Core Principles

- **Flask/Python only** - leverage existing stack
- **LLM-optional** - system works fully without LLMs, enhanced with user API keys
- **Incremental migration** - existing discussions preserved during transition
- **Open source friendly** - no expensive API costs for the platform

### Technology Stack

- **Backend**: Flask (existing)
- **Database**: PostgreSQL with new tables for arguments/votes
- **Clustering**: scikit-learn, UMAP, HDBSCAN (no LLM required)
- **Visualization**: D3.js or Plotly for consensus maps
- **Optional LLM**: OpenAI/Anthropic clients (user brings own keys)

## Phase 0: pol.is Code Review & Learning (Week 0-1)

### 0.1 Repository Analysis

**Objective**: Deep dive into the pol.is codebase to understand their proven architecture and extract valuable insights.

**Repository**: https://github.com/compdemocracy/polis (AGPL-3.0 licensed, same as Society Speaks)

**Key Areas to Study**:

1. **Math/Clustering Engine** (`/math` directory - Python 20.7%)
   - PCA/dimensionality reduction algorithms
   - User clustering based on voting patterns (NOT text similarity)
   - Consensus detection algorithms
   - Bridge statement identification
   - Cluster quality metrics
   - **Critical**: This is their core innovation - how they group users by opinion similarity

2. **Data Models & Schema** (`/server`)
   - Conversation/discussion structure
   - Comment (statement) model
   - Vote model and constraints
   - Participant tracking
   - Metadata for consensus analysis
   - How they handle anonymous vs authenticated users

3. **Client Participation UI** (`/client-participation` - TypeScript 17.2%)
   - Statement presentation flow
   - Voting interface (agree/disagree/pass)
   - Real-time feedback mechanisms
   - Mobile responsiveness patterns
   - Progressive disclosure (not showing all statements at once)
   - User engagement patterns

4. **Report Generation** (`/client-report`)
   - Cluster visualization approach
   - Consensus summary generation
   - Divisive statement highlighting
   - Export formats (CSV, JSON, visualizations)
   - How they explain clusters to non-technical users

5. **API Design** (`/server`)
   - RESTful endpoint structure
   - Authentication/authorization patterns
   - Rate limiting strategies
   - Error handling approaches
   - Real-time update mechanisms (if any)

6. **Deployment & Scaling** (`/deploy`, `/cdk`)
   - Docker architecture
   - Database configuration
   - Caching strategies
   - CDN usage
   - Performance optimizations

### 0.2 Key Questions to Answer

During the code review, document answers to:

1. **Clustering**:
   - What specific algorithm do they use? (PCA + k-means? t-SNE? UMAP?)
   - How do they determine optimal number of clusters?
   - How often do they recalculate clusters?
   - What's the minimum threshold for clustering (votes/participants)?

2. **Data Model**:
   - Do they use Statement vs Argument terminology?
   - How do they handle vote changes?
   - What indexes do they use for performance?
   - How do they prevent vote manipulation?

3. **UX Flow**:
   - How many statements do users see at once?
   - Do they prioritize which statements to show first?
   - How do they handle new statements appearing mid-session?
   - What's their onboarding flow?

4. **Performance**:
   - How do they scale to conversations with 10K+ participants?
   - What's their caching strategy?
   - Do they use background jobs for clustering?
   - How do they handle real-time updates?

5. **Moderation**:
   - How do they handle spam/abuse?
   - Can conversation owners moderate statements?
   - Is there an approval queue for statements?

### 0.3 Extraction & Adaptation Strategy

**What to Potentially Reuse** (AGPL-3.0 compatible):

1. **Math algorithms** - Their clustering code is the crown jewel
   - Consider importing their Python clustering module directly
   - Or adapting it to our needs with proper attribution
   - This could save 2-3 weeks of Phase 3 development

2. **Data model patterns** - Follow their proven schema
   - Statement-centric vs argument-centric architecture
   - Vote matrix structure
   - Participant tracking

3. **UX patterns** - Recreate their proven interfaces
   - Not copying code, but understanding what works
   - Statement presentation order
   - Voting interaction patterns

**What to Build Fresh**:

1. **Evidence linking** - pol.is doesn't have this, we're adding value
2. **Threaded responses** - pol.is statements are flat, we're going deeper
3. **LLM integration** - Our unique feature with user API keys
4. **Pro/con structure** - Enhanced debate features beyond voting

### 0.4 Deliverables

At end of Phase 0, produce:

1. **Technical Analysis Document** (`docs/polis-analysis.md`):
   - Architecture overview
   - Clustering algorithm breakdown
   - Data model comparison
   - API design patterns
   - Performance insights

2. **Reusability Assessment**:
   - List of pol.is components to adapt
   - Components to build from scratch
   - Licensing compliance notes (AGPL-3.0 attribution)

3. **Refined Database Schema**:
   - Update Phase 1.1 based on pol.is learnings
   - Ensure compatibility with their clustering approach
   - Document deviations and rationale

4. **Updated Phase 3 Plan**:
   - Specific algorithms to use (based on pol.is)
   - Whether to adapt their code or build fresh
   - Updated dependency list
   - Realistic effort estimates

5. **UI/UX Mockups**:
   - Sketch voting interface inspired by pol.is
   - Add our enhancements (evidence, threads, pro/con)
   - Mobile-first design considerations

### 0.5 Tools & Setup

**Clone and explore**:
```bash
git clone https://github.com/compdemocracy/polis.git
cd polis
# Review key directories
```

**Focus areas** (priority order):
1. `/math` - 🔴 Critical - clustering algorithms
2. `/server` - 🔴 Critical - data models and API
3. `/client-participation` - 🟡 Important - UI/UX patterns
4. `/client-report` - 🟡 Important - visualization approach
5. `/docs` - 🟢 Helpful - architecture decisions

**Time allocation**:
- Days 1-2: Math/clustering deep dive
- Days 3-4: Data models and API design
- Day 5: UI/UX review
- Days 6-7: Documentation and plan refinement

### 0.6 Replit Environment Setup

**Critical**: Address Replit-specific deployment considerations.

**Replit Secrets Required**:

Existing (already configured):
- `DATABASE_URL` - PostgreSQL connection
- `REDIS_URL` - Redis cache
- `SECRET_KEY` - Flask session secret
- `EMAIL_USER`, `EMAIL_PASS` - Email notifications
- `LOOPS_API_KEY` - Email service
- `WEBHOOK_SECRET` - Webhook validation

New (to add):
- `ENCRYPTION_KEY` - Fernet key for API key encryption (Phase 4)
```python
from cryptography.fernet import Fernet
ENCRYPTION_KEY = Fernet.generate_key()  # Store in Replit secrets
```

**Replit Object Storage Integration**:

Evidence attachments → use Replit object storage:
```python
# Update Evidence model
class Evidence(db.Model):
    # ... existing fields ...
    storage_key = db.Column(db.String(500))  # Replit object storage key
    storage_url = db.Column(db.String(1000))  # Public URL
```

**Background Task Strategy** (Replit doesn't support Celery/RQ well):

Use APScheduler instead of task queues:
```python
# app/__init__.py
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()

@scheduler.scheduled_job('interval', minutes=10)
def refresh_clustering():
    """Recalculate clustering for active discussions"""
    from app.models import Discussion
    from app.lib.consensus_engine import cluster_users_by_votes
    
    discussions_needing_refresh = Discussion.query.filter(
        Discussion.has_native_statements == True,
        Discussion.participant_count >= 20
    ).all()
    
    for discussion in discussions_needing_refresh:
        try:
            if should_recalculate(discussion.id):
                cluster_users_by_votes(discussion.id)
        except Exception as e:
            logger.error(f"Clustering failed for {discussion.id}: {e}")

# Start scheduler
scheduler.start()
```

Add to `requirements.txt`:
```
APScheduler==3.10.4
```

**AGPL-3.0 Compliance Checklist** (if adapting pol.is code):

1. **Attribution in UI** - Add to footer:
```html
<footer>
  Consensus clustering powered by algorithms adapted from
  <a href="https://github.com/compdemocracy/polis">pol.is</a> (AGPL-3.0)
</footer>
```

2. **Copyright notices** - Add to clustering files:
```python
# app/lib/consensus_engine.py
"""
Consensus clustering engine for Society Speaks.

Clustering algorithms adapted from pol.is:
https://github.com/compdemocracy/polis
Copyright (c) 2012-present, The Computational Democracy Project

Licensed under AGPL-3.0
"""
```

3. **Source code availability** - Ensure GitHub repo stays public
4. **Modifications documented** - Track changes from original pol.is code

## Phase 1: Core Statement System (Weeks 2-4)

**Note**: Renamed from "Argument System" to "Statement System" to align with pol.is terminology and avoid confusion with threaded arguments (which come in Phase 2)

### 1.1 Database Schema Design

**Key Insight**: Mirror pol.is architecture (statements that users vote on) rather than a generic "argument" model. This makes consensus clustering natural and aligns with user expectations.

Create new models in `app/models.py`:

**Statement Model** (core claim/proposition)
```python
class Statement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)  # Max 500 chars
    statement_type = db.Column(db.Enum('claim', 'question', name='statement_types'), default='claim')
    parent_statement_id = db.Column(db.Integer, db.ForeignKey('statement.id'), nullable=True)  # For threading
    vote_count_agree = db.Column(db.Integer, default=0)
    vote_count_disagree = db.Column(db.Integer, default=0)
    vote_count_unsure = db.Column(db.Integer, default=0)
    is_deleted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

**StatementVote Model** (user positions on statements - THE CORE FOR CLUSTERING)
```python
class StatementVote(db.Model):
    __table_args__ = (db.UniqueConstraint('statement_id', 'user_id'),)
    id = db.Column(db.Integer, primary_key=True)
    statement_id = db.Column(db.Integer, db.ForeignKey('statement.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    vote_type = db.Column(db.Enum('agree', 'disagree', 'unsure', name='vote_types'), nullable=False)
    confidence = db.Column(db.Integer)  # Optional 1-5 scale
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

**Response Model** (elaborations on why user voted a certain way)
```python
class Response(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    statement_id = db.Column(db.Integer, db.ForeignKey('statement.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    position = db.Column(db.Enum('pro', 'con', 'neutral', name='positions'))
    content = db.Column(db.Text)  # Optional elaboration
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
```

**Evidence Model** (supporting evidence for responses)
```python
class Evidence(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    response_id = db.Column(db.Integer, db.ForeignKey('response.id'), nullable=False)
    source_title = db.Column(db.String(500))
    source_url = db.Column(db.String(1000))
    citation = db.Column(db.Text)
    added_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
```

**UserAPIKey Model** (for Phase 4)
```python
class UserAPIKey(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    provider = db.Column(db.Enum('openai', 'anthropic', name='llm_providers'), nullable=False)
    encrypted_api_key = db.Column(db.Text, nullable=False)  # Fernet encrypted
    is_active = db.Column(db.Boolean, default=True)
    last_validated = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
```

### 1.2 Migration Scripts

**Cleaner approach**: Add boolean flag instead of enum to Discussion model

Create Alembic migration:
```python
# Add to existing Discussion model
has_native_statements = db.Column(db.Boolean, default=False)
# Keep embed_code nullable for backwards compatibility
# When has_native_statements=True, embed_code should be None
# When has_native_statements=False, embed_code contains pol.is embed
```

Migration strategy:
- All existing discussions: `has_native_statements=False` (keep pol.is embeds)
- New discussions: Let creator choose mode
- No automatic conversion - existing pol.is data stays on pol.is servers

### 1.3 Core Routes

Create `app/discussions/statements.py`:

- `POST /discussions/<id>/statements` - create statement
- `GET /discussions/<id>/statements` - list statements (paginated, prioritized)
- `POST /statements/<id>/vote` - vote on statement (agree/disagree/unsure)
- `GET /statements/<id>/votes` - get vote breakdown
- `PUT /statements/<id>` - edit own statement (within 10 min window)
- `DELETE /statements/<id>` - soft delete own statement (audit logged)
- `POST /statements/<id>/flag` - flag for moderation

Create `app/discussions/responses.py`:

- `POST /responses` - create response (with statement_id, optional parent_response_id, position)
- `GET /responses/<id>` - get response details
- `PUT /responses/<id>` - edit own response (within 10 min window)
- `DELETE /responses/<id>` - soft delete own response

### 1.4 Basic Statement UI & UX Flow

**Participant Journey** (keep it simple):

1. **Progressive Disclosure**: Show 1-3 statements at a time
   - Prioritize statements with fewest votes
   - Shuffle to avoid order bias
   - Big touch targets for mobile: Agree / Disagree / Skip buttons

2. **Duplicate Detection**: When posting a new statement
   - "Looks similar to: [existing statement] - upvote instead?"
   - Simple string similarity for v1 (defer embeddings)

3. **Edit Window**: 10 minutes after posting
   - Then lock with "edited" badge
   - Immutable history for integrity

Update `app/templates/discussions/view_discussion.html`:

- Conditional rendering: if `discussion.has_native_statements` show native UI, else show embed
- Create separate templates for clarity:
  - `app/templates/discussions/view_native.html` - native statement UI
  - `app/templates/discussions/view_polis.html` - pol.is embed
- Statement submission form (textarea, 500 char limit, type selector)
- Mobile-first voting interface with immediate feedback

### 1.5 Statement Ranking & Sorting

Implement **Wilson Score** for statement ranking:

```python
def wilson_score(agree, disagree, confidence=0.95):
    """
    Lower bound of Wilson score confidence interval for Bernoulli parameter
    Better than simple upvote/downvote ratio for sparse data
    """
    from math import sqrt
    from scipy import stats
    
    n = agree + disagree
    if n == 0:
        return 0
    
    z = stats.norm.ppf(1 - (1 - confidence) / 2)
    phat = agree / n
    
    return (phat + z*z/(2*n) - z * sqrt((phat*(1-phat)+z*z/(4*n))/n))/(1+z*z/n)
```

**Sorting Options**:
- **Best**: Wilson score (default)
- **Controversial**: High controversy score = `1 - |agree_rate - 0.5| * 2`
- **Recent**: Newest first
- **Most Voted**: Total votes descending

## Phase 2: Rich Debate Features (Weeks 4-6)

### 2.1 Pro/Con Argument Trees

Implement hierarchical argument structure:

- Update Argument model with `position` field (pro/con/neutral)
- UI for replying to arguments with position selection
- Tree visualization showing argument hierarchy
- Collapsible argument threads

### 2.2 Evidence Linking System

Create evidence management:

- Evidence upload form on arguments
- Citation formatting (APA/MLA style)
- URL validation and preview
- Evidence quality indicators (verified, disputed, pending)

### 2.3 Threaded Discussions

Implement Reddit-style threading:

- Nested comment display (up to 5 levels deep)
- "Show more replies" pagination
- Sort options: newest, most voted, most controversial
- Highlight new arguments since last visit

### 2.4 Argument Quality Features

Add quality indicators:

- Vote score calculation (weighted by confidence)
- "Best arguments" algorithm (combines votes, evidence, engagement)
- Flag system for low-quality/off-topic arguments
- Moderation queue for discussion creators

### 2.5 Enhanced Forms & Validation

Update `app/discussions/forms.py`:

- `ArgumentForm` with rich text validation
- `EvidenceForm` with URL validation
- Character limits and content policies
- Anti-spam measures

## Phase 3: Consensus Clustering (Weeks 7-10)

### 3.1 Vote Pattern Analysis

Create `app/lib/consensus_engine.py`:

- Generate user-argument vote matrix
- Calculate user similarity based on voting patterns
- Identify agreement/disagreement patterns
- Find "bridge" arguments (high cross-cluster agreement)

### 3.2 Vote-Based User Clustering (The pol.is Core)

**Critical**: Cluster USERS by voting patterns, NOT text. This is what makes pol.is valuable.

Implement simple, proven clustering:

```python
def cluster_users_by_votes(discussion_id):
    """
    Group users based on their voting patterns (the pol.is approach)
    """
    # 1. Build user-statement vote matrix (rows=users, cols=statements)
    vote_matrix = build_vote_matrix(discussion_id)  
    # agree=1, disagree=-1, unsure=0, no-vote=NaN
    
    # 2. Start simple: Agglomerative clustering or k-means on PCA
    from sklearn.decomposition import PCA
    from sklearn.cluster import AgglomerativeClustering
    
    pca = PCA(n_components=min(10, n_statements))
    reduced = pca.fit_transform(vote_matrix)
    
    # Try k in range 2-5, pick best silhouette score
    best_k, best_clustering = optimize_k(reduced)
    
    clustering = AgglomerativeClustering(
        n_clusters=best_k,
        metric='cosine',
        linkage='average'
    )
    user_clusters = clustering.fit_predict(reduced)
    
    # 3. Find consensus statements (≥70% overall, ≥60% in each cluster)
    consensus = find_consensus_statements(vote_matrix, user_clusters)
    
    # 4. Find bridge statements (high mean agreement, low variance across clusters)
    bridges = find_bridge_statements(vote_matrix, user_clusters)
    
    # 5. Find divisive statements (cluster disagreement, ~50/50 splits)
    divisive = find_divisive_statements(vote_matrix, user_clusters)
    
    return {
        'user_clusters': user_clusters,
        'consensus': consensus,  # ≥70% overall AND ≥60% each cluster
        'bridges': bridges,      # High agreement, low variance
        'divisive': divisive,    # Controversy score high
        'silhouette': compute_silhouette_score(reduced, user_clusters)
    }
```

**Explicit Definitions**:
- **Consensus statement**: ≥70% agree overall AND ≥60% agree in EACH user cluster
- **Bridge statement**: High mean agreement (≥65%) with low variance across clusters (<0.15)
- **Divisive statement**: Controversy score = 1 - |agree_rate - 0.5| * 2 (high = controversial)

**Dependencies to add** (minimal, start here):
```
scikit-learn==1.4.0
```

**Defer until needed** (>500 users/discussion or poor cluster quality):
- UMAP for better dimensionality reduction
- HDBSCAN for automatic cluster detection
- Plotly for server-side rendering (use Chart.js frontend first)

### 3.3 Cluster Visualization

Create interactive visualizations:

- 2D scatter plot of argument clusters
- User opinion map showing where users fall
- Consensus statements (arguments with >70% agreement)
- Division points (arguments with ~50/50 split)
- Bridging opportunities (arguments that unite clusters)

### 3.4 Consensus Dashboard

Create `app/templates/discussions/consensus.html`:

- Cluster visualization canvas
- Summary statistics (# clusters, agreement levels)
- Top consensus points
- Key division points
- Downloadable reports (CSV, JSON)

### 3.5 Background Processing

Use simple task queue for clustering:

- Create `app/lib/clustering_tasks.py`
- Trigger clustering after discussion reaches threshold (e.g., 50 arguments)
- Store clustering results in new `ConsensusAnalysis` model
- Cache results for performance

## Phase 4: Optional LLM Features (Weeks 11-14)

### 4.1 User API Key Management

Create `app/settings/api_keys.py`:

- Secure storage (encrypt with Fernet)
- API key validation endpoint
- Usage tracking (prevent abuse)
- Provider selection (OpenAI, Anthropic, local models)

### 4.2 LLM-Powered Summarization

When user has API key:

- Discussion summaries (key themes, main points)
- Argument quality scoring
- Automatic tagging and categorization
- Suggested connections between arguments

### 4.3 Semantic Clustering Enhancement

With LLM embeddings:

- Use OpenAI/Anthropic embeddings instead of TF-IDF
- Richer semantic similarity detection
- Better cluster labeling (LLM generates cluster names)
- Improved bridge detection

### 4.4 Moderation Assistance

Optional AI moderation:

- Toxicity detection
- Off-topic detection
- Duplicate argument detection
- Suggested argument improvements

### 4.5 Settings UI

Update `app/templates/settings/preferences.html`:

- API key management section
- Provider selection
- Feature toggles (which LLM features to enable)
- Usage statistics
- Cost estimation

## Phase 5: Migration & Polish (Weeks 15-16)

### 5.1 Migration Tools

Create admin tools:

- Bulk convert discussions from 'polis_embed' to 'native_arguments'
- Export pol.is data (if available) to native format
- Admin panel to manage discussion modes

### 5.2 Performance Optimization

- Index optimization on argument and vote tables
- Caching strategy for clustering results
- Pagination optimization
- Lazy loading for large argument threads

### 5.3 Mobile Responsive Design

Ensure all new UI works on mobile:

- Touch-friendly voting buttons
- Collapsible argument trees
- Responsive visualizations
- Mobile-optimized forms

### 5.4 Documentation Updates

Update docs:

- README.md with new features
- User guide for creating native discussions
- API documentation for developers
- Deployment guide with new dependencies

## Key Files to Create/Modify

### New Files

- `app/discussions/arguments.py` - argument routes
- `app/lib/consensus_engine.py` - clustering logic
- `app/lib/clustering_tasks.py` - background tasks
- `app/settings/api_keys.py` - API key management
- `app/templates/discussions/arguments_view.html` - native UI
- `app/templates/discussions/consensus.html` - clustering dashboard
- `migrations/versions/XXX_add_argument_system.py` - schema migration

### Modified Files

- `app/models.py` - add new models
- `app/discussions/routes.py` - integrate argument routes
- `app/discussions/forms.py` - add argument forms
- `app/templates/discussions/view_discussion.html` - conditional rendering
- `config.py` - add clustering config
- `requirements.txt` - add ML dependencies

## Security Considerations

1. **API Key Storage**: Use Fernet symmetric encryption, never log keys
2. **Rate Limiting**: Apply strict limits on argument creation, voting, API usage
3. **Input Validation**: Sanitize all user content, prevent XSS/injection
4. **Vote Manipulation**: Detect suspicious voting patterns, implement cooldowns
5. **Moderation**: Flag system, report abuse, moderator tools

## Testing Strategy

1. **Unit Tests**: Models, vote calculations, clustering algorithms
2. **Integration Tests**: API endpoints, argument flows, voting
3. **Performance Tests**: Large discussions (1000+ arguments), clustering speed
4. **User Testing**: Pilot with small group, gather feedback

## Rollout Plan

1. **Alpha**: Enable native mode for new discussions only
2. **Beta**: Invite select users to try and provide feedback
3. **Migration**: Gradually convert existing discussions
4. **Full Launch**: Make native mode default, keep pol.is as fallback

## Success Metrics

- User engagement (arguments per discussion vs pol.is comments)
- Clustering quality (silhouette scores, user feedback)
- Performance (page load times, clustering time)
- LLM adoption rate (% users adding API keys)
- Discussion depth (argument tree depth, evidence citations)

### To-dos

- [ ] Design and create database schema (Argument, ArgumentVote, ArgumentRelationship, Evidence, UserAPIKey models)
- [ ] Create Alembic migration script with new tables and discussion_mode field
- [ ] Build core argument API routes (create, list, vote, edit, delete)
- [ ] Create basic argument submission and voting UI
- [ ] Implement pro/con argument tree structure and visualization
- [ ] Build evidence linking system with citation formatting
- [ ] Implement nested threading and sorting options
- [ ] Build non-LLM consensus clustering engine with sklearn/UMAP/HDBSCAN
- [ ] Create interactive cluster visualizations with Plotly/D3.js
- [ ] Build consensus dashboard showing clusters, agreement, and divisions
- [ ] Implement secure user API key management with encryption
- [ ] Add optional LLM features (summarization, semantic clustering, moderation)
- [ ] Create tools to migrate existing pol.is discussions to native format
- [ ] Performance optimization, mobile responsiveness, and documentation