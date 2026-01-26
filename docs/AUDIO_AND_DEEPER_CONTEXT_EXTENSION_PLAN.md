# Audio & Deeper Context - Extension to Paid Briefs

## Current Status

### ✅ Daily Brief (Working)
- `BriefItem` has: `deeper_context`, `audio_url`, `audio_voice_id`
- `AudioGenerationJob` works with `DailyBrief`
- UI implemented in `brief/view.html`

### ❌ Paid Briefs (Not Working)
- `BriefRunItem` does NOT have: `deeper_context`, `audio_url`, `audio_voice_id`
- `AudioGenerationJob` only works with `DailyBrief`
- No UI in `briefing/run_view.html`

---

## Required Changes

### 1. Database Migration
Add fields to `BriefRunItem`:
- `deeper_context` (Text)
- `audio_url` (String 500)
- `audio_voice_id` (String 100)
- `audio_generated_at` (DateTime)

### 2. Make AudioGenerationJob Polymorphic
Support both `DailyBrief` and `BriefRun`:
- Add `brief_type` field ('daily_brief' | 'brief_run')
- Add `brief_run_id` field (nullable, for BriefRun)
- Update `brief_id` to be nullable (or use polymorphic relationship)

**OR** (Better approach):
- Create separate `BriefRunAudioGenerationJob` model
- Reuse same generator logic

### 3. Extend Generator
- Add `_generate_deeper_context()` to `BriefingGenerator`
- Add audio generation support for `BriefRun`

### 4. Add UI to Paid Briefs
- Add "Generate All Audio" section to `briefing/run_view.html`
- Add "Dive deeper" buttons
- Add "Want more detail?" expandable sections

---

## Recommended Approach

**Option A: Polymorphic Job Model** (More complex)
- Single job model for both types
- Requires polymorphic relationships

**Option B: Separate Models** (Simpler, recommended)
- `AudioGenerationJob` for DailyBrief
- `BriefRunAudioGenerationJob` for BriefRun
- Share generator logic via service layer

**Option C: Unified Service** (Best for long-term)
- Abstract base class for both brief types
- Single generator service that works with both
- Cleaner architecture

---

## UI Best Practices Issues Found

1. **Inline Event Handlers**: Using `onclick=""` instead of event listeners
2. **No Error Boundaries**: Errors could break entire page
3. **Alert() for Errors**: Should use toast notifications or inline messages
4. **No Loading States**: Some actions don't show loading
5. **Accessibility**: Missing ARIA labels, keyboard navigation
6. **No Debouncing**: Polling could be optimized
7. **Hardcoded URLs**: ChatGPT/Claude URLs should be configurable

---

## Implementation Priority

1. **High**: Add fields to `BriefRunItem` (migration)
2. **High**: Add UI to paid brief templates
3. **Medium**: Extend audio generation to work with BriefRun
4. **Medium**: Fix UI best practices (event listeners, error handling)
5. **Low**: Accessibility improvements
6. **Low**: Configurable AI links
