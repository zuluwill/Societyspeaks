from app import db
from datetime import datetime, timedelta
from slugify import slugify as python_slugify
from flask_login import UserMixin
from unidecode import unidecode
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # New field to indicate profile type
    profile_type = db.Column(db.String(50))  # 'individual' or 'company'

    # Relationships to profiles
    individual_profile = db.relationship('IndividualProfile', backref='user', uselist=False)
    company_profile = db.relationship('CompanyProfile', backref='user', uselist=False)

    discussions_created = db.relationship('Discussion', backref='creator', lazy='dynamic')

    # Password methods
    def set_password(self, password):
        """Hashes and sets the password."""
        self.password = generate_password_hash(password)

    def check_password(self, password):
        """Verifies the password against the stored hash."""
        return check_password_hash(self.password, password)

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


class IndividualProfile(db.Model):
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
    id = db.Column(db.Integer, primary_key=True)
    embed_code = db.Column(db.String(800), nullable=False)  # Store full embed code
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


    @staticmethod
    def get_featured(limit=6):
        # First get discussions marked as featured
        featured = Discussion.query\
            .filter_by(is_featured=True)\
            .order_by(Discussion.created_at.desc())\
            .all()

        # If we have fewer than limit (6), add recent non-featured discussions
        if len(featured) < limit:
            featured_ids = [d.id for d in featured]
            additional = Discussion.query\
                .filter(Discussion.id.notin_(featured_ids))\
                .order_by(Discussion.created_at.desc())\
                .limit(limit - len(featured))\
                .all()
            featured.extend(additional)

        return featured[:limit]

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
        query = Discussion.query

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


