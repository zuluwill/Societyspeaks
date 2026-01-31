"""
Webpage Content Scraper

Fetches and extracts main content from web pages.
Uses readability algorithms to extract article content.
"""

import logging
import re
import socket
import ipaddress
import requests
from typing import Optional, Dict
from datetime import datetime
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Patterns to identify cookie-related content in text
COOKIE_CONTENT_PATTERNS = [
    # Cookie table patterns (common on privacy policy pages)
    re.compile(r'\bCookie[:\s]*\w+[\s\n]+Duration[:\s]*\d+\s*(year|month|day|hour|minute|session)', re.IGNORECASE),
    re.compile(r'\bDuration[:\s]*\d+\s*(year|month|day)[\s\n]+Description', re.IGNORECASE),
    re.compile(r'No description available\.?[\s\n]+Cookie', re.IGNORECASE),
    # Cookie consent text
    re.compile(r'This (website|site) uses cookies', re.IGNORECASE),
    re.compile(r'We use cookies to', re.IGNORECASE),
    re.compile(r'By (continuing|clicking|using)', re.IGNORECASE),
    re.compile(r'Accept (all )?cookies', re.IGNORECASE),
    re.compile(r'Cookie (settings|preferences|policy)', re.IGNORECASE),
    re.compile(r'Manage (cookie|your) preferences', re.IGNORECASE),
]

# CSS classes and IDs commonly used for cookie banners
COOKIE_ELEMENT_SELECTORS = [
    'cookie', 'consent', 'gdpr', 'privacy-banner', 'cookie-banner',
    'cookie-notice', 'cookie-consent', 'cookie-policy', 'cookie-popup',
    'cc-banner', 'cc-window', 'ccm-', 'cookieconsent', 'cookie-law',
    'eu-cookie', 'onetrust', 'trustarc', 'cookiebot', 'termly',
    'osano', 'complianz', 'iubenda', 'quantcast', 'usercentrics'
]


def remove_cookie_elements(soup):
    """
    Remove cookie consent banners and related elements from BeautifulSoup.
    
    Args:
        soup: BeautifulSoup object
    """
    # Remove elements by common cookie-related class/id patterns
    for selector in COOKIE_ELEMENT_SELECTORS:
        # Find by class containing the selector
        for elem in soup.find_all(class_=lambda x: x and selector in str(x).lower()):
            elem.decompose()
        # Find by id containing the selector
        for elem in soup.find_all(id=lambda x: x and selector in str(x).lower()):
            elem.decompose()
        # Find by data attributes
        for elem in soup.find_all(attrs={'data-cookie': True}):
            elem.decompose()
        for elem in soup.find_all(attrs={'data-consent': True}):
            elem.decompose()
    
    # Remove common cookie banner elements by role
    for elem in soup.find_all(attrs={'role': 'dialog'}):
        text = elem.get_text().lower()
        if 'cookie' in text or 'consent' in text or 'privacy' in text:
            elem.decompose()
    
    # Remove elements with aria-label mentioning cookies
    for elem in soup.find_all(attrs={'aria-label': lambda x: x and 'cookie' in str(x).lower()}):
        elem.decompose()


def clean_cookie_content_from_text(text: str) -> str:
    """
    Remove cookie policy content from extracted text.
    
    Args:
        text: Extracted article text
        
    Returns:
        Cleaned text with cookie content removed
    """
    if not text:
        return text
    
    lines = text.split('\n')
    cleaned_lines = []
    skip_next = 0
    in_cookie_section = False
    cookie_section_lines = 0
    
    for i, line in enumerate(lines):
        if skip_next > 0:
            skip_next -= 1
            continue
        
        line_lower = line.lower().strip()
        
        # Detect start of cookie table/section
        if line_lower in ('cookie', 'cookies', 'cookie name', 'name'):
            # Check if next few lines look like cookie table content
            next_lines = [l.lower().strip() for l in lines[i+1:i+5] if l.strip()]
            if any('duration' in nl or 'expiry' in nl or 'purpose' in nl or 
                   re.match(r'^\d+\s*(year|month|day)', nl) for nl in next_lines):
                in_cookie_section = True
                cookie_section_lines = 0
                continue
        
        # Track cookie section - exit when we hit clearly non-cookie content
        if in_cookie_section:
            cookie_section_lines += 1
            # Check if this line is cookie-table content
            is_table_content = any([
                line_lower in ('cookie', 'duration', 'description', 'purpose', 'expiry', 'type', 'no description available.', 'no description available'),
                re.match(r'^\d+\s*(year|month|day|hour|minute|session)s?\.?$', line_lower),
                re.match(r'^[a-z_]{1,30}$', line_lower),  # Cookie names like "pc", "_ga"
                line_lower.startswith('cookie:'),
                line_lower.startswith('duration:'),
                not line.strip(),  # Empty lines
            ])
            
            # Exit cookie section if: hit normal content OR been in section too long
            if not is_table_content or cookie_section_lines > 15:
                in_cookie_section = False
                # Only continue (skip) if this was still table content
                if is_table_content:
                    continue
            else:
                continue
            
        # Skip lines that match cookie patterns
        is_cookie_content = False
        for pattern in COOKIE_CONTENT_PATTERNS:
            if pattern.search(line):
                is_cookie_content = True
                skip_next = 3
                break
        
        if is_cookie_content:
            continue
        
        # Skip lines that look like cookie table entries
        if any([
            line_lower.startswith('cookie:'),
            line_lower.startswith('duration:'),
            line_lower.startswith('description:'),
            line_lower.startswith('purpose:'),
            line_lower.startswith('expiry:'),
            line_lower == 'no description available.',
            line_lower == 'no description available',
            line_lower in ('cookie', 'duration', 'description', 'purpose', 'expiry', 'type'),
            re.match(r'^\d+\s*(year|month|day|hour|minute|session)s?$', line_lower),
            re.match(r'^(necessary|functional|analytics|performance|marketing|advertising|targeting)\s*cookies?$', line_lower),
            # Common cookie names
            re.match(r'^[a-z_]{1,30}$', line_lower) and i + 1 < len(lines) and 
                re.match(r'^\d+\s*(year|month|day|session)', lines[i+1].lower().strip()),
        ]):
            is_cookie_content = True
            skip_next = 2
        
        if not is_cookie_content:
            cleaned_lines.append(line)
    
    # Clean up multiple consecutive empty lines
    result = '\n'.join(cleaned_lines)
    result = re.sub(r'\n{3,}', '\n\n', result)
    
    return result.strip()


# Blocked IP ranges for SSRF protection
BLOCKED_IP_RANGES = [
    ipaddress.ip_network('127.0.0.0/8'),      # Loopback
    ipaddress.ip_network('10.0.0.0/8'),       # Private Class A
    ipaddress.ip_network('172.16.0.0/12'),    # Private Class B
    ipaddress.ip_network('192.168.0.0/16'),   # Private Class C
    ipaddress.ip_network('169.254.0.0/16'),   # Link-local (AWS metadata)
    ipaddress.ip_network('0.0.0.0/8'),        # Current network
    ipaddress.ip_network('100.64.0.0/10'),    # Shared address space
    ipaddress.ip_network('192.0.0.0/24'),     # IETF protocol assignments
    ipaddress.ip_network('192.0.2.0/24'),     # TEST-NET-1
    ipaddress.ip_network('198.51.100.0/24'),  # TEST-NET-2
    ipaddress.ip_network('203.0.113.0/24'),   # TEST-NET-3
    ipaddress.ip_network('224.0.0.0/4'),      # Multicast
    ipaddress.ip_network('240.0.0.0/4'),      # Reserved
    ipaddress.ip_network('255.255.255.255/32'),  # Broadcast
]

BLOCKED_IPV6_RANGES = [
    ipaddress.ip_network('::1/128'),          # Loopback
    ipaddress.ip_network('fc00::/7'),         # Unique local
    ipaddress.ip_network('fe80::/10'),        # Link-local
    ipaddress.ip_network('ff00::/8'),         # Multicast
]


def is_safe_url(url: str) -> bool:
    """
    Check if a URL is safe to fetch (SSRF protection).

    Args:
        url: URL to validate

    Returns:
        True if URL is safe to fetch, False otherwise
    """
    try:
        parsed = urlparse(url)

        # Only allow http/https
        if parsed.scheme not in ('http', 'https'):
            logger.warning(f"Blocked URL with scheme: {parsed.scheme}")
            return False

        hostname = parsed.hostname
        if not hostname:
            return False

        # Block localhost variations
        if hostname.lower() in ('localhost', 'localhost.localdomain', '127.0.0.1', '::1', '0.0.0.0'):
            logger.warning(f"Blocked localhost URL: {url}")
            return False

        # Block internal hostnames
        if hostname.lower().endswith(('.local', '.internal', '.localhost', '.lan')):
            logger.warning(f"Blocked internal hostname: {hostname}")
            return False

        # Resolve hostname and check IP
        try:
            # Get all IPs for the hostname
            addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)

            for family, _, _, _, sockaddr in addr_info:
                ip_str = sockaddr[0]

                try:
                    ip = ipaddress.ip_address(ip_str)

                    # Check IPv4 ranges
                    if isinstance(ip, ipaddress.IPv4Address):
                        for blocked_range in BLOCKED_IP_RANGES:
                            if ip in blocked_range:
                                logger.warning(f"Blocked IP {ip} for URL {url} (in range {blocked_range})")
                                return False

                    # Check IPv6 ranges
                    elif isinstance(ip, ipaddress.IPv6Address):
                        for blocked_range in BLOCKED_IPV6_RANGES:
                            if ip in blocked_range:
                                logger.warning(f"Blocked IPv6 {ip} for URL {url} (in range {blocked_range})")
                                return False

                except ValueError:
                    continue

        except socket.gaierror:
            # DNS resolution failed - could be a way to bypass, block it
            logger.warning(f"DNS resolution failed for {hostname}")
            return False

        return True

    except Exception as e:
        logger.error(f"Error validating URL {url}: {e}")
        return False


def scrape_webpage(url: str, timeout: int = 10) -> Optional[Dict]:
    """
    Scrape main content from a webpage.
    
    Args:
        url: URL to scrape
        timeout: Request timeout in seconds
    
    Returns:
        Dict with keys: 'title', 'content', 'published_at', or None if fails
    """
    try:
        # SSRF protection - validate URL before fetching
        if not is_safe_url(url):
            logger.warning(f"Blocked unsafe URL: {url}")
            return None

        # Fetch HTML
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        
        html_content = response.text
        
        # Pre-process HTML to remove cookie elements before extraction
        try:
            from bs4 import BeautifulSoup
            pre_soup = BeautifulSoup(html_content, 'html.parser')
            remove_cookie_elements(pre_soup)
            html_content = str(pre_soup)
        except Exception as e:
            logger.debug(f"Pre-processing failed for {url}: {e}")
        
        # Try readability-lxml first (better extraction)
        try:
            from readability import Document
            
            doc = Document(html_content)
            title = doc.title()
            content = doc.summary()
            
            # Clean HTML tags from content
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content, 'html.parser')
            
            # Remove any remaining cookie elements
            remove_cookie_elements(soup)
            
            clean_content = soup.get_text(separator='\n', strip=True)
            
            # Clean cookie content from extracted text
            clean_content = clean_cookie_content_from_text(clean_content)
            
            # Try to extract published date from meta tags
            published_at = None
            try:
                meta_soup = BeautifulSoup(html_content, 'html.parser')
                # Try common meta tags
                for meta_tag in meta_soup.find_all('meta'):
                    prop = meta_tag.get('property') or meta_tag.get('name', '').lower()
                    if 'date' in prop or 'published' in prop or 'time' in prop:
                        content_attr = meta_tag.get('content')
                        if content_attr:
                            try:
                                # Try parsing common date formats
                                published_at = datetime.fromisoformat(content_attr.replace('Z', '+00:00'))
                            except:
                                pass
            except:
                pass
            
            if not clean_content or len(clean_content.strip()) < 100:
                logger.warning(f"Webpage scraping returned minimal content for {url}")
                return None
            
            return {
                'title': title or urlparse(url).netloc,
                'content': clean_content.strip(),
                'published_at': published_at,
                'url': url
            }
            
        except ImportError:
            # Fallback to BeautifulSoup only (basic extraction)
            try:
                from bs4 import BeautifulSoup
                
                soup = BeautifulSoup(html_content, 'html.parser')
                
                # Remove script and style elements
                for script in soup(["script", "style", "nav", "header", "footer", "aside"]):
                    script.decompose()
                
                # Remove cookie consent elements
                remove_cookie_elements(soup)
                
                # Try to find main content
                main_content = soup.find('main') or soup.find('article') or soup.find('body')
                
                if main_content:
                    content = main_content.get_text(separator='\n', strip=True)
                else:
                    content = soup.get_text(separator='\n', strip=True)
                
                # Clean cookie content from text
                content = clean_cookie_content_from_text(content)
                
                # Get title
                title_tag = soup.find('title')
                title = title_tag.get_text() if title_tag else urlparse(url).netloc
                
                # Try to extract published date
                published_at = None
                for meta_tag in soup.find_all('meta'):
                    prop = meta_tag.get('property') or meta_tag.get('name', '').lower()
                    if 'date' in prop or 'published' in prop:
                        content_attr = meta_tag.get('content')
                        if content_attr:
                            try:
                                published_at = datetime.fromisoformat(content_attr.replace('Z', '+00:00'))
                            except:
                                pass
                
                if not content or len(content.strip()) < 100:
                    logger.warning(f"Webpage scraping returned minimal content for {url}")
                    return None
                
                return {
                    'title': title.strip(),
                    'content': content.strip(),
                    'published_at': published_at,
                    'url': url
                }
                
            except ImportError:
                logger.error("BeautifulSoup4 is not installed. Install it: pip install beautifulsoup4")
                return None
                
    except requests.RequestException as e:
        logger.error(f"Error fetching webpage {url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error scraping webpage {url}: {e}", exc_info=True)
        return None
