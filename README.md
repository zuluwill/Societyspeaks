# Society Speaks

![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)
![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![Flask](https://img.shields.io/badge/flask-2.3.3-blue.svg)

## Overview

Society Speaks is a public discussion platform where nuanced debate leads to better understanding and real solutions. Inspired by Pol.is, it features a native consensus-building system that uses machine learning to identify opinion groups, find common ground, and surface divisive topics - all without traditional threaded comments or upvotes.

## Community Compact

Society Speaks is committed to building a thriving, transparent, and supportive community. We value every contribution, feedback, and use of the platform. We encourage everyone to use the software freely and ethically, and to share back improvements so everyone benefits. Our goal is to align our success with the success of our community.

## Support This Project

Society Speaks is open source, and your support helps us keep it alive! If you find this platform useful, please consider donating to help us continue development and maintenance.

- **[Sponsor on GitHub](https://github.com/sponsors/zuluwill)**

Thank you for your support!

## Roadmap & Ideas

To see our future plans and ideas, check out [IDEAS.md](./IDEAS.md).

## Features

### Core Discussion System
- **Native Statement System** - One-click voting (Agree/Disagree/Unsure) with progressive disclosure
- **Threaded Responses** - Pro/con/neutral responses to statements with evidence linking
- **Evidence Attachments** - Citations, URLs, and file uploads via Replit Object Storage
- **Moderation Queue** - Flag and review system for discussion owners
- **Edit Windows** - 10-minute edit window for statements, then immutable for integrity

### Consensus Analysis (Machine Learning)
- **Opinion Clustering** - PCA dimensionality reduction + Agglomerative clustering
- **Consensus Detection** - Identifies statements with broad agreement across groups
- **Bridge Statements** - Finds statements that unite different opinion clusters
- **Divisive Statements** - Surfaces controversial topics with high disagreement
- **Silhouette Scoring** - Automatic cluster count optimization
- **JSON Export** - Export analysis results for external use

### AI Integration (Optional)
- **LLM Support** - OpenAI, Anthropic (Claude), and Mistral integration
- **AI Summaries** - Generate discussion summaries automatically
- **Cluster Labeling** - AI-generated names for opinion groups
- **Semantic Deduplication** - Prevent similar statements using embeddings
- **User-Provided Keys** - Encrypted API key storage (Fernet encryption)

### Trending Topics System
- **News Fetching** - RSS feed integration with feedparser
- **Topic Clustering** - Automatic grouping of related news articles
- **Discussion Generation** - Create discussions from trending topics
- **Social Posting** - Bluesky integration for sharing discussions

### User Features
- **Individual & Company Profiles** - Customizable public profiles
- **Geographic Filtering** - Location-based discussion discovery
- **Topic-Based Filtering** - Find discussions by subject area
- **Notification System** - Stay updated on discussion activity
- **Admin Dashboard** - User, profile, and discussion management

### Security & Performance
- **CSRF Protection** - Flask-SeaSurf integration
- **Secure Headers** - Flask-Talisman with CSP
- **Rate Limiting** - Flask-Limiter on sensitive endpoints
- **Redis Caching** - Improved performance and session management
- **Background Jobs** - APScheduler for clustering and cleanup tasks
- **Error Tracking** - Sentry.io integration

## Demo

You can try the live version at https://societyspeaks.io/

## Tech Stack

| Category | Technology |
|----------|------------|
| Backend | Python 3.11+ / Flask 2.3.3 |
| Database | PostgreSQL |
| Caching | Redis |
| Storage | Replit Object Storage |
| Frontend | Tailwind CSS |
| ML/Clustering | scikit-learn, numpy, pandas |
| Background Jobs | APScheduler |
| Encryption | cryptography (Fernet) |
| Social Integration | atproto (Bluesky) |
| News Fetching | feedparser |
| Monitoring | Sentry.io |
| Security | Flask-Talisman, Flask-SeaSurf |
| Session Management | Flask-Session with Redis |
| Rate Limiting | Flask-Limiter |
| Email | Flask-Mail |

## Requirements

```txt
# Core Flask
Flask==2.3.3
Flask-SQLAlchemy==3.0.5
Flask-Migrate==4.0.0
Flask-Login==0.6.3
Flask-WTF==1.2.2
WTForms==3.2.1
Flask-Session==0.8.0
Flask-Caching==2.3.0
Flask-Talisman==1.1.0
Flask-SeaSurf==2.0.0
Flask-Limiter==3.8.0
Flask-Mail==0.10.0

# Database
psycopg2-binary==2.9.10

# Machine Learning & Data
scikit-learn>=1.3.0
numpy>=1.24.0
pandas>=2.0.0

# Background Tasks
APScheduler==3.10.4

# Encryption
cryptography>=41.0.0

# Social & News
atproto
feedparser

# Utilities
python-slugify==8.0.1
email_validator==2.2.0
python-dotenv

# Monitoring
sentry-sdk==2.17.0

# Infrastructure
redis==5.2.0
replit>=4.1.0
gunicorn==21.2.0
```

## Environment Variables

```bash
# Core Configuration
SECRET_KEY=your_secret_key
DATABASE_URL=postgresql://user:password@localhost:5432/society_speaks
REDIS_URL=redis://localhost:6379/0

# Email Configuration
MAIL_SERVER=smtp.your-email-server.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USERNAME=your_email
MAIL_PASSWORD=your_password

# Error Tracking
SENTRY_DSN=your_sentry_dsn

# Bluesky Integration (optional - for social posting)
BLUESKY_HANDLE=your_handle.bsky.social
BLUESKY_APP_PASSWORD=your_app_password

# Environment
FLASK_ENV=development  # or production
```

**Note:** LLM API keys (OpenAI, Anthropic, Mistral) are provided by users in their account settings and stored encrypted. They are not configured as environment variables.

## Installation

### Local Development

1. Clone the repository:
```bash
git clone https://github.com/zuluwill/Societyspeaks.git
cd societyspeaks
```

2. Set up Python environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

3. Install Node dependencies:
```bash
npm install
```

4. Configure environment:
```bash
cp .env.example .env
# Edit .env with your configurations
```

5. Set up Redis and PostgreSQL:
```bash
# Start Redis server
redis-server

# Create PostgreSQL database
createdb societyspeaks
```

6. Initialize database:
```bash
flask db upgrade
flask seed-db  # Optional: for sample data
```

7. Compile Tailwind CSS:
```bash
# Development (with watch)
npx tailwindcss -i ./app/static/src/input.css -o ./app/static/css/output.css --watch

# Production (minified)
npx tailwindcss -i ./app/static/src/input.css -o ./app/static/css/output.css --minify
```

8. Run the application:
```bash
flask run
# Or for production:
gunicorn --bind 0.0.0.0:5000 run:app
```

### Replit Setup

1. Fork the Repl
2. Configure Secrets:
   - `DATABASE_URL`
   - `SECRET_KEY`
   - `REDIS_URL`
   - `SENTRY_DSN` (optional)
   - `MAIL_*` configurations
   - `BLUESKY_*` configurations (optional)

3. Install dependencies and initialize:
```bash
pip install -r requirements.txt
flask db upgrade
```

## Project Structure

```
society_speaks/
├── app/
│   ├── admin/              # Admin dashboard routes and forms
│   │   ├── routes.py
│   │   └── forms.py
│   ├── auth/               # Authentication (login, register, password reset)
│   │   └── routes.py
│   ├── discussions/        # Core discussion functionality
│   │   ├── routes.py       # Discussion CRUD
│   │   ├── statements.py   # Statement voting and management
│   │   ├── consensus.py    # Consensus analysis routes
│   │   ├── moderation.py   # Moderation queue
│   │   └── forms.py
│   ├── help/               # User documentation
│   │   └── routes.py
│   ├── lib/                # Core libraries
│   │   ├── consensus_engine.py  # ML clustering algorithms
│   │   └── llm_utils.py         # LLM integrations
│   ├── profiles/           # User profiles (individual & company)
│   │   ├── routes.py
│   │   └── forms.py
│   ├── settings/           # User settings and API key management
│   │   ├── routes.py
│   │   └── api_keys.py
│   ├── trending/           # Trending topics system
│   │   ├── routes.py
│   │   ├── news_fetcher.py
│   │   ├── clustering.py
│   │   └── social_poster.py
│   ├── templates/          # Jinja2 templates
│   ├── static/             # CSS, JS, images
│   ├── models.py           # SQLAlchemy models
│   ├── routes.py           # Main routes (index, about, etc.)
│   ├── scheduler.py        # APScheduler background jobs
│   └── __init__.py         # App factory
├── docs/                   # Implementation documentation
├── migrations/             # Alembic database migrations
├── scripts/                # Utility scripts
├── config.py               # Configuration classes
├── run.py                  # Application entry point
├── requirements.txt
├── package.json            # Tailwind dependencies
└── tailwind.config.js
```

## Security Features

- **CSRF Protection** - Flask-SeaSurf on all forms
- **Secure Headers** - Flask-Talisman with Content Security Policy
- **Rate Limiting** - Configurable limits on sensitive endpoints
- **Session Security** - Redis-backed secure sessions
- **Input Validation** - Character limits, type checking, sanitization
- **Encrypted API Keys** - Fernet encryption for user LLM keys
- **Edit Windows** - 10-minute edit window, then statements are immutable
- **Soft Deletes** - Audit trail preservation
- **Permission Checks** - Owner/moderator role verification

## Monitoring and Performance

- **Error Tracking** - Sentry.io integration
- **Redis Caching** - Response caching and session storage
- **Database Indexes** - Optimized queries on foreign keys
- **Denormalized Counts** - Avoid expensive COUNT(*) queries
- **Background Jobs** - Non-blocking clustering analysis
- **Pagination** - 20 items per page default
- **Old Analysis Cleanup** - Keeps only 10 most recent per discussion

## Documentation

- [COMPLETE_SYSTEM_GUIDE.md](./COMPLETE_SYSTEM_GUIDE.md) - Full technical documentation
- [QUICK_START.md](./QUICK_START.md) - Getting started guide
- [IDEAS.md](./IDEAS.md) - Future plans and roadmap
- [docs/](./docs/) - Implementation summaries

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## Known Issues

- Image upload size limited to 10MB on Replit Object Storage
- Clustering requires minimum 7 users with votes
- Large vote matrices (>1000 users) may slow clustering

## Support

For support, please open an issue or contact the maintainers.

## Acknowledgments

- [Pol.is](https://pol.is) - Inspiration for consensus-building approach
- [scikit-learn](https://scikit-learn.org) - Clustering algorithms
- [Tailwind CSS](https://tailwindcss.com) - Styling framework
- [Flask](https://flask.palletsprojects.com) - Web framework
- [APScheduler](https://apscheduler.readthedocs.io) - Background job scheduling
- [Replit](https://replit.com) - Hosting and development environment

## License

GNU AFFERO GENERAL PUBLIC LICENSE
Version 3, 19 November 2007

Copyright (C) 2024 William Roberts

This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License along with this program. If not, see <https://www.gnu.org/licenses/agpl-3.0.html>.

---

Made with care by William Roberts
