# Society Speaks 🗣️

![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)
![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![Flask](https://img.shields.io/badge/flask-3.0.0-blue.svg)

## 🎯 Overview

Society Speaks is a public discussion platform where nuanced debate leads to better understanding and real solutions. It provides a space where users can create and participate in Pol.is-powered discussions, share opinions, and reach a consensus on various topics of social importance.

## 🌍 Community Compact

Society Speaks is committed to building a thriving, transparent, and supportive community. We value every contribution, feedback, and use of the platform. We encourage everyone to use the software freely and ethically, and to share back improvements so everyone benefits. Our goal is to align our success with the success of our community.💡

## 🙌 Support This Project

Society Speaks is open source, and your support helps us keep it alive! If you find this platform useful, please consider donating to help us continue development and maintenance.

- **[Sponsor on GitHub](https://github.com/sponsors/zuluwill)**

Thank you for your support! 💖

## 📖 Roadmap & Ideas
To see our future plans and ideas, check out [IDEAS.md](./IDEAS.md).



## 🌟 Features

- 💬 Create and embed Pol.is discussions
- 🔍 Explore and join public debates
- 👥 Individual and Company profiles
- 🌍 Geographic and topic-based filtering
- 📊 Discussion analytics and participation tracking
- 🔒 Secure authentication system
- 💨 Redis caching for improved performance
- 🚨 Error tracking with Sentry
- 📧 Email functionality
- 🛡️ Enhanced security with Flask-Talisman
- 🚦 Rate limiting protection

## 🖥️ Demo
You can try the live version at https://societyspeaks.io/

## 🛠️ Tech Stack

- Backend: Python/Flask
- Database: PostgreSQL
- Caching: Redis
- Storage: Replit Object Storage
- Frontend: Tailwind CSS
- Monitoring: Sentry.io
- Security: Flask-Talisman, Flask-SeaSurf
- Session Management: Flask-Session with Redis
- Rate Limiting: Flask-Limiter
- Email Integration: Flask-Mail

## 📋 Requirements

```txt
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
psycopg2-binary==2.9.10
python-slugify==8.0.1
email_validator==2.2.0
sentry-sdk==2.17.0
redis==5.2.0
replit>=4.1.0
gunicorn==21.2.0
```

## ⚙️ Environment Variables

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

# Environment
FLASK_ENV=development  # or production
```

## 🚀 Installation

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
# Development
npx tailwindcss -i ./app/static/src/input.css -o ./app/static/css/output.css --watch

# Production
npx tailwindcss -i ./app/static/src/input.css -o ./app/static/css/output.css --minify
```

### Replit Setup

1. Fork the Repl
2. Configure Secrets:
   - DATABASE_URL
   - SECRET_KEY
   - REDIS_URL
   - SENTRY_DSN (optional)
   - MAIL_* configurations

3. Install dependencies:
```bash
poetry install
flask db upgrade
```

## 🔒 Security Features

- CSRF Protection with Flask-SeaSurf
- Secure headers with Flask-Talisman
- Rate limiting on sensitive endpoints
- Secure session handling with Redis
- Input validation and sanitization
- Protected against common web vulnerabilities
- Content Security Policy (CSP) implementation

## 📈 Monitoring and Performance

- Error tracking with Sentry.io
- Redis caching for improved performance
- Database connection pooling
- Rate limiting protection
- Session management optimization
- Static file caching

## 📁 Project Structure
```
society_speaks/
├── app/
│   ├── __init__.py
│   ├── models.py
│   ├── routes.py
│   ├── forms.py
│   ├── templates/
│   └── static/
├── migrations/
├── config.py
├── run.py
├── requirements.txt
└── tailwind.config.js
```

## 🤝 Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 🐛 Known Issues

- Image upload size limitations on Replit
- Rate limiting on free tier databases
- Tailwind CSS compilation time on first build

## 🙋‍♂️ Support

For support, please open an issue or contact the maintainers.

## 🙏 Acknowledgments

- [Pol.is](https://pol.is) for discussion infrastructure
- [Tailwind CSS](https://tailwindcss.com) for styling
- [Flask](https://flask.palletsprojects.com) for the web framework
- [Replit](https://replit.com) for hosting and development environment

## 📄 License

GNU AFFERO GENERAL PUBLIC LICENSE
Version 3, 19 November 2007

Copyright (C) 2024 William Roberts

Everyone is permitted to copy and distribute verbatim copies of this license document, but changing it is not allowed.

Preamble

The GNU Affero General Public License is a free, copyleft license for software and other kinds of works, specifically designed to ensure cooperation with the community in the case of network server software.

The licenses for most software are designed to take away your freedom to share and change it. By contrast, the GNU General Public Licenses are intended to guarantee your freedom to share and change all versions of a program--to make sure it remains free software for all its users.

When we speak of free software, we are referring to freedom, not price. Our General Public Licenses are designed to make sure that you have the freedom to distribute copies of free software (and charge for them if you wish), that you receive source code or can get it if you want it, that you can change the software or use pieces of it in new free programs, and that you know you can do these things.

Developers that use the GNU AGPL protect your rights with two steps: (1) assert copyright on the software, and (2) offer you this License giving you legal permission to copy, distribute, and/or modify it.

Terms and Conditions

0. Definitions.

“This License” refers to version 3 of the GNU Affero General Public License.

“Copyright” also means copyright-like laws that apply to other kinds of works, such as semiconductor masks.

“The Program” refers to any copyrightable work licensed under this License. Each licensee is addressed as “you”. “Licensees” and “recipients” may be individuals or organizations.

To “modify” a work means to copy from or adapt all or part of the work in a fashion requiring copyright permission, other than the making of an exact copy. The resulting work is called a “modified version” of the earlier work or a work “based on” the earlier work.

A “covered work” means either the unmodified Program or a work based on the Program.

To “propagate” a work means to do anything with it that, without permission, would make you directly or secondarily liable for infringement under applicable copyright law, except executing it on a computer or modifying a private copy. Propagation includes copying, distribution (with or without modification), making available to the public, and in some countries other activities as well.

To “convey” a work means any kind of propagation that enables other parties to make or receive copies. Mere interaction with a user through a computer network, with no transfer of a copy, is not conveying.

(Full license text continues at https://www.gnu.org/licenses/agpl-3.0.html)



## 🙌 Support This Project

Society Speaks is open source, and your support helps us keep it alive! If you find this platform useful, please consider donating to help us continue development and maintenance.

- **[Sponsor on GitHub](https://github.com/sponsors/zuluwill)**


Thank you for your support! 💖


---
Made with ❤️ by William Roberts
