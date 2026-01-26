# Daily Brief Enhancements - Deeper Context & Audio

## Overview

Two major enhancements to the Daily Brief based on user feedback:

1. **"Want a bit more detail?"** - Expandable deeper context section
2. **Audio/Text-to-Speech** - Eleven Labs integration for listening

---

## Feature 1: Deeper Context

### What It Does

Adds an expandable "Want a bit more detail?" section to each brief item that provides:
- Historical context
- Broader implications
- Key players and institutions
- What to watch in coming days/weeks

### Implementation

**Database:**
- Added `deeper_context` field to `BriefItem` model (Text field)

**Generation:**
- Extended `BriefGenerator._generate_deeper_context()` method
- Generates 3-4 paragraphs of extended analysis using LLM
- Uses more articles (12 vs 8) for richer context
- Includes historical context, implications, key players, and future watch items

**UI:**
- Collapsible section with smooth toggle animation
- Button text changes: "Want a bit more detail?" ↔ "Show less detail"
- Styled with slate background and left border accent

### Usage

The deeper context is automatically generated when brief items are created. Users can click the button to expand/collapse the additional information.

---

## Feature 2: Audio/Text-to-Speech

### What It Does

Allows users to listen to brief items using Eleven Labs text-to-speech. Users can:
- Generate audio on-demand for any brief item
- Choose from multiple voice options
- Listen while doing other tasks

### Implementation

**Database:**
- Added `audio_url` field (String 500) - URL to generated audio file
- Added `audio_voice_id` field (String 100) - Voice ID used
- Added `audio_generated_at` field (DateTime) - Generation timestamp

**Service:**
- Created `ElevenLabsClient` class in `app/brief/eleven_labs_client.py`
- Supports 9 popular voices (Rachel, Domi, Bella, Antoni, Elli, Josh, Arnold, Adam, Sam)
- Configurable voice settings (stability, similarity, style, speaker boost)
- Handles API errors gracefully

**API Routes:**
- `POST /api/brief/item/<id>/audio` - Generate audio for an item
- `GET /audio/<filename>` - Serve audio files

**UI:**
- "Listen to this story" button when audio not yet generated
- Voice selector dropdown (hidden until user clicks generate)
- HTML5 audio player when audio is available
- Shows voice name used

### Voice Options

Default voices available:
- **Rachel** (Default) - Professional, clear female
- **Domi** - Warm, friendly female
- **Bella** - Calm, soothing female
- **Antoni** - Professional male
- **Elli** - Energetic female
- **Josh** - Deep, authoritative male
- **Arnold** - Strong, confident male
- **Adam** - Calm, clear male
- **Sam** - Friendly, approachable male

Users can experiment with different voices to find their preferred listening experience.

### Configuration

Set environment variable:
```bash
ELEVEN_LABS_API_KEY=your_api_key_here
```

### Storage

Audio files are stored in Replit Object Storage (or can be adapted for S3/filesystem). Files are cached with 1-year expiration.

---

## Database Migration

Run migration to add new fields:
```bash
flask db upgrade
```

Migration file: `migrations/versions/46ebc21e5d8625dd_add_deeper_context_and_audio_to_brief.py`

---

## Dependencies

Added to `requirements.txt`:
- `requests>=2.31.0` (for Eleven Labs API calls)

---

## User Experience

### Deeper Context Flow:
1. User reads brief item summary
2. Clicks "Want a bit more detail?"
3. Section expands with extended analysis
4. Can collapse to save space

### Audio Flow:
1. User clicks "Listen to this story"
2. (Optional) Selects preferred voice
3. Audio generates (takes 5-15 seconds)
4. Page reloads with audio player
5. User can play/pause audio

---

## Future Enhancements

Potential improvements:
- Pre-generate audio during brief creation (background job)
- Support for multilingual voices
- Playback speed controls
- Download audio option
- Batch audio generation for entire brief
- Voice preferences saved per user
- Audio analytics (play counts, completion rates)

---

## Notes

- Audio generation is on-demand to save costs (Eleven Labs charges per character)
- Deeper context generation uses existing LLM infrastructure
- Both features gracefully degrade if services unavailable
- Audio files are cached to avoid regeneration

---

## Testing

To test:
1. Generate a daily brief
2. View brief at `/brief`
3. Click "Want a bit more detail?" on any item
4. Click "Listen to this story" and select a voice
5. Verify audio plays correctly
