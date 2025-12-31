from app import db, cache
from flask import current_app
from datetime import datetime, timedelta
from slugify import slugify as python_slugify
from flask_login import UserMixin
from unidecode import unidecode
from itsdangerous import URLSafeTimedSerializer as Serializer
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.orm import validates

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
    def track_participant(cls, discussion_id, user_id=None, participant_identifier=None):
        """Track a new participant in a discussion"""
        # Check if participant already exists
        existing = cls.query.filter_by(
            discussion_id=discussion_id,
            user_id=user_id,
            participant_identifier=participant_identifier
        ).first()
        
        if not existing:
            participant = cls(
                discussion_id=discussion_id,
                user_id=user_id,
                participant_identifier=participant_identifier
            )
            db.session.add(participant)
            db.session.commit()
            return participant
        else:
            # Update last activity
            existing.last_activity = datetime.utcnow()
            db.session.commit()
            return existing


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

    # Constants for geographic scope
    SCOPE_GLOBAL = 'global'
    SCOPE_COUNTRY = 'country'
    SCOPE_CITY = 'city'

    # Define topics for validation
    TOPICS = [
        'Healthcare', 'Environment', 'Education', 'Technology', 'Economy', 'Politics', 'Society', 'Infrastructure'
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
    - Unique constraint on (statement_id, user_id)
    """
    __tablename__ = 'statement_vote'
    __table_args__ = (
        db.Index('idx_vote_discussion_user', 'discussion_id', 'user_id'),
        db.Index('idx_vote_discussion_statement', 'discussion_id', 'statement_id'),
        db.UniqueConstraint('statement_id', 'user_id', name='uq_statement_user_vote'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    statement_id = db.Column(db.Integer, db.ForeignKey('statement.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=False)  # For fast lookups
    
    # Vote value: -1 (disagree), 0 (unsure), 1 (agree) - like pol.is
    vote = db.Column(db.SmallInteger, nullable=False)
    
    # Optional confidence (1-5 scale) for weighted clustering
    confidence = db.Column(db.SmallInteger, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    statement = db.relationship('Statement', backref='votes')
    user = db.relationship('User', backref='statement_votes')
    discussion = db.relationship('Discussion', backref='statement_votes')
    
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
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    parent_response_id = db.Column(db.Integer, db.ForeignKey('response.id'), nullable=True)
    
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
    
    reputation_score = db.Column(db.Float, default=0.8)  # 0-1 scale
    is_active = db.Column(db.Boolean, default=True)
    
    last_fetched_at = db.Column(db.DateTime)
    fetch_error_count = db.Column(db.Integer, default=0)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    articles = db.relationship('NewsArticle', backref='source', lazy='dynamic')
    
    def __repr__(self):
        return f'<NewsSource {self.name}>'


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
    risk_flag = db.Column(db.Boolean, default=False)  # Culture war / sensitive / defamation risk
    risk_reason = db.Column(db.String(200))  # Why it's flagged as risky
    
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
    
    @property
    def is_high_confidence(self):
        """
        Auto-publish criteria:
        - 2+ reputable sources
        - High quality score
        - High civic score
        - Not risky
        """
        return (
            self.source_count >= 2 and
            (self.quality_score or 0) >= 0.7 and
            (self.civic_score or 0) >= 0.7 and
            not self.risk_flag
        )
    
    @property
    def should_auto_publish(self):
        """
        Very high confidence for auto-publish (V1 conservative)
        Requires wire service (AP/Reuters) + 1 other
        """
        # Check if any source is a wire service
        has_wire = False
        for ta in self.articles:
            if ta.article and ta.article.source:
                if ta.article.source.name.lower() in ['associated press', 'reuters', 'ap', 'afp']:
                    has_wire = True
                    break
        
        return self.is_high_confidence and has_wire
    
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
    """
    __tablename__ = 'trending_topic_article'
    __table_args__ = (
        db.Index('idx_tta_topic', 'topic_id'),
        db.Index('idx_tta_article', 'article_id'),
        db.UniqueConstraint('topic_id', 'article_id', name='uq_topic_article'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    topic_id = db.Column(db.Integer, db.ForeignKey('trending_topic.id'), nullable=False)
    article_id = db.Column(db.Integer, db.ForeignKey('news_article.id'), nullable=False)
    
    # When this article was added to the topic
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Similarity score to the topic centroid
    similarity_score = db.Column(db.Float)
    
    # Relationships
    article = db.relationship('NewsArticle', backref='topic_associations')


