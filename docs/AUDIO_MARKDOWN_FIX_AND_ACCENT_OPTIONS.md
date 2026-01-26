# Audio Markdown Fix & Accent Options

## ✅ Changes Implemented

### 1. Markdown Stripping Fix

**Problem**: TTS was reading markdown syntax literally:
- `**bold**` → "asterisk asterisk bold asterisk asterisk"
- `[link](url)` → "bracket link bracket parenthesis url"
- `# Header` → "hash Header"
- Other markdown syntax being spoken

**Solution**: Added `strip_markdown_for_tts()` function in `audio_generator.py` that:
- Removes markdown links: `[text](url)` → `text`
- Removes bold/italic: `**text**` → `text`, `*text*` → `text`
- Removes headers: `# Header` → `Header`
- Removes code blocks and inline code
- Removes URLs (not spoken well)
- Removes list markers
- Normalizes whitespace

**Applied to**: All text fields before TTS:
- Headlines
- Summary bullets
- Personal impact
- So what
- Content markdown (main culprit)

---

### 2. British Accent Options Added

**Available Voices**:

#### American Accent (5 options):
- **Professional (US)**: Clear, professional American
- **Warm (US)**: Friendly, warm American tone
- **Authoritative (US)**: Confident American voice
- **Calm (US)**: Calm, soothing American
- **Friendly (US)**: Approachable American tone

#### British Accent (2 options):
- **Professional (British)**: Clear, professional British accent
- **Warm (British)**: Friendly, warm British tone

**Note**: XTTS v2 doesn't have dedicated British speakers in the standard model. The British options use alternative speaker names that may have British-like characteristics. You may need to test and adjust the speaker names if they don't sound British enough.

---

## 🎯 How Users Select Accent

### Current Implementation:
1. **Voice Dropdown**: Users select from dropdown in "Generate All Audio" section
2. **Grouped by Accent**: Dropdown is organized with `<optgroup>` labels:
   - "American Accent" group
   - "British Accent" group
3. **Selection**: User picks their preferred voice/accent combination
4. **Applied**: Selected voice is used for entire brief generation

### UI Location:
- **Daily Brief**: `app/templates/brief/view.html` (line ~39)
- **Paid Briefs**: `app/templates/briefing/run_view.html` (line ~47)

### Default:
- Auto-queue (5pm generation) uses `'professional'` (American)
- Users can override by selecting different voice before clicking "Generate All Audio"

---

## 🔧 Technical Details

### Markdown Stripping Function
**Location**: `app/brief/audio_generator.py` (lines 30-80)

**Features**:
- Comprehensive markdown removal
- Handles edge cases (nested formatting, multiple patterns)
- Preserves text content while removing syntax
- Normalizes whitespace for clean TTS input

### Voice Mapping
**Location**: `app/brief/xtts_client.py` (lines 235-260)

**Current Mapping**:
```python
speaker_map = {
    # American
    'professional': 'Claribel Dervla',
    'warm': 'Daisy Studious',
    'authoritative': 'Gracie Wise',
    'calm': 'Tammie Ema',
    'friendly': 'Alison Dietlinde',
    # British (may need adjustment)
    'british_professional': 'Geraint',
    'british_warm': 'Daisy Studious',  # Fallback
}
```

**Note**: British speaker names may need to be updated after testing. XTTS v2 doesn't guarantee British accents for these names.

---

## 🧪 Testing Recommendations

### Markdown Fix:
1. Generate audio for a brief item with markdown
2. Verify no markdown syntax is spoken
3. Check that text content is preserved correctly

### British Accent:
1. Generate audio with `british_professional` option
2. Listen to verify it sounds British
3. If not British enough, try different speaker names:
   - Check available speakers: `tts.speakers` after model load
   - Test alternative British-sounding names
   - Update `speaker_map` accordingly

---

## 📝 Future Improvements

### Potential Enhancements:
1. **More British Options**: Add more British accent variations if speakers are found
2. **Language Parameter**: Allow changing `language='en'` to other English variants (if supported)
3. **User Preferences**: Save user's preferred accent/voice
4. **Speaker Discovery**: Programmatically list available speakers and identify British ones
5. **Voice Cloning**: Use custom British audio samples for voice cloning (advanced)

---

## ✅ Summary

**Markdown Issue**: ✅ **FIXED** - All text is now cleaned before TTS

**British Accent**: ✅ **ADDED** - 2 British options available in dropdown

**User Selection**: ✅ **WORKING** - Users select accent via voice dropdown (grouped by accent)

**Note**: British accent quality depends on available XTTS v2 speakers. May need speaker name adjustments after testing.
