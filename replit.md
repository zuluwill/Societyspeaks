# Society Speaks Platform

## Overview

Society Speaks is an open-source public discussion platform that empowers communities through meaningful dialogue using Pol.is technology. The platform enables users to create and participate in structured discussions on critical social, political, and community topics. Built with Flask and PostgreSQL, it provides a space where nuanced debate leads to better understanding and potential policy solutions.

The application integrates with Pol.is to facilitate consensus-building discussions and includes features for user profiles (both individual and company), discussion management, geographic filtering, and comprehensive analytics tracking.

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