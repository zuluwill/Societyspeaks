"""
Machine-translation caches for user-visible dynamic content.

StatementTranslation, DiscussionTranslation, ProgrammeTranslation —
display-only caches. Votes and canonical content always target the
parent row's ID; rows here are re-generated if they go missing.
Moved from app/models.py as part of the models-split refactor.
Related classes (Statement, Discussion, Programme) are referenced via
string.
"""

from app import db
from app.lib.time import utcnow_naive


class StatementTranslation(db.Model):
    """
    Machine-translated content for individual statements.

    Votes always target the canonical Statement.id — this table is a pure display
    cache. Rows are created lazily on first request for a given language and reused
    on every subsequent request (zero translation cost after the first hit).
    """
    __tablename__ = 'statement_translation'
    __table_args__ = (
        db.UniqueConstraint('statement_id', 'language_code', name='uq_statement_translation'),
        db.Index('idx_stmt_translation_stmt_lang', 'statement_id', 'language_code'),
    )

    id = db.Column(db.Integer, primary_key=True)
    statement_id = db.Column(db.Integer, db.ForeignKey('statement.id', ondelete='CASCADE'), nullable=False)
    language_code = db.Column(db.String(10), nullable=False)
    content = db.Column(db.Text, nullable=False)
    translation_source = db.Column(db.String(20), default='machine')  # 'machine' | 'human'
    created_at = db.Column(db.DateTime, default=utcnow_naive)

    statement = db.relationship('Statement', backref=db.backref('translations', cascade='all, delete-orphan'))


class DiscussionTranslation(db.Model):
    """Machine-translated title, description, and journey info panel for discussions."""
    __tablename__ = 'discussion_translation'
    __table_args__ = (
        db.UniqueConstraint('discussion_id', 'language_code', name='uq_discussion_translation'),
        db.Index('idx_disc_translation_disc_lang', 'discussion_id', 'language_code'),
    )

    id = db.Column(db.Integer, primary_key=True)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id', ondelete='CASCADE'), nullable=False)
    language_code = db.Column(db.String(10), nullable=False)
    title = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=True)
    information_title = db.Column(db.Text, nullable=True)  # Journey info panel heading
    information_body = db.Column(db.Text, nullable=True)   # Journey info panel body (markdown)
    translation_source = db.Column(db.String(20), default='machine')
    created_at = db.Column(db.DateTime, default=utcnow_naive)

    discussion = db.relationship('Discussion', backref=db.backref('translations', cascade='all, delete-orphan'))


class ProgrammeTranslation(db.Model):
    """Machine-translated name and description for programmes (civic journey guides)."""
    __tablename__ = 'programme_translation'
    __table_args__ = (
        db.UniqueConstraint('programme_id', 'language_code', name='uq_programme_translation'),
        db.Index('idx_prog_translation_prog_lang', 'programme_id', 'language_code'),
    )

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey('programme.id', ondelete='CASCADE'), nullable=False)
    language_code = db.Column(db.String(10), nullable=False)
    name = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=True)
    translation_source = db.Column(db.String(20), default='machine')
    created_at = db.Column(db.DateTime, default=utcnow_naive)

    programme = db.relationship('Programme', backref=db.backref('translations', cascade='all, delete-orphan'))
