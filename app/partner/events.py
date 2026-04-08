"""Canonical partner event names and payload serializers."""

from app.api.utils import build_discussion_urls


EVENT_DISCUSSION_CREATED = 'discussion.created'
EVENT_DISCUSSION_UPDATED = 'discussion.updated'
EVENT_CONSENSUS_UPDATED = 'consensus.updated'
EVENT_KEY_REVOKED = 'key.revoked'
EVENT_DOMAIN_VERIFICATION_CHANGED = 'domain.verification_changed'

ALL_PARTNER_EVENTS = {
    EVENT_DISCUSSION_CREATED,
    EVENT_DISCUSSION_UPDATED,
    EVENT_CONSENSUS_UPDATED,
    EVENT_KEY_REVOKED,
    EVENT_DOMAIN_VERIFICATION_CHANGED,
}


def serialize_discussion_payload(discussion):
    urls = build_discussion_urls(discussion, include_ref=False)
    return {
        'discussion_id': discussion.id,
        'slug': discussion.slug,
        'title': discussion.title,
        'partner_id': discussion.partner_id,
        'partner_env': discussion.partner_env,
        'partner_article_url': discussion.partner_article_url,
        'external_id': discussion.partner_external_id,
        'embed_statement_submissions_enabled': bool(getattr(discussion, 'embed_statement_submissions_enabled', False)),
        'is_closed': bool(discussion.is_closed),
        'integrity_mode': bool(discussion.integrity_mode),
        'urls': urls,
        'updated_at': discussion.updated_at.isoformat() if discussion.updated_at else None,
    }


def serialize_key_payload(key_record):
    return {
        'key_id': key_record.id,
        'env': key_record.env,
        'status': key_record.status,
        'key_prefix': key_record.key_prefix,
        'key_last4': key_record.key_last4,
        'last_used_at': key_record.last_used_at.isoformat() if key_record.last_used_at else None,
    }


def serialize_domain_payload(domain):
    return {
        'domain_id': domain.id,
        'domain': domain.domain,
        'env': domain.env,
        'is_active': bool(domain.is_active),
        'is_verified': bool(domain.verified_at),
        'verified_at': domain.verified_at.isoformat() if domain.verified_at else None,
    }


def serialize_consensus_payload(discussion, analysis):
    return {
        'discussion_id': discussion.id,
        'analysis_id': analysis.id,
        'num_clusters': analysis.num_clusters,
        'participants_count': analysis.participants_count,
        'statements_count': analysis.statements_count,
        'method': analysis.method,
        'created_at': analysis.created_at.isoformat() if analysis.created_at else None,
    }
