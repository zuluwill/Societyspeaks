# Society Speaks Platform

## Overview
Society Speaks is an AGPL-3.0 licensed public discussion platform built with Flask and PostgreSQL. It aims to facilitate structured dialogue, build consensus on social, political, and community topics, and inform policy. Key capabilities include user profiles, discussion management, geographic filtering, a "News-to-Deliberation Compiler" for trending news, a "Daily Civic Question" for engagement, sophisticated consensus clustering, and a customizable briefing system with a template marketplace. The platform's vision is to foster nuanced debate and enhance civic engagement by leveraging Pol.is technology.

## User Preferences
Preferred communication style: Simple, everyday language.

## System Architecture

### UI/UX Decisions
The platform prioritizes a consistent, mobile-first UI with reusable components and enhanced accessibility (ARIA labels), using Tailwind CSS for styling. It features `discussion_card` components, toast notifications, empty states, and loading spinners. The homepage emphasizes a "sense-making system" by highlighting "Today's Question" and "From the News."

### Open Access Model
Society Speaks employs a "reading is open, delivery is opt-in" model. This includes a daily brief with full content viewable without login, a news dashboard showing all sources and political balance, and email capture components for subscription. A cross-sell strategy is implemented to upsell free users to custom brief options.

### Technical Implementations
The backend is built with Flask, utilizing a modular, blueprint-based architecture, SQLAlchemy for PostgreSQL, Flask-Login for authentication, and Redis for session management and caching. The "News-to-Deliberation Compiler" uses LLMs to identify trending news, score articles, cluster them into discussions, and generate balanced seed statements via hourly background jobs. The "Daily Civic Question" promotes participation with voting, streaks, and one-click email voting. AI automatically detects geographic scope and categories in articles and daily questions. A community moderation system allows flagging of inappropriate content. AI is used for "Lens Check Optimization" and enhanced comment UX. A single-source-to-discussion pipeline automatically creates discussions from various content types. A political leaning system categorizes sources based on AllSides.com data. A multi-tenant briefing system enables customizable, branded briefings with AI settings, source management, and output enhancements. The content selection algorithm uses global scoring based on topic preferences, keyword matches, and source priority, followed by fair source distribution.

### Unified Ingestion Architecture
A unified content ingestion system uses `InputSource` (tracking provenance, domain, channel permissions) and `IngestedItem` models. An `ItemFeedService` provides filtered access to content, ensuring editorial control and source credibility scoring (using `is_verified` and `political_leaning` data) for different features like the Daily Brief and user briefings.

### Feature Specifications
The platform integrates Pol.is for discussion dynamics, supports topic categorization, and geographic filtering. A dedicated News feed page displays trending discussions with source transparency. Security is handled by Flask-Talisman (CSP), Flask-Limiter (rate limiting), Flask-SeaSurf (CSRF protection), and Werkzeug for password hashing. Replit Object Storage manages user-uploaded images. The platform supports dual individual and company profiles. Daily question emails include one-click voting with privacy-controlled comment sharing. Source pages provide metadata and "Engagement Scores." A political diversity system monitors and balances political leanings across content.

### Deployment Architecture
The application uses gunicorn with multiple workers for Replit VM deployments. Werkzeug ProxyFix middleware (`x_for=1, x_proto=1, x_host=1`) is applied so `request.remote_addr` reflects the real client IP behind Replit's reverse proxy — critical for per-user rate limiting. It includes a health check endpoint (`/health`) and defers APScheduler startup to prevent blocking gunicorn's port binding. Production detection relies on the `REPLIT_DEPLOYMENT=1` environment variable. A Redis-based scheduler lock with heartbeat (60s TTL, 30s refresh) ensures only one worker runs the scheduler. Three-layer email deduplication: (1) Redis scheduler lock, (2) Redis per-hour send lock, (3) DB-level `last_brief_id_sent` idempotency guard. Magic tokens are stable across sends (only regenerated when expired/missing, with 168h TTL) to prevent "View in Browser" link invalidation.

### System Design Choices
PostgreSQL is the primary database, optimized with connection pooling, pagination, eager loading, and indexing. Redis caching enhances performance. Logging is centralized, and configuration uses `config.py` with environment variables. A `SparsityAwareScaler` is used in consensus clustering. A "Participation Gate" requires users to vote before viewing consensus analysis. Briefing templates are available via a marketplace. Briefing output includes structured HTML, email analytics, and Slack integration.

## External Dependencies

### Core Services
- **Pol.is Platform**: For structured discussions and consensus building.
- **PostgreSQL Database**: Primary data store.
- **Redis Cloud**: For session management, caching, and performance.
- **Replit Object Storage**: For user-uploaded media.

### Email and Analytics
- **Resend Email Service**: For transactional emails and user communications.
- **Sentry Error Tracking**: For error monitoring and performance.
- **Google Tag Manager**: For web analytics.

### APIs
- **Guardian API**: For news article fetching.
- **OpenAI/Anthropic APIs**: For LLM-based scoring, embeddings, and content generation.
- **Clearbit API**: For fetching source logos.

### Social Media Integration
- **Bluesky (AT Protocol)**: For automatic posting of news discussions.
- **X/Twitter**: For automatic posting of news discussions.

### Billing & Subscriptions
- **Stripe**: For subscription billing and payment processing, including pricing tiers, free trials, webhooks, and a customer portal.

### Development & Security Tools
- **Flask Extensions**: For security, forms, and database management.
- **Tailwind CSS**: Utility-first CSS framework.
- **Node.js**: For frontend asset management.

### Audio Generation (TTS)
- **Coqui XTTS v2**: Open-source text-to-speech for generating audio versions of brief items.
- **Audio Storage**: Uses Replit Object Storage for persistence.

### Geographic Data
- **Static JSON files**: For country/city data.