# TTS Removal and Deployment Changes

**Date:** January 26, 2026  
**Status:** Completed

## Summary

Removed the heavy TTS (Text-to-Speech) package from production deployment to resolve bundle size issues on Replit. Changed deployment type from autoscale to VM to support background scheduled jobs. Audio generation feature is now gracefully disabled when TTS is not available.

## What Changed

### 1. TTS Package Removal

**Problem:**
- The `TTS==0.22.0` package (Coqui XTTS v2) plus its dependencies (PyTorch ~1.8GB, transformers, torchaudio, scipy, librosa, CUDA libraries) totaled several gigabytes
- This caused deployment bundle stage failures on Replit
- Bundle size exceeded limits and caused timeouts

**Solution:**
- Removed `TTS` package from `requirements.txt`
- Code already handles missing TTS gracefully via `XTTSClient.available` check
- Audio generation UI is now conditionally hidden when TTS is not available

**Files Changed:**
- `requirements.txt` - Removed TTS package and dependencies
- `.replit` - No changes (package removal handled in requirements.txt)

### 2. Deployment Type Change

**Problem:**
- Autoscale deployment only runs during requests
- Background scheduled jobs (social media posting, trending topics, queue processing) need a server that stays on continuously
- Multiple autoscale instances caused race conditions (fixed separately with `FOR UPDATE SKIP LOCKED`)

**Solution:**
- Changed deployment type from `autoscale` to `vm` in `.replit`
- VM deployment ensures background jobs run continuously
- Single instance eliminates race condition concerns (though defensive code remains)

**Files Changed:**
- `.replit` - Changed `deploymentTarget` from `"autoscale"` to `"vm"`

### 3. UI Improvements

**Enhancement:**
- Audio generation button now only appears when TTS is actually available
- Prevents confusion when users try to generate audio but TTS isn't installed
- Better UX - feature is hidden rather than showing an error after clicking

**Files Changed:**
- `app/brief/routes.py` - Added `is_tts_available()` helper, pass `tts_available` to templates
- `app/briefing/routes.py` - Added `is_tts_available()` helper, pass `tts_available` to templates
- `app/templates/brief/view.html` - Conditionally show audio section based on `tts_available`
- `app/templates/briefing/run_view.html` - Conditionally show audio section based on `tts_available`

## Technical Details

### TTS Availability Check

The code uses a helper function to check if TTS is available:

```python
def is_tts_available():
    """Check if TTS is available (XTTS package installed)."""
    try:
        from app.brief.xtts_client import XTTSClient
        client = XTTSClient()
        return client.available
    except Exception:
        return False
```

The `XTTSClient` class already had built-in availability checking:
- `_check_availability()` tries to import `TTS` package
- Sets `self.available = False` if import fails
- `generate_audio()` returns `None` if not available

### Graceful Degradation

The system handles missing TTS gracefully:
1. **Backend:** `XTTSClient.generate_audio()` returns `None` if TTS unavailable
2. **Job Processing:** Audio generation jobs fail gracefully with error messages
3. **UI:** Audio generation button is hidden when TTS unavailable
4. **No Crashes:** All code paths handle missing TTS without exceptions

## Impact

### What Still Works
- ✅ All core functionality (briefs, discussions, social media posting)
- ✅ Background scheduled jobs (now more reliable on VM)
- ✅ Social media posting (race condition fix remains as defensive code)
- ✅ All other features unaffected

### What's Disabled
- ❌ Audio generation for briefs (feature disabled in production)
- Only 2 users had requested this feature
- Can be re-enabled later with cloud TTS API if demand grows

## Future Options

If audio generation is needed in the future, consider:

1. **Cloud TTS APIs** (Recommended if demand grows):
   - OpenAI TTS: $15 per 1M characters (~$0.015 per 1K chars)
   - AWS Polly: $4 per 1M characters (cheapest)
   - Google Cloud TTS: $4 per 1M characters
   - ElevenLabs: $5/month for 30K chars (free tier: 10K/month)

2. **User-Provided API Keys**:
   - Infrastructure already exists (`UserAPIKey` model)
   - Users could bring their own OpenAI/ElevenLabs keys
   - Minimal code changes needed (swap `XTTSClient` for cloud client)

3. **Edge TTS** (Experimental):
   - Free, lightweight alternative
   - Not officially supported for server-side use
   - Risk of breaking changes or ToS violations

## Related Changes

### Race Condition Fix (Separate Change)
- Fixed duplicate social media posts caused by Replit autoscale
- Used PostgreSQL `FOR UPDATE SKIP LOCKED` to prevent concurrent processing
- Still valuable as defensive code even with single VM instance

## Testing

To test TTS availability:
1. **With TTS installed:** Audio generation button should appear for admins
2. **Without TTS:** Audio generation button should be hidden
3. **Job creation:** Should fail gracefully with clear error if TTS unavailable

## Deployment Notes

- No database migrations required
- No environment variable changes needed
- Code changes are backward compatible
- Existing audio files in storage remain accessible
- Audio generation jobs in queue will fail gracefully

## Rollback Plan

If TTS needs to be re-enabled:
1. Add `TTS==0.22.0` back to `requirements.txt`
2. Re-deploy (will increase bundle size significantly)
3. UI will automatically show audio generation button when TTS is available

## Documentation References

- Original audio implementation: `docs/DAILY_BRIEF_AUDIO_IMPLEMENTATION.md`
- Audio features summary: `docs/DAILY_BRIEF_FEATURES_SUMMARY.md`
- Race condition fix: See commit `43d12f6` - "Fix duplicate social media posts caused by Replit autoscale race condition"
