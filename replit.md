# Society Speaks Platform

## Overview

Society Speaks is an open-source public discussion platform designed to foster meaningful dialogue using Pol.is technology. It enables users to create and participate in structured discussions on critical social, political, and community topics. Built with Flask and PostgreSQL, the platform aims to facilitate nuanced debate, build consensus, and potentially inform policy. Key capabilities include user profiles, discussion management, geographic filtering, and analytics, with a recent focus on automatically surfacing trending news for nuanced public debate through a "News-to-Deliberation Compiler."

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### UI/UX Decisions
The platform utilizes a consistent UI with reusable components like `discussion_card`, toast notifications, empty state components, and loading spinners. It prioritizes mobile accessibility with 44x44px minimum touch targets and includes enhanced accessibility features like ARIA labels. Tailwind CSS is used for styling, ensuring a utility-first approach with custom typography plugins.

### Technical Implementations
The backend is built with Flask, adopting a modular, blueprint-based architecture. SQLAlchemy with Flask-SQLAlchemy manages database operations, and Flask-Login handles user authentication for both individual and company profiles. Redis is integrated for session management, caching (Flask-Caching), and performance optimization. The "News-to-Deliberation Compiler" is a core system that automatically identifies trending news topics, scores articles for sensationalism and civic value using LLMs, clusters them into discussions, and generates balanced seed statements. This system relies on background hourly jobs and features an admin interface for review and management.

### Feature Specifications
The platform supports a comprehensive discussion system with Pol.is integration, topic categorization, and geographic filtering. It includes a dedicated News feed page (`/discussions/news`) displaying discussions derived from trending topics with: topic-grouped horizontal scroll sections, source transparency (collapsible list of trusted news outlets), clear differentiation from community discussions, responsive mobile layout, and multiple view modes (by topic, latest, or filtered). When news-based discussions are published, source article attribution is preserved via the `DiscussionSourceArticle` join table, displaying the original article title, source name, country, and publication date on the discussion page. Analytics track profile views and discussion engagement. Security features include Flask-Talisman for CSP, Flask-Limiter for rate limiting, Flask-SeaSurf for CSRF protection, and Werkzeug for password hashing. File storage uses Replit Object Storage for user-uploaded images, with built-in cropping and compression.

### System Design Choices
PostgreSQL is the primary database, configured with connection pooling and health checks. A dual-profile system supports individual and company accounts. The application emphasizes performance through pagination, eager loading, database indexing, and Redis caching. Logging is centralized using `current_app.logger`, and configuration is managed through `config.py`. Environment variables are used for API keys (e.g., Guardian, OpenAI/Anthropic).

## External Dependencies

### Core Services
- **Pol.is Platform**: For structured discussions and consensus building.
- **PostgreSQL Database**: External primary data store.
- **Redis Cloud**: For session management, caching, and performance.
- **Replit Object Storage**: For user-uploaded media.

### Email and Analytics
- **Loops Email Service**: For transactional emails and user communications.
- **Sentry Error Tracking**: For error monitoring and performance.
- **Google Tag Manager**: For web analytics.

### APIs
- **Guardian API**: For news article fetching.
- **OpenAI/Anthropic APIs**: For LLM-based scoring, embeddings, and content generation within the "News-to-Deliberation Compiler."

### Social Media Integration
- **Bluesky (AT Protocol)**: Automatic posting when news discussions are published via the `atproto` package. Requires `BLUESKY_APP_PASSWORD` secret.
- **X/Twitter**: One-click share links (no API required) with pre-filled text including discussion link, topic hashtags, and podcast audience handles.
- **Social Poster Service**: `app/trending/social_poster.py` handles all social media formatting and posting with topic-based hashtags targeting intellectual podcast audiences.

### Development & Security Tools
- **Flask Extensions**: Various extensions for security, forms, and database management.
- **Tailwind CSS**: Utility-first CSS framework.
- **Node.js**: For frontend asset management and build processes.
- **Flask-Talisman**: For security headers and CSP.
- **Flask-Limiter**: For rate limiting.
- **Flask-SeaSurf**: For CSRF protection.

### Geographic Data
- **Static JSON files**: For country/city data used in filtering.

## Recent Changes (January 2026)

### Article Relevance Scoring
- Dual scoring system: **Relevance** (0-100%, how valuable for civic discussion) + **Clickbait Risk** (Low/Med/High)
- Relevance-based filtering: High (70%+), Medium (40-70%), Low (<40%)
- Pre-filtering with LOW_VALUE_KEYWORDS and PRODUCT_REVIEW_PATTERNS to catch product reviews, sports scores, listicles
- Cleanup: Articles with <30% relevance deleted after 7 days, all articles after 30 days
- UI shows relevance as primary badge, clickbait risk as secondary indicator

### Auto-Publishing System
- Daily auto-publish now runs once at 8am UTC (separate cron job from news fetching)
- Publishes up to 5 diverse topics from 21 trusted sources (news + premium podcasts)
- Diversity check: skips topics with 3+ common keywords to avoid publishing similar stories
- Quality threshold: civic_score >= 0.5 (lowered from 0.7)

### Admin Controls
- Added unpublish button for published topics (deletes discussion, reverts topic to pending_review)
- Relevance Score displayed as primary metric; Clickbait Risk as secondary indicator

### Scheduler Jobs
- `trending_topics_pipeline`: cron[7,12,18,22] - fetches news from RSS feeds
- `daily_auto_publish`: cron[8] - publishes up to 5 diverse topics once daily
- `cleanup_old_analyses`: cron[3] - removes old data
- `auto_cluster_discussions`: interval[6h] - clustering for active discussions

### Daily Civic Question Feature
- **Purpose**: Wordle-like daily participation ritual for quick civic engagement
- **Routes**: `/daily` (today's question), `/daily/YYYY-MM-DD` (historical questions)
- **Voting**: Agree/Disagree/Unsure with optional reason (max 500 chars)
- **Models**: `DailyQuestion` (question scheduling, stats), `DailyQuestionResponse` (user votes), `DailyQuestionSubscriber` (email subscribers), `DailyQuestionSelection` (auto-selection tracking)
- **Cold Start Mode**: Shows "Early Signal" messaging below configurable threshold (default 50 responses)
- **Share Snippets**: Emoji bar chart for social media sharing (X, WhatsApp, copy to clipboard)
- **Session Fingerprinting**: Anonymous users identified by session + user-agent for one-vote-per-day
- **Admin Interface**: Full CRUD at `/admin/daily-questions` for scheduling and managing questions
- **Navigation**: "Daily" link added to main navigation bar
- **Email Subscription**: `/daily/subscribe` for email signup, magic-link voting without login, 48-hour token expiry
- **Magic Links**: `/daily/m/<token>` for one-click voting from emails, auto-login for linked users
- **Participation Streaks**: Tracks current_streak, longest_streak, and thoughtful_participations (40-50% reasons)
- **Auto-Selection Service**: `app/daily/auto_selection.py` picks questions from discussions > trending topics > statements
- **Scheduler Jobs**: `daily_question_publish` (7:30am) auto-publishes today + 7 days ahead, `daily_question_email` (8:00am) sends to all subscribers
- **Templates**: Subscribe, success, and unsubscribe pages with streak display in results
- **Discussion Vote Sync**: When daily question is linked to a discussion statement, votes auto-sync to `StatementVote` table, contributing to consensus analysis
- **Participation Progress UI**: Results page shows "Your Vote Counts" section with progress bar toward unlocking consensus analysis (5 votes required), links to continue voting or view analysis when unlocked

### Homepage Redesign (January 2026)
- **Hero section**: Updated messaging to "Making Disagreement Useful Again" with "sense-making system" positioning
- **Primary CTAs**: "Today's Question" and "From the News" buttons replace generic "Join the Conversation"
- **Daily Question section**: Prominent feature section after hero explaining the daily civic ritual workflow
- **From the News section**: 3 feature cards highlighting curated sources, relevance filtering, and balanced discussions
- **Voices of Democracy**: Condensed from 9 quotes to 3 (Mead, Mandela, Mill) for better scroll weight
- **Page flow**: Hero -> Daily Question -> From the News -> Quotes -> Value Props -> How It Works -> Featured Discussions

### About Page & SEO Updates (January 2026)
- **About page**: Completely rewritten with new "sense-making system" narrative, covering: how it works (voting-based clustering), what it reveals (consensus/bridge/divisive statements), news-to-deliberation pipeline, Daily Question, and policy relevance
- **SEO meta tags**: Updated descriptions, keywords, OG/Twitter cards to reflect platform positioning as "sense-making system for society"
- **JSON-LD structured data**: Enhanced with Organization and WebApplication schemas including feature lists
- **LLM discoverability (GEO)**: Added `/llms.txt` route with comprehensive platform description for AI crawlers
- **robots.txt**: Updated to reference llms.txt for LLM crawler discovery

### Voting Security Fix (January 2026)
- **Bug fix**: Vote endpoints no longer default to "unsure" when vote value is missing - now returns 400 error requiring explicit vote
- **Bot protection**: Added user-agent filtering to reject known bots/crawlers/preview fetchers from submitting votes
- **Affected endpoints**: `/statements/<id>/vote` and `/daily/vote`
- **Edge cases**: Proper validation for empty strings, null values, and malformed JSON requests

### Geographic Scope Detection (January 2026)
- **AI-powered detection**: When articles are scored, AI now extracts geographic scope (global, regional, national, local) and countries mentioned
- **New fields**: `NewsArticle.geographic_scope` and `NewsArticle.geographic_countries` store detected geographic context
- **Propagation**: Geographic info flows from articles -> discussions -> daily questions
- **Display**: Daily questions and discussions now show geographic badges ("Global" or country name like "United Kingdom")

### Consensus Clustering Improvements (January 2026)
- **SparsityAwareScaler**: Pol.is innovation adapted from red-dwarf library that prevents sparse voters from bunching at PCA center
  - Enables discovery of 4-5+ opinion groups instead of just 2-3
  - Uses `sqrt(total_statements / participant_votes)` scaling factor
  - Code properly attributed to pol.is community (AGPL-3.0)
- **Representative Statements Per Opinion Group**: New feature showing what each group believes
  - Identifies top 5 statements each group agrees on most strongly
  - Uses "strength" metric: `agreement_rate × participation_weight`
  - UI displays "What Each Group Believes" section in Consensus Analysis page
  - Makes opinion groups interpretable: "Group 1 believes [X, Y, Z]"
- **Participation Gate**: Users must vote on 5+ statements before viewing consensus analysis
  - Prevents anchoring bias (seeing results before voting influences opinions)
  - Discussion creators and admins bypass the gate (need to manage discussions)
  - Gate UI shows progress bar and unlockable benefits
  - Button on discussion page shows lock icon + vote progress (e.g., "2/5") when gated
  - Gate check happens every request (database query, no caching bypass)
  - Gate applies to both `/consensus` and `/consensus/report` routes
  - Authenticated users get credit for votes cast before logging in (session fingerprint merge)
- **Implementation**: `app/lib/consensus_engine.py` contains `calculate_scaling_factors()`, `apply_sparsity_scaling()`, `identify_representative_statements()`
- **UI**: `app/templates/discussions/consensus_results.html` displays representative statements in responsive 2-column grid with XSS protection
- **Templates**: `consensus_gate.html` (participation gate), `consensus_report.html` (printable report)