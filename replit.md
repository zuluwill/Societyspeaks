# Society Speaks Platform

## Overview
Society Speaks is an AGPL-3.0 licensed public discussion platform built with Flask and PostgreSQL, leveraging Pol.is technology. Its core purpose is to facilitate structured dialogue, build consensus on social, political, and community topics, and inform policy. Key capabilities include user profiles, discussion management, geographic filtering, and a "News-to-Deliberation Compiler" that surfaces trending news for public deliberation. The platform also features a "Daily Civic Question" for regular engagement, sophisticated consensus clustering to identify diverse opinion groups, and a customizable briefing system with a template marketplace. The long-term vision is to foster nuanced debate and enhance civic engagement.

## User Preferences
Preferred communication style: Simple, everyday language.

## System Architecture

### UI/UX Decisions
The platform features a consistent, mobile-first UI with reusable components and enhanced accessibility (ARIA labels). Tailwind CSS is used for utility-first styling with custom typography. Key elements include `discussion_card` components, toast notifications, empty states, and loading spinners. The homepage highlights "Today's Question" and "From the News" to emphasize a "sense-making system."

### Technical Implementations
The backend uses Flask with a modular, blueprint-based architecture, SQLAlchemy for PostgreSQL interactions, Flask-Login for authentication, and Redis for session management, caching, and performance. The "News-to-Deliberation Compiler" identifies trending news, scores articles using LLMs, clusters them into discussions, and generates balanced seed statements via hourly background jobs. The "Daily Civic Question" promotes daily participation with voting, streaks, email subscriptions, and one-click voting from emails. AI is used for automatic detection of geographic scope and categories in articles and daily questions. A community moderation system allows users to flag inappropriate daily question responses, which are auto-hidden after multiple flags and subject to admin review. The platform also includes a "Lens Check Optimization" for parallel LLM calls in perspective analysis and enhanced comment UX with representative sampling and quality scoring. A single-source-to-discussion pipeline automatically creates discussions from various content types (podcasts, newsletters) by generating AI seed statements. A political leaning system categorizes sources based on AllSides.com ratings to track and manage political diversity. A multi-tenant briefing system allows users and organizations to create customizable, branded briefings with AI settings, source management, and output enhancements including AI-generated insights, key takeaways, and source attribution. The briefing customization system includes topic preferences with weights (Low/Medium/High), include/exclude keyword filters, source priority controls, and custom AI prompts. The content selection algorithm uses global scoring: items are scored based on topic preference matches (+1-3), include keyword matches (+5), source priority (+1-3), then sorted globally before fair source distribution selection.

### Unified Ingestion Architecture
The platform uses a unified content ingestion system through the `InputSource` and `IngestedItem` models:
- **InputSource** stores all content sources with provenance tracking (`origin_type`: admin/template/user), content domain classification (`content_domain`: news/sport/tech/finance/politics/science/crypto), and channel permissions (`allowed_channels`: daily_brief/trending/user_briefings)
- **ItemFeedService** provides filtered access to ingested content, ensuring editorial control. The Daily Brief only uses admin-verified sources excluding sport/crypto/entertainment/gaming domains, while user briefings have unrestricted access to their selected sources
- **Source Credibility Scoring** uses `is_verified` flag (1.3x boost) and `political_leaning` data (1.2x boost) to prioritize trusted sources
- This architecture maintains editorial integrity while sharing a single ingestion pipeline across all features

### Feature Specifications
The platform integrates Pol.is for discussion dynamics, supports topic categorization, and geographic filtering. A dedicated News feed page displays discussions from trending topics with source transparency. Security measures include Flask-Talisman (CSP), Flask-Limiter (rate limiting), Flask-SeaSurf (CSRF protection), and Werkzeug for password hashing. Replit Object Storage handles user-uploaded images. The platform supports dual individual and company profiles. Daily question emails include one-click voting with privacy-controlled comment sharing and syncing to linked discussion statements for authenticated users. Source pages provide comprehensive metadata and an "Engagement Score." A political diversity system monitors and ensures balanced representation of political leanings across content.

### System Design Choices
PostgreSQL is the primary database, optimized with connection pooling, health checks, pagination, eager loading, and indexing. Redis caching further enhances performance. Logging is centralized, and configuration uses `config.py` with environment variables. A `SparsityAwareScaler` is used in consensus clustering to identify diverse opinion groups. A "Participation Gate" requires users to vote on statements before viewing consensus analysis to prevent anchoring bias. Briefing templates are available via a marketplace, enforcing guardrails upon cloning. Briefing output includes structured HTML with branding, email analytics (open/click tracking), and Slack integration.

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
- **Stripe**: For subscription billing and payment processing.
  - Pricing tiers: Starter (£12/mo), Professional (£25/mo or £250/yr), Team (£300/mo), Enterprise (£2,000/mo)
  - 30-day free trial for all plans
  - Webhook handling for subscription lifecycle events
  - Customer portal for self-service billing management
  - Tier enforcement: brief limits, source limits, feature gating

### Development & Security Tools
- **Flask Extensions**: For security, forms, and database management.
- **Tailwind CSS**: Utility-first CSS framework.
- **Node.js**: For frontend asset management.

### Geographic Data
- **Static JSON files**: For country/city data.