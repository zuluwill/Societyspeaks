# Leveraging Existing Data for Social Media Growth

**DRY Principle Implementation: Reusing Discussion Data for Engaging Posts**

---

## Overview

Instead of creating new data structures, we're **leveraging existing discussion data** (consensus analysis, votes, statements) to create engaging social media posts that stay true to our mission.

---

## What Data We Already Have

### 1. **ConsensusAnalysis Model** (`app/models.py`)
- `cluster_data` (JSON): Contains consensus/bridge/divisive statements
- `participants_count`: Number of people who participated
- `statements_count`: Number of statements in discussion
- Already calculated and cached!

### 2. **Statement Model** (`app/models.py`)
- `agreement_rate` property: Percentage who agree
- `controversy_score` property: How divisive (1 = 50/50, 0 = consensus)
- `vote_count_agree/disagree/unsure`: Denormalized counts
- `total_votes`: Total vote count
- Already calculated!

### 3. **StatementVote Model** (`app/models.py`)
- Vote history for all participants
- Links to discussions and statements
- Already stored!

### 4. **Discussion Model** (`app/models.py`)
- `participant_count`: Number of participants
- `title`, `description`, `topic`
- Links to consensus analyses
- Already available!

---

## How We Leverage This Data

### New Module: `app/trending/social_insights.py`

This module **reuses existing models and data** to extract insights:

```python
def get_discussion_insights(discussion) -> Dict:
    """
    Extract insights from a discussion using existing data structures.
    
    Reuses:
    - ConsensusAnalysis.cluster_data (consensus/bridge/divisive statements)
    - Statement.agreement_rate, controversy_score properties
    - StatementVote counts
    - Discussion.participant_count
    """
```

**What it extracts:**
1. **Consensus statements** - High agreement (70%+)
2. **Bridge statements** - Common ground across groups
3. **Divisive statements** - 50/50 splits
4. **Surprising findings** - Mission-aligned insights
5. **Hook candidates** - Engaging opening lines

### Integration: Updated `app/trending/social_poster.py`

The `generate_post_text()` function now accepts an optional `discussion` parameter:

```python
def generate_post_text(
    title: str,
    topic: str,
    discussion_url: str,
    platform: str = 'bluesky',
    discussion=None  # Optional: pass Discussion object to use insights
) -> str:
```

**If discussion is provided:**
- Calls `generate_data_driven_post()` from `social_insights.py`
- Leverages consensus data, vote counts, participant counts
- Creates engaging hooks like "78% agree on this—but you'd never know from headlines"

**If discussion is not provided:**
- Falls back to basic format (backwards compatible)
- No breaking changes

---

## Example: Before vs After

### Before (Generic)
```
New debate: Should the UK increase defense spending?

https://societyspeaks.io/discussions/123/...

#Politics #Defense
```

### After (Data-Driven, Mission-Aligned)
```
78% of people agree on this—but you'd never know from the headlines.

💡 78% agree: Defense spending should focus on effectiveness, not just amount

👥 150+ people have shared their perspective

https://societyspeaks.io/discussions/123/...

#Politics #Defense
```

**Why this is better:**
- ✅ **Surprising stat** (78% agree) - drives engagement
- ✅ **Mission-aligned** (reveals consensus)
- ✅ **Social proof** (150+ participants)
- ✅ **Uses existing data** (no new calculations)

---

## Mission Alignment

Our mission: **Reveal consensus, find bridge ideas, understand nuance**

### How We Stay True to Mission:

1. **Consensus Statements** → "78% agree on this"
2. **Bridge Statements** → "Common ground found: [statement]"
3. **Divisive Statements** → "Here's where people disagree"
4. **Participation** → "150+ people have shared their perspective"
5. **Nuance** → "Both consensus and division revealed"

**We're not just promoting discussions—we're revealing insights that already exist in the data.**

---

## DRY Principles Applied

### ✅ Reuse Existing Models
- `ConsensusAnalysis.cluster_data` - Already calculated!
- `Statement.agreement_rate` - Already a property!
- `Statement.controversy_score` - Already a property!
- `Discussion.participant_count` - Already stored!

### ✅ Reuse Existing Functions
- `get_discussion_insights()` - Extracts from existing data
- `generate_data_driven_post()` - Uses existing insights
- `generate_post_text()` - Falls back to existing format

### ✅ No Duplication
- No new database queries (uses existing relationships)
- No new calculations (uses existing properties)
- No new data structures (uses existing JSON)

### ✅ Backwards Compatible
- If `discussion=None`, uses basic format
- Existing code continues to work
- New code gets enhanced posts

---

## Implementation Details

### 1. **Insight Extraction** (`social_insights.py`)

```python
# Reuses ConsensusAnalysis.cluster_data
analysis = ConsensusAnalysis.query.filter_by(
    discussion_id=discussion.id
).order_by(ConsensusAnalysis.created_at.desc()).first()

# Reuses existing JSON structure
consensus_data = cluster_data.get('consensus_statements', [])
bridge_data = cluster_data.get('bridge_statements', [])
divisive_data = cluster_data.get('divisive_statements', [])
```

### 2. **Hook Generation** (`social_insights.py`)

```python
# Uses existing agreement_rate property
if top_consensus['agreement_rate'] >= 0.75:
    hooks.append(
        f"{int(top_consensus['agreement_rate'] * 100)}% of people agree on this—"
        f"but you'd never know from the headlines."
    )
```

### 3. **Post Generation** (`social_poster.py`)

```python
# Passes discussion object to leverage insights
text = generate_post_text(
    title=discussion.title,
    topic=discussion.topic,
    discussion_url=discussion_url,
    platform='x',
    discussion=discussion  # Enables data-driven posts
)
```

---

## Benefits

### 1. **Mission-Aligned**
- Posts reveal consensus, bridges, nuance
- Not just promotional—educational and insightful

### 2. **Engaging**
- Surprising stats drive engagement
- Social proof (participant counts)
- Data-driven hooks

### 3. **DRY**
- Reuses existing data structures
- No duplication
- No new calculations

### 4. **Backwards Compatible**
- Existing code continues to work
- New code gets enhanced posts
- Graceful fallback

### 5. **Maintainable**
- Single source of truth (existing models)
- Changes to consensus analysis automatically reflected
- No sync issues

---

## Usage Examples

### Example 1: Auto-Publish (Already Integrated)
```python
# In app/trending/publisher.py
publish_topic(topic, admin_user, schedule_x=True)

# Automatically uses discussion object when posting
# Leverages consensus data if available
```

### Example 2: Manual Post
```python
# In app/trending/social_poster.py
share_discussion_to_social(discussion)

# Automatically passes discussion object
# Generates data-driven post
```

### Example 3: Direct Usage
```python
from app.trending.social_insights import get_discussion_insights

insights = get_discussion_insights(discussion)
print(insights['hook_candidates'])
# ["78% of people agree on this—but you'd never know from headlines"]
```

---

## Future Enhancements

### 1. **Visual Content**
- Generate quote cards from consensus statements
- Create charts from vote data
- Screenshot interesting discussions

### 2. **Thread Generation**
- Break complex insights into threads
- One tweet per insight type (consensus/bridge/divisive)

### 3. **A/B Testing**
- Test different hook formats
- Measure engagement rates
- Optimize based on data

### 4. **Real-Time Updates**
- Post when consensus analysis completes
- Share surprising findings as they emerge
- Highlight bridge statements

---

## Summary

**We're not creating new data—we're using what we already have.**

- ✅ Reuses `ConsensusAnalysis.cluster_data`
- ✅ Reuses `Statement.agreement_rate` and `controversy_score`
- ✅ Reuses `Discussion.participant_count`
- ✅ Reuses existing relationships and queries
- ✅ Stays true to mission (consensus, bridges, nuance)
- ✅ Backwards compatible
- ✅ DRY principles applied

**Result:** Engaging, mission-aligned social media posts that reveal insights already present in our data.
