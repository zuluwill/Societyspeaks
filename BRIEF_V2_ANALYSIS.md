# Brief Model v2 - Codebase Analysis & Implementation Plan

## Executive Summary

ChatGPT's spec proposes a **multi-tenant briefing system** where users/orgs can create custom briefs with their own sources, approval workflows, and distribution. This is a significant architectural shift from the current **single daily brief** model.

**Key Finding**: The current codebase has ~70% of the infrastructure needed. The main gap is the **multi-tenancy layer** - everything else (email, scheduling, ingestion, admin UI) can be extended.

---

## Current Architecture vs. Proposed

### Current State (Single Daily Brief)

- **DailyBrief**: One brief per day (date-based, unique)
- **BriefItem**: Items within the daily brief (references TrendingTopic)
- **DailyBriefSubscriber**: Email recipients (tier-based: trial/individual/team)
- **BriefTeam**: Team subscriptions (multi-seat)
- **NewsSource**: Curated RSS/API sources (Guardian, RSS feeds)
- **TrendingTopic**: Auto-clustered news topics
- **NewsArticle**: Individual articles from sources

### Proposed State (Multi-Tenant Briefs)

- **Briefing**: Per-user/org brief configuration (many briefs, not date-based)
- **BriefRun**: Scheduled execution of a briefing (like DailyBrief but per-briefing)
- **BriefTemplate**: Predefined themed briefs (Politics, Tech, etc.)
- **InputSource**: User-defined sources (RSS, URLs, uploads, X/Substack)
- **BriefRecipient**: Distribution lists (per-briefing, not global)
- **SendingDomain**: Custom email domains for orgs (Resend)

---

## Existing Components (Reusable)

### ✅ Models That Exist

1. **DailyBrief** → Can be generalized to **BriefRun** (execution instance)
2. **BriefItem** → Can be reused (items within a run)
3. **DailyBriefSubscriber** → Pattern reusable for **BriefRecipient**
4. **BriefTeam** → Pattern reusable for org management
5. **NewsSource** → Can be extended to **InputSource** (add upload types)
6. **User** → Already has IndividualProfile/CompanyProfile
7. **EmailEvent** → Already tracks opens/clicks/bounces

### ✅ Services That Exist

1. **ResendClient** (`app/brief/email_client.py`)

   - ✅ Rate limiting
   - ✅ Retry logic
   - ✅ HTML rendering
   - ⚠️ **Missing**: Custom domain support (needs Resend domain API)

2. **BriefGenerator** (`app/brief/generator.py`)

   - ✅ LLM-powered content generation
   - ✅ Coverage analysis
   - ✅ Sensationalism scoring
   - ⚠️ **Needs**: Generalization to work with custom sources (not just TrendingTopic)

3. **NewsFetcher** (`app/trending/news_fetcher.py`)

   - ✅ RSS ingestion
   - ✅ Guardian API
   - ⚠️ **Missing**: PDF/DOCX extraction, webpage scraping, X/Substack

4. **Scheduler** (`app/scheduler.py`)

   - ✅ APScheduler integration
   - ✅ Cron jobs
   - ✅ Background tasks
   - ✅ Can schedule per-briefing jobs

5. **Admin Dashboards** (`app/brief/admin.py`, `app/admin/routes.py`)
   - ✅ Brief preview/edit UI
   - ✅ Subscriber management
   - ✅ Table components
   - ✅ Can be extended for multi-brief management

### ✅ Infrastructure That Exists

1. **File Upload** (`app/profiles/routes.py`, `app/discussions/statements.py`)

   - ✅ Replit Object Storage integration
   - ✅ File validation (size, type)
   - ⚠️ **Missing**: PDF/DOCX text extraction (need libraries: `pypdf`, `python-docx`)

2. **Stripe Integration**

   - ✅ Already in DailyBriefSubscriber/BriefTeam
   - ✅ Subscription management
   - ✅ Can be reused for billing gates

3. **Magic Link Auth**
   - ✅ Pattern exists in DailyBriefSubscriber
   - ✅ Can be reused for BriefRecipient

---

## What Needs to Be Built

### 1. New Models (Database Schema)

#### **Briefing** (Core Configuration)

```python
# NEW MODEL - Multi-tenant brief configuration
class Briefing(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    # Ownership
    owner_type = db.Column(db.String(20))  # 'user' | 'org'
    owner_id = db.Column(db.Integer)  # User.id or CompanyProfile.id

    # Configuration
    name = db.Column(db.String(200))
    description = db.Column(db.Text)
    theme_template_id = db.Column(db.Integer, db.ForeignKey('brief_template.id'), nullable=True)

    # Schedule
    cadence = db.Column(db.String(20))  # 'daily' | 'weekly'
    timezone = db.Column(db.String(50))
    preferred_send_hour = db.Column(db.Integer)  # 6, 8, 18

    # Workflow
    mode = db.Column(db.String(20))  # 'auto_send' | 'approval_required'

    # Visibility
    visibility = db.Column(db.String(20))  # 'private' | 'org_only' | 'public'

    # Status
    status = db.Column(db.String(20), default='active')  # 'active' | 'paused'

    # Email config (for orgs)
    from_name = db.Column(db.String(200))
    from_email = db.Column(db.String(255))  # Must be from verified domain
    sending_domain_id = db.Column(db.Integer, db.ForeignKey('sending_domain.id'), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    sources = db.relationship('BriefingSource', backref='briefing', cascade='all, delete-orphan')
    runs = db.relationship('BriefRun', backref='briefing', lazy='dynamic', order_by='BriefRun.scheduled_at.desc()')
    recipients = db.relationship('BriefRecipient', backref='briefing', cascade='all, delete-orphan')
```

**Migration Strategy**:

- Keep `DailyBrief` for backward compatibility (existing public brief)
- Add `Briefing` as new model
- Gradually migrate DailyBrief logic to use Briefing internally

#### **BriefRun** (Execution Instance)

```python
# NEW MODEL - Each scheduled execution of a briefing
class BriefRun(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    briefing_id = db.Column(db.Integer, db.ForeignKey('briefing.id'), nullable=False)

    # Status workflow
    status = db.Column(db.String(30))  # 'generated_draft' | 'awaiting_approval' | 'approved' | 'sent' | 'failed'

    # Content (markdown + HTML)
    draft_markdown = db.Column(db.Text)
    draft_html = db.Column(db.Text)
    approved_markdown = db.Column(db.Text, nullable=True)
    approved_html = db.Column(db.Text, nullable=True)

    # Approval tracking
    approved_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)

    # Timing
    scheduled_at = db.Column(db.DateTime)  # When it should run
    generated_at = db.Column(db.DateTime)
    sent_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    items = db.relationship('BriefRunItem', backref='run', cascade='all, delete-orphan')
    approved_by = db.relationship('User', backref='approved_brief_runs')
```

**Reuse Strategy**:

- `BriefRun` is similar to `DailyBrief` (date-based → scheduled-based)
- `BriefRunItem` can reuse `BriefItem` structure (or extend it)

#### **BriefTemplate** (Predefined Themes)

```python
# NEW MODEL - Off-the-shelf brief templates
class BriefTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))  # 'Politics', 'Technology', 'Climate', etc.
    description = db.Column(db.Text)

    # Default config (JSON)
    default_sources = db.Column(db.JSON)  # List of NewsSource IDs or RSS URLs
    default_filters = db.Column(db.JSON)  # Keywords, topics
    default_cadence = db.Column(db.String(20), default='daily')
    default_tone = db.Column(db.String(50), default='calm_neutral')

    # Customization
    allow_customization = db.Column(db.Boolean, default=True)  # Can user modify?

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
```

**Seeding Strategy**:

- Create 8-10 templates (Politics, Tech, Climate, Health, Business, Culture, AI, Sports)
- Seed via migration or CLI command

#### **InputSource** (Generalized Source)

```python
# NEW MODEL - User-defined sources (extends NewsSource concept)
class InputSource(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    # Ownership
    owner_type = db.Column(db.String(20))  # 'user' | 'org' | 'system'
    owner_id = db.Column(db.Integer)  # User.id or CompanyProfile.id (nullable for system)

    # Source config
    name = db.Column(db.String(200))
    type = db.Column(db.String(50))  # 'rss' | 'url_list' | 'webpage' | 'upload' | 'substack' | 'x'
    config_json = db.Column(db.JSON)  # Type-specific config

    # For uploads
    storage_key = db.Column(db.String(500))  # Replit Object Storage key
    storage_url = db.Column(db.String(500))
    extracted_text = db.Column(db.Text)  # Extracted text from PDF/DOCX

    # Status
    enabled = db.Column(db.Boolean, default=True)
    last_fetched_at = db.Column(db.DateTime)
    fetch_error_count = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    ingested_items = db.relationship('IngestedItem', backref='source', lazy='dynamic')
```

**Migration Strategy**:

- `NewsSource` becomes system-level `InputSource` (owner_type='system')
- Users can create their own `InputSource` instances
- Reuse `NewsFetcher` logic for RSS/webpage types

#### **IngestedItem** (Content from Sources)

```python
# NEW MODEL - Individual items ingested from sources
class IngestedItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey('input_source.id'), nullable=False)

    # Content
    title = db.Column(db.String(500))
    url = db.Column(db.String(1000), nullable=True)  # Nullable for uploads
    source_name = db.Column(db.String(200))  # Denormalized for performance

    # Timing
    published_at = db.Column(db.DateTime, nullable=True)  # From source
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Content
    content_text = db.Column(db.Text)  # Extracted text
    content_hash = db.Column(db.String(64))  # SHA-256 for deduplication
    metadata_json = db.Column(db.JSON)  # Author, tags, etc.

    # For uploads
    storage_key = db.Column(db.String(500), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('source_id', 'content_hash', name='uq_source_content_hash'),
        db.Index('idx_ingested_source_fetched', 'source_id', 'fetched_at'),
    )
```

**Reuse Strategy**:

- Similar to `NewsArticle` but more generic
- Can replace `NewsArticle` in future (or keep both for backward compat)

#### **BriefingSource** (Many-to-Many)

```python
# NEW MODEL - Links briefings to sources
class BriefingSource(db.Model):
    briefing_id = db.Column(db.Integer, db.ForeignKey('briefing.id'), primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey('input_source.id'), primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
```

#### **BriefRecipient** (Distribution Lists)

```python
# NEW MODEL - Per-briefing recipients
class BriefRecipient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    briefing_id = db.Column(db.Integer, db.ForeignKey('briefing.id'), nullable=False)

    email = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(200), nullable=True)

    status = db.Column(db.String(20), default='active')  # 'active' | 'unsubscribed'
    unsubscribed_at = db.Column(db.DateTime, nullable=True)

    # Magic link auth (reuse pattern)
    magic_token = db.Column(db.String(64), unique=True, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('briefing_id', 'email', name='uq_briefing_recipient'),
        db.Index('idx_brief_recipient_status', 'briefing_id', 'status'),
    )
```

**Reuse Strategy**:

- Pattern similar to `DailyBriefSubscriber` but per-briefing
- Reuse magic link logic

#### **SendingDomain** (Custom Email Domains)

```python
# NEW MODEL - Resend domain verification for orgs
class SendingDomain(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey('company_profile.id'), nullable=False)

    domain = db.Column(db.String(255), nullable=False)  # e.g., 'client.org'
    status = db.Column(db.String(30))  # 'pending_verification' | 'verified' | 'failed'

    # Resend API data
    resend_domain_id = db.Column(db.String(255), nullable=True)
    dns_records_required = db.Column(db.JSON)  # SPF, DKIM, etc.

    verified_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    org = db.relationship('CompanyProfile', backref='sending_domains')
```

**New Integration**:

- Need Resend Domain API integration
- DNS verification workflow

#### **BriefEdit** (Optional - Versioning)

```python
# NEW MODEL - Edit history for approval workflow
class BriefEdit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    brief_run_id = db.Column(db.Integer, db.ForeignKey('brief_run.id'), nullable=False)

    edited_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content_markdown = db.Column(db.Text)
    content_html = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    edited_by = db.relationship('User', backref='brief_edits')
```

---

### 2. Services to Extend/Build

#### **A. Source Ingestion Extensions**

**Current**: `NewsFetcher` handles RSS + Guardian API

**Needed**:

1. **PDF Extraction** (`app/briefing/ingestion/pdf_extractor.py`)

   ```python
   # Use: pypdf or pdfplumber
   def extract_text_from_pdf(storage_key: str) -> str:
       # Download from Replit Object Storage
       # Extract text
       # Return plain text
   ```

2. **DOCX Extraction** (`app/briefing/ingestion/docx_extractor.py`)

   ```python
   # Use: python-docx
   def extract_text_from_docx(storage_key: str) -> str:
       # Download from Replit Object Storage
       # Extract text
       # Return plain text
   ```

   **⚠️ Important: Async Processing**

   - PDF/DOCX extraction can take 1-5 seconds for large files
   - **Do NOT block upload request** - use background job queue
   - Upload endpoint: Save file → Create InputSource (status='extracting') → Queue job → Return immediately
   - Background job: Extract text → Update InputSource (status='ready', extracted_text=...)
   - Use APScheduler (already in codebase) or job queue for processing
   - Benefits: Fast response, retry on failure, progress tracking

3. **Webpage Scraper** (`app/briefing/ingestion/webpage_scraper.py`)

   ```python
   # Use: requests + BeautifulSoup or readability-lxml
   def scrape_webpage(url: str) -> dict:
       # Fetch HTML
       # Extract main content (readability)
       # Return: {'title': ..., 'content': ..., 'published_at': ...}
   ```

4. **X/Twitter Connector** (Optional - MVP skip)

   - Requires official API (expensive)
   - Fallback: URL ingestion (paste tweet URLs)

5. **Substack Connector** (Optional - MVP skip)
   - Fallback: RSS feed if available, or URL ingestion

**Implementation**:

- Create `app/briefing/ingestion/` module
- Extend `NewsFetcher` or create new `SourceIngester` class
- Add to requirements.txt: `pypdf`, `python-docx`, `beautifulsoup4`, `readability-lxml`
- **Async extraction pattern**:

  ```python
  # Upload endpoint (fast response)
  @briefing_bp.route('/sources/upload', methods=['POST'])
  def upload_source():
      # 1. Save file to Replit Object Storage (fast)
      # 2. Create InputSource with status='extracting'
      # 3. Queue background extraction job
      # 4. Return immediately with status='processing'
      queue_extraction_job(source_id=input_source.id)
      return jsonify({'status': 'processing', 'source_id': input_source.id})

  # Background job (APScheduler or job queue)
  @scheduler.scheduled_job('interval', seconds=10)
  def process_extraction_queue():
      # Find InputSource with status='extracting'
      # Extract text (pypdf/python-docx)
      # Update InputSource: extracted_text, status='ready'
      # Handle errors: status='failed', error_message=...
  ```

#### **B. Brief Generator Generalization**

**Current**: `BriefGenerator` works with `TrendingTopic` (pre-clustered)

**Needed**:

- Generalize to work with `IngestedItem` list
- Support custom source selection (not just trending topics)
- Keep coverage analysis (if sources have political_leaning)

**Changes**:

```python
# app/briefing/generator.py
class BriefingGenerator:
    def generate_brief_run(
        self,
        briefing: Briefing,
        ingested_items: List[IngestedItem],  # Instead of TrendingTopic
        scheduled_at: datetime
    ) -> BriefRun:
        # Similar logic to BriefGenerator but:
        # - Work with IngestedItem instead of TrendingTopic
        # - Use briefing config (tone, filters)
        # - Create BriefRun instead of DailyBrief
```

**Reuse**:

- LLM prompts can be reused (just change input)
- Coverage analysis can be reused (if sources have leaning data)

#### **C. Approval Workflow**

**Current**: Admin can edit DailyBrief before publish (manual)

**Needed**:

- Draft generation → notification → editor UI → approve/send

**New Components**:

1. **Draft Notification** (`app/briefing/notifications.py`)

   - Email editor when draft ready
   - In-app notification

2. **Draft Editor UI** (`app/briefing/admin/draft_editor.py`)

   - Markdown editor (reuse existing admin components)
   - Preview (email + web)
   - Approve/send button
   - Schedule send time

3. **Approval Queue** (`app/briefing/admin/approval_queue.py`)
   - List of drafts awaiting approval
   - Filter by briefing, status

**Reuse**:

- Admin UI patterns from `app/brief/admin.py`
- Email templates from `app/brief/email_client.py`

#### **D. Resend Domain Management**

**Current**: Single sending domain (hardcoded in `ResendClient`)

**Needed**:

- Multi-domain support
- DNS verification workflow

**New Components**:

1. **Domain Verification** (`app/briefing/domains/verifier.py`)

   ```python
   def verify_domain(domain: str) -> dict:
       # Call Resend API to add domain
       # Get DNS records required
       # Return: {'status': 'pending', 'dns_records': [...]}

   def check_verification_status(domain_id: str) -> str:
       # Poll Resend API
       # Return: 'verified' | 'pending' | 'failed'
   ```

2. **Domain Settings UI** (`app/briefing/admin/domains.py`)
   - Add domain form
   - Show DNS records
   - Refresh verification status

**New Integration**:

- Resend Domain API (documentation: https://resend.com/docs/api-reference/domains)

---

### 3. UI/UX Extensions

#### **A. Briefing Management**

**Reuse**:

- Admin table components from `app/admin/routes.py`
- Brief preview/edit from `app/brief/admin.py`

**New Pages**:

1. **Briefing List** (`/briefings`)

   - Table of user's briefings
   - Filter by status, visibility
   - Create new briefing button

2. **Briefing Detail** (`/briefings/<id>`)

   - Sources list (add/remove)
   - Schedule config
   - Recipients list
   - Run history
   - Pause/resume

3. **Briefing Create** (`/briefings/create`)

   - Choose template OR custom
   - Source selection (RSS, URLs, uploads)
   - Schedule setup
   - Approval mode toggle

4. **Draft Editor** (`/briefings/<id>/runs/<run_id>/edit`)
   - Markdown editor
   - Preview tabs (email/web)
   - Approve/send button

#### **B. Source Management**

**Reuse**:

- Source list pattern from `app/trending/routes.py` (manage_sources)

**New Pages**:

1. **My Sources** (`/sources`)

   - List user's InputSource instances
   - Add RSS, URL list, upload
   - Test fetch button

2. **Upload Source** (`/sources/upload`)
   - File upload (PDF/DOCX)
   - Extract text preview
   - Save as InputSource

#### **C. Template Marketplace** (Nice-to-Have)

**New Page**:

- `/briefings/templates`
- Browse predefined templates
- Preview sources/filters
- "Use Template" button

---

## Implementation Phases

### Phase 1: Core Models & Multi-Tenancy (Week 1-2)

**Goal**: Database schema + basic CRUD

1. Create migrations for new models:

   - `Briefing`, `BriefRun`, `BriefTemplate`, `InputSource`, `IngestedItem`
   - `BriefingSource`, `BriefRecipient`, `SendingDomain`, `BriefEdit`

2. Seed `BriefTemplate` table (8-10 templates)

3. Basic CRUD routes:

   - `POST /briefings` (create)
   - `GET /briefings` (list)
   - `GET /briefings/<id>` (detail)
   - `PATCH /briefings/<id>` (update)
   - `DELETE /briefings/<id>` (delete)

4. Build `InputSource` alongside `NewsSource` (coexistence):
   - Create `InputSource` model (new table)
   - Keep `NewsSource` unchanged (used by DailyBrief)
   - Allow users to create `InputSource` instances
   - **Note**: Migration of `NewsSource` → `InputSource` deferred to Phase 3+ (after system stable)

**Deliverable**: Users can create briefings, add sources, configure schedule

---

### Phase 2: Ingestion & Generation (Week 3-4)

**Goal**: Content ingestion + brief generation

1. Build ingestion extensions:

   - PDF/DOCX extractors (**with async queue processing**)
   - Webpage scraper
   - Extend `NewsFetcher` → `SourceIngester`
   - **Async extraction pattern**: Upload endpoint queues background job, returns immediately
     - InputSource status: 'extracting' → 'ready' (or 'failed')
     - Use APScheduler background job to process extraction queue
     - Prevents blocking upload requests (1-5 second extraction time)

2. Generalize `BriefGenerator` → `BriefingGenerator`:

   - Work with `IngestedItem` instead of `TrendingTopic`
   - Support custom source selection
   - Create `BriefRun` instead of `DailyBrief`

3. Scheduled job:
   - Per-briefing cron (daily/weekly)
   - Fetch from sources → create `IngestedItem`
   - Generate `BriefRun` (draft or auto-send)

**Deliverable**: Briefings generate content automatically on schedule

---

### Phase 3: Approval Workflow (Week 5)

**Goal**: Human-in-the-loop editing

1. Draft notification system:

   - Email editor when draft ready
   - In-app notification

2. Draft editor UI:

   - Markdown editor
   - Preview (email/web)
   - Approve/send button

3. Approval queue:
   - List drafts awaiting approval
   - Filter/search

**Deliverable**: Users can review/edit before sending

---

### Phase 4: Email & Distribution (Week 6)

**Goal**: Multi-recipient sending + custom domains

1. Recipient management:

   - Add/remove emails per briefing
   - Unsubscribe handling
   - Magic link auth (reuse pattern)

2. Extend `ResendClient`:

   - Support custom `from_email` per briefing
   - Domain verification workflow
   - Multi-domain sending

3. Sending logic:
   - Per-briefing recipient lists
   - Timezone-aware delivery (reuse existing logic)
   - Bounce handling

**Deliverable**: Briefings send to custom recipient lists

---

### Phase 5: Visibility & Publishing (Week 7)

**Goal**: Public/private briefs

1. Visibility modes:

   - `private`: owner only
   - `org_only`: org members
   - `public`: web archive

2. Public archive pages:

   - `/briefings/public/<briefing_id>`
   - `/briefings/public/<briefing_id>/runs/<run_id>`
   - Simple landing page + archive list

3. Moderation:
   - Basic reporting mechanism
   - Admin unpublish action

**Deliverable**: Users can publish briefs publicly

---

### Phase 6: Billing & Limits (Week 8)

**Goal**: Plan gating

1. Extend Stripe integration:

   - Plan metadata (max briefings, sources, etc.)
   - Enforce limits in API + workers

2. Billing gates:

   - Personal: templates, >N sources, daily cadence, multiple briefs
   - Org: briefings, sources, seats, custom domain

3. Upgrade prompts:
   - Show limits in UI
   - "Upgrade to unlock" CTAs

**Deliverable**: Paid features properly gated

---

## Open Questions / Decisions Needed

### 1. **DailyBrief vs. Briefing Coexistence**

- **Option A**: Keep `DailyBrief` as public brief, add `Briefing` for custom
- **Option B**: Migrate `DailyBrief` to use `Briefing` internally (owner_type='system')
- **Recommendation**: Option A (backward compat), then Option B (gradual migration)

### 2. **TrendingTopic vs. IngestedItem**

- **Option A**: Keep both (TrendingTopic for public, IngestedItem for custom)
- **Option B**: Unify (IngestedItem replaces TrendingTopic)
- **Recommendation**: Option A (backward compat), then Option B (future)

### 3. **NewsSource vs. InputSource**

- **Option A**: Keep both (NewsSource for system, InputSource for users)
- **Option B**: Migrate NewsSource to InputSource (owner_type='system')
- **Recommendation**: **Phased approach** (safer, less risky)
  - **Phase 1-2**: Build `InputSource` alongside `NewsSource` (coexistence)
    - `NewsSource` → Used by existing DailyBrief (no changes)
    - `InputSource` → Used by new Briefing system
  - **Phase 3+**: After Briefing system is stable, migrate in separate migration
    - Migrate all `NewsSource` rows to `InputSource` with `owner_type='system'`
    - Update all references (NewsFetcher, etc.)
    - Deprecate `NewsSource` (or keep as alias for backward compat)
  - **Rationale**: Reduces risk, allows testing new model without breaking DailyBrief

### 4. **X/Substack in MVP**

- **Decision**: Skip (use URL ingestion fallback)
- **Rationale**: Official APIs expensive, ToS constraints

### 5. **Template Customization**

- **Decision**: Allow customization (user can modify sources/filters)
- **Rationale**: More flexible, better UX

### 6. **Approval Workflow Default**

- **Decision**: User chooses (auto_send vs. approval_required)
- **Rationale**: Flexibility for different use cases

---

## Minimal-Change Implementation Strategy

### Principle: Extend, Don't Replace

1. **Keep existing models** (`DailyBrief`, `BriefItem`, `NewsSource`) for backward compat
2. **Add new models** (`Briefing`, `BriefRun`, `InputSource`) alongside
3. **Reuse services** (email, scheduling, admin UI) with minimal changes
4. **Gradual migration** (users can opt into new system)
5. **Phased model migration**: Defer `NewsSource` → `InputSource` migration until after new system is stable
6. **Async processing**: Use background jobs for PDF/DOCX extraction (don't block upload requests)

### Code Organization

```
app/
├── brief/              # Existing (keep for DailyBrief)
│   ├── generator.py
│   ├── email_client.py
│   └── admin.py
├── briefing/           # NEW - Multi-tenant briefings
│   ├── models.py       # Briefing, BriefRun, etc.
│   ├── routes.py       # Public routes
│   ├── admin.py        # Admin routes
│   ├── generator.py    # Generalized BriefGenerator
│   ├── ingestion/      # NEW - Source ingestion
│   │   ├── pdf_extractor.py
│   │   ├── docx_extractor.py
│   │   └── webpage_scraper.py
│   ├── domains/        # NEW - Resend domain management
│   │   └── verifier.py
│   └── notifications.py # NEW - Draft notifications
├── trending/           # Existing (keep for public news)
│   └── news_fetcher.py
└── models.py           # Add new models here
```

---

## Acceptance Criteria (Revised for Codebase)

✅ **Individual paid user can:**

- Pick a predefined template OR custom configure
- Add sources (RSS, URLs, uploads)
- Receive a daily/weekly email brief
- Optionally review/edit before sending

✅ **Org can:**

- Set up sending domain via Resend verification
- Create a weekly brief with recipients
- Use approval workflow before send
- Keep briefs private or publish publicly

✅ **Upload ingestion works:**

- PDF + DOCX extraction (async background processing)
- Upload returns immediately with status='processing'
- Text extracted and stored (status updates to 'ready')
- Appears as selectable source once extraction complete

✅ **Visibility works:**

- `private`: owner only
- `org_only`: org members
- `public`: simple archive page

---

## Estimated Effort

- **Phase 1** (Models + CRUD): 2 weeks
- **Phase 2** (Ingestion + Generation): 2 weeks
- **Phase 3** (Approval): 1 week
- **Phase 4** (Email + Distribution): 1 week
- **Phase 5** (Visibility): 1 week
- **Phase 6** (Billing): 1 week

**Total**: ~8 weeks for full MVP

**MVP Scope** (reduce to 4-5 weeks):

- Skip X/Substack connectors (use URL fallback)
- Skip template marketplace UI (just seed DB)
- Skip advanced moderation (basic reporting only)
- Skip follower marketplace (future)

---

## Next Steps

1. **Review this analysis** with team
2. **Decide on coexistence strategy** (DailyBrief vs. Briefing)
3. **Prioritize phases** (MVP vs. full)
4. **Create migration files** for Phase 1
5. **Start with Phase 1** (models + basic CRUD)

---

## Notes

- ChatGPT's spec is solid but assumes greenfield. This analysis maps it to existing codebase.
- ~70% of infrastructure exists (email, scheduling, admin UI, Stripe)
- Main gap: multi-tenancy layer (Briefing model + per-briefing logic)
- Recommendation: Extend existing code, don't rewrite

### Key Refinements (Based on Code Review)

1. **NewsSource Migration**: Phased approach - build `InputSource` alongside `NewsSource` in Phase 1-2, migrate in Phase 3+ after system is stable. Reduces risk of breaking DailyBrief.

2. **PDF/DOCX Extraction**: Use async background jobs (APScheduler) to avoid blocking upload requests. Upload endpoint returns immediately with status='processing', background job extracts text and updates InputSource status to 'ready'. Better UX and error handling.

3. **Implementation Safety**: Keep existing models unchanged initially, add new models alongside. Gradual migration reduces risk and allows testing without breaking production.
