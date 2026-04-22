"""
Profile models: individual + company profiles, org membership, and
profile-view tracking.

ProfileView — per-view analytics row for both profile types, with
anonymous views allowed (viewer_id nullable).
IndividualProfile — per-user public profile with slug, social links,
and image assets.
CompanyProfile — the organisation equivalent (also owned by a User
via user_id, but functions as a team/org container).
OrganizationMember — seat membership linking users to a
CompanyProfile, with role (owner/admin/editor/viewer) and invite-token
onboarding.

Moved here from app/models.py as part of the models-split refactor.
ProfileView is included in this submodule because IndividualProfile
and CompanyProfile reference its class attributes directly in their
`foreign_keys=[ProfileView.individual_profile_id]` relationships — a
real Python reference, not a string, so the class must be in-scope at
class-body evaluation time. Keeping the four together in one file is
simpler than shuttling ProfileView across modules.
"""

from app import db
from app.lib.time import utcnow_naive
from app.models_legacy import generate_slug


class ProfileView(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Allow the view to be associated with either type of profile
    individual_profile_id = db.Column(db.Integer, db.ForeignKey('individual_profile.id'), nullable=True)
    company_profile_id = db.Column(db.Integer, db.ForeignKey('company_profile.id'), nullable=True)
    viewer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # nullable for anonymous views
    timestamp = db.Column(db.DateTime, default=utcnow_naive)
    ip_address = db.Column(db.String(45))  # Store IP address for analytics


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
    invited_at = db.Column(db.DateTime, default=utcnow_naive)
    joined_at = db.Column(db.DateTime, nullable=True)  # NULL if invite pending

    # Invitation token for email invites
    invite_token = db.Column(db.String(64), unique=True, nullable=True)
    invite_email = db.Column(db.String(255), nullable=True)  # Email for pending invites

    # Status: 'pending', 'active', 'removed'
    status = db.Column(db.String(20), default='pending', nullable=False)

    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)

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
