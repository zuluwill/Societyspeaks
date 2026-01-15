# Society Speaks Platform

## Overview

Society Speaks is an AGPL-3.0 licensed public discussion platform leveraging Pol.is technology to foster structured dialogue on social, political, and community topics. Built with Flask and PostgreSQL, its core purpose is to facilitate nuanced debate, build consensus, and inform policy. Key features include user profiles, discussion management, geographic filtering, and a "News-to-Deliberation Compiler" which automatically surfaces trending news for public deliberation. The platform also features a "Daily Civic Question" to encourage regular engagement and a sophisticated consensus clustering system to identify diverse opinion groups.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### UI/UX Decisions
The platform features a consistent UI with reusable components, prioritizing mobile accessibility and enhanced accessibility features (e.g., ARIA labels). Tailwind CSS provides a utility-first styling approach with custom typography. Key elements include `discussion_card` components, toast notifications, empty states, and loading spinners. The homepage has been redesigned to highlight "Today's Question" and "From the News" sections, emphasizing a "sense-making system" narrative.

### Technical Implementations
The backend uses Flask with a modular, blueprint-based architecture. SQLAlchemy and Flask-SQLAlchemy manage PostgreSQL interactions, while Flask-Login handles user authentication. Redis is employed for session management, caching (Flask-Caching), and performance. The "News-to-Deliberation Compiler" automatically identifies trending news, scores articles for relevance and clickbait risk using LLMs, clusters them into discussions, and generates balanced seed statements. This system operates via hourly background jobs and includes an admin interface for oversight. A "Daily Civic Question" feature provides a Wordle-like daily participation ritual, complete with voting, streaks, email subscriptions, and one-click voting from emails with privacy-controlled comment sharing.

### Feature Specifications
The platform integrates Pol.is for discussion dynamics, supports topic categorization, and geographic filtering. A dedicated News feed page (`/discussions/news`) displays discussions derived from trending topics, ensuring source transparency and responsive design. Discussions preserve source article attribution. Analytics track profile views and discussion engagement. Security measures include Flask-Talisman (CSP), Flask-Limiter (rate limiting), Flask-SeaSurf (CSRF protection), and Werkzeug for password hashing. Replit Object Storage handles user-uploaded images with cropping and compression. The platform supports a dual-profile system for individual and company accounts. Geographic scope (global, national, local) and countries mentioned in news articles are automatically detected using AI and propagate to discussions and daily questions.

### System Design Choices
PostgreSQL serves as the primary database, configured for connection pooling and health checks. Performance is optimized through pagination, eager loading, database indexing, and Redis caching. Logging is centralized, and configuration uses `config.py` with environment variables for API keys. A `SparsityAwareScaler` adapted from Pol.is innovations is used in consensus clustering to better identify diverse opinion groups. A "Participation Gate" requires users to vote on 5+ statements before viewing consensus analysis to prevent anchoring bias.

### Community Moderation System (January 2026)
The platform includes a community-driven moderation system for daily question responses:
- Users can flag inappropriate responses (spam, harassment, misinformation)
- Responses are auto-hidden after receiving 3 community flags
- Anonymous flagging is supported via session fingerprints
- Rate limiting (5 flags/hour) prevents abuse
- Row-level locking prevents race conditions in flag counting
- Admin review workflow allows unhiding responses if flags are dismissed

### Lens Check Optimization (January 2026)
The "Same Story, Different Lens" feature for Daily Briefs includes:
- Parallel LLM calls (3x speedup) for perspective analysis
- Retry logic with exponential backoff for API resilience
- Thread-safe token usage tracking for cost monitoring
- Enhanced JSON validation with type checking

### Comment UX Enhancements (January 2026)
Public comments on daily questions use representative sampling:
- Diversity guarantees: at least 1 comment from each perspective (Agree/Disagree/Unsure)
- Quality scoring: 70% length weighting, 30% recency
- Hidden responses excluded from counts and display
- Stats API for perspective badges

### Daily Question Email Voting
Daily question emails include one-click vote buttons (Agree/Disagree/Unsure) that use a two-step confirmation flow to prevent mail scanner prefetch attacks. Users can optionally share their reasoning with three visibility levels: public with name (authenticated users only), public anonymous, or private. Public reasons are displayed on the results page. The visibility selector appears dynamically when users start typing a reason. Votes and public reasons from authenticated users are synced to linked discussion statements.

### Source Profile Enhancements (January 2026)
Source pages now include comprehensive metadata for sharing with communities:
- **62 sources** updated with: website URLs, descriptions, correct categories (podcast/broadcaster/newspaper/magazine/newsletter/think_tank), and logo URLs
- **Engagement Score**: Calculated as (discussion_count * total_participants) / days_since_first_discussion, displayed as a green badge on source profile pages
- **Logo handling**: Clearbit API logos with first-letter gradient fallbacks when images fail to load
- **Metadata script**: scripts/update_source_metadata.py contains SOURCE_METADATA dictionary with all source data including podcast platform links (Apple/Spotify/YouTube)

### Podcast-to-Discussion Pipeline (January 2026)
Automatic pipeline to create discussions from podcast episodes:
- **File**: app/trending/podcast_publisher.py
- **Scheduler**: Runs daily at 9am UTC (after daily auto-publish)
- **Process**: Fetches recent podcast episodes (14 days), generates AI seed statements using OpenAI/Anthropic, creates Discussion records with linked source articles
- **Controls**: max_per_source=3 to prevent flooding, skips episodes already linked to discussions
- **Source coverage**: 56 active sources (11 podcasts, 45 news/magazines), 6 sources disabled due to Cloudflare blocking

### Political Leaning System (January 2026)
Political leanings follow AllSides.com ratings (chart v10.1/v11) with 5 categories:
- **Label terminology**: Uses "Centre-Left" and "Centre-Right" (not "Lean Left/Lean Right")
- **Database values**: Left (-2.0), Centre-Left (-1.0), Centre (0), Centre-Right (1.0), Right (2.0)
- **Threshold mapping**: Left (≤ -1.5), Centre-Left (-1.5 to -0.5), Centre (-0.5 to 0.5), Centre-Right (0.5 to 1.5), Right (≥ 1.5)
- **Label functions**: Defined in models.py, allsides_seed.py, and news/routes.py (must stay synchronized)
- **Version tracking**: RATINGS_VERSION in allsides_seed.py tracks updates (currently '2026.01.15')
- **Notable updates**: The Guardian, The Atlantic moved to "Left" per AllSides Nov 2024 review

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
- **OpenAI/Anthropic APIs**: For LLM-based scoring, embeddings, and content generation within the "News-to-Deliberation Compiler."

### Social Media Integration
- **Bluesky (AT Protocol)**: Automatic posting of news discussions with staggered scheduling (2pm, 4pm, 6pm, 8pm, 10pm UTC = 9am, 11am, 1pm, 3pm, 5pm EST) to maximize US audience engagement across different timezones. Uses external embed link cards with OpenGraph metadata for rich previews, with fallback to URL facets if embed creation fails.
- **X/Twitter**: Automatic posting with 280 character limit compliance (URLs count as 23 chars via t.co shortening).

### Social Media Best Practices (January 2026)
- **Character limits**: Bluesky 300 chars, X 280 chars (URLs = 23 chars)
- **Hashtag strategy**: 1-2 hashtags max, placed mid-text (never start with hashtag)
- **Link cards**: Bluesky uses external embeds for rich previews; X auto-generates preview for trailing URLs
- **Fallback handling**: Guaranteed clickable links on Bluesky via embed or URL facets
- **Edge cases**: Very long URLs handled with graduated fallback text to ensure compliance

### Development vs Production Environment (January 2026)
The scheduler now checks for production environment before running certain jobs:
- **Email sending**: Daily question emails and brief emails only sent in production
- **Social media posting**: All scheduled social posts only run in production
- **Detection method**: Checks REPLIT_DEPLOYMENT, FLASK_ENV, and domain patterns
- **Purpose**: Prevents duplicate emails/posts when both dev and production are running
- **Manual testing**: Dev environment scheduler jobs log "Skipping... development environment" instead of executing

### Development & Security Tools
- **Flask Extensions**: For security, forms, and database management.
- **Tailwind CSS**: Utility-first CSS framework.
- **Node.js**: For frontend asset management.

### Geographic Data
- **Static JSON files**: For country/city data used in filtering.