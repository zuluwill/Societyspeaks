"""
Tests for URL Normalization Utility

Tests various URL normalization scenarios to ensure consistent
article URL matching for partner embed lookups.
"""
import pytest
import sys
import os

# Import directly from lib to avoid app initialization and DATABASE_URL requirement
# The url_normalizer module is self-contained and doesn't need Flask
lib_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app', 'lib')
sys.path.insert(0, lib_path)
from url_normalizer import normalize_url, url_hash, is_amp_url, extract_domain


class TestNormalizeUrl:
    """Tests for the normalize_url function."""

    def test_basic_normalization(self):
        """Test basic URL normalization."""
        assert normalize_url('https://example.com/article') == 'https://example.com/article'

    def test_force_https(self):
        """Test that HTTP is converted to HTTPS."""
        assert normalize_url('http://example.com/article') == 'https://example.com/article'

    def test_lowercase_hostname(self):
        """Test hostname is lowercased."""
        assert normalize_url('https://EXAMPLE.COM/Article') == 'https://example.com/Article'

    def test_strip_www(self):
        """Test www. prefix is stripped."""
        assert normalize_url('https://www.example.com/article') == 'https://example.com/article'
        assert normalize_url('https://WWW.EXAMPLE.COM/article') == 'https://example.com/article'

    def test_strip_trailing_slash(self):
        """Test trailing slash is stripped."""
        assert normalize_url('https://example.com/article/') == 'https://example.com/article'
        assert normalize_url('https://example.com/') == 'https://example.com/'  # Root keeps slash

    def test_strip_fragment(self):
        """Test URL fragment is stripped."""
        assert normalize_url('https://example.com/article#comments') == 'https://example.com/article'
        assert normalize_url('https://example.com/article#section-1') == 'https://example.com/article'

    def test_strip_utm_params(self):
        """Test UTM tracking parameters are stripped."""
        url = 'https://example.com/article?utm_source=twitter&utm_medium=social&utm_campaign=test'
        assert normalize_url(url) == 'https://example.com/article'

    def test_strip_facebook_params(self):
        """Test Facebook tracking parameters are stripped."""
        url = 'https://example.com/article?fbclid=IwAR3abc123'
        assert normalize_url(url) == 'https://example.com/article'

    def test_strip_google_params(self):
        """Test Google tracking parameters are stripped."""
        url = 'https://example.com/article?gclid=abc123&gclsrc=aw.ds'
        assert normalize_url(url) == 'https://example.com/article'

    def test_strip_multiple_tracking_params(self):
        """Test multiple tracking parameters are stripped together."""
        url = 'https://example.com/article?utm_source=twitter&fbclid=abc&gclid=def&ref=homepage'
        assert normalize_url(url) == 'https://example.com/article'

    def test_keep_content_params(self):
        """Test content-defining parameters are kept."""
        url = 'https://example.com/search?q=test&page=2'
        normalized = normalize_url(url)
        assert 'q=test' in normalized
        assert 'page=2' in normalized

    def test_mixed_params(self):
        """Test mix of tracking and content params."""
        url = 'https://example.com/article?id=123&utm_source=twitter'
        normalized = normalize_url(url)
        assert 'id=123' in normalized
        assert 'utm_source' not in normalized

    def test_amp_url_normalization(self):
        """Test AMP URLs are converted to canonical."""
        assert normalize_url('https://example.com/article/amp/') == 'https://example.com/article'
        assert normalize_url('https://example.com/article/amp') == 'https://example.com/article'
        assert normalize_url('https://example.com/amp/article') == 'https://example.com/article'

    def test_same_article_different_urls(self):
        """Test that different variations of the same article URL normalize to the same result."""
        variations = [
            'http://www.example.com/article',
            'https://www.example.com/article',
            'https://example.com/article/',
            'https://EXAMPLE.COM/article',
            'https://www.example.com/article?utm_source=twitter',
            'https://example.com/article?fbclid=abc123',
            'https://www.example.com/article#comments',
            'https://www.example.com/article/?utm_source=fb&utm_medium=social#top',
        ]

        normalized = [normalize_url(url) for url in variations]
        assert all(n == 'https://example.com/article' for n in normalized)

    def test_invalid_urls(self):
        """Test invalid URLs return None."""
        assert normalize_url(None) is None
        assert normalize_url('') is None
        assert normalize_url('   ') is None
        assert normalize_url('not a url') is None
        assert normalize_url('ftp://example.com/file') is None
        assert normalize_url('javascript:alert(1)') is None

    def test_port_handling(self):
        """Test port numbers are handled correctly."""
        # Non-standard ports are kept
        assert normalize_url('https://example.com:8080/article') == 'https://example.com:8080/article'
        # Standard ports are removed
        assert normalize_url('https://example.com:443/article') == 'https://example.com/article'
        assert normalize_url('http://example.com:80/article') == 'https://example.com/article'


class TestDomainRules:
    """Tests for domain-specific normalization rules."""

    def test_guardian_locale_stripping(self):
        """Test Guardian locale prefixes are stripped."""
        assert normalize_url('https://www.theguardian.com/uk/news/article') == \
               'https://theguardian.com/news/article'
        assert normalize_url('https://www.theguardian.com/us/news/article') == \
               'https://theguardian.com/news/article'
        assert normalize_url('https://theguardian.com/au/news/article') == \
               'https://theguardian.com/news/article'

    def test_guardian_params(self):
        """Test Guardian-specific tracking params are stripped."""
        url = 'https://www.theguardian.com/news/article?CMP=share_btn_tw&INTCMP=srch'
        assert normalize_url(url) == 'https://theguardian.com/news/article'

    def test_nytimes_params(self):
        """Test NYTimes-specific tracking params are stripped."""
        url = 'https://www.nytimes.com/article?smid=tw-share&smtyp=cur'
        assert normalize_url(url) == 'https://nytimes.com/article'

    def test_bbc_params(self):
        """Test BBC-specific tracking params are stripped."""
        url = 'https://www.bbc.com/news/article?at_medium=social&at_campaign=test'
        assert normalize_url(url) == 'https://bbc.com/news/article'

    def test_disable_domain_rules(self):
        """Test domain rules can be disabled."""
        url = 'https://www.theguardian.com/uk/news/article?CMP=test'
        # With rules
        assert normalize_url(url, apply_domain_rules=True) == 'https://theguardian.com/news/article'
        # Without rules - /uk/ prefix stays, CMP param stays (it's Guardian-specific, not general tracking)
        result = normalize_url(url, apply_domain_rules=False)
        assert '/uk/' in result
        assert 'CMP=test' in result  # Guardian-specific param kept when domain rules disabled


class TestUrlHash:
    """Tests for the url_hash function."""

    def test_basic_hash(self):
        """Test hash generation."""
        h = url_hash('https://example.com/article')
        assert h is not None
        assert len(h) == 32  # Default length
        assert all(c in '0123456789abcdef' for c in h)  # Valid hex

    def test_hash_consistency(self):
        """Test same URL produces same hash."""
        url = 'https://example.com/article'
        assert url_hash(url) == url_hash(url)

    def test_hash_after_normalization(self):
        """Test different URL variants produce same hash."""
        hash1 = url_hash('http://www.example.com/article?utm_source=twitter')
        hash2 = url_hash('https://example.com/article')
        assert hash1 == hash2

    def test_hash_length(self):
        """Test custom hash length."""
        h = url_hash('https://example.com/article', length=16)
        assert len(h) == 16

    def test_invalid_url_hash(self):
        """Test invalid URLs return None."""
        assert url_hash(None) is None
        assert url_hash('not a url') is None


class TestIsAmpUrl:
    """Tests for the is_amp_url function."""

    def test_amp_path(self):
        """Test AMP detection via path."""
        assert is_amp_url('https://example.com/article/amp') is True
        assert is_amp_url('https://example.com/article/amp/') is True
        assert is_amp_url('https://example.com/amp/article') is True

    def test_amp_query_param(self):
        """Test AMP detection via query param."""
        assert is_amp_url('https://example.com/article?amp=1') is True
        assert is_amp_url('https://example.com/article?amp') is True

    def test_amp_hostname(self):
        """Test AMP detection via hostname (Google AMP cache)."""
        assert is_amp_url('https://example-com.cdn.ampproject.org/article') is True
        assert is_amp_url('https://example.amp.cloudflare.com/article') is True

    def test_non_amp_url(self):
        """Test non-AMP URLs return False."""
        assert is_amp_url('https://example.com/article') is False
        assert is_amp_url('https://example.com/vampire') is False  # Contains 'amp' but not AMP

    def test_invalid_urls(self):
        """Test invalid URLs return False."""
        assert is_amp_url(None) is False
        assert is_amp_url('') is False


class TestExtractDomain:
    """Tests for the extract_domain function."""

    def test_basic_extraction(self):
        """Test basic domain extraction."""
        assert extract_domain('https://example.com/article') == 'example.com'

    def test_strip_www(self):
        """Test www. is stripped."""
        assert extract_domain('https://www.example.com/article') == 'example.com'

    def test_subdomain(self):
        """Test subdomains are kept (except www)."""
        assert extract_domain('https://blog.example.com/article') == 'blog.example.com'
        assert extract_domain('https://www.blog.example.com/article') == 'blog.example.com'

    def test_port_removed(self):
        """Test port is removed."""
        assert extract_domain('https://example.com:8080/article') == 'example.com'

    def test_invalid_urls(self):
        """Test invalid URLs return None."""
        assert extract_domain(None) is None
        assert extract_domain('') is None
        assert extract_domain('not a url') is None
