"""Add lens_check field to DailyBrief for cross-perspective headline comparison

This field stores the "Same Story, Different Lens" analysis that shows how
different political perspectives frame the same news story. The analysis
is generated automatically during brief creation.

Schema:
{
    "story_summary": "Neutral one-sentence description of the event",
    "topic_id": 123,  # Reference to TrendingTopic if applicable
    "selection_criteria": {
        "total_sources": 10,
        "left_sources": 4,
        "centre_sources": 3,
        "right_sources": 3,
        "coverage_balance_score": 0.85,
        "selected_reason": "Highest cross-spectrum coverage in last 24h"
    },
    "perspectives": {
        "left": {
            "source_count": 4,
            "emphasis": "Environmental impact, developer influence",
            "language_patterns": ["cave", "lobby", "sacrifice"],
            "headlines": [
                {"source": "The Guardian", "title": "...", "url": "..."},
                {"source": "The Independent", "title": "...", "url": "..."}
            ]
        },
        "centre": { ... },
        "right": { ... }
    },
    "contrast_analysis": "Left frames as environmental loss, right as economic gain...",
    "omissions": "No outlet mentioned impact on existing homeowners...",
    "methodology_version": "1.0",
    "generated_at": "2026-01-11T17:00:00Z"
}

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-01-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'h2i3j4k5l6m7'
down_revision = 'g1h2i3j4k5l6'
branch_labels = None
depends_on = None


def upgrade():
    # Add lens_check JSON field to daily_brief table
    # This stores the cross-perspective headline comparison analysis
    op.add_column('daily_brief', sa.Column('lens_check', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('daily_brief', 'lens_check')
