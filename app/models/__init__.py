"""
Models package — aggregated import surface.

The original monolithic app/models.py has been split across domain
submodules. Every persistent class reaches the SQLAlchemy declarative
registry via one of the imports in this file, so the `from app.models
import X` contract used by ~300 call sites in the rest of the app
continues to resolve the same names.

Invariant for the package layout:
    Every submodule in app/models/ MUST be imported here, whether its
    classes are re-exported individually or not. The SQLAlchemy
    declarative registry is populated by import side-effect; a submodule
    that is defined but not imported has zero tables in db.metadata, and
    alembic autogenerate will happily emit a DROP TABLE migration for it.
    Do not "clean up" what look like unused imports in this file.
"""

# Non-class public names re-exported by historical convention
# (db: 4 call sites, generate_slug: 4 call sites).
from app import db  # noqa: F401
from app.models._base import generate_slug  # noqa: F401

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
from app.models.profiles import (  # noqa: F401
    ProfileView,
    IndividualProfile,
    CompanyProfile,
    OrganizationMember,
)
from app.models.programme import (  # noqa: F401
    Programme,
    ProgrammeSteward,
    ProgrammeAccessGrant,
    ProgrammeExportJob,
)
from app.models.discussions import (  # noqa: F401
    DiscussionView,
    Notification,
    DiscussionFollow,
    DiscussionUpdate,
    DiscussionParticipant,
    Discussion,
    Statement,
    StatementVote,
    Response,
    Evidence,
    JourneyReminderSubscription,
    StatementFlag,
)
from app.models.users import User, UserAPIKey  # noqa: F401
