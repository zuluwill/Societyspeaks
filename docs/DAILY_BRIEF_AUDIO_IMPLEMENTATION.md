# Daily Brief Audio Implementation - Scalable Architecture

## Overview

Production-ready batch audio generation system using open-source XTTS v2, designed to scale from day one.

## Architecture

### Components

1. **XTTS v2 Client** (`app/brief/xtts_client.py`)
   - Open-source TTS using Coqui XTTS v2
   - CPU-friendly (no GPU required)
   - Multiple voice presets
   - Free and scalable

2. **Storage Abstraction** (`app/brief/audio_storage.py`)
   - S3-compatible storage (primary)
   - Replit storage (fallback)
   - Filesystem (development fallback)
   - Automatic provider detection

3. **Batch Audio Generator** (`app/brief/audio_generator.py`)
   - Creates jobs for entire briefs
   - Progress tracking
   - Error handling and retries
   - Database-backed job queue

4. **Job Processor** (in `app/scheduler.py`)
   - Background job processing
   - Runs every 5 seconds
   - Processes one job at a time

5. **Database Model** (`AudioGenerationJob`)
   - Tracks job status (queued, processing, completed, failed)
   - Progress tracking (0-100%)
   - Error messages
   - Timestamps

## User Experience

### Flow

1. User clicks "Generate All Audio" button
2. Selects voice (Professional, Warm, Authoritative, Calm, Friendly)
3. Job created in database
4. Background processor picks up job
5. Progress bar shows real-time status
6. Audio players appear when complete
7. Page auto-refreshes to show audio

### Features

- **Batch Generation**: All items in brief generated at once
- **Progress Tracking**: Real-time progress bar with percentage
- **Voice Selection**: 5 preset voices
- **Status Polling**: Client polls every second for updates
- **Error Handling**: Graceful error messages
- **Auto-refresh**: Page reloads when complete

## API Endpoints

### `POST /api/brief/<brief_id>/audio/generate`
Creates a new audio generation job.

**Request:**
```json
{
  "voice_id": "professional"  // optional
}
```

**Response:**
```json
{
  "success": true,
  "job_id": 123,
  "status": "queued",
  "total_items": 5
}
```

### `GET /api/brief/audio/job/<job_id>/status`
Get job status and progress.

**Response:**
```json
{
  "id": 123,
  "brief_id": 456,
  "voice_id": "professional",
  "status": "processing",
  "progress": 60,
  "total_items": 5,
  "completed_items": 3,
  "error_message": null
}
```

### `GET /audio/<filename>`
Serve audio files from storage.

## Database Schema

### AudioGenerationJob

```python
id: Integer (PK)
brief_id: Integer (FK to daily_brief)
voice_id: String(100)  # Voice preset used
status: String(20)  # queued, processing, completed, failed
progress: Integer  # 0-100 percentage
total_items: Integer
completed_items: Integer
error_message: Text
created_at: DateTime
started_at: DateTime
completed_at: DateTime
```

## Storage Strategy

### Priority Order

1. **S3-compatible** (if AWS credentials set)
   - Scalable, reliable
   - CDN-ready
   - Best for production

2. **Replit Storage** (fallback)
   - Simple, no setup
   - Good for development
   - Limited capacity

3. **Filesystem** (development)
   - Local development only
   - Not persistent on Replit

### File Naming

Format: `brief_{brief_id}_item_{item_id}_{timestamp}_{hash}.wav`

Example: `brief_123_item_456_20260126_143022_a1b2c3d4.wav`

## Voice Presets

- **Professional**: Clear, professional narration
- **Warm**: Friendly, warm tone
- **Authoritative**: Confident, authoritative voice
- **Calm**: Calm, soothing narration
- **Friendly**: Approachable, friendly tone

## Installation

### Dependencies

Add to `requirements.txt`:
```
TTS>=0.22.0  # Coqui TTS library
```

### Optional (for S3 storage)
```
boto3>=1.34.0
```

### Setup

1. Install TTS library:
   ```bash
   pip install TTS
   ```

2. Run migration:
   ```bash
   flask db upgrade
   ```

3. (Optional) Set S3 credentials for production:
   ```bash
   export AWS_ACCESS_KEY_ID=your_key
   export AWS_SECRET_ACCESS_KEY=your_secret
   export AWS_S3_BUCKET=your-bucket
   ```

## Performance

### Generation Time

- Per item: ~30-60 seconds (CPU)
- Full brief (5 items): ~3-5 minutes
- Background processing (non-blocking)

### Resource Usage

- CPU: Moderate (XTTS v2 is CPU-friendly)
- Memory: ~2GB for model loading
- Storage: ~1-2MB per audio file

## Scaling Considerations

### Current Design

- ✅ Database-backed job queue (scales horizontally)
- ✅ Storage abstraction (S3-ready)
- ✅ Background processing (non-blocking)
- ✅ Progress tracking (real-time updates)
- ✅ Error handling (graceful failures)

### Future Enhancements

1. **Multiple Workers**: Process multiple jobs in parallel
2. **Redis Queue**: For higher throughput
3. **CDN Integration**: Serve audio via CDN
4. **Pre-generation**: Generate audio during brief creation
5. **Voice Cloning**: Allow custom voices
6. **Multilingual**: Support multiple languages

## Cost Analysis

### Current (Open Source)

- **TTS**: $0 (self-hosted)
- **Storage**: ~$0.023/GB/month (S3) or free (Replit)
- **Compute**: Included in hosting costs

### Comparison to Eleven Labs

- **Eleven Labs**: ~$180 per 1M characters
- **XTTS v2**: $0 (self-hosted)
- **Savings**: ~$1,350-$2,700/month at scale

## Monitoring

### Key Metrics

- Job queue length
- Average generation time
- Success/failure rate
- Storage usage
- User engagement (audio plays)

### Logging

All operations logged with:
- Job creation
- Progress updates
- Completion/failure
- Errors with stack traces

## Troubleshooting

### Audio Not Generating

1. Check TTS library installed: `pip list | grep TTS`
2. Check job status: `/api/brief/audio/job/<id>/status`
3. Check logs for errors
4. Verify storage provider available

### Slow Generation

1. Normal: 30-60s per item on CPU
2. Consider GPU for faster generation
3. Can pre-generate during brief creation

### Storage Issues

1. Check storage provider credentials
2. Verify storage limits (Replit has limits)
3. Implement cleanup for old files

## Best Practices

1. **Always use batch generation** (not per-item)
2. **Show progress** to users
3. **Handle errors gracefully**
4. **Cache audio files** (don't regenerate)
5. **Monitor job queue** for backlog
6. **Clean up old files** periodically

## Future Roadmap

- [ ] Pre-generation during brief creation
- [ ] Multiple workers for parallel processing
- [ ] Voice cloning support
- [ ] Multilingual support
- [ ] Audio analytics (play counts)
- [ ] Download audio option
- [ ] Playback speed controls
