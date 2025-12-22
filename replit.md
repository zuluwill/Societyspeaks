# Society Speaks Platform

## Overview

Society Speaks is an open-source public discussion platform that empowers communities through meaningful dialogue using Pol.is technology. The platform enables users to create and participate in structured discussions on critical social, political, and community topics. Built with Flask and PostgreSQL, it provides a space where nuanced debate leads to better understanding and potential policy solutions.

The application integrates with Pol.is to facilitate consensus-building discussions and includes features for user profiles (both individual and company), discussion management, geographic filtering, and comprehensive analytics tracking.

## Recent Changes (December 22, 2025)

### Performance Optimizations (December 22, 2025)
- **Pagination**: Added pagination to admin routes (profiles, users, discussions at 20 items/page) and profile view routes (10 items/page) to reduce database load
- **Eager Loading**: Added joinedload for related data in admin queries to prevent N+1 query issues
- **Database Indexes**: Added indexes on Discussion (creator_id, is_featured, topic), IndividualProfile (user_id), and CompanyProfile (user_id)
- **Scheduler Optimization**: Optimized cleanup_old_consensus_analyses to only query discussions with >10 analyses
- **Fixed view_profile Route**: Changed to redirect pattern instead of using non-existent template
- **Exception Handling**: Replaced bare except clauses with proper exception handling

### Security Fixes (December 22, 2025)
- **Removed Duplicate Sentry**: Eliminated duplicate sentry_sdk.init() call that was causing double instrumentation
- **Consolidated Rate Limiter**: auth/routes.py now imports shared limiter from app module instead of creating duplicate instance
- **Protected Test Routes**: /test-sitemap and /test-robots now require admin login (previously public)
- **Verified Webhook Security**: WEBHOOK_SECRET configured, production properly fails closed when missing

## Previous Changes (December 10, 2025)

### Fixes & UX/UI Improvements (December 10, 2025)
- **N+1 Query Fix in view_discussion**: Added eager loading with `joinedload(Statement.user)` to fetch user data in single query. Resolves Sentry issues #82444121 and #73094553.
- **Duplicate Statement Type Options**: Fixed form field displaying "Claim Claim Question Question" by changing SelectField to RadioField in StatementForm
- **CSS Loading**: Verified output.css loads correctly

### UX/UI Enhancements
- **Toast Notifications System**: Created reusable toast component for success/error/warning messages with auto-dismiss (3-5 seconds)
- **Form Error Handling**: Improved visual feedback with error messages and color-coded validation states
- **Mobile Button Sizing**: Ensured all interactive elements meet 44x44px minimum touch target for mobile accessibility
- **Empty State Component**: Reusable empty state template for no-results scenarios with helpful context
- **Loading Spinner Component**: Reusable spinner component for async operations
- **Better Form Labels**: Improved hover states and cursor feedback on radio buttons
- **Enhanced Accessibility**: Added proper ARIA labels and sr-only text for screen readers

### Content Seeding
- **20 Engaging Discussions Created**: Seeded platform with discussions across all topics with diverse perspectives:
  
  **Global Foundation Discussions (9):**
  - The Future of Remote Work (Technology)
  - Solving Global Housing Crisis (Economy)
  - Climate Action: Individual vs Government (Environment)
  - Reshaping Education Post-Pandemic (Education)
  - Healthcare Access & Global Inequalities (Healthcare)
  - AI Ethics and Regulation (Technology)
  - Immigration and Cultural Diversity (Society)
  - Infrastructure Investment (Infrastructure)
  - Democracy in Crisis (Politics)

  **Pressing Global Issues (11):**
  - Geopolitical Tensions: Military Intervention vs Non-Interference (Politics)
  - Disinformation and Social Media: Can We Protect Truth? (Technology)
  - The Mental Health Crisis: What's Driving Youth Depression? (Healthcare)
  - Economic Inequality: Is Capitalism Broken? (Economy)
  - Reparations and Historical Justice: What Do We Owe the Past? (Society)
  - Gender and LGBTQ+ Rights: How Far Should Society Go? (Society)
  - Automation and Job Displacement: Will There Be Work in 2050? (Economy)
  - Corporate Accountability: Do Companies Have Too Much Power? (Economy)
  - Global Manufacturing: Should the West Reshore Production? (Economy)
  - Water and Resource Wars: Who Owns the Commons? (Environment)
  - Pandemic Prevention: Are We Ready for the Next One? (Healthcare)

- **28 Total Discussions with 226 Seed Statements**: Comprehensive coverage of global issues
  
  **Additional Critical Topics (8):**
  - Gun Control: Safety vs Constitutional Rights (Politics)
  - Abortion and Reproductive Rights (Society)
  - Criminal Justice Reform (Politics)
  - Food Security and Agriculture (Environment)
  - Energy Transition (Environment)
  - Drug Policy and Legalization (Healthcare)
  - Privacy vs Surveillance (Technology)
  - Religious Freedom vs Secularism (Society)
  
  **Statement Distribution:**
  - All 28 discussions have 7+ statements each
  - 2 discussions with 7 statements
  - 5 discussions with 8 statements
  - 21 discussions with 7-9 statements
  - Diverse perspectives on each topic to spark genuine debate
- Created admin user for seeding operations

### Previous Fixes (November 2025)
- **CAPTCHA Validation Error**: Added try-except handling for bot garbage data in auth/routes.py
- **Response Form "Position Field Required"**: Changed SelectField to RadioField in statement_forms.py
- **Redis Cache Connection**: Fixed Flask-Caching localhost:6379 issue, now uses cloud Redis
- **Voting Interface**: Redesigned with always-visible buttons (AGREE, DISAGREE, UNSURE) with 80px touch targets

### Production Status
- All critical errors resolved
- Ready for production deployment
- Redis caching configured and tested
- Background scheduler operational

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Backend Framework
- **Flask Application Structure**: Modular blueprint-based architecture with separate modules for authentication, profiles, discussions, admin, help, and settings
- **Database ORM**: SQLAlchemy with Flask-SQLAlchemy for database operations and Flask-Migrate for schema management
- **Authentication System**: Flask-Login with custom User model supporting both individual and company profile types
- **Session Management**: Flask-Session with Redis backend for scalable session storage

### Database Design
- **Primary Database**: PostgreSQL with connection pooling and health checks configured
- **User Management**: Dual profile system supporting individual and company accounts linked to a central User model
- **Discussion System**: Comprehensive discussion model with Pol.is integration, geographic filtering, topic categorization, and view tracking
- **Analytics Tracking**: Dedicated models for tracking profile views and discussion engagement

### Caching and Performance
- **Redis Integration**: Used for session storage, caching, and performance optimization with Flask-Caching
- **Database Connection Pooling**: Configured with connection health checks, automatic reconnection, and optimized pool settings
- **Static Asset Management**: Tailwind CSS for styling with custom configuration and typography plugins

### Security Implementation
- **Content Security Policy**: Flask-Talisman with comprehensive CSP rules allowing necessary inline scripts while maintaining security
- **Rate Limiting**: Flask-Limiter for registration and authentication endpoints
- **CSRF Protection**: Flask-SeaSurf for cross-site request forgery protection
- **Password Security**: Werkzeug password hashing with strong hash algorithms

### File Storage System
- **Replit Object Storage**: Integration for profile images, company logos, and banner images
- **Image Processing**: Built-in cropping and compression capabilities for uploaded images
- **Secure File Handling**: Proper filename sanitization and storage path management

### Email and Communication
- **Loops Integration**: Transactional email system for user communications, password resets, and notifications
- **Welcome Email Flow**: Automated onboarding sequence for new users
- **Event Tracking**: User action tracking for engagement analytics

## External Dependencies

### Core Services
- **Pol.is Platform**: Primary discussion technology for consensus-building and opinion clustering
- **PostgreSQL Database**: Production database hosted externally with connection pooling
- **Redis Cloud**: Session storage and caching layer for improved performance
- **Replit Object Storage**: File storage for user-uploaded images and media

### Email and Analytics
- **Loops Email Service**: Transactional email delivery and user engagement tracking
- **Sentry Error Tracking**: Comprehensive error monitoring and performance tracking
- **Google Tag Manager**: Web analytics and conversion tracking

### Development Tools
- **Flask Extensions**: Comprehensive security, form handling, and database management stack
- **Tailwind CSS**: Utility-first CSS framework with custom plugins for typography and forms
- **Node.js Dependencies**: Build tools for CSS processing and frontend asset management

### Security and Monitoring
- **Flask-Talisman**: Security headers and content security policy enforcement
- **Flask-Limiter**: Rate limiting for API endpoints and user actions
- **Flask-SeaSurf**: CSRF protection for form submissions

### Geographic Data
- **Country/City Data**: Static JSON files for geographic filtering and location selection in discussions and profiles