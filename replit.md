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
The platform supports a comprehensive discussion system with Pol.is integration, topic categorization, and geographic filtering. It includes a dedicated News feed page displaying discussions derived from trending topics, with pagination and topic filter chips. Analytics track profile views and discussion engagement. Security features include Flask-Talisman for CSP, Flask-Limiter for rate limiting, Flask-SeaSurf for CSRF protection, and Werkzeug for password hashing. File storage uses Replit Object Storage for user-uploaded images, with built-in cropping and compression.

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

### Development & Security Tools
- **Flask Extensions**: Various extensions for security, forms, and database management.
- **Tailwind CSS**: Utility-first CSS framework.
- **Node.js**: For frontend asset management and build processes.
- **Flask-Talisman**: For security headers and CSP.
- **Flask-Limiter**: For rate limiting.
- **Flask-SeaSurf**: For CSRF protection.

### Geographic Data
- **Static JSON files**: For country/city data used in filtering.