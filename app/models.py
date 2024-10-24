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
    country = db.Column(db.String(100))
    city = db.Column(db.String(100))
    topic = db.Column(db.String(100))
    is_featured = db.Column(db.Boolean, default=False)
    participant_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    # Topic choices for validation
    TOPICS = [
        'Environment',
        'Politics',
        'Technology',
        'Education',
        'Healthcare',
        'Economy',
        'Society',
        'Culture'
    ]

    def to_dict(self):
        return {
            'id': self.id,
            'polis_id': self.polis_id,
            'title': self.title,
            'description': self.description,
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
    def search_discussions(search=None, country=None, city=None, topic=None, page=1, per_page=9):
        query = Discussion.query

        if search:
            search_term = f"%{search}%"
            query = query.filter(
                db.or_(
                    Discussion.title.ilike(search_term),
                    Discussion.description.ilike(search_term)
                )
            )

        if country:
            query = query.filter(Discussion.country.ilike(f"%{country}%"))

        if city:
            query = query.filter(Discussion.city.ilike(f"%{city}%"))

        if topic:
            query = query.filter(Discussion.topic == topic)

        return query.order_by(Discussion.created_at.desc())\
                   .paginate(page=page, per_page=per_page, error_out=False)