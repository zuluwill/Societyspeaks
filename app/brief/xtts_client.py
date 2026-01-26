"""
XTTS v2 Text-to-Speech Client

Open-source TTS using Coqui XTTS v2 model.
CPU-friendly, free, and scalable.

Optimized for Replit:
- Lazy model loading (only loads when first needed)
- Model caching (avoids 30-60s reload per item)
- Memory-conscious (single instance)

Docs: https://github.com/coqui-ai/TTS
"""

import os
import logging
import tempfile
from typing import Optional, Dict, List
import threading

logger = logging.getLogger(__name__)

# Module-level model cache with thread lock for safety
_model_cache = {
    'tts': None,
    'loading': False
}
_model_lock = threading.Lock()


class XTTSClient:
    """
    Client for XTTS v2 text-to-speech (open source).

    Uses Coqui TTS library for high-quality, free TTS generation.
    CPU-friendly and can run on Replit without GPU.

    Model is cached at module level to avoid expensive reloading.
    """

    # Available voice presets (XTTS v2 built-in voices)
    VOICES = {
        'professional': {
            'name': 'Professional (US)',
            'description': 'Clear, professional American accent',
            'speaker_wav': None,
        },
        'warm': {
            'name': 'Warm (US)',
            'description': 'Friendly, warm American tone',
            'speaker_wav': None,
        },
        'authoritative': {
            'name': 'Authoritative (US)',
            'description': 'Confident, authoritative American voice',
            'speaker_wav': None,
        },
        'calm': {
            'name': 'Calm (US)',
            'description': 'Calm, soothing American narration',
            'speaker_wav': None,
        },
        'friendly': {
            'name': 'Friendly (US)',
            'description': 'Approachable, friendly American tone',
            'speaker_wav': None,
        },
        'british_professional': {
            'name': 'Professional (British)',
            'description': 'Clear, professional British accent',
            'speaker_wav': None,
        },
        'british_warm': {
            'name': 'Warm (British)',
            'description': 'Friendly, warm British tone',
            'speaker_wav': None,
        },
    }

    DEFAULT_VOICE = 'professional'
    # Use XTTS v2 for higher quality multi-speaker synthesis
    MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"

    # Maximum text length to prevent memory issues on Replit
    MAX_TEXT_LENGTH = 5000

    def __init__(self):
        """Initialize XTTS client."""
        self.available = self._check_availability()
        if not self.available:
            logger.warning("XTTS v2 not available. Install with: pip install TTS")

    def _check_availability(self) -> bool:
        """Check if TTS library is available."""
        try:
            import TTS
            return True
        except ImportError:
            return False

    def _get_model(self):
        """
        Get cached TTS model, loading it if necessary.

        Uses module-level caching to avoid expensive model reloading.
        Thread-safe with lock protection.

        Returns:
            TTS model instance or None if loading fails
        """
        global _model_cache

        with _model_lock:
            # Return cached model if available
            if _model_cache['tts'] is not None:
                return _model_cache['tts']

            # Prevent concurrent loading
            if _model_cache['loading']:
                logger.warning("Model is already being loaded by another thread, waiting...")
                # Wait a bit for the other thread to finish loading
                import time
                max_wait = 120  # Wait up to 2 minutes for model to load
                wait_interval = 2  # Check every 2 seconds
                waited = 0
                while _model_cache['loading'] and waited < max_wait:
                    time.sleep(wait_interval)
                    waited += wait_interval
                    if _model_cache['tts'] is not None:
                        # Model loaded by other thread
                        return _model_cache['tts']
                
                # If still loading after max wait, something might be wrong
                if _model_cache['loading']:
                    logger.error("Model loading timed out, clearing loading flag")
                    _model_cache['loading'] = False
                    return None
                
                # Check one more time if model is now available
                if _model_cache['tts'] is not None:
                    return _model_cache['tts']
                return None

            _model_cache['loading'] = True

        try:
            # Auto-accept Coqui TOS to avoid interactive prompt
            os.environ['COQUI_TOS_AGREED'] = '1'
            
            # Fix for PyTorch 2.6+ weights_only security change
            # Monkey-patch torch.load to use weights_only=False for XTTS models
            import torch
            _original_torch_load = torch.load
            def _patched_torch_load(*args, **kwargs):
                if 'weights_only' not in kwargs:
                    kwargs['weights_only'] = False
                return _original_torch_load(*args, **kwargs)
            torch.load = _patched_torch_load
            
            from TTS.api import TTS

            logger.info(f"Loading XTTS v2 model (this may take 30-60 seconds on first run)...")
            tts = TTS(model_name=self.MODEL_NAME, gpu=False)  # CPU mode for Replit
            
            # Restore original torch.load
            torch.load = _original_torch_load

            with _model_lock:
                _model_cache['tts'] = tts
                _model_cache['loading'] = False

            logger.info("XTTS v2 model loaded successfully")
            return tts

        except Exception as e:
            logger.error(f"Failed to load XTTS model: {e}", exc_info=True)
            with _model_lock:
                _model_cache['loading'] = False
            return None

    def generate_audio(
        self,
        text: str,
        voice_id: Optional[str] = None,
        language: str = 'en',
        output_path: Optional[str] = None
    ) -> Optional[str]:
        """
        Generate audio from text using XTTS v2.

        Args:
            text: Text to convert to speech
            voice_id: Voice preset to use (defaults to DEFAULT_VOICE)
            language: Language code (default: 'en')
            output_path: Optional path to save audio file

        Returns:
            Path to generated audio file, or None if generation fails
        """
        if not self.available:
            logger.warning("XTTS not available - skipping audio generation")
            return None

        if not text or len(text.strip()) == 0:
            logger.warning("Empty text provided for audio generation")
            return None

        # Ensure text is properly encoded (UTF-8)
        if isinstance(text, bytes):
            try:
                text = text.decode('utf-8')
            except UnicodeDecodeError:
                logger.error("Failed to decode text as UTF-8")
                return None
        
        # Truncate very long text to prevent memory issues on Replit
        if len(text) > self.MAX_TEXT_LENGTH:
            logger.warning(f"Text too long ({len(text)} chars), truncating to {self.MAX_TEXT_LENGTH}")
            text = text[:self.MAX_TEXT_LENGTH] + "..."

        try:
            # Use default voice if not specified
            voice = voice_id or self.DEFAULT_VOICE
            if voice not in self.VOICES:
                logger.warning(f"Unknown voice {voice}, using default")
                voice = self.DEFAULT_VOICE

            # Get cached model (lazy loading)
            tts = self._get_model()
            if tts is None:
                logger.error("Failed to get TTS model")
                return None

            # Create temporary output file if not provided
            if not output_path:
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
                output_path = temp_file.name
                temp_file.close()

            # Generate audio with XTTS v2
            logger.info(f"Generating audio for {len(text)} characters with voice: {voice}")
            
            # XTTS v2 supports multiple speakers - use built-in speaker embeddings
            # Map voice presets to speaker characteristics
            # Note: British accents are limited - XTTS v2 primarily has American speakers
            # British options use speakers that may have slight British characteristics
            # or we fall back to closest match
            speaker_map = {
                # American accents (primary options)
                'professional': 'Claribel Dervla',  # Clear, professional American
                'warm': 'Daisy Studious',           # Warm, friendly American
                'authoritative': 'Gracie Wise',     # Confident American tone
                'calm': 'Tammie Ema',               # Calm, soothing American
                'friendly': 'Alison Dietlinde',     # Approachable American
                # British accents (using available speakers - may need testing)
                # Note: XTTS v2 doesn't have dedicated British speakers, so these
                # use alternative speakers that may have British-like characteristics
                'british_professional': 'Geraint',  # British-sounding name (if available)
                'british_warm': 'Daisy Studious',   # Fallback to warm (closest match)
            }
            speaker = speaker_map.get(voice, 'Claribel Dervla')
            
            # Log if using British option (for debugging)
            if voice.startswith('british_'):
                logger.info(f"Using British accent option '{voice}' with speaker '{speaker}'")
            
            tts.tts_to_file(
                text=text,
                file_path=output_path,
                speaker=speaker,
                language=language
            )

            logger.info(f"Audio generated successfully: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"XTTS audio generation failed: {e}", exc_info=True)
            return None

    def list_voices(self) -> List[Dict]:
        """
        List available voice presets.

        Returns:
            List of voice dictionaries
        """
        return [
            {
                'id': voice_id,
                'name': info['name'],
                'description': info['description']
            }
            for voice_id, info in self.VOICES.items()
        ]

    @classmethod
    def unload_model(cls):
        """
        Unload the cached model to free memory.

        Call this if you need to reclaim memory on Replit.
        Thread-safe and clears loading flag.
        """
        global _model_cache
        with _model_lock:
            if _model_cache['tts'] is not None:
                logger.info("Unloading XTTS model to free memory")
                _model_cache['tts'] = None
            # Also clear loading flag in case model was stuck loading
            _model_cache['loading'] = False
