# Society Speaks Platform

## Overview

Society Speaks is an AGPL-3.0 licensed public discussion platform leveraging Pol.is technology to foster structured dialogue on social, political, and community topics. Built with Flask and PostgreSQL, its core purpose is to facilitate nuanced debate, build consensus, and inform policy. Key features include user profiles, discussion management, geographic filtering, and a "News-to-Deliberation Compiler" which automatically surfaces trending news for public deliberation. The platform also features a "Daily Civic Question" to encourage regular engagement and a sophisticated consensus clustering system to identify diverse opinion groups.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### UI/UX Decisions
The platform features a consistent UI with reusable components, prioritizing mobile accessibility and enhanced accessibility features (e.g., ARIA labels). Tailwind CSS provides a utility-first styling approach with custom typography. Key elements include `discussion_card` components, toast notifications, empty states, and loading spinners. The homepage has been redesigned to highlight "Today's Question" and "From the News" sections, emphasizing a "sense-making system" narrative.

### Technical Implementations
The backend uses Flask with a modular, blueprint-based architecture. SQLAlchemy and Flask-SQLAlchemy manage PostgreSQL interactions, while Flask-Login handles user authentication. Redis is employed for session management, caching (Flask-Caching), and performance. The "News-to-Deliberation Compiler" automatically identifies trending news, scores articles for relevance and clickbait risk using LLMs, clusters them into discussions, and generates balanced seed statements. This system operates via hourly background jobs and includes an admin interface for oversight. A "Daily Civic Question" feature provides a Wordle-like daily participation ritual, complete with voting, streaks, and email subscriptions.

### Feature Specifications
The platform integrates Pol.is for discussion dynamics, supports topic categorization, and geographic filtering. A dedicated News feed page (`/discussions/news`) displays discussions derived from trending topics, ensuring source transparency and responsive design. Discussions preserve source article attribution. Analytics track profile views and discussion engagement. Security measures include Flask-Talisman (CSP), Flask-Limiter (rate limiting), Flask-SeaSurf (CSRF protection), and Werkzeug for password hashing. Replit Object Storage handles user-uploaded images with cropping and compression. The platform supports a dual-profile system for individual and company accounts. Geographic scope (global, national, local) and countries mentioned in news articles are automatically detected using AI and propagate to discussions and daily questions.

### System Design Choices
PostgreSQL serves as the primary database, configured for connection pooling and health checks. Performance is optimized through pagination, eager loading, database indexing, and Redis caching. Logging is centralized, and configuration uses `config.py` with environment variables for API keys. A `SparsityAwareScaler` adapted from Pol.is innovations is used in consensus clustering to better identify diverse opinion groups. A "Participation Gate" requires users to vote on 5+ statements before viewing consensus analysis to prevent anchoring bias.

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
- **Bluesky (AT Protocol)**: Automatic posting of news discussions with staggered scheduling (2pm, 4pm, 6pm, 8pm, 10pm UTC = 9am, 11am, 1pm, 3pm, 5pm EST) to maximize US audience engagement across different timezones.
- **X/Twitter**: One-click share links.

### Development & Security Tools
- **Flask Extensions**: For security, forms, and database management.
- **Tailwind CSS**: Utility-first CSS framework.
- **Node.js**: For frontend asset management.

### Geographic Data
- **Static JSON files**: For country/city data used in filtering.