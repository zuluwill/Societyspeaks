from app import db
from datetime import datetime

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), nullable=False, unique=True)
    email = db.Column(db.String(150), nullable=False, unique=True)
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    discussions_created = db.relationship('Discussion', backref='creator', lazy='dynamic')

class Discussion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    polis_id = db.Column(db.String(100), nullable=False, unique=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)

    # Use string instead of Enum
    geographic_scope = db.Column(db.String(20), nullable=False, default='country')
    country = db.Column(db.String(100))
    city = db.Column(db.String(100))
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    topic = db.Column(db.String(100))
    is_featured = db.Column(db.Boolean, default=False)
    participant_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Constants for geographic scope
    SCOPE_GLOBAL = 'global'
    SCOPE_COUNTRY = 'country'
    SCOPE_CITY = 'city'

    # Topic choices for validation
    TOPICS = [
        'Healthcare',
        'Environment',
        'Education',
        'Technology',
        'Economy',
        'Politics',
        'Society',
        'Infrastructure'
    ]

    def __init__(self, **kwargs):
        # Determine geographic scope based on provided fields
        if 'geographic_scope' not in kwargs:
            if 'city' in kwargs and kwargs['city']:
                kwargs['geographic_scope'] = self.SCOPE_CITY
            elif 'country' in kwargs and kwargs['country']:
                kwargs['geographic_scope'] = self.SCOPE_COUNTRY
            else:
                kwargs['geographic_scope'] = self.SCOPE_GLOBAL

        super(Discussion, self).__init__(**kwargs)

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
            'polis_id': self.polis_id,
            'title': self.title,
            'description': self.description,
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
    def get_featured(limit=3):
        return Discussion.query.filter_by(is_featured=True)\
                             .order_by(Discussion.created_at.desc())\
                             .limit(limit)\
                             .all()

    @staticmethod
    def search_discussions(search=None, country=None, city=None, topic=None, scope=None, page=1, per_page=9):
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

        return query.order_by(Discussion.created_at.desc())\
                   .paginate(page=page, per_page=per_page, error_out=False)