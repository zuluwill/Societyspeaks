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
    country = db.Column(db.String(100))  # Country the source primarily covers (e.g., 'United Kingdom', 'United States')
    
    reputation_score = db.Column(db.Float, default=0.8)  # 0-1 scale
    is_active = db.Column(db.Boolean, default=True)

    # Political leaning for coverage analysis (-3 to +3: left to right, 0 = center)
    political_leaning = db.Column(db.Float)  # -2=Left, -1=Lean Left, 0=Center, 1=Lean Right, 2=Right
    leaning_source = db.Column(db.String(50))  # 'allsides', 'manual', 'llm_inferred'
    leaning_updated_at = db.Column(db.DateTime)

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
    relevance_score = db.Column(db.Float)  # 0-1: discussion potential (1=policy debate, 0=product review)
    
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


class DiscussionSourceArticle(db.Model):
    """
    Join table linking Discussion to NewsArticle for news-based discussions.
    Preserves source attribution when topics are published as discussions.
    """
    __tablename__ = 'discussion_source_article'
    __table_args__ = (
        db.Index('idx_dsa_discussion', 'discussion_id'),
        db.Index('idx_dsa_article', 'article_id'),
        db.UniqueConstraint('discussion_id', 'article_id', name='uq_discussion_article'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=False)
    article_id = db.Column(db.Integer, db.ForeignKey('news_article.id'), nullable=False)
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

    # Relationships
    items = db.relationship('BriefItem', backref='brief', lazy='dynamic',
                           cascade='all, delete-orphan', order_by='BriefItem.position')
    admin_editor = db.relationship('User', backref='edited_briefs', foreign_keys=[admin_edited_by])

    @property
    def item_count(self):
        """Number of items in this brief"""
        return self.items.count()

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
    brief_id = db.Column(db.Integer, db.ForeignKey('daily_brief.id'), nullable=False)
    position = db.Column(db.Integer, nullable=False)  # Display order 1-5

    # Source (DRY - reference existing TrendingTopic)
    trending_topic_id = db.Column(db.Integer, db.ForeignKey('trending_topic.id'), nullable=False)

    # Generated content (LLM-created for brief context)
    headline = db.Column(db.String(200))  # Shorter, punchier than TrendingTopic title
    summary_bullets = db.Column(db.JSON)  # ['bullet1', 'bullet2', 'bullet3']
    so_what = db.Column(db.Text)  # "So what?" analysis paragraph
    perspectives = db.Column(db.JSON)  # {'left': '...', 'center': '...', 'right': '...'}

    # Coverage analysis (computed from TrendingTopic articles)
    coverage_distribution = db.Column(db.JSON)  # {'left': 0.2, 'center': 0.5, 'right': 0.3}
    coverage_imbalance = db.Column(db.Float)  # 0-1 score (0=balanced, 1=single perspective)
    source_count = db.Column(db.Integer)  # Number of unique sources
    sources_by_leaning = db.Column(db.JSON)  # {'left': ['Guardian'], 'center': ['BBC', 'FT'], 'right': []}

    # Sensationalism (from source articles)
    sensationalism_score = db.Column(db.Float)  # Average of article scores
    sensationalism_label = db.Column(db.String(20))  # 'low', 'medium', 'high'

    # Verification links (LLM-extracted + admin additions)
    verification_links = db.Column(db.JSON)  # [{'tier': 'primary', 'url': '...', 'type': '...', 'description': '...', 'is_paywalled': bool}]

    # CTA to discussion
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=True)
    cta_text = db.Column(db.String(200))  # Customizable per item

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
            'so_what': self.so_what,
            'perspectives': self.perspectives,
            'coverage_distribution': self.coverage_distribution,
            'coverage_imbalance': self.coverage_imbalance,
            'source_count': self.source_count,
            'sources_by_leaning': self.sources_by_leaning,
            'sensationalism_score': self.sensationalism_score,
            'sensationalism_label': self.sensationalism_label,
            'verification_links': self.verification_links,
            'discussion_id': self.discussion_id,
            'cta_text': self.cta_text,
            'trending_topic': self.trending_topic.to_dict() if self.trending_topic else None
        }

    def __repr__(self):
        return f'<BriefItem {self.position}. {self.headline}>'


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
    )

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True)

    # Subscription tier
    tier = db.Column(db.String(20), default='trial')  # trial|individual|team
    trial_started_at = db.Column(db.DateTime)
    trial_ends_at = db.Column(db.DateTime)  # 14-day trial

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

    def start_trial(self):
        """Start 14-day free trial"""
        self.tier = 'trial'
        self.trial_started_at = datetime.utcnow()
        self.trial_ends_at = datetime.utcnow() + timedelta(days=14)
        self.status = 'active'

    def is_subscribed_eligible(self):
        """Check if subscriber should receive emails"""
        if self.status != 'active':
            return False

        # During test phase: everyone gets access (check env var)
        import os
        if not os.environ.get('BILLING_ENFORCEMENT_ENABLED'):
            return True

        # Post-launch: check subscription status
        if self.tier == 'trial':
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
            'trial_ends_at': self.trial_ends_at.isoformat() if self.trial_ends_at else None
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


class BriefEmailEvent(db.Model):
    """
    Tracks email events (opens, clicks, bounces) from Resend webhooks.
    Used for analytics and deliverability monitoring.
    """
    __tablename__ = 'brief_email_event'
    __table_args__ = (
        db.Index('idx_bee_subscriber', 'subscriber_id'),
        db.Index('idx_bee_brief', 'brief_id'),
        db.Index('idx_bee_type', 'event_type'),
        db.Index('idx_bee_created', 'created_at'),
    )

    id = db.Column(db.Integer, primary_key=True)
    subscriber_id = db.Column(db.Integer, db.ForeignKey('daily_brief_subscriber.id'), nullable=True)
    brief_id = db.Column(db.Integer, db.ForeignKey('daily_brief.id'), nullable=True)

    # Resend event data
    resend_email_id = db.Column(db.String(255))  # Resend's email ID for tracking
    event_type = db.Column(db.String(50), nullable=False)  # email.sent, email.delivered, email.opened, email.clicked, email.bounced, email.complained
    
    # Additional data
    click_url = db.Column(db.String(500))  # For click events, which link was clicked
    bounce_type = db.Column(db.String(50))  # hard, soft
    user_agent = db.Column(db.String(500))
    ip_address = db.Column(db.String(45))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    subscriber = db.relationship('DailyBriefSubscriber', backref='email_events')
    brief = db.relationship('DailyBrief', backref='email_events')

    def __repr__(self):
        return f'<BriefEmailEvent {self.event_type} for subscriber {self.subscriber_id}>'


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
    
    cold_start_threshold = db.Column(db.Integer, default=50)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    published_at = db.Column(db.DateTime)
    
    source_discussion = db.relationship('Discussion', backref='daily_questions')
    source_statement = db.relationship('Statement', backref='daily_questions')
    source_trending_topic = db.relationship('TrendingTopic', backref='daily_questions')
    created_by = db.relationship('User', backref='created_daily_questions')
    
    @property
    def response_count(self):
        """Total number of responses to this daily question"""
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
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    daily_question = db.relationship('DailyQuestion', backref='responses')
    user = db.relationship('User', backref='daily_question_responses')
    
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
            'created_at': self.created_at.isoformat()
        }
    
    def __repr__(self):
        return f'<DailyQuestionResponse {self.vote_label} on Q#{self.daily_question_id}>'


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
    
    user = db.relationship('User', backref='daily_subscription')
    
    def generate_magic_token(self, expires_hours=48):
        """Generate a new magic link token"""
        import secrets
        self.magic_token = secrets.token_urlsafe(32)
        self.token_expires_at = datetime.utcnow() + timedelta(hours=expires_hours)
        return self.magic_token
    
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


