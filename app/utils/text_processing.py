"""
Centralized Text Processing Utilities

Provides consistent text processing functions across the application.
"""

import re
from typing import Optional


def strip_markdown_for_tts(text: str) -> str:
    """
    Strip markdown formatting from text before sending to TTS.
    
    Removes markdown syntax that would be read aloud incorrectly:
    - Links: [text](url) -> text
    - Bold: **text** -> text
    - Italic: *text* -> text
    - Headers: # Header -> Header
    - Code blocks: `code` -> code
    - URLs: Removed (not spoken)
    - Extra whitespace: Normalized
    
    Args:
        text: Text potentially containing markdown
        
    Returns:
        Cleaned text safe for TTS
    """
    if not text:
        return ''
    
    # Remove markdown links: [text](url) -> text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    
    # Remove bold: **text** -> text
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    
    # Remove italic: *text* -> text (but be careful not to match **)
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'\1', text)
    
    # Remove headers: # Header -> Header
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    
    # Remove inline code: `code` -> code
    text = re.sub(r'`([^`]+)`', r'\1', text)
    
    # Remove code blocks: ```code``` -> (removed)
    text = re.sub(r'```[\s\S]*?```', '', text)
    
    # Remove URLs (they're not spoken well)
    text = re.sub(r'https?://\S+', '', text)
    
    # Remove markdown list markers: - item, * item, 1. item -> item
    text = re.sub(r'^[\s]*[-*•]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)
    
    # Remove horizontal rules
    text = re.sub(r'^[-*_]{3,}$', '', text, flags=re.MULTILINE)
    
    # Normalize whitespace (multiple spaces/newlines -> single space)
    text = re.sub(r'\s+', ' ', text)
    
    # Remove leading/trailing whitespace
    text = text.strip()
    
    return text


def strip_markdown(text: str) -> str:
    """
    Strip markdown formatting for plain text display.
    
    Simpler version for display purposes (less aggressive than TTS version).
    Preserves more content while removing formatting.
    
    Args:
        text: Text potentially containing markdown
        
    Returns:
        Cleaned text for display
    """
    if not text:
        return ''
    
    # Remove markdown links: [text](url) -> text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    
    # Remove bold: **text** -> text
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    
    # Remove italic: *text* -> text
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    
    # Remove URLs (optional - can be kept for display)
    # text = re.sub(r'https?://\S+', '', text)
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()


def strip_html_tags(text: str) -> str:
    """
    Remove HTML tags and decode HTML entities from text.
    
    Args:
        text: Text potentially containing HTML
        
    Returns:
        Cleaned text without HTML tags
    """
    if not text:
        return ""
    
    import html
    
    # Replace <br> and <p> tags with spaces
    text = re.sub(r'<br\s*/?>', ' ', text)
    text = re.sub(r'<p\s*/?>', ' ', text)
    text = re.sub(r'</p>', ' ', text)
    
    # Remove all HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Decode HTML entities
    text = html.unescape(text)
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()
