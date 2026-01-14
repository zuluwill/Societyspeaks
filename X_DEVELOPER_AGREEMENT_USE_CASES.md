# X Developer Agreement - Use Cases Description

## Use Cases for X API Integration

**Society Speaks** (societyspeaks.io) is a public discussion platform that facilitates nuanced civic debate and consensus-building. We use X's API to automatically post announcements about new public discussions to promote civic engagement and increase participation in important public conversations.

### Primary Use Case: Discussion Promotion

We use X's API v2 (via Tweepy library) to automatically post announcements when new public discussions are created on our platform. These posts:

1. **Announce new discussion topics** - When our system creates discussions from trending news topics or user-generated content, we post a brief announcement to X that includes:
   - A short description of the discussion topic
   - A link to the discussion on our platform
   - Relevant hashtags for discoverability
   - Topic category information

2. **Respect rate limits** - We implement strict rate limiting to ensure compliance with X's API limits:
   - Maximum 15 posts per day (well below the 500/month free tier limit)
   - Monthly tracking to ensure we never exceed 500 posts per month
   - Proactive rate limit checking before each post attempt
   - Exponential backoff retry logic for transient errors

3. **Staggered scheduling** - Posts are scheduled at optimal times throughout the day (5 time slots) to:
   - Avoid overwhelming our followers
   - Target peak engagement times
   - Distribute content evenly across the day

### Data Usage

- **We only POST content** - We use the `create_tweet` endpoint to post announcements
- **We do NOT read or analyze user data** - We do not fetch tweets, user profiles, timelines, or any other X data
- **We do NOT resell data** - All data from X API is used solely for posting our own content
- **We track our own posts** - We store tweet IDs in our database only to prevent duplicate posts and track posting history

### Purpose

Our use of X's API serves to:
- **Promote civic engagement** - Help people discover important public discussions
- **Increase platform visibility** - Share discussions about current events, politics, policy, and social issues
- **Drive traffic to our platform** - Direct X users to participate in structured, nuanced discussions on our site
- **Support democratic discourse** - Encourage informed public debate on important topics

### Technical Implementation

- **API Endpoint Used**: `POST /2/tweets` (via Tweepy's `create_tweet` method)
- **Authentication**: OAuth 1.0a with consumer keys and access tokens
- **Error Handling**: Comprehensive retry logic with exponential backoff
- **Rate Limit Compliance**: Proactive checking and tracking of daily/monthly limits
- **Account**: @societyspeaksio

### Data Protection & Privacy

- We do not collect, store, or process any X user data
- We only post our own original content (discussion announcements)
- All API credentials are stored securely as environment variables
- We comply with X's Developer Agreement and Terms of Service

---

**Summary**: We use X's API exclusively to post automated announcements about new public discussions on our civic engagement platform. We do not read, analyze, or resell any X data. Our goal is to promote informed public discourse by sharing discussion topics with the X community.
