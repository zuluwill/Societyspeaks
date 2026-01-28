from app import db, cache
from flask import current_app
from datetime import datetime, timedelta
from slugify import slugify as python_slugify
from flask_login import UserMixin
from unidecode import unidecode
from itsdangerous import URLSafeTimedSerializer as Serializer
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.orm import validates
from sqlalchemy import event
from typing import Optional

import re



def generate_slug(name):
    """Generate a URL-friendly slug from a string."""
    if not name:
        return ""

    # Convert to lowercase and normalize unicode characters
    name = str(name).lower()
    name = unidecode(name)

    # Replace non-alphanumeric characters with hyphens
    name = re.sub(r'[^a-z0-9]+', '-', name)

    # Remove leading/trailing hyphens
    name = name.strip('-')

    # Replace multiple consecutive hyphens with a single hyphen
    name = re.sub(r'-+', '-', name)

    return name


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), nullable=False, unique=True)
    email = db.Column(db.String(150), nullable=False, unique=True)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # New field to indicate profile type
    profile_type = db.Column(db.String(50))  # 'individual' or 'company'

    # Notification preferences
    email_notifications = db.Column(db.Boolean, default=True)  # Enable email notifications
    discussion_participant_notifications = db.Column(db.Boolean, default=True)  # New participants
    discussion_response_notifications = db.Column(db.Boolean, default=True)  # New responses
    weekly_digest_enabled = db.Column(db.Boolean, default=True)  # Weekly digest emails

    # Stripe billing
    stripe_customer_id = db.Column(db.String(255), nullable=True, unique=True, index=True)

    # Relationships to profiles
    individual_profile = db.relationship('IndividualProfile', backref='user', uselist=False)
    company_profile = db.relationship('CompanyProfile', backref='user', uselist=False)

    discussions_created = db.relationship('Discussion', backref='creator', lazy='dynamic')
    notifications = db.relationship('Notification', backref='user', lazy='dynamic')

    # Password methods
    def set_password(self, password):
        """Hashes and sets the password."""
        self.password = generate_password_hash(password)

    def check_password(self, password):
        """Verifies the password against the stored hash."""
        return check_password_hash(self.password, password)

    # Token generation and verification methods for password reset
    def get_reset_token(self, expires_sec=1800):
        """Generates a token valid for `expires_sec` seconds (default: 30 minutes)."""
        s = Serializer(current_app.config['SECRET_KEY'])
        return s.dumps({'user_id': self.id}, salt='password-reset-salt')

    @staticmethod
    def verify_reset_token(token, expiration=1800):
        """Verifies the token and returns the user if valid, otherwise None."""
        s = Serializer(current_app.config['SECRET_KEY'])
        try:
            user_id = s.loads(token, salt='password-reset-salt', max_age=expiration)['user_id']
        except Exception:
            return None
        return User.query.get(user_id)

    # Flask-Login required methods
    def is_active(self):
        # Here, we assume all users are active. Adjust if you have inactive users.
        return True

    def get_id(self):
        # Flask-Login needs this to identify users across sessions.
        return str(self.id)



class ProfileView(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Allow the view to be associated with either type of profile
    individual_profile_id = db.Column(db.Integer, db.ForeignKey('individual_profile.id'), nullable=True)
    company_profile_id = db.Column(db.Integer, db.ForeignKey('company_profile.id'), nullable=True)
    viewer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # nullable for anonymous views
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(45))  # Store IP address for analytics


class DiscussionView(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=False)
    viewer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # nullable for anonymous views
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(45))  # Store IP address for analytics


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # 'new_participant', 'new_response', etc.
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    email_sent = db.Column(db.Boolean, default=False)

    # Relationships
    discussion = db.relationship('Discussion', backref='notifications')

    def mark_as_read(self):
        """Mark notification as read"""
        self.is_read = True
        db.session.commit()


class DiscussionParticipant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Can be null for anonymous
    participant_identifier = db.Column(db.String(255))  # External identifier from Pol.is
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_activity = db.Column(db.DateTime, default=datetime.utcnow)
    response_count = db.Column(db.Integer, default=0)

    # Relationships
    discussion = db.relationship('Discussion', backref='participants')
    user = db.relationship('User', backref='discussion_participations')

    @classmethod
    def track_participant(cls, discussion_id, user_id=None, participant_identifier=None, commit=True, return_is_new=False):
        """
        Track a participant in a discussion.

        Args:
            discussion_id: ID of the discussion
            user_id: ID of the user (optional, for authenticated users)
            participant_identifier: External identifier (optional, for anonymous users)
            commit: Whether to commit the transaction (default True)
            return_is_new: If True, returns tuple (participant, is_new) instead of just participant

        Returns:
            DiscussionParticipant instance, or tuple (participant, is_new) if return_is_new=True

        Raises:
            ValueError: If both user_id and participant_identifier are None
        """
        # Validate that at least one identifier is provided
        if user_id is None and participant_identifier is None:
            raise ValueError("Either user_id or participant_identifier must be provided")

        # Check if participant already exists
        existing = cls.query.filter_by(
            discussion_id=discussion_id,
            user_id=user_id,
            participant_identifier=participant_identifier
        ).first()

        is_new = existing is None

        if not existing:
            participant = cls(
                discussion_id=discussion_id,
                user_id=user_id,
                participant_identifier=participant_identifier
            )
            db.session.add(participant)
            # Flush to get the ID even if not committing (needed for increment_response_count)
            db.session.flush()
        else:
            # Update last activity
            existing.last_activity = datetime.utcnow()
            participant = existing

        if commit:
            db.session.commit()

        if return_is_new:
            return participant, is_new
        return participant

    def increment_response_count(self, commit=True):
        """
        Atomically increment the response count for this participant.

        Args:
            commit: Whether to commit the transaction (default True)

        Note:
            This uses a database-level atomic increment to prevent race conditions.
        """
        # Use atomic update to prevent race conditions
        self.__class__.query.filter_by(id=self.id).update({
            'response_count': self.__class__.response_count + 1,
            'last_activity': datetime.utcnow()
        }, synchronize_session=False)

        if commit:
            db.session.commit()
            # Refresh to get updated values
            db.session.refresh(self)


class IndividualProfile(db.Model):
    __table_args__ = (
        db.Index('idx_individual_profile_user_id', 'user_id'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    bio = db.Column(db.Text)
    city = db.Column(db.String(100))  # New field for city
    country = db.Column(db.String(100))  # New field for country
    email = db.Column(db.String(150), nullable=True)  # Optional public email
    website = db.Column(db.String(255))  # Optional website link
    profile_image = db.Column(db.String(255))  # Path to profile image
    banner_image = db.Column(db.String(255))  # Path to banner image
    # Individual social media fields
    linkedin_url = db.Column(db.String(255))
    twitter_url = db.Column(db.String(255))
    facebook_url = db.Column(db.String(255))
    instagram_url = db.Column(db.String(255))
    tiktok_url = db.Column(db.String(255))
    slug = db.Column(db.String(150), unique=True, nullable=False)

    discussions = db.relationship('Discussion', backref='individual_profile', lazy='dynamic', foreign_keys='Discussion.individual_profile_id')
    views = db.relationship('ProfileView', 
          foreign_keys=[ProfileView.individual_profile_id],
          backref='individual_profile', 
          lazy='dynamic')

    

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.slug and self.full_name:
            self.slug = generate_slug(self.full_name)

    def update_slug(self):
        if self.full_name:
            self.slug = generate_slug(self.full_name)

class CompanyProfile(db.Model):
    __table_args__ = (
        db.Index('idx_company_profile_user_id', 'user_id'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    company_name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    city = db.Column(db.String(100))  # New field for city
    country = db.Column(db.String(100))  # New field for country
    email = db.Column(db.String(150), nullable=True)  # Optional public email
    website = db.Column(db.String(255))  # Optional website link
    logo = db.Column(db.String(255))  # Path to company logo
    banner_image = db.Column(db.String(255))  # Path to banner image
    # Individual social media fields
    linkedin_url = db.Column(db.String(255))
    twitter_url = db.Column(db.String(255))
    facebook_url = db.Column(db.String(255))
    instagram_url = db.Column(db.String(255))
    tiktok_url = db.Column(db.String(255))
    slug = db.Column(db.String(150), unique=True, nullable=False)

    discussions = db.relationship('Discussion', backref='company_profile', lazy='dynamic', foreign_keys='Discussion.company_profile_id')
    views = db.relationship('ProfileView', 
          foreign_keys=[ProfileView.company_profile_id],
          backref='company_profile', 
          lazy='dynamic')

    

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.slug and self.company_name:
            self.slug = generate_slug(self.company_name)

    def update_slug(self):
        if self.company_name:
            self.slug = generate_slug(self.company_name)


class OrganizationMember(db.Model):
    """
    Tracks membership of users in organizations (CompanyProfile).
    Used for Team/Enterprise plans to manage team seats.
    """
    __tablename__ = 'organization_member'
    __table_args__ = (
        db.Index('idx_org_member_org', 'org_id'),
        db.Index('idx_org_member_user', 'user_id'),
        db.UniqueConstraint('org_id', 'user_id', name='uq_org_member'),
    )

    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey('company_profile.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)

    # Role: 'owner', 'admin', 'editor', 'viewer'
    role = db.Column(db.String(20), default='editor', nullable=False)

    # Invitation tracking
    invited_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    invited_at = db.Column(db.DateTime, default=datetime.utcnow)
    joined_at = db.Column(db.DateTime, nullable=True)  # NULL if invite pending

    # Invitation token for email invites
    invite_token = db.Column(db.String(64), unique=True, nullable=True)
    invite_email = db.Column(db.String(255), nullable=True)  # Email for pending invites

    # Status: 'pending', 'active', 'removed'
    status = db.Column(db.String(20), default='pending', nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    org = db.relationship('CompanyProfile', backref=db.backref('members', lazy='dynamic'))
    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('org_memberships', lazy='dynamic'))
    invited_by = db.relationship('User', foreign_keys=[invited_by_id])

    @property
    def is_active(self):
        return self.status == 'active'

    @property
    def is_pending(self):
        return self.status == 'pending'

    @property
    def is_owner(self):
        return self.role == 'owner'

    @property
    def is_admin(self):
        return self.role in ('owner', 'admin')

    @property
    def can_edit(self):
        return self.role in ('owner', 'admin', 'editor')

    def to_dict(self):
        return {
            'id': self.id,
            'org_id': self.org_id,
            'user_id': self.user_id,
            'role': self.role,
            'status': self.status,
            'invited_at': self.invited_at.isoformat() if self.invited_at else None,
            'joined_at': self.joined_at.isoformat() if self.joined_at else None,
            'invite_email': self.invite_email,
            'user': {
                'id': self.user.id,
                'username': self.user.username,
                'email': self.user.email,
            } if self.user else None,
        }

    def __repr__(self):
        return f'<OrganizationMember org:{self.org_id} user:{self.user_id} ({self.role})>'


class Discussion(db.Model):
    __table_args__ = (
        db.Index('idx_discussion_title_desc', 'title', 'description'),
        db.Index('idx_discussion_created_at', 'created_at'),
        db.Index('idx_discussion_creator_id', 'creator_id'),
        db.Index('idx_discussion_is_featured', 'is_featured'),
        db.Index('idx_discussion_topic', 'topic'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    embed_code = db.Column(db.String(800), nullable=True)  # Nullable for native discussions
    has_native_statements = db.Column(db.Boolean, default=False)  # Native vs pol.is embed mode
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    keywords = db.Column(db.String(200))
    slug = db.Column(db.String(150), unique=True, nullable=False)

    # Geographic fields and other properties
    geographic_scope = db.Column(db.String(20), nullable=False, default='country')
    country = db.Column(db.String(100))
    city = db.Column(db.String(100))
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    topic = db.Column(db.String(100))
    is_featured = db.Column(db.Boolean, default=False)
    participant_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Foreign keys to link discussions to profiles
    individual_profile_id = db.Column(db.Integer, db.ForeignKey('individual_profile.id'), nullable=True)
    company_profile_id = db.Column(db.Integer, db.ForeignKey('company_profile.id'), nullable=True)
    views = db.relationship('DiscussionView', backref='discussion', lazy='dynamic')

    # Bluesky posting schedule (for staggered posts throughout the day)
    bluesky_scheduled_at = db.Column(db.DateTime, nullable=True)  # When to post to Bluesky
    bluesky_posted_at = db.Column(db.DateTime, nullable=True)  # When actually posted
    bluesky_post_uri = db.Column(db.String(500), nullable=True)  # Bluesky post URI after posting

    # X/Twitter posting schedule (mirrors Bluesky pattern)
    x_scheduled_at = db.Column(db.DateTime, nullable=True)  # When to post to X
    x_posted_at = db.Column(db.DateTime, nullable=True)  # When actually posted
    x_post_id = db.Column(db.String(100), nullable=True)  # X tweet ID after posting

    # Constants for geographic scope
    SCOPE_GLOBAL = 'global'
    SCOPE_COUNTRY = 'country'
    SCOPE_CITY = 'city'

    # Define topics for validation
    TOPICS = [
        'Healthcare', 'Environment', 'Education', 'Technology', 'Economy', 
        'Politics', 'Society', 'Infrastructure', 'Geopolitics', 'Business', 'Culture'
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.slug and self.title:
            self.slug = generate_slug(self.title)

    def update_slug(self):
        if self.title:
            self.slug = generate_slug(self.title)

    @property
    def location_display(self):
        """Returns formatted location based on geographic scope"""
        if self.geographic_scope == self.SCOPE_GLOBAL:
            return "Global Discussion"
        elif self.geographic_scope == self.SCOPE_COUNTRY:
            return self.country
        else:
            return f"{self.city}, {self.country}"

    def to_dict(self):
        return {
            'id': self.id,
            'embed_code': self.embed_code,  # Store full embed code in dictionary
            'title': self.title,
            'description': self.description,
            'keywords': self.keywords,  # Include keywords here
            'slug': self.slug,
            'geographic_scope': self.geographic_scope,
            'country': self.country,
            'city': self.city,
            'topic': self.topic,
            'is_featured': self.is_featured,
            'participant_count': self.participant_count,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


    def get_featured(limit=6):
        # Try to get from cache first, fallback to direct query if cache fails
        cache_key = f'featured_discussions_{limit}'
        try:
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                return cached_result
        except Exception as e:
            # Log cache error but continue with database query
            current_app.logger.warning(f"Cache get failed for featured discussions: {e}")
        
        # First get discussions marked as featured, excluding test discussions
        featured = Discussion.query\
            .filter_by(is_featured=True)\
            .filter(~Discussion.title.ilike('%test%'))\
            .filter(~Discussion.description.ilike('%test%'))\
            .order_by(Discussion.created_at.desc())\
            .all()

        # If we have fewer than limit (6), add recent non-featured discussions
        if len(featured) < limit:
            featured_ids = [d.id for d in featured]
            additional = Discussion.query\
                .filter(Discussion.id.notin_(featured_ids))\
                .filter(~Discussion.title.ilike('%test%'))\
                .filter(~Discussion.description.ilike('%test%'))\
                .order_by(Discussion.created_at.desc())\
                .limit(limit - len(featured))\
                .all()
            featured.extend(additional)

        result = featured[:limit]
        
        # Try to cache the result, but don't fail if caching fails
        try:
            cache.set(cache_key, result, timeout=300)  # Cache for 5 minutes
        except Exception as e:
            current_app.logger.warning(f"Cache set failed for featured discussions: {e}")
        
        return result

    @staticmethod
    def feature_discussion(discussion_id, feature=True):
        """Manually feature or unfeature a discussion"""
        discussion = Discussion.query.get_or_404(discussion_id)
        discussion.is_featured = feature
        db.session.commit()
        return discussion

    @classmethod
    def auto_feature_discussions(cls):
        """Automatically feature discussions with balanced criteria"""
        total_count = cls.query.count()

        if total_count <= 6:
            # If we have 6 or fewer discussions total, feature them all
            cls.query.update({cls.is_featured: True})
            db.session.commit()
            return cls.query.all()

        # If we have more than 6 discussions, use the balanced criteria
        cls.query.update({cls.is_featured: False})
        db.session.commit()

        featured = []

        # Get one discussion per topic from the last 30 days
        for topic in cls.TOPICS:
            discussion = cls.query\
                .filter(
                    cls.topic == topic,
                    cls.created_at >= (datetime.utcnow() - timedelta(days=30))
                )\
                .order_by(cls.created_at.desc())\
                .first()

            if discussion:
                discussion.is_featured = True
                featured.append(discussion)

        # If we need more to reach 6, add most recent discussions
        if len(featured) < 6:
            additional = cls.query\
                .filter(cls.id.notin_([d.id for d in featured]))\
                .order_by(cls.created_at.desc())\
                .limit(6 - len(featured))\
                .all()

            for discussion in additional:
                discussion.is_featured = True

        db.session.commit()
        return featured


    
    @staticmethod
    def search_discussions(search=None, country=None, city=None, topic=None, scope=None, keywords=None, page=1, per_page=9):
        query = Discussion.query.options(db.joinedload(Discussion.creator))

        if search:
            search_term = f"%{search}%"
            query = query.filter(
                db.or_(
                    Discussion.title.ilike(search_term),
                    Discussion.description.ilike(search_term)
                )
            )

        if scope:
            query = query.filter(Discussion.geographic_scope == scope)

        if country:
            query = query.filter(Discussion.country.ilike(f"%{country}%"))

        if city:
            query = query.filter(Discussion.city.ilike(f"%{city}%"))

        if topic:
            query = query.filter(Discussion.topic == topic)

        # New keyword filtering
        if keywords:
            query = query.filter(Discussion.keywords.ilike(f"%{keywords}%"))

        return query.order_by(Discussion.created_at.desc())\
                    .paginate(page=page, per_page=per_page, error_out=False)


# ============================================================================
# Native Debate System Models (Phase 1)
# Adapted from pol.is architecture (AGPL-3.0)
# ============================================================================

class Statement(db.Model):
    """
    Core claim/proposition in native debates (analogous to pol.is 'comments')
    
    Based on pol.is data model patterns:
    - Per-discussion auto-incrementing tid (not global id)
    - Content limited to 500 chars (pol.is uses 1000)
    - Unique constraint prevents duplicates per discussion
    """
    __tablename__ = 'statement'
    __table_args__ = (
        db.Index('idx_statement_discussion', 'discussion_id'),
        db.Index('idx_statement_user', 'user_id'),
        db.Index('idx_statement_session', 'session_fingerprint'),
        db.UniqueConstraint('discussion_id', 'content', name='uq_discussion_statement'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Nullable for anonymous users
    session_fingerprint = db.Column(db.String(64), nullable=True)  # For anonymous user tracking
    content = db.Column(db.Text, nullable=False)  # Max 500 chars (validated below)
    statement_type = db.Column(db.String(20), default='claim')  # 'claim' or 'question'
    parent_statement_id = db.Column(db.Integer, db.ForeignKey('statement.id'), nullable=True)
    
    # Vote counts (denormalized for performance, like pol.is)
    vote_count_agree = db.Column(db.Integer, default=0)
    vote_count_disagree = db.Column(db.Integer, default=0)
    vote_count_unsure = db.Column(db.Integer, default=0)
    
    # Moderation (like pol.is mod field)
    mod_status = db.Column(db.Integer, default=0)  # -1=reject, 0=no action, 1=accept
    is_deleted = db.Column(db.Boolean, default=False)
    is_seed = db.Column(db.Boolean, default=False)  # Moderator-created seed statement
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    discussion = db.relationship('Discussion', backref='statements')
    user = db.relationship('User', backref='statements')
    parent = db.relationship('Statement', remote_side=[id], backref='replies')
    
    @validates('content')
    def validate_content(self, key, content):
        """Enforce 10-500 character limit"""
        if not content or len(content.strip()) < 10:
            raise ValueError("Statement must be at least 10 characters")
        if len(content) > 500:
            raise ValueError("Statement must not exceed 500 characters")
        return content.strip()
    
    @property
    def total_votes(self):
        """Total number of votes cast on this statement"""
        return self.vote_count_agree + self.vote_count_disagree + self.vote_count_unsure
    
    @property
    def agreement_rate(self):
        """Percentage of agree votes (excluding unsure)"""
        decisive_votes = self.vote_count_agree + self.vote_count_disagree
        if decisive_votes == 0:
            return 0
        return self.vote_count_agree / decisive_votes
    
    @property
    def controversy_score(self):
        """
        Controversy score: 1 - |agree_rate - 0.5| * 2
        High score (close to 1) = controversial (~50/50 split)
        Low score (close to 0) = consensus
        """
        if self.total_votes < 5:
            return 0
        return 1 - abs(self.agreement_rate - 0.5) * 2
    
    def to_dict(self):
        return {
            'id': self.id,
            'discussion_id': self.discussion_id,
            'user_id': self.user_id,
            'content': self.content,
            'statement_type': self.statement_type,
            'parent_statement_id': self.parent_statement_id,
            'vote_count_agree': self.vote_count_agree,
            'vote_count_disagree': self.vote_count_disagree,
            'vote_count_unsure': self.vote_count_unsure,
            'total_votes': self.total_votes,
            'agreement_rate': self.agreement_rate,
            'controversy_score': self.controversy_score,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


class StatementVote(db.Model):
    """
    User votes on statements - THE CORE DATA FOR CLUSTERING
    
    Based on pol.is 'votes' table:
    - vote values: -1 (disagree), 0 (unsure), 1 (agree)
    - Users can change votes (history preserved)
    - Supports both authenticated (user_id) and anonymous (session_fingerprint) voting
    - Anonymous votes can be merged to user account on signup/login
    
    Database constraints (created via SQL, not ORM):
    - uq_statement_user_vote: UNIQUE (statement_id, user_id) WHERE user_id IS NOT NULL
    - uq_statement_session_vote: UNIQUE (statement_id, session_fingerprint) WHERE session_fingerprint IS NOT NULL
    """
    __tablename__ = 'statement_vote'
    __table_args__ = (
        db.Index('idx_vote_discussion_user', 'discussion_id', 'user_id'),
        db.Index('idx_vote_discussion_statement', 'discussion_id', 'statement_id'),
        db.Index('idx_vote_session_fingerprint', 'session_fingerprint'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    statement_id = db.Column(db.Integer, db.ForeignKey('statement.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    session_fingerprint = db.Column(db.String(64), nullable=True)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=False)
    
    vote = db.Column(db.SmallInteger, nullable=False)
    
    confidence = db.Column(db.SmallInteger, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    statement = db.relationship('Statement', backref='votes')
    user = db.relationship('User', backref='statement_votes')
    discussion = db.relationship('Discussion', backref='statement_votes')
    
    @classmethod
    def merge_anonymous_votes(cls, session_fingerprint, user_id):
        """
        Merge anonymous votes to a user account when they sign up or log in.
        If user already voted on a statement, keep their authenticated vote and
        decrement the denormalized counts to avoid inflation.
        """
        from app.models import Statement
        
        anonymous_votes = cls.query.filter_by(session_fingerprint=session_fingerprint, user_id=None).all()
        merged_count = 0
        
        for anon_vote in anonymous_votes:
            existing_user_vote = cls.query.filter_by(
                statement_id=anon_vote.statement_id,
                user_id=user_id
            ).first()
            
            if existing_user_vote:
                statement = Statement.query.get(anon_vote.statement_id)
                if statement:
                    if anon_vote.vote == 1:
                        statement.vote_count_agree = max(0, statement.vote_count_agree - 1)
                    elif anon_vote.vote == -1:
                        statement.vote_count_disagree = max(0, statement.vote_count_disagree - 1)
                    elif anon_vote.vote == 0:
                        statement.vote_count_unsure = max(0, statement.vote_count_unsure - 1)
                db.session.delete(anon_vote)
            else:
                anon_vote.user_id = user_id
                anon_vote.session_fingerprint = None
                merged_count += 1
        
        db.session.commit()
        return merged_count
    
    @validates('vote')
    def validate_vote(self, key, vote):
        """Ensure vote is -1, 0, or 1"""
        if vote not in [-1, 0, 1]:
            raise ValueError("Vote must be -1 (disagree), 0 (unsure), or 1 (agree)")
        return vote
    
    @validates('confidence')
    def validate_confidence(self, key, confidence):
        """Ensure confidence is 1-5 if provided"""
        if confidence is not None and (confidence < 1 or confidence > 5):
            raise ValueError("Confidence must be between 1 and 5")
        return confidence


class Response(db.Model):
    """
    Elaborations on why user voted a certain way (our enhancement beyond pol.is)
    Enables threaded discussions with pro/con structure
    """
    __tablename__ = 'response'
    __table_args__ = (
        db.Index('idx_response_statement', 'statement_id'),
        db.Index('idx_response_user', 'user_id'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    statement_id = db.Column(db.Integer, db.ForeignKey('statement.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Nullable for anonymous
    parent_response_id = db.Column(db.Integer, db.ForeignKey('response.id'), nullable=True)

    # Support for anonymous responses (synced from daily questions)
    session_fingerprint = db.Column(db.String(64), nullable=True)
    is_anonymous = db.Column(db.Boolean, default=False)

    position = db.Column(db.String(20))  # 'pro', 'con', 'neutral'
    content = db.Column(db.Text)  # Optional elaboration
    is_deleted = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    statement = db.relationship('Statement', backref='responses')
    user = db.relationship('User', backref='responses')
    parent = db.relationship('Response', remote_side=[id], backref='replies')


class Evidence(db.Model):
    """
    Supporting evidence for responses (our enhancement beyond pol.is)
    """
    __tablename__ = 'evidence'
    __table_args__ = (
        db.Index('idx_evidence_response', 'response_id'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    response_id = db.Column(db.Integer, db.ForeignKey('response.id'), nullable=False)
    
    source_title = db.Column(db.String(500))
    source_url = db.Column(db.String(1000))
    citation = db.Column(db.Text)
    quality_status = db.Column(db.String(20), default='pending')  # 'pending', 'verified', 'disputed'
    
    # For Replit object storage (Phase 0.6)
    storage_key = db.Column(db.String(500))  # Replit object storage key
    storage_url = db.Column(db.String(1000))  # Public URL
    
    added_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    response = db.relationship('Response', backref='evidence')
    added_by = db.relationship('User', backref='added_evidence')


class ConsensusAnalysis(db.Model):
    """
    Stores clustering results for caching (like pol.is math_main table)
    """
    __tablename__ = 'consensus_analysis'
    __table_args__ = (
        db.Index('idx_consensus_discussion', 'discussion_id'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=False)
    
    # Clustering results stored as JSON
    cluster_data = db.Column(db.JSON, nullable=False)
    num_clusters = db.Column(db.Integer)
    silhouette_score = db.Column(db.Float)
    
    # Metadata
    method = db.Column(db.String(50))  # 'pca_kmeans', 'umap_hdbscan', etc.
    participants_count = db.Column(db.Integer)
    statements_count = db.Column(db.Integer)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    discussion = db.relationship('Discussion', backref='consensus_analyses')


class StatementFlag(db.Model):
    """
    Moderation flags for statements (our enhancement)
    """
    __tablename__ = 'statement_flag'
    __table_args__ = (
        db.Index('idx_flag_statement', 'statement_id'),
        db.Index('idx_flag_status', 'status'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    statement_id = db.Column(db.Integer, db.ForeignKey('statement.id'), nullable=False)
    flagger_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    flag_reason = db.Column(db.String(50))  # 'spam', 'offensive', 'off_topic', 'duplicate'
    additional_context = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')  # 'pending', 'reviewed', 'dismissed'
    
    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    statement = db.relationship('Statement', backref='flags')
    flagger = db.relationship('User', foreign_keys=[flagger_user_id], backref='flags_created')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by_user_id], backref='flags_reviewed')


class UserAPIKey(db.Model):
    """
    User-provided API keys for optional LLM features (Phase 4)
    """
    __tablename__ = 'user_api_key'
    __table_args__ = (
        db.Index('idx_api_key_user', 'user_id'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    provider = db.Column(db.String(50), nullable=False)  # 'openai', 'anthropic'
    encrypted_api_key = db.Column(db.Text, nullable=False)  # Fernet encrypted
    is_active = db.Column(db.Boolean, default=True)
    last_validated = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref='api_keys')


# =============================================================================
# TRENDING TOPICS SYSTEM (News-to-Deliberation Compiler)
# =============================================================================

class NewsSource(db.Model):
    """
    Curated allowlist of trusted news sources.
    Only fetch from sources on this list.
    """
    __tablename__ = 'news_source'
    __table_args__ = (
        db.Index('idx_news_source_active', 'is_active'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    feed_url = db.Column(db.String(500), nullable=False)
    source_type = db.Column(db.String(20), default='rss')  # 'rss', 'api', 'guardian', 'nyt'
    country = db.Column(db.String(100))  # Country the source primarily covers (e.g., 'United Kingdom', 'United States')
    
    reputation_score = db.Column(db.Float, default=0.8)  # 0-1 scale
    is_active = db.Column(db.Boolean, default=True)

    # Political leaning for coverage analysis (-3 to +3: left to right, 0 = center)
    political_leaning = db.Column(db.Float)  # -2=Left, -1=Lean Left, 0=Center, 1=Lean Right, 2=Right
    leaning_source = db.Column(db.String(50))  # 'allsides', 'mbfc', 'adfontesmedia', 'manual'
    leaning_updated_at = db.Column(db.DateTime)

    last_fetched_at = db.Column(db.DateTime)
    fetch_error_count = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Source profile fields
    slug = db.Column(db.String(200), unique=True, nullable=True)
    source_category = db.Column(db.String(50), default='newspaper')  # 'podcast', 'newspaper', 'magazine', 'broadcaster'

    # Basic branding (for unclaimed sources)
    logo_url = db.Column(db.String(500), nullable=True)
    website_url = db.Column(db.String(500), nullable=True)
    description = db.Column(db.Text, nullable=True)

    # Claiming fields
    claim_status = db.Column(db.String(20), default='unclaimed')  # 'unclaimed', 'pending', 'approved', 'rejected'
    claimed_by_profile_id = db.Column(db.Integer, db.ForeignKey('company_profile.id', ondelete='SET NULL'), nullable=True)
    claimed_at = db.Column(db.DateTime, nullable=True)
    claim_requested_at = db.Column(db.DateTime, nullable=True)
    claim_requested_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)

    # Relationships
    articles = db.relationship('NewsArticle', backref='source', lazy='dynamic')
    claimed_by = db.relationship('CompanyProfile', backref='claimed_sources', foreign_keys=[claimed_by_profile_id])
    claim_requested_by = db.relationship('User', backref='source_claims', foreign_keys=[claim_requested_by_id])

    @property
    def is_claimed(self):
        """Check if source has been claimed and approved."""
        return self.claim_status == 'approved' and self.claimed_by_profile_id is not None

    @property
    def display_logo(self):
        """
        Return logo info as a dict for template rendering.

        Returns:
            dict with 'type' ('profile' or 'url') and 'src' (filename or URL),
            or None if no logo is available.
        """
        if self.is_claimed and self.claimed_by and self.claimed_by.logo:
            return {'type': 'profile', 'src': self.claimed_by.logo}
        if self.logo_url:
            return {'type': 'url', 'src': self.logo_url}
        return None

    @property
    def display_description(self):
        """Return claimed profile description, or basic description."""
        if self.is_claimed and self.claimed_by and self.claimed_by.description:
            return self.claimed_by.description
        return self.description

    @property
    def political_leaning_label(self):
        """Return human-readable political leaning label based on AllSides ratings."""
        if self.political_leaning is None:
            return 'Unknown'
        if self.political_leaning <= -1.5:
            return 'Left'
        elif self.political_leaning <= -0.5:
            return 'Centre-Left'
        elif self.political_leaning <= 0.5:
            return 'Centre'
        elif self.political_leaning <= 1.5:
            return 'Centre-Right'
        else:
            return 'Right'

    def generate_slug(self):
        """Generate URL-friendly slug from name."""
        self.slug = generate_slug(self.name)

    def __repr__(self):
        return f'<NewsSource {self.name}>'


@event.listens_for(NewsSource, 'before_insert')
def auto_generate_source_slug(mapper, connection, target):
    """Auto-generate slug for new NewsSource records if not already set."""
    if not target.slug and target.name:
        base_slug = generate_slug(target.name)
        if not base_slug:
            import uuid
            base_slug = f"source-{uuid.uuid4().hex[:8]}"
        
        slug = base_slug
        suffix = 1
        while db.session.query(NewsSource).filter(NewsSource.slug == slug).first():
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        target.slug = slug


class NewsArticle(db.Model):
    """
    Individual news articles fetched from sources.
    Stored separately for querying, deduplication, and auditing.
    """
    __tablename__ = 'news_article'
    __table_args__ = (
        db.Index('idx_article_source', 'source_id'),
        db.Index('idx_article_fetched', 'fetched_at'),
        db.Index('idx_article_external_id', 'external_id'),
        db.UniqueConstraint('source_id', 'external_id', name='uq_source_article'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey('news_source.id'), nullable=False)
    
    external_id = db.Column(db.String(500))  # Source's unique ID for deduplication
    title = db.Column(db.String(500), nullable=False)
    summary = db.Column(db.Text)
    url = db.Column(db.String(1000), nullable=False)
    
    published_at = db.Column(db.DateTime)
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Scoring (computed at fetch time)
    sensationalism_score = db.Column(db.Float)  # 0-1: higher = more clickbait
    relevance_score = db.Column(db.Float)  # 0-1: discussion potential (1=policy debate, 0=product review)
    personal_relevance_score = db.Column(db.Float)  # 0-1: direct impact on daily life (economic/health/rights)

    # Geographic scope detection (AI-analyzed from content)
    geographic_scope = db.Column(db.String(20), default='unknown')  # 'global', 'regional', 'national', 'local', 'unknown'
    geographic_countries = db.Column(db.String(500))  # Comma-separated list of countries mentioned (e.g., "UK, US" or "Global")
    
    # Embedding for clustering (stored as JSON array of floats)
    title_embedding = db.Column(db.JSON)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<NewsArticle {self.title[:50]}...>'


class TrendingTopic(db.Model):
    """
    A clustered news topic ready for deliberation.
    Multiple articles are grouped into one topic.
    """
    __tablename__ = 'trending_topic'
    __table_args__ = (
        db.Index('idx_topic_status', 'status'),
        db.Index('idx_topic_created', 'created_at'),
        db.Index('idx_topic_hold_until', 'hold_until'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    
    # The neutral framing question for discussion
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)
    
    # Canonical tags for long-term merging (LLM-derived)
    # e.g., ["uk", "nhs", "junior_doctors", "pay"]
    canonical_tags = db.Column(db.JSON)
    topic_slug = db.Column(db.String(200))  # Normalized slug from tags
    
    # Scoring (separate scores per ChatGPT's advice)
    civic_score = db.Column(db.Float)  # 0-1: Is this worthwhile for civic discussion?
    quality_score = db.Column(db.Float)  # 0-1: Non-clickbait, fact density, multi-source
    audience_score = db.Column(db.Float)  # 0-1: Appeal to target podcast audience
    risk_flag = db.Column(db.Boolean, default=False)  # Culture war / sensitive / defamation risk
    risk_reason = db.Column(db.String(200))  # Why it's flagged as risky
    
    # Primary topic category for the discussion
    primary_topic = db.Column(db.String(50))  # Maps to Discussion.TOPICS
    
    # Geographic scope (derived from source articles)
    geographic_scope = db.Column(db.String(20), default='global')  # 'global', 'country', 'regional'
    geographic_countries = db.Column(db.String(500))  # Comma-separated: "UK, US" or None for global
    
    source_count = db.Column(db.Integer, default=0)  # Number of unique sources
    
    # Embedding for question-level deduplication (last 30 days)
    topic_embedding = db.Column(db.JSON)
    
    # Workflow status
    status = db.Column(db.String(20), default='pending')
    # pending -> held -> pending_review -> approved -> published
    # pending -> held -> pending_review -> discarded
    # pending -> held -> pending_review -> merged
    
    hold_until = db.Column(db.DateTime)  # Cooldown window (30-90 mins)
    
    # If merged into another topic/discussion
    merged_into_topic_id = db.Column(db.Integer, db.ForeignKey('trending_topic.id'), nullable=True)
    merged_into_discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=True)
    
    # Generated seed statements (JSON array)
    seed_statements = db.Column(db.JSON)  # [{"content": "...", "position": "pro/con/neutral"}]
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    published_at = db.Column(db.DateTime)
    
    # Link to created discussion (if published)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=True)
    
    # Relationships
    articles = db.relationship('TrendingTopicArticle', backref='topic', lazy='dynamic')
    merged_into_topic = db.relationship('TrendingTopic', remote_side=[id], backref='merged_topics')
    merged_into_discussion = db.relationship('Discussion', foreign_keys=[merged_into_discussion_id], backref='merged_topics')
    created_discussion = db.relationship('Discussion', foreign_keys=[discussion_id], backref='source_topic')
    reviewer = db.relationship('User', backref='reviewed_topics')
    
    HIGH_TRUST_SOURCES = [
        'bbc news', 'the guardian', 'financial times', 'the economist',
        'foreign affairs', 'the atlantic', 'the new yorker', 'bloomberg',
        'the rest is politics', 'the news agents', 'all-in podcast',
        'triggernometry', 'the tim ferriss show', 'diary of a ceo', 'modern wisdom',
        'unherd', 'politico eu', 'the telegraph', 'the independent', 'techcrunch', 'axios'
    ]
    
    @property
    def is_high_confidence(self):
        """
        High confidence for publishing:
        - From a trusted source
        - Has civic relevance (worth discussing)
        - Not flagged as risky
        """
        return (
            self.has_trusted_source and
            (self.civic_score or 0) >= 0.5 and
            not self.risk_flag
        )
    
    @property
    def has_trusted_source(self):
        """Check if any article is from a high-trust source."""
        for ta in self.articles:
            if ta.article and ta.article.source:
                if ta.article.source.name.lower() in self.HIGH_TRUST_SOURCES:
                    return True
        return False
    
    @property
    def should_auto_publish(self):
        """
        Auto-publish criteria:
        - From a trusted source
        - Has civic relevance
        - Not risky
        """
        return self.is_high_confidence
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'canonical_tags': self.canonical_tags,
            'civic_score': self.civic_score,
            'quality_score': self.quality_score,
            'risk_flag': self.risk_flag,
            'risk_reason': self.risk_reason,
            'source_count': self.source_count,
            'status': self.status,
            'hold_until': self.hold_until.isoformat() if self.hold_until else None,
            'seed_statements': self.seed_statements,
            'is_high_confidence': self.is_high_confidence,
            'created_at': self.created_at.isoformat(),
            'articles': [ta.article.title for ta in self.articles if ta.article]
        }
    
    def __repr__(self):
        return f'<TrendingTopic {self.title[:50]}...>'


class TrendingTopicArticle(db.Model):
    """
    Join table linking TrendingTopic to NewsArticle.
    Allows many-to-many with additional metadata.
    
    Foreign Key Behavior:
    - topic_id: CASCADE - auto-delete when topic is deleted
    - article_id: CASCADE - auto-delete when article is deleted
    """
    __tablename__ = 'trending_topic_article'
    __table_args__ = (
        db.Index('idx_tta_topic', 'topic_id'),
        db.Index('idx_tta_article', 'article_id'),
        db.UniqueConstraint('topic_id', 'article_id', name='uq_topic_article'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    topic_id = db.Column(db.Integer, db.ForeignKey('trending_topic.id', ondelete='CASCADE'), nullable=False)
    article_id = db.Column(db.Integer, db.ForeignKey('news_article.id', ondelete='CASCADE'), nullable=False)
    
    # When this article was added to the topic
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Similarity score to the topic centroid
    similarity_score = db.Column(db.Float)
    
    # Relationships
    article = db.relationship('NewsArticle', backref='topic_associations')


class DiscussionSourceArticle(db.Model):
    """
    Join table linking Discussion to NewsArticle for news-based discussions.
    Preserves source attribution when topics are published as discussions.
    
    Foreign Key Behavior:
    - discussion_id: CASCADE - auto-delete when discussion is deleted
    - article_id: SET NULL - preserve link record but clear article reference when article deleted
    """
    __tablename__ = 'discussion_source_article'
    __table_args__ = (
        db.Index('idx_dsa_discussion', 'discussion_id'),
        db.Index('idx_dsa_article', 'article_id'),
        db.UniqueConstraint('discussion_id', 'article_id', name='uq_discussion_article'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id', ondelete='CASCADE'), nullable=False)
    article_id = db.Column(db.Integer, db.ForeignKey('news_article.id', ondelete='CASCADE'), nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    discussion = db.relationship('Discussion', backref='source_article_links')
    article = db.relationship('NewsArticle', backref='discussion_links')


class DailyBrief(db.Model):
    """
    Daily Sense-Making Brief - Evening news summary (6pm).
    Aggregates 3-5 curated topics with coverage analysis.
    Separate from Daily Question (morning participation prompt).
    """
    __tablename__ = 'daily_brief'
    __table_args__ = (
        db.Index('idx_brief_date', 'date'),
        db.Index('idx_brief_status', 'status'),
        db.UniqueConstraint('date', name='uq_daily_brief_date'),
    )

    id = db.Column(db.Integer, primary_key=True)

    date = db.Column(db.Date, nullable=False, unique=True)
    title = db.Column(db.String(200))  # e.g., "Tuesday's Brief: Climate, Tech, Healthcare"
    intro_text = db.Column(db.Text)  # 2-3 sentence calm framing

    status = db.Column(db.String(20), default='draft')  # draft|ready|published|skipped

    # Admin override tracking
    auto_selected = db.Column(db.Boolean, default=True)  # False if admin edited
    admin_edited_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    admin_notes = db.Column(db.Text)  # Why was this edited/skipped?

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    published_at = db.Column(db.DateTime)

    # "Same Story, Different Lens" cross-perspective analysis
    # Shows how left/centre/right outlets frame the same story differently
    # Generated automatically during brief creation - see app/brief/lens_check.py
    lens_check = db.Column(db.JSON)

    # Relationships
    items = db.relationship('BriefItem', backref='brief', lazy='dynamic',
                           cascade='all, delete-orphan', order_by='BriefItem.position')
    admin_editor = db.relationship('User', backref='edited_briefs', foreign_keys=[admin_edited_by])

    @property
    def item_count(self):
        """Number of items in this brief.
        
        Uses cached count if available (set by batch queries in routes)
        to prevent N+1 query issues.
        """
        if hasattr(self, '_cached_item_count'):
            return self._cached_item_count
        # Use count() method if available (for lazy/dynamic relationships)
        # Otherwise fall back to len() for eagerly loaded lists
        if hasattr(self.items, 'count') and callable(self.items.count):
            return self.items.count()
        try:
            return len(self.items)
        except TypeError:
            # Fallback: query the database directly
            return BriefItem.query.filter_by(brief_id=self.id).count()

    @classmethod
    def get_today(cls):
        """Get today's brief"""
        from datetime import date
        today = date.today()
        return cls.query.filter_by(date=today, status='published').first()

    @classmethod
    def get_by_date(cls, brief_date):
        """Get brief for a specific date"""
        return cls.query.filter_by(date=brief_date, status='published').first()

    def to_dict(self):
        return {
            'id': self.id,
            'date': self.date.isoformat(),
            'title': self.title,
            'intro_text': self.intro_text,
            'status': self.status,
            'item_count': self.item_count,
            'items': [item.to_dict() for item in self.items.order_by(BriefItem.position)],
            'lens_check': self.lens_check,
            'published_at': self.published_at.isoformat() if self.published_at else None,
            'created_at': self.created_at.isoformat()
        }

    def __repr__(self):
        return f'<DailyBrief {self.date} ({self.status})>'


class BriefItem(db.Model):
    """
    Individual story in a daily brief (3-5 per brief).
    References TrendingTopic for DRY principle.
    """
    __tablename__ = 'brief_item'
    __table_args__ = (
        db.Index('idx_brief_item_brief', 'brief_id'),
        db.Index('idx_brief_item_topic', 'trending_topic_id'),
        db.UniqueConstraint('brief_id', 'position', name='uq_brief_position'),
    )

    id = db.Column(db.Integer, primary_key=True)
    brief_id = db.Column(db.Integer, db.ForeignKey('daily_brief.id', ondelete='CASCADE'), nullable=False)
    position = db.Column(db.Integer, nullable=False)  # Display order 1-5

    # Source (DRY - reference existing TrendingTopic)
    # RESTRICT prevents deleting topics that are used in briefs
    trending_topic_id = db.Column(db.Integer, db.ForeignKey('trending_topic.id', ondelete='RESTRICT'), nullable=False)

    # Generated content (LLM-created for brief context)
    headline = db.Column(db.String(200))  # Shorter, punchier than TrendingTopic title
    summary_bullets = db.Column(db.JSON)  # ['bullet1', 'bullet2', 'bullet3']
    personal_impact = db.Column(db.Text)  # One-sentence personal relevance ("Why This Matters To You")
    so_what = db.Column(db.Text)  # "So what?" analysis paragraph
    perspectives = db.Column(db.JSON)  # {'left': '...', 'center': '...', 'right': '...'}

    # Coverage analysis (computed from TrendingTopic articles)
    coverage_distribution = db.Column(db.JSON)  # {'left': 0.2, 'center': 0.5, 'right': 0.3}
    coverage_imbalance = db.Column(db.Float)  # 0-1 score (0=balanced, 1=single perspective)
    source_count = db.Column(db.Integer)  # Number of unique sources
    sources_by_leaning = db.Column(db.JSON)  # {'left': ['Guardian'], 'center': ['BBC', 'FT'], 'right': []}
    blindspot_explanation = db.Column(db.Text)  # LLM-generated explanation for coverage gaps

    # Sensationalism (from source articles)
    sensationalism_score = db.Column(db.Float)  # Average of article scores
    sensationalism_label = db.Column(db.String(20))  # 'low', 'medium', 'high'

    # Verification links (LLM-extracted + admin additions)
    verification_links = db.Column(db.JSON)  # [{'tier': 'primary', 'url': '...', 'type': '...', 'description': '...', 'is_paywalled': bool}]

    # CTA to discussion
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=True)
    cta_text = db.Column(db.String(200))  # Customizable per item

    # Special item types
    is_underreported = db.Column(db.Boolean, default=False)  # "Under the Radar" bonus item

    # Polymarket Integration (optional market signal data)
    # Stored as JSON snapshot at brief generation time for historical accuracy
    # Schema: see PolymarketMarket.to_signal_dict()
    market_signal = db.Column(db.JSON)  # null if no matching market

    # Deeper context for "Want more detail?" feature
    deeper_context = db.Column(db.Text)  # Extended analysis and background

    # Audio/TTS integration (XTTS v2 - open source)
    audio_url = db.Column(db.String(500))  # URL to generated audio file
    audio_voice_id = db.Column(db.String(100))  # XTTS voice ID used
    audio_generated_at = db.Column(db.DateTime)  # When audio was generated

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    trending_topic = db.relationship('TrendingTopic', backref='brief_items')
    discussion = db.relationship('Discussion', backref='brief_items')

    def to_dict(self):
        return {
            'id': self.id,
            'position': self.position,
            'headline': self.headline,
            'summary_bullets': self.summary_bullets,
            'personal_impact': self.personal_impact,
            'so_what': self.so_what,
            'perspectives': self.perspectives,
            'coverage_distribution': self.coverage_distribution,
            'coverage_imbalance': self.coverage_imbalance,
            'source_count': self.source_count,
            'sources_by_leaning': self.sources_by_leaning,
            'blindspot_explanation': self.blindspot_explanation,
            'sensationalism_score': self.sensationalism_score,
            'sensationalism_label': self.sensationalism_label,
            'verification_links': self.verification_links,
            'discussion_id': self.discussion_id,
            'cta_text': self.cta_text,
            'is_underreported': self.is_underreported,
            'market_signal': self.market_signal,
            'deeper_context': self.deeper_context,
            'audio_url': self.audio_url,
            'audio_voice_id': self.audio_voice_id,
            'trending_topic': self.trending_topic.to_dict() if self.trending_topic else None
        }

    def __repr__(self):
        return f'<BriefItem {self.position}. {self.headline}>'


class NewsPerspectiveCache(db.Model):
    """
    Cache for perspective analysis generated on news transparency page.

    Separate from BriefItem to avoid coupling. Caches LLM-generated perspectives
    for topics that appear on /news but weren't in the daily brief.
    """
    __tablename__ = 'news_perspective_cache'
    __table_args__ = (
        db.Index('idx_npc_topic_date', 'trending_topic_id', 'generated_date'),
        db.UniqueConstraint('trending_topic_id', 'generated_date', name='uq_npc_topic_date'),
    )

    id = db.Column(db.Integer, primary_key=True)
    trending_topic_id = db.Column(db.Integer, db.ForeignKey('trending_topic.id', ondelete='CASCADE'), nullable=False)

    # Generated content (LLM-created)
    perspectives = db.Column(db.JSON)  # {'left': '...', 'center': '...', 'right': '...'}
    so_what = db.Column(db.Text)  # "So what?" analysis
    personal_impact = db.Column(db.Text)  # "Why This Matters To You"

    # Cache metadata
    generated_date = db.Column(db.Date, nullable=False)  # Date generated for (allows re-generation)
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    trending_topic = db.relationship('TrendingTopic', backref='news_perspective_cache')

    def to_dict(self):
        return {
            'id': self.id,
            'trending_topic_id': self.trending_topic_id,
            'perspectives': self.perspectives,
            'so_what': self.so_what,
            'personal_impact': self.personal_impact,
            'generated_date': self.generated_date.isoformat() if self.generated_date else None,
            'generated_at': self.generated_at.isoformat() if self.generated_at else None
        }

    def __repr__(self):
        return f'<NewsPerspectiveCache topic_id={self.trending_topic_id} date={self.generated_date}>'


class AudioGenerationJob(db.Model):
    """
    Tracks batch audio generation jobs for daily briefs.

    Allows generating audio for all items in a brief at once,
    with progress tracking and status updates.

    Optimized for Replit deployment with stale job recovery.
    """
    __tablename__ = 'audio_generation_job'
    __table_args__ = (
        db.Index('idx_audio_job_brief', 'brief_id'),
        db.Index('idx_audio_job_status', 'status'),
    )

    id = db.Column(db.Integer, primary_key=True)
    
    # Support both DailyBrief and BriefRun (polymorphic)
    brief_type = db.Column(db.String(20), nullable=False, default='daily_brief')  # 'daily_brief' | 'brief_run'
    brief_id = db.Column(db.Integer, db.ForeignKey('daily_brief.id', ondelete='CASCADE'), nullable=True)  # For DailyBrief
    brief_run_id = db.Column(db.Integer, db.ForeignKey('brief_run.id', ondelete='CASCADE'), nullable=True)  # For BriefRun
    
    voice_id = db.Column(db.String(100), nullable=True)  # XTTS voice ID

    status = db.Column(db.String(20), nullable=False, default='queued')  # queued, processing, completed, failed
    progress = db.Column(db.Integer, default=0)  # 0-100 percentage
    total_items = db.Column(db.Integer, nullable=False)
    completed_items = db.Column(db.Integer, default=0)
    failed_items = db.Column(db.Integer, default=0)  # Track items that failed to generate
    error_message = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    brief = db.relationship('DailyBrief', backref='audio_jobs', foreign_keys=[brief_id])
    brief_run = db.relationship('BriefRun', backref='audio_jobs', foreign_keys=[brief_run_id])

    @property
    def progress_percentage(self):
        """Calculate progress percentage based on processed items (completed + failed)."""
        if self.total_items == 0:
            return 0
        processed = (self.completed_items or 0) + (self.failed_items or 0)
        # Cap at 100% to handle edge cases
        return min(int((processed / self.total_items) * 100), 100)

    @property
    def is_stale(self):
        """Check if job is stuck in processing for too long (30 minutes)."""
        if self.status != 'processing' or not self.started_at:
            return False
        return datetime.utcnow() - self.started_at > timedelta(minutes=30)

    def to_dict(self):
        return {
            'id': self.id,
            'brief_type': self.brief_type,
            'brief_id': self.brief_id,
            'brief_run_id': self.brief_run_id,
            'voice_id': self.voice_id,
            'status': self.status,
            'progress': self.progress_percentage,
            'total_items': self.total_items,
            'completed_items': self.completed_items or 0,
            'failed_items': self.failed_items or 0,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }

    def __repr__(self):
        return f'<AudioGenerationJob brief_id={self.brief_id} status={self.status} progress={self.progress_percentage}%>'


class AdminSettings(db.Model):
    """
    Key-value store for admin configuration settings.

    Allows adjusting system parameters (like news page quality thresholds)
    without code deployments. Settings can be updated via admin UI.
    """
    __tablename__ = 'admin_settings'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.JSON, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    # Relationships
    updated_by = db.relationship('User', backref='admin_settings')

    @classmethod
    def get(cls, key: str, default=None):
        """Get setting value by key, or return default if not found."""
        setting = cls.query.filter_by(key=key).first()
        return setting.value if setting else default

    @classmethod
    def set(cls, key: str, value, user_id: int = None):
        """Set setting value, creating or updating as needed."""
        setting = cls.query.filter_by(key=key).first()
        if setting:
            setting.value = value
            setting.updated_by_id = user_id
        else:
            setting = cls(key=key, value=value, updated_by_id=user_id)
            db.session.add(setting)
        db.session.commit()

    def to_dict(self):
        return {
            'id': self.id,
            'key': self.key,
            'value': self.value,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'updated_by_id': self.updated_by_id
        }

    def __repr__(self):
        return f'<AdminSettings {self.key}>'


class DailyBriefSubscriber(db.Model):
    """
    Subscribers to daily brief (separate from daily question).
    Supports paid tiers and timezone preferences.
    """
    __tablename__ = 'daily_brief_subscriber'
    __table_args__ = (
        db.Index('idx_dbs_email', 'email'),
        db.Index('idx_dbs_token', 'magic_token'),
        db.Index('idx_dbs_team', 'team_id'),
        db.Index('idx_dbs_status', 'status'),
        db.Index('idx_dbs_tier_status', 'tier', 'status'),  # Composite index for tier+status queries
    )

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True)

    # Subscription tier
    tier = db.Column(db.String(20), default='trial')  # trial|free|individual|team
    trial_started_at = db.Column(db.DateTime)
    trial_ends_at = db.Column(db.DateTime)  # 30-day trial

    # Team management
    team_id = db.Column(db.Integer, db.ForeignKey('brief_team.id'), nullable=True)

    # Preferences
    timezone = db.Column(db.String(50), default='UTC')  # e.g., 'Europe/London', 'America/New_York'
    preferred_send_hour = db.Column(db.Integer, default=18)  # 6pm in their timezone (options: 6, 8, 18)

    # Status
    status = db.Column(db.String(20), default='active')  # active|unsubscribed|bounced|payment_failed
    unsubscribed_at = db.Column(db.DateTime)

    # Magic link auth (reuse pattern from DailyQuestionSubscriber)
    magic_token = db.Column(db.String(64), unique=True)
    magic_token_expires = db.Column(db.DateTime)

    # Stripe integration
    stripe_customer_id = db.Column(db.String(255))
    stripe_subscription_id = db.Column(db.String(255))
    subscription_expires_at = db.Column(db.DateTime)  # For grace period

    # Optional: Link to User account
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    # Tracking
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_sent_at = db.Column(db.DateTime)
    total_briefs_received = db.Column(db.Integer, default=0)
    welcome_email_sent_at = db.Column(db.DateTime)  # Prevents duplicate welcome emails

    # Email analytics
    total_opens = db.Column(db.Integer, default=0)
    total_clicks = db.Column(db.Integer, default=0)
    last_opened_at = db.Column(db.DateTime)
    last_clicked_at = db.Column(db.DateTime)

    # Relationships
    user = db.relationship('User', backref='brief_subscription')
    team = db.relationship('BriefTeam', backref='members')

    def generate_magic_token(self, expires_hours=48):
        """Generate a new magic link token"""
        import secrets
        self.magic_token = secrets.token_urlsafe(32)
        self.magic_token_expires = datetime.utcnow() + timedelta(hours=expires_hours)
        return self.magic_token

    @staticmethod
    def verify_magic_token(token):
        """Verify magic token and return subscriber if valid"""
        subscriber = DailyBriefSubscriber.query.filter_by(
            magic_token=token,
            status='active'
        ).first()

        if not subscriber:
            return None

        if subscriber.magic_token_expires and subscriber.magic_token_expires < datetime.utcnow():
            return None

        return subscriber

    def start_trial(self, days=30):
        """Start free trial with specified duration (default 30 days)"""
        self.tier = 'trial'
        self.trial_started_at = datetime.utcnow()
        self.trial_ends_at = datetime.utcnow() + timedelta(days=days)
        self.status = 'active'

    def extend_trial(self, additional_days=30):
        """Extend trial by specified number of days"""
        if not self.trial_ends_at:
            self.trial_ends_at = datetime.utcnow()
        self.trial_ends_at = self.trial_ends_at + timedelta(days=additional_days)
        self.tier = 'trial'

    def grant_free_access(self):
        """Grant permanent free access (admin use only)"""
        self.tier = 'free'
        self.trial_ends_at = None  # No expiration
        self.subscription_expires_at = None
        self.status = 'active'

    @property
    def trial_days_remaining(self):
        """Returns days remaining in trial, or None if not on trial"""
        if self.tier != 'trial' or not self.trial_ends_at:
            return None
        remaining = (self.trial_ends_at - datetime.utcnow()).days
        return max(0, remaining)

    @property
    def is_trial_expired(self):
        """Check if trial has expired"""
        if self.tier != 'trial':
            return False
        if not self.trial_ends_at:
            return True
        return datetime.utcnow() > self.trial_ends_at

    @property
    def subscription_status_display(self):
        """Human-readable subscription status for admin UI"""
        if self.tier == 'free':
            return 'Free (Admin)'
        elif self.tier == 'trial':
            if self.is_trial_expired:
                return 'Trial Expired'
            days = self.trial_days_remaining
            if days == 0:
                return 'Trial Expires Today'
            elif days == 1:
                return 'Trial: 1 day left'
            else:
                return f'Trial: {days} days left'
        elif self.tier in ['individual', 'team']:
            if self.subscription_expires_at:
                if datetime.utcnow() > self.subscription_expires_at:
                    return f'{self.tier.title()} (Expired)'
                return f'{self.tier.title()} (Active)'
            return f'{self.tier.title()} (Pending)'
        return 'Unknown'

    def is_subscribed_eligible(self):
        """Check if subscriber should receive emails
        
        Tier values:
        - 'trial': 30-day free trial, expires at trial_ends_at
        - 'free': Admin-granted permanent free access (never expires)
        - 'individual': Paid individual subscription via Stripe
        - 'team': Team subscription via Stripe
        """
        if self.status != 'active':
            return False

        # Admin-granted free tier: always eligible
        if self.tier == 'free':
            return True

        # During test phase: everyone gets access (check env var)
        import os
        if not os.environ.get('BILLING_ENFORCEMENT_ENABLED'):
            return True

        # Post-launch: check subscription status
        if self.tier == 'trial':
            if not self.trial_ends_at:
                return False
            return datetime.utcnow() < self.trial_ends_at

        if self.tier in ['individual', 'team']:
            # Check Stripe subscription status
            return self.subscription_expires_at and datetime.utcnow() < self.subscription_expires_at

        return False

    def has_received_brief_today(self, brief_date=None):
        """Check if subscriber already received brief for given date (prevents duplicate sends)"""
        from datetime import date as date_type
        if brief_date is None:
            brief_date = date_type.today()

        if not self.last_sent_at:
            return False

        return self.last_sent_at.date() == brief_date

    def can_receive_brief(self, brief_date=None):
        """Full eligibility check including duplicate prevention"""
        if not self.is_subscribed_eligible():
            return False

        if self.has_received_brief_today(brief_date):
            return False

        return True

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'tier': self.tier,
            'timezone': self.timezone,
            'preferred_send_hour': self.preferred_send_hour,
            'status': self.status,
            'is_eligible': self.is_subscribed_eligible(),
            'trial_ends_at': self.trial_ends_at.isoformat() if self.trial_ends_at else None,
            'trial_days_remaining': self.trial_days_remaining,
            'is_trial_expired': self.is_trial_expired,
            'subscription_status_display': self.subscription_status_display
        }

    def __repr__(self):
        return f'<DailyBriefSubscriber {self.email} ({self.tier})>'


class BriefTeam(db.Model):
    """
    Multi-seat team subscriptions for daily brief.
    """
    __tablename__ = 'brief_team'
    __table_args__ = (
        db.Index('idx_brief_team_admin', 'admin_email'),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255))

    # Billing
    seat_limit = db.Column(db.Integer, default=5)
    price_per_seat = db.Column(db.Integer, default=800)  # $8.00 in cents (team rate)
    base_price = db.Column(db.Integer, default=4000)  # $40/month for 5 seats

    # Stripe
    stripe_customer_id = db.Column(db.String(255))
    stripe_subscription_id = db.Column(db.String(255))

    # Admin contact
    admin_email = db.Column(db.String(255))  # Who manages the team

    # Status
    status = db.Column(db.String(20), default='active')  # active|cancelled|payment_failed

    # Tracking
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def current_seat_count(self):
        """Number of active members"""
        return DailyBriefSubscriber.query.filter_by(
            team_id=self.id,
            status='active'
        ).count()

    @property
    def has_available_seats(self):
        """Check if team has available seats"""
        return self.current_seat_count < self.seat_limit

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'seat_limit': self.seat_limit,
            'current_seat_count': self.current_seat_count,
            'has_available_seats': self.has_available_seats,
            'admin_email': self.admin_email,
            'status': self.status
        }

    def __repr__(self):
        return f'<BriefTeam {self.name} ({self.current_seat_count}/{self.seat_limit} seats)>'


class EmailEvent(db.Model):
    """
    Unified email event tracking for all email types.
    Tracks opens, clicks, bounces from Resend webhooks.
    
    Email categories:
    - auth: Password reset, welcome, account activation
    - daily_brief: Daily Brief emails
    - daily_question: Daily Question emails
    - discussion: Discussion notification emails
    - admin: Admin-generated emails
    """
    __tablename__ = 'email_event'
    __table_args__ = (
        db.Index('idx_ee_email', 'recipient_email'),
        db.Index('idx_ee_category', 'email_category'),
        db.Index('idx_ee_event_type', 'event_type'),
        db.Index('idx_ee_created', 'created_at'),
        db.Index('idx_ee_resend_id', 'resend_email_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    
    # Email identification (generic - works for any email type)
    recipient_email = db.Column(db.String(255), nullable=False)
    resend_email_id = db.Column(db.String(255), index=True)  # Resend's email ID
    
    # Email categorization
    email_category = db.Column(db.String(30), nullable=False)  # auth, daily_brief, daily_question, discussion, admin
    email_subject = db.Column(db.String(500))  # Store subject for reference
    
    # Event data from Resend
    event_type = db.Column(db.String(50), nullable=False)  # sent, delivered, opened, clicked, bounced, complained
    
    # Optional references (for analytics drill-down)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    brief_subscriber_id = db.Column(db.Integer, db.ForeignKey('daily_brief_subscriber.id'), nullable=True)
    question_subscriber_id = db.Column(db.Integer, db.ForeignKey('daily_question_subscriber.id'), nullable=True)
    brief_id = db.Column(db.Integer, db.ForeignKey('daily_brief.id'), nullable=True)
    daily_question_id = db.Column(db.Integer, db.ForeignKey('daily_question.id'), nullable=True)
    
    # Additional event data
    click_url = db.Column(db.String(500))  # For click events
    bounce_type = db.Column(db.String(50))  # hard, soft
    complaint_type = db.Column(db.String(50))  # spam, abuse
    user_agent = db.Column(db.String(500))
    ip_address = db.Column(db.String(45))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref='email_events')
    brief_subscriber = db.relationship('DailyBriefSubscriber', backref='email_events')
    question_subscriber = db.relationship('DailyQuestionSubscriber', backref='email_events')
    brief = db.relationship('DailyBrief', backref='email_events')
    daily_question = db.relationship('DailyQuestion', backref='email_events')

    # Class constants for email categories
    CATEGORY_AUTH = 'auth'
    CATEGORY_DAILY_BRIEF = 'daily_brief'
    CATEGORY_DAILY_QUESTION = 'daily_question'
    CATEGORY_DISCUSSION = 'discussion'
    CATEGORY_ADMIN = 'admin'
    
    # Class constants for event types (without email. prefix for clean storage)
    EVENT_SENT = 'sent'
    EVENT_DELIVERED = 'delivered'
    EVENT_OPENED = 'opened'
    EVENT_CLICKED = 'clicked'
    EVENT_BOUNCED = 'bounced'
    EVENT_COMPLAINED = 'complained'

    @classmethod
    def record_event(cls, recipient_email: str, event_type: str, email_category: str,
                     resend_email_id: Optional[str] = None, email_subject: Optional[str] = None,
                     user_id: Optional[int] = None, brief_subscriber_id: Optional[int] = None,
                     question_subscriber_id: Optional[int] = None, brief_id: Optional[int] = None,
                     daily_question_id: Optional[int] = None, click_url: Optional[str] = None,
                     bounce_type: Optional[str] = None, complaint_type: Optional[str] = None,
                     user_agent: Optional[str] = None, ip_address: Optional[str] = None):
        """
        Factory method to record an email event.
        DRY: Single point of entry for all event recording.
        
        Args:
            recipient_email: Required - email address of recipient
            event_type: Required - type of event (sent, delivered, opened, etc.)
            email_category: Required - category (auth, daily_brief, etc.)
            
        Returns:
            EmailEvent instance or None if validation fails
        """
        if not recipient_email or not event_type or not email_category:
            import logging
            logging.getLogger(__name__).error(
                f"EmailEvent.record_event missing required fields: "
                f"email={recipient_email}, type={event_type}, category={email_category}"
            )
            return None
        
        # Normalize event_type (remove 'email.' prefix if present)
        if event_type.startswith('email.'):
            event_type = event_type[6:]
        
        event = cls(
            recipient_email=recipient_email,
            resend_email_id=resend_email_id,
            email_category=email_category,
            email_subject=email_subject,
            event_type=event_type,
            user_id=user_id,
            brief_subscriber_id=brief_subscriber_id,
            question_subscriber_id=question_subscriber_id,
            brief_id=brief_id,
            daily_question_id=daily_question_id,
            click_url=click_url,
            bounce_type=bounce_type,
            complaint_type=complaint_type,
            user_agent=user_agent,
            ip_address=ip_address
        )
        db.session.add(event)
        return event

    @classmethod
    def get_stats(cls, email_category: Optional[str] = None, days: int = 7) -> dict:
        """
        Get aggregated statistics for emails.
        DRY: Reusable stats method for any category.
        email_category can be None to get stats for all categories.
        """
        from sqlalchemy import func
        
        cutoff = datetime.utcnow() - timedelta(days=days)
        query = cls.query.filter(cls.created_at >= cutoff)
        
        if email_category:
            query = query.filter(cls.email_category == email_category)
        
        # Count by event type
        event_counts = db.session.query(
            cls.event_type,
            func.count(cls.id)
        ).filter(cls.created_at >= cutoff)
        
        if email_category:
            event_counts = event_counts.filter(cls.email_category == email_category)
        
        event_counts = dict(event_counts.group_by(cls.event_type).all())
        
        total_sent = event_counts.get('sent', 0)
        total_delivered = event_counts.get('delivered', 0)
        total_opened = event_counts.get('opened', 0)
        total_clicked = event_counts.get('clicked', 0)
        total_bounced = event_counts.get('bounced', 0)
        total_complained = event_counts.get('complained', 0)
        
        return {
            'total_sent': total_sent,
            'total_delivered': total_delivered,
            'total_opened': total_opened,
            'total_clicked': total_clicked,
            'total_bounced': total_bounced,
            'total_complained': total_complained,
            'delivery_rate': round((total_delivered / total_sent * 100), 1) if total_sent > 0 else 0,
            'open_rate': round((total_opened / total_delivered * 100), 1) if total_delivered > 0 else 0,
            'click_rate': round((total_clicked / total_opened * 100), 1) if total_opened > 0 else 0,
            'bounce_rate': round((total_bounced / total_sent * 100), 1) if total_sent > 0 else 0,
            'event_counts': event_counts
        }

    @classmethod
    def get_recent_events(cls, email_category: Optional[str] = None, limit: int = 50):
        """Get recent events, optionally filtered by category."""
        query = cls.query.order_by(cls.created_at.desc())
        if email_category:
            query = query.filter(cls.email_category == email_category)
        return query.limit(limit).all()

    def to_dict(self):
        return {
            'id': self.id,
            'recipient_email': self.recipient_email,
            'email_category': self.email_category,
            'email_subject': self.email_subject,
            'event_type': self.event_type,
            'click_url': self.click_url,
            'bounce_type': self.bounce_type,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<EmailEvent {self.event_type} ({self.email_category}) to {self.recipient_email}>'


# Backward compatibility alias
BriefEmailEvent = EmailEvent


class DailyQuestion(db.Model):
    """
    Daily Civic Question - Wordle-like daily participation ritual.
    Links to existing discussions/statements as question source.
    One question per day, designed for finite, low-friction engagement.
    """
    __tablename__ = 'daily_question'
    __table_args__ = (
        db.Index('idx_daily_question_date', 'question_date'),
        db.Index('idx_daily_question_status', 'status'),
        db.UniqueConstraint('question_date', name='uq_daily_question_date'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    
    question_date = db.Column(db.Date, nullable=False, unique=True)
    question_number = db.Column(db.Integer, nullable=False)
    
    question_text = db.Column(db.String(500), nullable=False)
    context = db.Column(db.Text)
    why_this_question = db.Column(db.String(300))
    
    source_type = db.Column(db.String(20), default='discussion')
    source_discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=True)
    source_statement_id = db.Column(db.Integer, db.ForeignKey('statement.id'), nullable=True)
    source_trending_topic_id = db.Column(db.Integer, db.ForeignKey('trending_topic.id'), nullable=True)
    
    topic_category = db.Column(db.String(100))
    
    status = db.Column(db.String(20), default='scheduled')
    
    cold_start_threshold = db.Column(db.Integer, default=20)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    published_at = db.Column(db.DateTime)

    # Polymarket Integration (optional, for consensus divergence feature)
    polymarket_market_id = db.Column(db.Integer, db.ForeignKey('polymarket_market.id'), nullable=True)

    source_discussion = db.relationship('Discussion', backref='daily_questions')
    source_statement = db.relationship('Statement', backref='daily_questions')
    source_trending_topic = db.relationship('TrendingTopic', backref='daily_questions')
    created_by = db.relationship('User', backref='created_daily_questions')
    
    @property
    def response_count(self):
        """Total number of responses to this daily question.
        
        Uses cached count if available (set by batch queries in admin routes)
        to prevent N+1 query issues.
        """
        # Check for cached count (set by admin list routes to prevent N+1)
        if hasattr(self, '_cached_response_count'):
            return self._cached_response_count
        return DailyQuestionResponse.query.filter_by(daily_question_id=self.id).count()
    
    @property
    def is_cold_start(self):
        """Check if below cold start threshold"""
        return self.response_count < self.cold_start_threshold
    
    @property
    def vote_percentages(self):
        """Calculate vote percentages"""
        responses = DailyQuestionResponse.query.filter_by(daily_question_id=self.id).all()
        total = len(responses)
        if total == 0:
            return {'agree': 0, 'disagree': 0, 'unsure': 0, 'total': 0}
        
        agree = sum(1 for r in responses if r.vote == 1)
        disagree = sum(1 for r in responses if r.vote == -1)
        unsure = sum(1 for r in responses if r.vote == 0)
        
        return {
            'agree': round((agree / total) * 100),
            'disagree': round((disagree / total) * 100),
            'unsure': round((unsure / total) * 100),
            'total': total
        }
    
    @property
    def early_signal_message(self):
        """Generate cold start early signal message"""
        stats = self.vote_percentages
        if stats['total'] == 0:
            return "Be the first to respond to today's question."

        if stats['agree'] > stats['disagree'] + 20:
            return "Early responses lean toward agreement."
        elif stats['disagree'] > stats['agree'] + 20:
            return "Early responses lean toward disagreement."
        elif stats['unsure'] > 30:
            return "Early responses show uncertainty on this topic."
        else:
            return "Early responses suggest opinions are still forming."

    @property
    def market_divergence(self) -> Optional[dict]:
        """
        Calculate divergence between user votes and market probability.
        Returns None if no market linked or insufficient data.

        Returns:
            {
                'user_probability': 0.62,  # % of users who voted "agree"
                'market_probability': 0.78,
                'divergence': 0.16,
                'is_significant': True,  # divergence >= 0.15
                'direction': 'lower',  # users are 'higher' or 'lower' than market
                'market_question': "Will X happen?",
                'market_url': "https://polymarket.com/..."
            }
        """
        if not self.polymarket_market_id:
            return None

        # Import here to avoid circular import
        market = PolymarketMarket.query.get(self.polymarket_market_id)
        if not market or market.probability is None:
            return None

        vote_pcts = self.vote_percentages
        if vote_pcts.get('total', 0) < 10:  # Need minimum votes for meaningful comparison
            return None

        # User "agree" percentage as probability estimate
        user_prob = vote_pcts.get('agree', 0) / 100
        market_prob = market.probability
        divergence = abs(user_prob - market_prob)

        return {
            'user_probability': user_prob,
            'market_probability': market_prob,
            'divergence': divergence,
            'is_significant': divergence >= 0.15,  # 15+ points = interesting
            'direction': 'higher' if user_prob > market_prob else 'lower',
            'market_question': market.question,
            'market_url': market.polymarket_url,
            'market_change_24h': market.change_24h_formatted
        }

    @classmethod
    def get_today(cls):
        """Get today's daily question"""
        from datetime import date
        today = date.today()
        return cls.query.filter_by(question_date=today, status='published').first()
    
    @classmethod
    def get_by_date(cls, question_date):
        """Get daily question for a specific date"""
        return cls.query.filter_by(question_date=question_date, status='published').first()
    
    @classmethod
    def get_next_question_number(cls):
        """Get the next question number"""
        last = cls.query.order_by(cls.question_number.desc()).first()
        return (last.question_number + 1) if last else 1
    
    def to_dict(self):
        return {
            'id': self.id,
            'question_date': self.question_date.isoformat(),
            'question_number': self.question_number,
            'question_text': self.question_text,
            'context': self.context,
            'why_this_question': self.why_this_question,
            'topic_category': self.topic_category,
            'status': self.status,
            'response_count': self.response_count,
            'is_cold_start': self.is_cold_start,
            'vote_percentages': self.vote_percentages,
            'created_at': self.created_at.isoformat()
        }
    
    def __repr__(self):
        return f'<DailyQuestion #{self.question_number} ({self.question_date})>'


class DailyQuestionResponse(db.Model):
    """
    User response to a daily question.
    Simplified voting with optional reason.
    """
    __tablename__ = 'daily_question_response'
    __table_args__ = (
        db.Index('idx_dqr_question', 'daily_question_id'),
        db.Index('idx_dqr_user', 'user_id'),
        db.Index('idx_dqr_date', 'created_at'),
        db.UniqueConstraint('daily_question_id', 'user_id', name='uq_daily_question_user'),
        db.UniqueConstraint('daily_question_id', 'session_fingerprint', name='uq_daily_question_session'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    daily_question_id = db.Column(db.Integer, db.ForeignKey('daily_question.id'), nullable=False)
    
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    session_fingerprint = db.Column(db.String(64), nullable=True)
    
    vote = db.Column(db.SmallInteger, nullable=False)
    
    reason = db.Column(db.String(500), nullable=True)
    
    # Visibility for reason: 'public_named', 'public_anonymous', 'private'
    # Defaults to 'public_anonymous' for email subscribers, 'public_named' for logged-in users
    reason_visibility = db.Column(db.String(20), default='public_anonymous')
    
    # Track if vote was submitted via one-click email (no reason prompt shown initially)
    voted_via_email = db.Column(db.Boolean, default=False)

    # Track which question the email was about (for analytics on vote mismatch patterns)
    # If user clicks old email link, this will differ from daily_question_id
    email_question_id = db.Column(db.Integer, db.ForeignKey('daily_question.id'), nullable=True)

    # Moderation flags
    is_hidden = db.Column(db.Boolean, default=False)  # Hidden by admin or auto-flagged
    flag_count = db.Column(db.Integer, default=0)  # Number of user flags
    reviewed_by_admin = db.Column(db.Boolean, default=False)  # Admin has reviewed
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    daily_question = db.relationship('DailyQuestion', foreign_keys=[daily_question_id], backref='responses')
    email_question = db.relationship('DailyQuestion', foreign_keys=[email_question_id], backref='email_responses')
    user = db.relationship('User', foreign_keys=[user_id], backref='daily_question_responses')
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_user_id], backref='reviewed_comments')
    
    @validates('vote')
    def validate_vote(self, key, vote):
        """Ensure vote is -1, 0, or 1"""
        if vote not in [-1, 0, 1]:
            raise ValueError("Vote must be -1 (disagree), 0 (unsure), or 1 (agree)")
        return vote
    
    @validates('reason')
    def validate_reason(self, key, reason):
        """Validate reason length (280-500 chars if provided)"""
        if reason and len(reason) > 500:
            raise ValueError("Reason must not exceed 500 characters")
        return reason
    
    @property
    def vote_emoji(self):
        """Return emoji block for sharing"""
        emoji_map = {1: '🟦', -1: '🟥', 0: '🟨'}
        return emoji_map.get(self.vote, '⬜')
    
    @property
    def vote_label(self):
        """Return human-readable vote label"""
        label_map = {1: 'Agree', -1: 'Disagree', 0: 'Unsure'}
        return label_map.get(self.vote, 'Unknown')
    
    def to_dict(self):
        return {
            'id': self.id,
            'daily_question_id': self.daily_question_id,
            'vote': self.vote,
            'vote_label': self.vote_label,
            'vote_emoji': self.vote_emoji,
            'reason': self.reason,
            'reason_visibility': self.reason_visibility,
            'voted_via_email': self.voted_via_email,
            'created_at': self.created_at.isoformat()
        }
    
    @property
    def display_name(self):
        """Return display name based on visibility setting"""
        if self.reason_visibility == 'public_named' and self.user:
            return self.user.display_name or self.user.email.split('@')[0]
        elif self.reason_visibility == 'public_anonymous':
            return 'Someone'
        return None
    
    @property
    def is_reason_public(self):
        """Check if the reason should be publicly visible"""
        return self.reason and self.reason_visibility in ('public_named', 'public_anonymous')
    
    def __repr__(self):
        return f'<DailyQuestionResponse {self.vote_label} on Q#{self.daily_question_id}>'


class DailyQuestionResponseFlag(db.Model):
    """
    User flags for inappropriate daily question responses.
    Enables community moderation and admin review.
    """
    __tablename__ = 'daily_question_response_flag'
    __table_args__ = (
        db.Index('idx_dqrf_response', 'response_id'),
        db.Index('idx_dqrf_status', 'status'),
        db.Index('idx_dqrf_created', 'created_at'),
        # Prevent duplicate flags from same user on same response
        db.UniqueConstraint('response_id', 'flagged_by_fingerprint', name='uq_response_flag_fingerprint'),
    )

    id = db.Column(db.Integer, primary_key=True)
    response_id = db.Column(db.Integer, db.ForeignKey('daily_question_response.id'), nullable=False)

    # Who flagged (can be anonymous via fingerprint)
    flagged_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    flagged_by_fingerprint = db.Column(db.String(64), nullable=True)

    # Flag details
    reason = db.Column(db.String(50), nullable=False)  # 'spam', 'harassment', 'misinformation', 'other'
    details = db.Column(db.String(500), nullable=True)  # Optional explanation

    # Status tracking
    status = db.Column(db.String(20), default='pending')  # 'pending', 'reviewed_valid', 'reviewed_invalid', 'dismissed'
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    review_notes = db.Column(db.String(500), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    response = db.relationship('DailyQuestionResponse', backref='flags')
    flagged_by = db.relationship('User', foreign_keys=[flagged_by_user_id], backref='daily_response_flags_submitted')
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_user_id], backref='daily_response_flags_reviewed')

    def to_dict(self):
        return {
            'id': self.id,
            'response_id': self.response_id,
            'reason': self.reason,
            'details': self.details,
            'status': self.status,
            'created_at': self.created_at.isoformat(),
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None
        }

    def __repr__(self):
        return f'<DailyQuestionResponseFlag {self.reason} on Response#{self.response_id}>'


class DailyQuestionSubscriber(db.Model):
    """
    Email-only subscriber for Daily Civic Questions.
    Supports magic-link voting without requiring a full account.
    """
    __tablename__ = 'daily_question_subscriber'
    __table_args__ = (
        db.Index('idx_dqs_email', 'email'),
        db.Index('idx_dqs_token', 'magic_token'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True)
    
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    is_active = db.Column(db.Boolean, default=True)
    
    magic_token = db.Column(db.String(64), unique=True)
    token_expires_at = db.Column(db.DateTime)
    
    current_streak = db.Column(db.Integer, default=0)
    longest_streak = db.Column(db.Integer, default=0)
    last_participation_date = db.Column(db.Date)
    thoughtful_participations = db.Column(db.Integer, default=0)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_email_sent = db.Column(db.DateTime)

    # Track unsubscribe reason: 'too_frequent', 'not_interested', 'content_quality', 'other'
    unsubscribe_reason = db.Column(db.String(50), nullable=True)
    unsubscribed_at = db.Column(db.DateTime, nullable=True)

    # Weekly digest email preferences
    email_frequency = db.Column(db.String(20), default='weekly')  # 'daily'|'weekly'|'monthly'
    last_weekly_email_sent = db.Column(db.DateTime, nullable=True)
    preferred_send_day = db.Column(db.Integer, default=1)  # 0=Mon, 1=Tue (default), ..., 6=Sun
    preferred_send_hour = db.Column(db.Integer, default=9)  # 0-23, default 9am
    timezone = db.Column(db.String(50), nullable=True)  # e.g., 'Europe/London', 'America/New_York'

    user = db.relationship('User', backref='daily_subscription')
    
    def generate_magic_token(self, expires_hours=48):
        """Generate a new magic link token for login/authentication"""
        import secrets
        self.magic_token = secrets.token_urlsafe(32)
        self.token_expires_at = datetime.utcnow() + timedelta(hours=expires_hours)
        return self.magic_token

    def generate_vote_token(self, question_id, expires_hours=None):
        """
        Generate a question-specific vote token with longer expiration (7 days default).

        Uses signed tokens that embed the question_id, preventing old email links
        from voting on wrong questions. More secure than reusing magic_token.

        Args:
            question_id: The daily question ID this token is for
            expires_hours: Token expiration in hours (default from constants)

        Returns:
            Signed token string containing subscriber_id and question_id
        """
        from app.daily.constants import VOTE_TOKEN_EXPIRY_HOURS
        
        if expires_hours is None:
            expires_hours = VOTE_TOKEN_EXPIRY_HOURS
            
        s = Serializer(current_app.config['SECRET_KEY'])
        token = s.dumps({
            'subscriber_id': self.id,
            'question_id': question_id,
            'type': 'vote'
        })
        
        current_app.logger.debug(
            f"Generated vote token for subscriber {self.id}, question {question_id} "
            f"(expires in {expires_hours}h)"
        )
        return token

    @staticmethod
    def verify_vote_token(token, max_age=None):
        """
        Verify a question-specific vote token and return (subscriber, question_id, error) tuple.

        Args:
            token: The signed token to verify
            max_age: Maximum token age in seconds (default from constants)

        Returns:
            Tuple of (DailyQuestionSubscriber, question_id, error_code) where:
            - Success: (subscriber, question_id, None)
            - Expired token: (None, None, 'expired')
            - Invalid/tampered token: (None, None, 'invalid')
            - Wrong token type: (None, None, 'invalid_type')
            - Subscriber not found/inactive: (None, None, 'subscriber_not_found')
        """
        from itsdangerous import SignatureExpired, BadSignature
        from app.daily.constants import VOTE_TOKEN_EXPIRY_SECONDS
        
        if max_age is None:
            max_age = VOTE_TOKEN_EXPIRY_SECONDS
            
        s = Serializer(current_app.config['SECRET_KEY'])
        
        try:
            data = s.loads(token, max_age=max_age)
        except SignatureExpired:
            current_app.logger.info(f"Vote token expired")
            return None, None, 'expired'
        except BadSignature:
            current_app.logger.warning(f"Invalid vote token signature")
            return None, None, 'invalid'
        except Exception as e:
            current_app.logger.error(f"Unexpected error verifying vote token: {e}")
            return None, None, 'invalid'

        if data.get('type') != 'vote':
            current_app.logger.warning(f"Token type mismatch: expected 'vote', got '{data.get('type')}'")
            return None, None, 'invalid_type'

        subscriber = DailyQuestionSubscriber.query.filter_by(
            id=data.get('subscriber_id'),
            is_active=True
        ).first()

        if not subscriber:
            current_app.logger.info(f"Subscriber {data.get('subscriber_id')} not found or inactive")
            return None, None, 'subscriber_not_found'

        return subscriber, data.get('question_id'), None

    @staticmethod
    def verify_magic_token(token):
        """Verify magic token and return subscriber if valid"""
        subscriber = DailyQuestionSubscriber.query.filter_by(
            magic_token=token,
            is_active=True
        ).first()

        if not subscriber:
            return None

        if subscriber.token_expires_at and subscriber.token_expires_at < datetime.utcnow():
            return None

        return subscriber
    
    def has_received_email_today(self):
        """Check if subscriber already received daily question email today (prevents duplicate sends)"""
        from datetime import date as date_type
        if not self.last_email_sent:
            return False
        return self.last_email_sent.date() == date_type.today()
    
    def can_receive_email(self):
        """Full eligibility check including duplicate prevention"""
        if not self.is_active:
            return False
        if self.has_received_email_today():
            return False
        return True
    
    def update_participation_streak(self, has_reason=False):
        """Update participation streak after a vote"""
        from datetime import date
        today = date.today()
        
        if self.last_participation_date:
            days_since = (today - self.last_participation_date).days
            
            if days_since == 0:
                pass
            elif days_since == 1:
                self.current_streak += 1
            else:
                self.current_streak = 1
        else:
            self.current_streak = 1
        
        if has_reason:
            self.thoughtful_participations += 1
        
        if self.current_streak > self.longest_streak:
            self.longest_streak = self.current_streak
        
        self.last_participation_date = today
    
    @property
    def is_thoughtful_participant(self):
        """Check if user provides reasons regularly (at least 3 times per week on average)"""
        if self.current_streak < 7:
            return self.thoughtful_participations >= self.current_streak * 0.5
        return self.thoughtful_participations >= self.current_streak * 0.4

    # Weekly digest helper constants
    SEND_DAYS = {
        0: 'Monday',
        1: 'Tuesday',
        2: 'Wednesday',
        3: 'Thursday',
        4: 'Friday',
        5: 'Saturday',
        6: 'Sunday'
    }
    VALID_EMAIL_FREQUENCIES = ['daily', 'weekly', 'monthly']

    def get_send_day_name(self):
        """Return human-readable send day name"""
        return self.SEND_DAYS.get(self.preferred_send_day, 'Tuesday')

    def should_receive_weekly_digest_now(self, utc_now=None):
        """
        Check if this subscriber should receive their weekly digest right now.
        Used by the hourly scheduler job.

        Args:
            utc_now: Current UTC datetime (optional, defaults to now)

        Returns:
            bool: True if it's the right day and hour in the subscriber's timezone
        """
        import pytz
        from flask import current_app

        if utc_now is None:
            utc_now = datetime.utcnow()

        # Only applies to weekly subscribers
        if self.email_frequency != 'weekly':
            return False

        # Get subscriber's timezone (default to UTC)
        try:
            tz = pytz.timezone(self.timezone) if self.timezone else pytz.UTC
        except pytz.exceptions.UnknownTimeZoneError:
            # Log timezone error for debugging
            if current_app:
                current_app.logger.warning(
                    f"Invalid timezone '{self.timezone}' for subscriber {self.id}, "
                    f"defaulting to UTC"
                )
            tz = pytz.UTC

        # Convert UTC to subscriber's local time
        try:
            local_now = utc_now.replace(tzinfo=pytz.UTC).astimezone(tz)
        except Exception as e:
            # Fallback to UTC on any timezone conversion error
            if current_app:
                current_app.logger.error(
                    f"Error converting timezone for subscriber {self.id}: {e}, "
                    f"defaulting to UTC"
                )
            local_now = utc_now.replace(tzinfo=pytz.UTC)

        # Check if it's the right day and hour
        return (local_now.weekday() == self.preferred_send_day and
                local_now.hour == self.preferred_send_hour)

    def has_received_weekly_digest_this_week(self):
        """Check if weekly digest was already sent this week (within last 6 days)"""
        if not self.last_weekly_email_sent:
            return False
        week_ago = datetime.utcnow() - timedelta(days=6)
        return self.last_weekly_email_sent > week_ago
    
    def has_received_monthly_digest_this_month(self):
        """Check if monthly digest was already sent this month (within last 25 days)"""
        if not self.last_weekly_email_sent:  # Reuse same field for monthly tracking
            return False
        month_ago = datetime.utcnow() - timedelta(days=25)
        return self.last_weekly_email_sent > month_ago
    
    def should_receive_monthly_digest_now(self, utc_now=None):
        """
        Check if this subscriber should receive their monthly digest right now.
        Monthly digests are sent on the 1st of each month at 9am in subscriber's timezone.

        Args:
            utc_now: Current UTC datetime (optional, defaults to now)

        Returns:
            bool: True if it's the 1st of the month and 9am in the subscriber's timezone
        """
        import pytz
        from flask import current_app

        if utc_now is None:
            utc_now = datetime.utcnow()

        # Only applies to monthly subscribers
        if self.email_frequency != 'monthly':
            return False

        # Get subscriber's timezone (default to UTC)
        try:
            tz = pytz.timezone(self.timezone) if self.timezone else pytz.UTC
        except pytz.exceptions.UnknownTimeZoneError:
            current_app.logger.warning(
                f"Invalid timezone '{self.timezone}' for subscriber {self.id}, defaulting to UTC"
            )
            tz = pytz.UTC

        # Convert UTC to subscriber's local time (ensure tzinfo is set)
        try:
            local_time = utc_now.replace(tzinfo=pytz.UTC).astimezone(tz)
        except Exception as e:
            # Fallback to UTC on any timezone conversion error
            if current_app:
                current_app.logger.error(
                    f"Error converting timezone for subscriber {self.id}: {e}, "
                    f"defaulting to UTC"
                )
            local_time = utc_now.replace(tzinfo=pytz.UTC)

        # Check if it's the 1st of the month and 9am (or within the hour)
        is_first_of_month = local_time.day == 1
        is_ninth_hour = local_time.hour == 9

        return is_first_of_month and is_ninth_hour

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'current_streak': self.current_streak,
            'longest_streak': self.longest_streak,
            'is_active': self.is_active
        }
    
    def __repr__(self):
        return f'<DailyQuestionSubscriber {self.email}>'


class DailyQuestionSelection(db.Model):
    """
    Track which content has been used for daily questions.
    Prevents repeating questions within a configurable time window.
    """
    __tablename__ = 'daily_question_selection'
    
    id = db.Column(db.Integer, primary_key=True)
    
    source_type = db.Column(db.String(20), nullable=False)
    source_discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=True)
    source_statement_id = db.Column(db.Integer, db.ForeignKey('statement.id'), nullable=True)
    source_trending_topic_id = db.Column(db.Integer, db.ForeignKey('trending_topic.id'), nullable=True)
    
    selected_at = db.Column(db.DateTime, default=datetime.utcnow)
    question_date = db.Column(db.Date, nullable=False)
    daily_question_id = db.Column(db.Integer, db.ForeignKey('daily_question.id'), nullable=True)
    
    @staticmethod
    def is_recently_used(source_type, source_id, days=30):
        """Check if a source has been used in the last N days"""
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        query = DailyQuestionSelection.query.filter(
            DailyQuestionSelection.source_type == source_type,
            DailyQuestionSelection.selected_at >= cutoff
        )
        
        if source_type == 'discussion':
            query = query.filter(DailyQuestionSelection.source_discussion_id == source_id)
        elif source_type == 'statement':
            query = query.filter(DailyQuestionSelection.source_statement_id == source_id)
        elif source_type == 'trending':
            query = query.filter(DailyQuestionSelection.source_trending_topic_id == source_id)
        
        return query.first() is not None


class SocialPostEngagement(db.Model):
    """
    Tracks engagement metrics for social media posts over time.

    Stores likes, retweets/reposts, replies, and impressions for posts
    on X and Bluesky. Updated periodically by scheduler job.
    """
    __tablename__ = 'social_post_engagement'

    id = db.Column(db.Integer, primary_key=True)

    # Link to discussion (nullable for non-discussion posts like daily brief)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=True, index=True)
    discussion = db.relationship('Discussion', backref=db.backref('social_engagements', lazy='dynamic'))

    # Platform and post identifier
    platform = db.Column(db.String(20), nullable=False)  # 'x' or 'bluesky'
    post_id = db.Column(db.String(500), nullable=False)  # Tweet ID or Bluesky URI

    # Content type for tracking different post types
    content_type = db.Column(db.String(50), nullable=False, default='discussion')  # 'discussion', 'daily_question', 'daily_brief', 'weekly_insights'

    # Hook variant used (for A/B testing)
    hook_variant = db.Column(db.String(50), nullable=True)

    # Engagement metrics
    likes = db.Column(db.Integer, default=0)
    reposts = db.Column(db.Integer, default=0)  # Retweets on X, reposts on Bluesky
    replies = db.Column(db.Integer, default=0)
    quotes = db.Column(db.Integer, default=0)
    impressions = db.Column(db.Integer, default=0)  # Views/impressions if available
    clicks = db.Column(db.Integer, default=0)  # Link clicks if available

    # Timestamps
    posted_at = db.Column(db.DateTime, nullable=False)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Unique constraint on platform + post_id
    __table_args__ = (
        db.UniqueConstraint('platform', 'post_id', name='uq_platform_post_id'),
    )

    @property
    def total_engagement(self) -> int:
        """Total engagement (likes + reposts + replies + quotes)."""
        return (self.likes or 0) + (self.reposts or 0) + (self.replies or 0) + (self.quotes or 0)

    @property
    def engagement_rate(self) -> float:
        """Engagement rate as percentage of impressions."""
        if not self.impressions or self.impressions == 0:
            return 0.0
        return (self.total_engagement / self.impressions) * 100

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'platform': self.platform,
            'post_id': self.post_id,
            'content_type': self.content_type,
            'hook_variant': self.hook_variant,
            'likes': self.likes,
            'reposts': self.reposts,
            'replies': self.replies,
            'quotes': self.quotes,
            'impressions': self.impressions,
            'clicks': self.clicks,
            'total_engagement': self.total_engagement,
            'engagement_rate': self.engagement_rate,
            'posted_at': self.posted_at.isoformat() if self.posted_at else None,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None,
        }


# =============================================================================
# BRIEFING SYSTEM MODELS (v2) - Multi-tenant briefing system
# =============================================================================

class BriefTemplate(db.Model):
    """
    Predefined brief templates (off-the-shelf themes) for the template marketplace.
    Templates are configurable archetypes with intent, cadence, structure, tone, and source types.
    Users can clone a template to create their own briefing with bounded customization.
    """
    __tablename__ = 'brief_template'
    __table_args__ = (
        db.Index('idx_brief_template_name', 'name'),
        db.Index('idx_brief_template_category', 'category'),
        db.Index('idx_brief_template_audience', 'audience_type'),
        db.Index('idx_brief_template_featured', 'is_featured'),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)  # Short description for marketplace listing
    slug = db.Column(db.String(100), unique=True)  # URL-friendly identifier

    # Marketplace categorization
    category = db.Column(db.String(50), nullable=False, default='core_insight')
    # Categories: 'core_insight', 'organizational', 'personal_interest', 'lifestyle'
    audience_type = db.Column(db.String(30), nullable=False, default='all')
    # Audience: 'individual', 'organization', 'all'

    # Display metadata
    icon = db.Column(db.String(50), default='newspaper')  # Icon name for UI
    tagline = db.Column(db.String(200))  # Short tagline (e.g., "What Changed" for Politics)
    sample_output = db.Column(db.Text)  # Example brief output for preview

    # Marketplace visibility
    is_featured = db.Column(db.Boolean, default=False)  # Show in featured section
    is_active = db.Column(db.Boolean, default=True)  # Available in marketplace
    sort_order = db.Column(db.Integer, default=0)  # Display order within category

    # Default config (JSON)
    default_sources = db.Column(db.JSON)  # List of NewsSource IDs or category filters
    default_filters = db.Column(db.JSON)  # Keywords, topics, geographic scope
    default_cadence = db.Column(db.String(20), default='daily')  # 'daily' | 'weekly'
    default_tone = db.Column(db.String(50), default='calm_neutral')
    default_accent_color = db.Column(db.String(20), default='#3B82F6')  # Topic-specific accent color

    # Configurable bounds (JSON) - what users CAN change
    configurable_options = db.Column(db.JSON, default=lambda: {
        'geography': True,  # Can user change geographic scope?
        'sources': True,  # Can user add/remove sources?
        'cadence': True,  # Can user change cadence?
        'visibility': True,  # Can user change visibility?
        'auto_send': True,  # Can user toggle auto-send vs approval?
        'tone': False,  # Tone is fixed by default for brand consistency
        'cadence_options': ['daily', 'weekly'],  # Allowed cadence values
    })

    # Fixed guardrails (JSON) - what is ALWAYS enforced
    guardrails = db.Column(db.JSON, default=lambda: {
        'max_items': 10,  # Maximum stories per brief
        'require_attribution': True,  # Always show sources
        'no_predictions': False,  # Disable speculative content (for crypto/markets)
        'no_outrage_framing': True,  # Filter sensational headlines
        'structure_template': 'standard',  # Fixed section structure
    })

    # AI generation hints
    custom_prompt_prefix = db.Column(db.Text)  # Added to AI prompt for this template
    focus_keywords = db.Column(db.JSON)  # Keywords to prioritize
    exclude_keywords = db.Column(db.JSON)  # Keywords to filter out

    # Customization
    allow_customization = db.Column(db.Boolean, default=True)  # Can user modify at all?

    # Usage tracking
    times_used = db.Column(db.Integer, default=0)  # How many briefings created from this

    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def get_category_label(category):
        """Get human-readable category label."""
        labels = {
            'core_insight': 'Core Insight',
            'organizational': 'Organizational',
            'personal_interest': 'Personal Interest',
            'lifestyle': 'Lifestyle & Wellbeing',
        }
        return labels.get(category, category.replace('_', ' ').title())

    @staticmethod
    def get_audience_label(audience_type):
        """Get human-readable audience label."""
        labels = {
            'individual': 'Individuals',
            'organization': 'Organizations',
            'all': 'Everyone',
        }
        return labels.get(audience_type, audience_type.title())

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'slug': self.slug,
            'category': self.category,
            'category_label': self.get_category_label(self.category),
            'audience_type': self.audience_type,
            'audience_label': self.get_audience_label(self.audience_type),
            'icon': self.icon,
            'tagline': self.tagline,
            'default_sources': self.default_sources,
            'default_filters': self.default_filters,
            'default_cadence': self.default_cadence,
            'default_tone': self.default_tone,
            'configurable_options': self.configurable_options,
            'guardrails': self.guardrails,
            'allow_customization': self.allow_customization,
            'is_featured': self.is_featured,
            'times_used': self.times_used,
        }

    def __repr__(self):
        return f'<BriefTemplate {self.name}>'


class InputSource(db.Model):
    """
    Generalized source model for user-defined sources.
    Extends NewsSource concept to support RSS, URLs, uploads, etc.
    
    Phase 1-2: Coexists with NewsSource (NewsSource for system, InputSource for users)
    Phase 3+: NewsSource will migrate to InputSource (owner_type='system')
    """
    __tablename__ = 'input_source'
    __table_args__ = (
        db.Index('idx_input_source_owner', 'owner_type', 'owner_id'),
        db.Index('idx_input_source_type', 'type'),
        db.Index('idx_input_source_status', 'status'),
    )

    id = db.Column(db.Integer, primary_key=True)

    # Ownership
    owner_type = db.Column(db.String(20), nullable=False)  # 'user' | 'org' | 'system'
    owner_id = db.Column(db.Integer, nullable=True)  # User.id or CompanyProfile.id (nullable for system)

    # Source config
    name = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # 'rss' | 'url_list' | 'webpage' | 'upload' | 'substack' | 'x'
    config_json = db.Column(db.JSON)  # Type-specific config (e.g., {'urls': [...]} for url_list)

    # For uploads
    storage_key = db.Column(db.String(500), nullable=True)  # Replit Object Storage key
    storage_url = db.Column(db.String(500), nullable=True)
    extracted_text = db.Column(db.Text, nullable=True)  # Extracted text from PDF/DOCX

    # Status (for async extraction)
    status = db.Column(db.String(30), default='ready')  # 'ready' | 'extracting' | 'failed'
    extraction_error = db.Column(db.Text, nullable=True)  # Error message if extraction failed

    # Source metadata
    enabled = db.Column(db.Boolean, default=True)
    last_fetched_at = db.Column(db.DateTime, nullable=True)
    fetch_error_count = db.Column(db.Integer, default=0)

    # Provenance & Editorial Control (unified ingestion architecture)
    origin_type = db.Column(db.String(20), default='user')  # 'admin' | 'template' | 'user'
    content_domain = db.Column(db.String(50), nullable=True)  # 'news' | 'sport' | 'tech' | 'finance' | 'culture' | 'science' | 'politics'
    allowed_channels = db.Column(db.JSON, default=lambda: ['user_briefings'])  # ['daily_brief', 'trending', 'user_briefings']
    political_leaning = db.Column(db.Float, nullable=True)  # -1.0 (left) to 1.0 (right), null = unknown
    is_verified = db.Column(db.Boolean, default=False)  # Admin-verified quality source

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    ingested_items = db.relationship('IngestedItem', backref='source', lazy='dynamic', cascade='all, delete-orphan')
    briefing_sources = db.relationship('BriefingSource', backref='input_source', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'owner_type': self.owner_type,
            'owner_id': self.owner_id,
            'name': self.name,
            'type': self.type,
            'config_json': self.config_json,
            'status': self.status,
            'enabled': self.enabled,
            'origin_type': self.origin_type,
            'content_domain': self.content_domain,
            'allowed_channels': self.allowed_channels,
            'is_verified': self.is_verified,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def can_be_used_in(self, channel: str) -> bool:
        """Check if this source is allowed in a specific channel."""
        if not self.allowed_channels:
            return channel == 'user_briefings'
        return channel in self.allowed_channels

    def __repr__(self):
        return f'<InputSource {self.name} ({self.type})>'


class IngestedItem(db.Model):
    """
    Individual items ingested from sources.
    Similar to NewsArticle but more generic (supports uploads, URLs, etc.).
    """
    __tablename__ = 'ingested_item'
    __table_args__ = (
        db.UniqueConstraint('source_id', 'content_hash', name='uq_source_content_hash'),
        db.Index('idx_ingested_source_fetched', 'source_id', 'fetched_at'),
        db.Index('idx_ingested_published', 'published_at'),
    )

    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey('input_source.id', ondelete='CASCADE'), nullable=False)

    # Content
    title = db.Column(db.String(500), nullable=False)
    url = db.Column(db.String(1000), nullable=True)  # Nullable for uploads
    source_name = db.Column(db.String(200))  # Denormalized for performance

    # Timing
    published_at = db.Column(db.DateTime, nullable=True)  # From source
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Content
    content_text = db.Column(db.Text)  # Extracted text
    content_hash = db.Column(db.String(64), nullable=False)  # SHA-256 for deduplication
    metadata_json = db.Column(db.JSON)  # Author, tags, etc.

    # For uploads
    storage_key = db.Column(db.String(500), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'source_id': self.source_id,
            'title': self.title,
            'url': self.url,
            'source_name': self.source_name,
            'published_at': self.published_at.isoformat() if self.published_at else None,
            'fetched_at': self.fetched_at.isoformat() if self.fetched_at else None,
            'content_text': self.content_text[:500] if self.content_text else None,  # Truncate for API
            'metadata_json': self.metadata_json,
        }

    def __repr__(self):
        return f'<IngestedItem {self.title[:50]}>'


class Briefing(db.Model):
    """
    Multi-tenant brief configuration.
    Each user/org can have multiple briefings with custom sources and schedules.
    """
    __tablename__ = 'briefing'
    __table_args__ = (
        db.Index('idx_briefing_owner', 'owner_type', 'owner_id'),
        db.Index('idx_briefing_status', 'status'),
        db.Index('idx_briefing_visibility', 'visibility'),
    )

    id = db.Column(db.Integer, primary_key=True)

    # Ownership
    owner_type = db.Column(db.String(20), nullable=False)  # 'user' | 'org'
    owner_id = db.Column(db.Integer, nullable=False)  # User.id or CompanyProfile.id

    # Configuration
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    theme_template_id = db.Column(db.Integer, db.ForeignKey('brief_template.id'), nullable=True)

    # Schedule
    cadence = db.Column(db.String(20), default='daily')  # 'daily' | 'weekly'
    timezone = db.Column(db.String(50), default='UTC')  # e.g., 'Europe/London', 'America/New_York'
    preferred_send_hour = db.Column(db.Integer, default=18)  # 0-23 (hour of day)
    preferred_send_minute = db.Column(db.Integer, default=0)  # 0-59 (minute of hour)

    # Workflow
    mode = db.Column(db.String(20), default='auto_send')  # 'auto_send' | 'approval_required'

    # Visibility
    visibility = db.Column(db.String(20), default='private')  # 'private' | 'org_only' | 'public'

    # Status
    status = db.Column(db.String(20), default='active')  # 'active' | 'paused'

    # AI Generation Settings
    custom_prompt = db.Column(db.Text, nullable=True)  # Custom instructions for AI generation
    tone = db.Column(db.String(50), default='calm_neutral')  # 'calm_neutral' | 'formal' | 'conversational'
    include_summaries = db.Column(db.Boolean, default=True)  # Include bullet summaries
    max_items = db.Column(db.Integer, default=10)  # Max stories per brief
    
    # Guardrails (inherited from template, if any)
    # JSON with keys: no_outrage_framing, no_predictions, require_attribution, 
    # perspective_balance, structure_template, visibility_locked
    guardrails = db.Column(db.JSON, nullable=True)
    
    # User customization settings
    # Topic preferences: {"football": 3, "cricket": 1, "tennis": 2} - higher = more priority
    topic_preferences = db.Column(db.JSON, nullable=True)
    # Content filters: {"include_keywords": ["premier league"], "exclude_keywords": ["betting"]}
    filters_json = db.Column(db.JSON, nullable=True)

    # Visual Branding
    logo_url = db.Column(db.String(500), nullable=True)  # Logo image URL
    accent_color = db.Column(db.String(20), default='#3B82F6')  # Hex color for accents
    header_text = db.Column(db.String(200), nullable=True)  # Custom header text

    # Email config (for orgs)
    from_name = db.Column(db.String(200), nullable=True)
    from_email = db.Column(db.String(255), nullable=True)  # Must be from verified domain
    sending_domain_id = db.Column(db.Integer, db.ForeignKey('sending_domain.id', ondelete='SET NULL'), nullable=True)

    # Slack integration
    slack_webhook_url = db.Column(db.String(500), nullable=True)  # Slack incoming webhook URL
    slack_channel_name = db.Column(db.String(100), nullable=True)  # For display purposes

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    template = db.relationship('BriefTemplate', backref='briefings')
    sources = db.relationship('BriefingSource', backref='briefing', cascade='all, delete-orphan')
    runs = db.relationship('BriefRun', backref='briefing', lazy='dynamic', order_by='BriefRun.scheduled_at.desc()')
    recipients = db.relationship('BriefRecipient', backref='briefing', lazy='dynamic', cascade='all, delete-orphan')
    sending_domain = db.relationship('SendingDomain', backref='briefings')

    @property
    def source_count(self):
        """Number of sources attached to this briefing."""
        return len(self.sources)

    @property
    def recipient_count(self):
        """Number of active recipients."""
        return self.recipients.filter_by(status='active').count()

    def to_dict(self):
        return {
            'id': self.id,
            'owner_type': self.owner_type,
            'owner_id': self.owner_id,
            'name': self.name,
            'description': self.description,
            'theme_template_id': self.theme_template_id,
            'cadence': self.cadence,
            'timezone': self.timezone,
            'preferred_send_hour': self.preferred_send_hour,
            'mode': self.mode,
            'visibility': self.visibility,
            'status': self.status,
            'guardrails': self.guardrails,
            'source_count': self.source_count,
            'recipient_count': self.recipient_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<Briefing {self.name} ({self.owner_type}:{self.owner_id})>'


class BriefingSource(db.Model):
    """
    Many-to-many relationship between Briefings and InputSources.
    """
    __tablename__ = 'briefing_source'
    __table_args__ = (
        db.UniqueConstraint('briefing_id', 'source_id', name='uq_briefing_source'),
    )

    briefing_id = db.Column(db.Integer, db.ForeignKey('briefing.id', ondelete='CASCADE'), primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey('input_source.id', ondelete='CASCADE'), primary_key=True)
    priority = db.Column(db.Integer, default=1)  # 1-5, higher = more important
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship to access source details
    source = db.relationship('InputSource', backref='briefing_associations')

    def __repr__(self):
        return f'<BriefingSource briefing:{self.briefing_id} source:{self.source_id} priority:{self.priority}>'


class BriefRun(db.Model):
    """
    Execution instance of a briefing.
    Each scheduled run creates a BriefRun (similar to DailyBrief but per-briefing).
    """
    __tablename__ = 'brief_run'
    __table_args__ = (
        db.Index('idx_brief_run_briefing', 'briefing_id'),
        db.Index('idx_brief_run_status', 'status'),
        db.Index('idx_brief_run_scheduled', 'scheduled_at'),
        # Prevent duplicate runs for same briefing at same time (race condition protection)
        db.UniqueConstraint('briefing_id', 'scheduled_at', name='uq_brief_run_briefing_scheduled'),
    )

    id = db.Column(db.Integer, primary_key=True)
    briefing_id = db.Column(db.Integer, db.ForeignKey('briefing.id', ondelete='CASCADE'), nullable=False)

    # Status workflow
    status = db.Column(db.String(30), default='generated_draft')  # 'generated_draft' | 'awaiting_approval' | 'approved' | 'sent' | 'failed'

    # Content (markdown + HTML)
    draft_markdown = db.Column(db.Text)
    draft_html = db.Column(db.Text)
    approved_markdown = db.Column(db.Text, nullable=True)
    approved_html = db.Column(db.Text, nullable=True)

    # Approval tracking
    approved_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)

    # Timing
    scheduled_at = db.Column(db.DateTime, nullable=False)  # When it should run
    generated_at = db.Column(db.DateTime, nullable=True)
    sent_at = db.Column(db.DateTime, nullable=True)

    # Analytics tracking
    emails_sent = db.Column(db.Integer, default=0)  # Count of emails sent
    unique_opens = db.Column(db.Integer, default=0)  # Count of unique email opens
    total_clicks = db.Column(db.Integer, default=0)  # Count of link clicks
    slack_sent = db.Column(db.Boolean, default=False)  # Whether Slack notification was sent

    # Relationships
    items = db.relationship('BriefRunItem', backref='run', cascade='all, delete-orphan', order_by='BriefRunItem.position')
    approved_by = db.relationship('User', backref='approved_brief_runs', foreign_keys=[approved_by_user_id])
    edits = db.relationship('BriefEdit', backref='brief_run', lazy='dynamic', order_by='BriefEdit.created_at.desc()')
    opens = db.relationship('BriefEmailOpen', backref='brief_run', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'briefing_id': self.briefing_id,
            'status': self.status,
            'scheduled_at': self.scheduled_at.isoformat() if self.scheduled_at else None,
            'generated_at': self.generated_at.isoformat() if self.generated_at else None,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'approved_by_user_id': self.approved_by_user_id,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'item_count': len(self.items),
        }

    def __repr__(self):
        return f'<BriefRun {self.id} ({self.status})>'


class BriefRunItem(db.Model):
    """
    Individual items within a BriefRun.
    Similar to BriefItem but for BriefRun.
    """
    __tablename__ = 'brief_run_item'
    __table_args__ = (
        db.Index('idx_brief_run_item_run', 'brief_run_id'),
        db.UniqueConstraint('brief_run_id', 'position', name='uq_brief_run_position'),
    )

    id = db.Column(db.Integer, primary_key=True)
    brief_run_id = db.Column(db.Integer, db.ForeignKey('brief_run.id', ondelete='CASCADE'), nullable=False)
    position = db.Column(db.Integer, nullable=False)  # Display order

    # Source reference (optional - can reference IngestedItem or TrendingTopic)
    # SET NULL on delete to prevent orphaned references when source items are cleaned up
    ingested_item_id = db.Column(db.Integer, db.ForeignKey('ingested_item.id', ondelete='SET NULL'), nullable=True)
    trending_topic_id = db.Column(db.Integer, db.ForeignKey('trending_topic.id', ondelete='SET NULL'), nullable=True)

    # Generated content (LLM-created)
    headline = db.Column(db.String(200))
    summary_bullets = db.Column(db.JSON)  # ['bullet1', 'bullet2', 'bullet3']
    content_markdown = db.Column(db.Text)
    content_html = db.Column(db.Text)
    source_name = db.Column(db.String(200), nullable=True)  # Denormalized for display
    source_url = db.Column(db.String(1000), nullable=True)  # Link to original article
    
    # Content metadata for scoring and diversity
    topic_category = db.Column(db.String(100), nullable=True)  # Category/topic of the item
    sentiment_score = db.Column(db.Float, nullable=True)  # -1.0 to 1.0 (negative to positive)
    
    # Engagement tracking (denormalized for faster queries)
    click_count = db.Column(db.Integer, default=0)  # Number of clicks on this item
    
    # Selection metadata (for learning/debugging)
    selection_score = db.Column(db.Float, nullable=True)  # Score at time of selection

    # Deeper context for "Want more detail?" feature
    deeper_context = db.Column(db.Text)  # Extended analysis and background

    # Audio/TTS integration (XTTS v2 - open source)
    audio_url = db.Column(db.String(500))  # URL to generated audio file
    audio_voice_id = db.Column(db.String(100))  # XTTS voice ID used
    audio_generated_at = db.Column(db.DateTime)  # When audio was generated

    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    ingested_item = db.relationship('IngestedItem', backref='brief_run_items')
    trending_topic = db.relationship('TrendingTopic', backref='brief_run_items')

    def to_dict(self):
        return {
            'id': self.id,
            'position': self.position,
            'headline': self.headline,
            'summary_bullets': self.summary_bullets,
            'content_markdown': self.content_markdown,
            'deeper_context': self.deeper_context,
            'audio_url': self.audio_url,
            'audio_voice_id': self.audio_voice_id,
        }

    def __repr__(self):
        return f'<BriefRunItem {self.position}. {self.headline}>'


class BriefEmailOpen(db.Model):
    """
    Tracks individual email opens for analytics.
    """
    __tablename__ = 'brief_email_open'
    __table_args__ = (
        db.Index('idx_brief_email_open_run', 'brief_run_id'),
        db.Index('idx_brief_email_open_recipient', 'recipient_email'),
    )

    id = db.Column(db.Integer, primary_key=True)
    brief_run_id = db.Column(db.Integer, db.ForeignKey('brief_run.id', ondelete='CASCADE'), nullable=False)
    recipient_email = db.Column(db.String(255), nullable=True)  # Hashed or anonymized
    opened_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_agent = db.Column(db.String(500), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)

    def __repr__(self):
        return f'<BriefEmailOpen {self.id} for run {self.brief_run_id}>'


class BriefLinkClick(db.Model):
    """
    Tracks individual link clicks for analytics.
    """
    __tablename__ = 'brief_link_click'
    __table_args__ = (
        db.Index('idx_brief_link_click_run', 'brief_run_id'),
        db.Index('idx_brief_link_click_item', 'brief_run_item_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    brief_run_id = db.Column(db.Integer, db.ForeignKey('brief_run.id', ondelete='CASCADE'), nullable=False)
    brief_run_item_id = db.Column(db.Integer, db.ForeignKey('brief_run_item.id', ondelete='SET NULL'), nullable=True)
    recipient_email = db.Column(db.String(255), nullable=True)  # Hashed or anonymized
    target_url = db.Column(db.String(2000), nullable=False)
    clicked_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_agent = db.Column(db.String(500), nullable=True)

    def __repr__(self):
        return f'<BriefLinkClick {self.id} for run {self.brief_run_id}>'


class BriefRecipient(db.Model):
    """
    Per-briefing recipient list.
    Similar to DailyBriefSubscriber but per-briefing (not global).
    """
    __tablename__ = 'brief_recipient'
    __table_args__ = (
        db.UniqueConstraint('briefing_id', 'email', name='uq_briefing_recipient'),
        db.Index('idx_brief_recipient_status', 'briefing_id', 'status'),
        db.Index('idx_brief_recipient_token', 'magic_token'),
    )

    id = db.Column(db.Integer, primary_key=True)
    briefing_id = db.Column(db.Integer, db.ForeignKey('briefing.id', ondelete='CASCADE'), nullable=False)

    email = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(200), nullable=True)

    status = db.Column(db.String(20), default='active')  # 'active' | 'unsubscribed'
    unsubscribed_at = db.Column(db.DateTime, nullable=True)

    # Magic link auth (reuse pattern from DailyBriefSubscriber)
    magic_token = db.Column(db.String(64), unique=True, nullable=True)
    magic_token_expires_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def generate_magic_token(self, expires_hours=48):
        """Generate a new magic link token with expiry"""
        import secrets
        from datetime import timedelta
        self.magic_token = secrets.token_urlsafe(32)
        self.magic_token_expires_at = datetime.utcnow() + timedelta(hours=expires_hours)
        return self.magic_token

    def is_magic_token_valid(self) -> bool:
        """Check if magic token is still valid (not expired)"""
        if not self.magic_token:
            return False
        if not self.magic_token_expires_at:
            # Legacy tokens without expiry - consider valid but should be regenerated
            return True
        return datetime.utcnow() < self.magic_token_expires_at

    def to_dict(self):
        return {
            'id': self.id,
            'briefing_id': self.briefing_id,
            'email': self.email,
            'name': self.name,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<BriefRecipient {self.email} ({self.status})>'


class SendingDomain(db.Model):
    """
    Custom email domain verification for organizations.
    Uses Resend Domain API for verification.
    """
    __tablename__ = 'sending_domain'
    __table_args__ = (
        db.Index('idx_sending_domain_org', 'org_id'),
        db.Index('idx_sending_domain_status', 'status'),
    )

    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey('company_profile.id', ondelete='CASCADE'), nullable=False)

    domain = db.Column(db.String(255), nullable=False, unique=True)  # e.g., 'client.org'
    status = db.Column(db.String(30), default='pending_verification')  # 'pending_verification' | 'verified' | 'failed'

    # Resend API data
    resend_domain_id = db.Column(db.String(255), nullable=True)
    dns_records_required = db.Column(db.JSON)  # SPF, DKIM, etc.

    verified_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    org = db.relationship('CompanyProfile', backref='sending_domains')

    def to_dict(self):
        return {
            'id': self.id,
            'org_id': self.org_id,
            'domain': self.domain,
            'status': self.status,
            'dns_records_required': self.dns_records_required,
            'verified_at': self.verified_at.isoformat() if self.verified_at else None,
        }

    def __repr__(self):
        return f'<SendingDomain {self.domain} ({self.status})>'


class BriefEdit(db.Model):
    """
    Edit history for approval workflow (optional versioning).
    Tracks edits made to BriefRun drafts.
    """
    __tablename__ = 'brief_edit'
    __table_args__ = (
        db.Index('idx_brief_edit_run', 'brief_run_id'),
        db.Index('idx_brief_edit_user', 'edited_by_user_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    brief_run_id = db.Column(db.Integer, db.ForeignKey('brief_run.id', ondelete='CASCADE'), nullable=False)

    edited_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content_markdown = db.Column(db.Text)
    content_html = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    edited_by = db.relationship('User', backref='brief_edits', foreign_keys=[edited_by_user_id])

    def to_dict(self):
        return {
            'id': self.id,
            'brief_run_id': self.brief_run_id,
            'edited_by_user_id': self.edited_by_user_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<BriefEdit {self.id} by user:{self.edited_by_user_id}>'


class PricingPlan(db.Model):
    """
    Pricing plans for the briefing subscription tiers.
    Pre-seeded with tier metadata and Stripe product/price IDs.
    """
    __tablename__ = 'pricing_plan'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)  # 'starter', 'professional', 'team', 'enterprise'
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)

    # Pricing
    price_monthly = db.Column(db.Integer, nullable=False)  # In pence (£12 = 1200)
    price_yearly = db.Column(db.Integer, nullable=True)    # In pence (£250 = 25000)
    currency = db.Column(db.String(3), default='GBP')

    # Stripe IDs
    stripe_product_id = db.Column(db.String(255), nullable=True)
    stripe_price_monthly_id = db.Column(db.String(255), nullable=True)
    stripe_price_yearly_id = db.Column(db.String(255), nullable=True)

    # Feature limits
    max_briefs = db.Column(db.Integer, default=1)        # -1 = unlimited
    max_sources = db.Column(db.Integer, default=10)      # -1 = unlimited
    max_recipients = db.Column(db.Integer, default=10)   # -1 = unlimited
    max_editors = db.Column(db.Integer, default=1)       # -1 = unlimited

    # Feature flags
    allow_document_uploads = db.Column(db.Boolean, default=False)
    allow_custom_branding = db.Column(db.Boolean, default=False)
    allow_approval_workflow = db.Column(db.Boolean, default=False)
    allow_slack_integration = db.Column(db.Boolean, default=False)
    allow_api_access = db.Column(db.Boolean, default=False)
    priority_processing = db.Column(db.Boolean, default=False)

    # Display
    is_active = db.Column(db.Boolean, default=True)
    is_organisation = db.Column(db.Boolean, default=False)  # Team/Enterprise plans
    display_order = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    subscriptions = db.relationship('Subscription', backref='plan', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'price_monthly': self.price_monthly,
            'price_yearly': self.price_yearly,
            'currency': self.currency,
            'max_briefs': self.max_briefs,
            'max_sources': self.max_sources,
            'max_recipients': self.max_recipients,
            'max_editors': self.max_editors,
            'allow_document_uploads': self.allow_document_uploads,
            'allow_custom_branding': self.allow_custom_branding,
            'allow_approval_workflow': self.allow_approval_workflow,
            'allow_slack_integration': self.allow_slack_integration,
            'allow_api_access': self.allow_api_access,
            'priority_processing': self.priority_processing,
            'is_organisation': self.is_organisation,
        }

    def __repr__(self):
        return f'<PricingPlan {self.code}>'


class Subscription(db.Model):
    """
    User or organisation subscription tracking.
    Links to Stripe subscription for billing.
    """
    __tablename__ = 'subscription'
    __table_args__ = (
        db.Index('idx_subscription_user', 'user_id'),
        db.Index('idx_subscription_org', 'org_id'),
        db.Index('idx_subscription_status', 'status'),
        db.Index('idx_subscription_stripe', 'stripe_subscription_id'),
    )

    id = db.Column(db.Integer, primary_key=True)

    # Owner (either user or organisation, not both)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=True)
    org_id = db.Column(db.Integer, db.ForeignKey('company_profile.id', ondelete='CASCADE'), nullable=True)

    # Plan
    plan_id = db.Column(db.Integer, db.ForeignKey('pricing_plan.id'), nullable=False)

    # Stripe data
    stripe_subscription_id = db.Column(db.String(255), unique=True, nullable=True)
    stripe_customer_id = db.Column(db.String(255), nullable=True)

    # Status: 'trialing', 'active', 'past_due', 'canceled', 'unpaid', 'incomplete'
    status = db.Column(db.String(30), default='trialing')

    # Billing period
    current_period_start = db.Column(db.DateTime, nullable=True)
    current_period_end = db.Column(db.DateTime, nullable=True)
    trial_end = db.Column(db.DateTime, nullable=True)
    cancel_at_period_end = db.Column(db.Boolean, default=False)
    canceled_at = db.Column(db.DateTime, nullable=True)

    # Billing interval: 'month' or 'year'
    billing_interval = db.Column(db.String(10), default='month')

    # Team seats (for Team/Enterprise plans)
    seat_count = db.Column(db.Integer, default=1)

    # Extra data
    extra_data = db.Column(db.JSON, default=dict)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref=db.backref('subscriptions', lazy='dynamic'))
    org = db.relationship('CompanyProfile', backref=db.backref('subscriptions', lazy='dynamic'))

    @property
    def is_active(self):
        """Check if subscription is in an active state (trialing or active)"""
        return self.status in ('trialing', 'active')

    @property
    def is_trial(self):
        """Check if subscription is in trial period"""
        return self.status == 'trialing'

    @property
    def days_remaining(self):
        """Days remaining in current period"""
        if not self.current_period_end:
            return None
        delta = self.current_period_end - datetime.utcnow()
        return max(0, delta.days)

    def can_use_feature(self, feature):
        """Check if plan allows a specific feature"""
        feature_map = {
            'document_uploads': self.plan.allow_document_uploads,
            'custom_branding': self.plan.allow_custom_branding,
            'approval_workflow': self.plan.allow_approval_workflow,
            'slack_integration': self.plan.allow_slack_integration,
            'api_access': self.plan.allow_api_access,
            'priority_processing': self.plan.priority_processing,
        }
        return feature_map.get(feature, False)

    def check_limit(self, resource, current_count):
        """Check if a resource limit has been reached"""
        limit_map = {
            'briefs': self.plan.max_briefs,
            'sources': self.plan.max_sources,
            'recipients': self.plan.max_recipients,
            'editors': self.plan.max_editors,
        }
        limit = limit_map.get(resource)
        if limit is None or limit == -1:  # -1 means unlimited
            return True
        return current_count < limit

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'org_id': self.org_id,
            'plan': self.plan.to_dict() if self.plan else None,
            'status': self.status,
            'is_active': self.is_active,
            'is_trial': self.is_trial,
            'current_period_end': self.current_period_end.isoformat() if self.current_period_end else None,
            'trial_end': self.trial_end.isoformat() if self.trial_end else None,
            'cancel_at_period_end': self.cancel_at_period_end,
            'billing_interval': self.billing_interval,
            'seat_count': self.seat_count,
            'days_remaining': self.days_remaining,
        }

    def __repr__(self):
        owner = f'user:{self.user_id}' if self.user_id else f'org:{self.org_id}'
        return f'<Subscription {self.id} {owner} ({self.status})>'


# =============================================================================
# POLYMARKET INTEGRATION
# =============================================================================

class PolymarketMarket(db.Model):
    """
    Cached Polymarket market data.

    Sync Strategy:
    - Full sync every 2 hours (all active markets)
    - Price refresh every 5 minutes (tracked markets only)
    - Embedding generation on first sync (for matching)

    Quality Thresholds:
    - MIN_VOLUME_24H: $1,000 minimum daily volume
    - MIN_LIQUIDITY: $5,000 minimum liquidity
    - Markets below thresholds excluded from matching
    """
    __tablename__ = 'polymarket_market'
    __table_args__ = (
        db.Index('idx_pm_market_condition', 'condition_id'),
        db.Index('idx_pm_market_category', 'category'),
        db.Index('idx_pm_market_active', 'is_active'),
        db.Index('idx_pm_market_quality', 'is_active', 'volume_24h', 'liquidity'),
    )

    id = db.Column(db.Integer, primary_key=True)

    # Polymarket Identifiers
    condition_id = db.Column(db.String(100), unique=True, nullable=False)
    slug = db.Column(db.String(200), index=True)
    clob_token_ids = db.Column(db.JSON)  # For CLOB API price fetching

    # Content
    question = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(100), index=True)  # politics, economics, tech...
    tags = db.Column(db.JSON)  # ['uk', 'election', 'labour'] - for keyword matching

    # Automated Matching
    question_embedding = db.Column(db.JSON)  # Vector for similarity search

    # Outcomes & Pricing
    outcomes = db.Column(db.JSON)  # [{"name": "Yes", "token_id": "...", "price": 0.78}, ...]
    probability = db.Column(db.Float)  # Primary outcome probability (0-1)
    probability_24h_ago = db.Column(db.Float)  # For calculating 24h change

    # Quality Signals (for filtering low-quality markets)
    volume_24h = db.Column(db.Float, default=0)
    volume_total = db.Column(db.Float, default=0)
    liquidity = db.Column(db.Float, default=0)
    trader_count = db.Column(db.Integer, default=0)

    # Lifecycle
    is_active = db.Column(db.Boolean, default=True, index=True)
    end_date = db.Column(db.DateTime)  # When market resolves
    resolution = db.Column(db.String(50))  # null until resolved, then 'Yes'/'No'/etc
    resolved_at = db.Column(db.DateTime)

    # Sync Tracking
    first_seen_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_synced_at = db.Column(db.DateTime)
    last_price_update_at = db.Column(db.DateTime)
    sync_failures = db.Column(db.Integer, default=0)  # Track consecutive failures

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Quality Thresholds (class constants)
    MIN_VOLUME_24H = 1000    # $1k minimum daily volume
    MIN_LIQUIDITY = 5000     # $5k minimum liquidity
    HIGH_QUALITY_VOLUME = 10000  # $10k for "high quality" designation

    # Relationships
    topic_matches = db.relationship('TopicMarketMatch', backref='market', lazy='dynamic',
                                    cascade='all, delete-orphan')

    @property
    def is_high_quality(self) -> bool:
        """Market meets minimum quality thresholds for matching."""
        return (
            self.is_active and
            (self.volume_24h or 0) >= self.MIN_VOLUME_24H and
            (self.liquidity or 0) >= self.MIN_LIQUIDITY
        )

    @property
    def quality_tier(self) -> str:
        """Returns quality tier for filtering in UI."""
        if not self.is_active:
            return 'inactive'
        if (self.volume_24h or 0) >= self.HIGH_QUALITY_VOLUME:
            return 'high'
        if (self.volume_24h or 0) >= self.MIN_VOLUME_24H:
            return 'medium'
        return 'low'

    @property
    def change_24h(self) -> Optional[float]:
        """24-hour probability change. Returns None if no historical data."""
        if self.probability is not None and self.probability_24h_ago is not None:
            return self.probability - self.probability_24h_ago
        return None

    @property
    def change_24h_formatted(self) -> str:
        """Formatted 24h change for display."""
        change = self.change_24h
        if change is None:
            return "—"
        if change > 0:
            return f"+{change:.1%}"
        return f"{change:.1%}"

    @property
    def polymarket_url(self) -> str:
        """Direct link to market on Polymarket."""
        if self.slug:
            return f"https://polymarket.com/event/{self.slug}"
        return f"https://polymarket.com/markets/{self.condition_id}"

    def to_signal_dict(self) -> dict:
        """
        Returns market data formatted for BriefItem.market_signal JSON field.
        Used by brief generator when attaching market signal to items.
        """
        return {
            'market_id': self.id,
            'condition_id': self.condition_id,
            'question': self.question,
            'probability': self.probability,
            'change_24h': self.change_24h,
            'change_24h_formatted': self.change_24h_formatted,
            'volume_24h': self.volume_24h,
            'liquidity': self.liquidity,
            'trader_count': self.trader_count,
            'quality_tier': self.quality_tier,
            'url': self.polymarket_url,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'fetched_at': self.last_price_update_at.isoformat() if self.last_price_update_at else None
        }

    def to_dict(self) -> dict:
        """Full serialization for API responses."""
        return {
            'id': self.id,
            'condition_id': self.condition_id,
            'slug': self.slug,
            'question': self.question,
            'description': self.description,
            'category': self.category,
            'tags': self.tags,
            'outcomes': self.outcomes,
            'probability': self.probability,
            'change_24h': self.change_24h,
            'volume_24h': self.volume_24h,
            'volume_total': self.volume_total,
            'liquidity': self.liquidity,
            'trader_count': self.trader_count,
            'quality_tier': self.quality_tier,
            'is_active': self.is_active,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'resolution': self.resolution,
            'url': self.polymarket_url,
            'last_synced_at': self.last_synced_at.isoformat() if self.last_synced_at else None
        }

    def __repr__(self):
        q = self.question[:50] if self.question else 'Unknown'
        return f'<PolymarketMarket {self.id}: {q}...>'


class TopicMarketMatch(db.Model):
    """
    Automated match between TrendingTopic and PolymarketMarket.

    Matching Strategy:
    1. Category mapping (Society Speaks topic → Polymarket categories)
    2. Embedding similarity (topic embedding vs market question embedding)
    3. Keyword overlap fallback (canonical_tags vs market tags)

    Only high-confidence matches (similarity >= 0.75) are stored.
    Matches are refreshed when topics are created/updated.
    """
    __tablename__ = 'topic_market_match'
    __table_args__ = (
        db.Index('idx_tmm_topic', 'trending_topic_id'),
        db.Index('idx_tmm_market', 'market_id'),
        db.Index('idx_tmm_similarity', 'similarity_score'),
        db.UniqueConstraint('trending_topic_id', 'market_id', name='uq_topic_market'),
    )

    id = db.Column(db.Integer, primary_key=True)
    trending_topic_id = db.Column(db.Integer, db.ForeignKey('trending_topic.id', ondelete='CASCADE'),
                                   nullable=False)
    market_id = db.Column(db.Integer, db.ForeignKey('polymarket_market.id', ondelete='CASCADE'),
                          nullable=False)

    # Match Quality
    similarity_score = db.Column(db.Float, nullable=False)  # 0-1, higher = better match
    match_method = db.Column(db.String(20), nullable=False)  # 'embedding', 'keyword', 'category'

    # Snapshot at Match Time (for historical analysis)
    probability_at_match = db.Column(db.Float)
    volume_at_match = db.Column(db.Float)

    # Lifecycle
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Thresholds (class constants)
    SIMILARITY_THRESHOLD = 0.75  # Minimum similarity to create match
    HIGH_CONFIDENCE_THRESHOLD = 0.85  # High confidence matches

    # Relationships
    trending_topic = db.relationship('TrendingTopic', backref=db.backref('market_matches', lazy='dynamic'))

    @property
    def is_high_confidence(self) -> bool:
        return self.similarity_score >= self.HIGH_CONFIDENCE_THRESHOLD

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'trending_topic_id': self.trending_topic_id,
            'market_id': self.market_id,
            'similarity_score': self.similarity_score,
            'match_method': self.match_method,
            'is_high_confidence': self.is_high_confidence,
            'probability_at_match': self.probability_at_match,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<TopicMarketMatch topic={self.trending_topic_id} market={self.market_id} sim={self.similarity_score:.2f}>'
