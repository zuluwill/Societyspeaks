"""Partner portal RBAC helpers."""

PERM_KEYS_MANAGE = 'keys.manage'
PERM_DISCUSSIONS_MANAGE = 'discussions.manage'
PERM_ANALYTICS_VIEW = 'analytics.view'
PERM_TEAM_MANAGE = 'team.manage'
PERM_DOMAINS_MANAGE = 'domains.manage'
PERM_BILLING_MANAGE = 'billing.manage'
PERM_WEBHOOKS_MANAGE = 'webhooks.manage'

# Canonical ordered tuple of all permission keys.
# routes.py and any form handler must use this — never hardcode the list elsewhere.
ALL_PERMISSIONS = (
    PERM_KEYS_MANAGE,
    PERM_DISCUSSIONS_MANAGE,
    PERM_ANALYTICS_VIEW,
    PERM_TEAM_MANAGE,
    PERM_DOMAINS_MANAGE,
    PERM_BILLING_MANAGE,
    PERM_WEBHOOKS_MANAGE,
)


DEFAULT_ROLE_PERMISSIONS = {
    'owner': {
        PERM_KEYS_MANAGE: True,
        PERM_DISCUSSIONS_MANAGE: True,
        PERM_ANALYTICS_VIEW: True,
        PERM_TEAM_MANAGE: True,
        PERM_DOMAINS_MANAGE: True,
        PERM_BILLING_MANAGE: True,
        PERM_WEBHOOKS_MANAGE: True,
    },
    'admin': {
        PERM_KEYS_MANAGE: True,
        PERM_DISCUSSIONS_MANAGE: True,
        PERM_ANALYTICS_VIEW: True,
        PERM_TEAM_MANAGE: True,
        PERM_DOMAINS_MANAGE: True,
        PERM_BILLING_MANAGE: False,
        PERM_WEBHOOKS_MANAGE: True,
    },
    'member': {
        PERM_KEYS_MANAGE: False,
        PERM_DISCUSSIONS_MANAGE: False,
        PERM_ANALYTICS_VIEW: True,
        PERM_TEAM_MANAGE: False,
        PERM_DOMAINS_MANAGE: False,
        PERM_BILLING_MANAGE: False,
        PERM_WEBHOOKS_MANAGE: False,
    },
}


def member_permissions(member):
    """Resolve effective permissions: role defaults overridden by explicit JSON flags."""
    if not member:
        return {}
    role = getattr(member, 'role', 'member') or 'member'
    resolved = dict(DEFAULT_ROLE_PERMISSIONS.get(role, DEFAULT_ROLE_PERMISSIONS['member']))
    explicit = getattr(member, 'permissions_json', None) or {}
    if isinstance(explicit, dict):
        for key, value in explicit.items():
            if key in resolved:
                resolved[key] = bool(value)
    return resolved


def member_can(member, permission):
    return bool(member_permissions(member).get(permission, False))
