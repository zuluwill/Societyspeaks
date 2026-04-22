"""
Models package — shim state during the models-split refactor.

Step 0 of the refactor renames the original app/models.py to
app/models_legacy.py and introduces this package. At this point every
class and helper still lives in models_legacy.py; this __init__.py
re-exports them so `from app.models import X` continues to work
unchanged for the 307 existing call sites.

Subsequent steps move classes into domain submodules (app/models/users.py,
app/models/discussions.py, etc.) and update this file to import from the
new locations. The public contract of `from app.models import X` must
survive every step.

Invariant for the final package layout:
    Every submodule in app/models/ MUST be imported here, whether its
    classes are re-exported individually or not. The SQLAlchemy
    declarative registry is populated by import side-effect; a submodule
    that is defined but not imported has zero tables in db.metadata, and
    alembic autogenerate will happily emit a DROP TABLE migration for it.
    Do not "clean up" what look like unused imports in this file.
"""

# Legacy shim (still holding most classes during the refactor).
from app.models_legacy import *  # noqa: F401, F403

# Explicit re-exports for the two non-class public names, both of which
# are imported directly by other modules (db: 4 sites, generate_slug: 3).
from app.models_legacy import db, generate_slug  # noqa: F401

# Moved submodules. Keep importing them even if nothing else in the codebase
# does — the side effect registers their tables in db.metadata.
from app.models.polymarket import PolymarketMarket, TopicMarketMatch  # noqa: F401
from app.models.billing import PricingPlan, Subscription, Donation  # noqa: F401
from app.models.email import EmailEvent, BriefEmailEvent  # noqa: F401
from app.models.analytics import AnalyticsEvent, AnalyticsDailyAggregate  # noqa: F401
from app.models.translations import (  # noqa: F401
    StatementTranslation,
    DiscussionTranslation,
    ProgrammeTranslation,
)
from app.models.consensus import ConsensusAnalysis, ConsensusJob  # noqa: F401
from app.models.admin import AdminAuditEvent, AdminSettings  # noqa: F401
from app.models.briefing import (  # noqa: F401
    BriefTemplate,
    InputSource,
    IngestedItem,
    Briefing,
    BriefingSource,
    BriefRun,
    BriefRunItem,
    BriefEmailOpen,
    BriefEmailSend,
    BriefLinkClick,
    BriefRecipient,
    SendingDomain,
    BriefEdit,
)
from app.models.daily_brief import (  # noqa: F401
    DailyBrief,
    BriefItem,
    NewsPerspectiveCache,
    AudioGenerationJob,
    DailyBriefSubscriber,
    BriefTeam,
)
from app.models.daily_question import (  # noqa: F401
    DailyQuestion,
    DailyQuestionResponse,
    DailyQuestionResponseFlag,
    DailyQuestionSubscriber,
    DailyQuestionSelection,
)
from app.models.trending import (  # noqa: F401
    TrendingTopic,
    TrendingTopicArticle,
    DiscussionSourceArticle,
    UpcomingEvent,
    SocialPostEngagement,
)
from app.models.news import NewsSource, NewsArticle  # noqa: F401
from app.models.partner import (  # noqa: F401
    Partner,
    PartnerDomain,
    PartnerApiKey,
    PartnerWebhookEndpoint,
    PartnerWebhookDelivery,
    PartnerMember,
    PartnerUsageEvent,
)
