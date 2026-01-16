"""
Sending Domain Management

Handles Resend API integration for custom sending domains.
Uses REST API (requests) to match existing email client patterns.
"""

import os
import time
import logging
from typing import Dict, Any, List
import requests

logger = logging.getLogger(__name__)

# Resend API endpoints
RESEND_API_BASE = 'https://api.resend.com'
DOMAINS_API_URL = f'{RESEND_API_BASE}/domains'

# Retry configuration (matches existing email clients)
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


def _get_api_key() -> str:
    """Get Resend API key from environment."""
    api_key = os.environ.get('RESEND_API_KEY')
    if not api_key:
        raise ValueError("RESEND_API_KEY not configured")
    return api_key


def _get_headers() -> Dict[str, str]:
    """Get API request headers."""
    return {
        'Authorization': f'Bearer {_get_api_key()}',
        'Content-Type': 'application/json'
    }


def _request_with_retry(
    method: str,
    url: str,
    json_data: Dict = None,
    timeout: int = 30
) -> Dict[str, Any]:
    """
    Make API request with retry logic.

    Matches the retry pattern used in app/resend_client.py and app/brief/email_client.py.

    Args:
        method: HTTP method ('GET', 'POST', 'DELETE')
        url: Full API URL
        json_data: Optional JSON payload
        timeout: Request timeout in seconds

    Returns:
        Dict with 'success', 'data', 'error' keys
    """
    for attempt in range(MAX_RETRIES):
        try:
            if method == 'GET':
                response = requests.get(url, headers=_get_headers(), timeout=timeout)
            elif method == 'POST':
                response = requests.post(url, json=json_data, headers=_get_headers(), timeout=timeout)
            elif method == 'DELETE':
                response = requests.delete(url, headers=_get_headers(), timeout=timeout)
            else:
                return {'success': False, 'error': f'Unsupported method: {method}'}

            # Success
            if response.status_code in (200, 201):
                try:
                    return {'success': True, 'data': response.json()}
                except ValueError:
                    return {'success': True, 'data': {}}

            # No content (successful delete)
            if response.status_code == 204:
                return {'success': True, 'data': {}}

            # Rate limited - retry
            if response.status_code == 429:
                if attempt < MAX_RETRIES - 1:
                    wait_time = RETRY_DELAY * (attempt + 2)
                    logger.warning(f"Rate limited, waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                else:
                    return {'success': False, 'error': 'Rate limited after retries'}

            # Not found
            if response.status_code == 404:
                return {'success': False, 'error': 'Not found'}

            # Other errors
            try:
                error_data = response.json()
                error_msg = error_data.get('message', error_data.get('error', response.text))
            except ValueError:
                error_msg = response.text

            logger.error(f"Resend API error: {response.status_code} - {error_msg}")
            return {'success': False, 'error': error_msg}

        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES - 1:
                logger.warning(f"Timeout (attempt {attempt + 1}/{MAX_RETRIES}), retrying...")
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                return {'success': False, 'error': 'Request timeout after retries'}

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {e}")
            return {'success': False, 'error': str(e)}

    return {'success': False, 'error': 'Max retries exceeded'}


def register_domain_with_resend(domain_name: str) -> Dict[str, Any]:
    """
    Register a new domain with Resend for email sending.

    Args:
        domain_name: The domain to register (e.g., 'mail.example.com')

    Returns:
        Dict with keys:
            - success: bool
            - domain_id: str (Resend's domain ID)
            - records: list of DNS records to configure
            - error: str (if failed)
    """
    try:
        result = _request_with_retry('POST', DOMAINS_API_URL, {'name': domain_name})

        if not result['success']:
            error = result.get('error', 'Unknown error')
            # Check for common errors
            if 'already exists' in error.lower():
                return {'success': False, 'error': 'Domain already registered with Resend'}
            elif 'invalid' in error.lower():
                return {'success': False, 'error': 'Invalid domain name'}
            return {'success': False, 'error': error}

        data = result.get('data', {})
        domain_id = data.get('id')
        records = data.get('records', [])

        if not domain_id:
            logger.error(f"No domain ID returned from Resend for {domain_name}")
            return {'success': False, 'error': 'No domain ID returned from Resend'}

        logger.info(f"Registered domain {domain_name} with Resend (ID: {domain_id})")

        return {
            'success': True,
            'domain_id': domain_id,
            'records': records,
            'status': data.get('status', 'pending')
        }

    except ValueError as e:
        # API key not configured
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Failed to register domain {domain_name}: {e}")
        return {'success': False, 'error': str(e)}


def check_domain_verification_status(resend_domain_id: str) -> Dict[str, Any]:
    """
    Check the verification status of a domain in Resend.

    Args:
        resend_domain_id: The Resend domain ID

    Returns:
        Dict with keys:
            - success: bool
            - status: str ('pending', 'verified', 'failed')
            - records: list of DNS records with their status
            - error: str (if failed)
    """
    try:
        url = f"{DOMAINS_API_URL}/{resend_domain_id}"
        result = _request_with_retry('GET', url)

        if not result['success']:
            error = result.get('error', 'Unknown error')
            if 'not found' in error.lower():
                return {'success': False, 'error': 'Domain not found in Resend'}
            return {'success': False, 'error': error}

        data = result.get('data', {})
        status = data.get('status', 'unknown')
        records = data.get('records', [])

        # Map Resend status to our status
        status_map = {
            'not_started': 'pending',
            'pending': 'pending',
            'verified': 'verified',
            'failed': 'failed',
            'temporary_failure': 'pending'
        }

        normalized_status = status_map.get(status.lower(), 'pending')

        logger.info(f"Domain {resend_domain_id} status: {normalized_status} (raw: {status})")

        return {
            'success': True,
            'status': normalized_status,
            'raw_status': status,
            'records': records
        }

    except ValueError as e:
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Failed to check domain {resend_domain_id} status: {e}")
        return {'success': False, 'error': str(e)}


def verify_domain_with_resend(resend_domain_id: str) -> Dict[str, Any]:
    """
    Trigger a verification check for a domain in Resend.

    Args:
        resend_domain_id: The Resend domain ID

    Returns:
        Dict with keys:
            - success: bool
            - status: str
            - error: str (if failed)
    """
    try:
        url = f"{DOMAINS_API_URL}/{resend_domain_id}/verify"
        result = _request_with_retry('POST', url)

        if not result['success']:
            return {'success': False, 'error': result.get('error', 'Verification failed')}

        logger.info(f"Triggered verification for domain {resend_domain_id}")

        data = result.get('data', {})
        return {
            'success': True,
            'status': data.get('status', 'pending'),
            'message': 'Verification check triggered'
        }

    except ValueError as e:
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Failed to verify domain {resend_domain_id}: {e}")
        return {'success': False, 'error': str(e)}


def delete_domain_from_resend(resend_domain_id: str) -> Dict[str, Any]:
    """
    Delete a domain from Resend.

    Args:
        resend_domain_id: The Resend domain ID

    Returns:
        Dict with keys:
            - success: bool
            - error: str (if failed)
    """
    try:
        url = f"{DOMAINS_API_URL}/{resend_domain_id}"
        result = _request_with_retry('DELETE', url)

        if not result['success']:
            error = result.get('error', 'Unknown error')
            if 'not found' in error.lower():
                # Domain already deleted, consider success
                return {'success': True, 'message': 'Domain already removed'}
            return {'success': False, 'error': error}

        logger.info(f"Deleted domain {resend_domain_id} from Resend")
        return {'success': True}

    except ValueError as e:
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Failed to delete domain {resend_domain_id}: {e}")
        return {'success': False, 'error': str(e)}


def list_domains_from_resend() -> Dict[str, Any]:
    """
    List all domains registered with Resend.

    Returns:
        Dict with keys:
            - success: bool
            - domains: list of domain objects
            - error: str (if failed)
    """
    try:
        result = _request_with_retry('GET', DOMAINS_API_URL)

        if not result['success']:
            return {'success': False, 'error': result.get('error'), 'domains': []}

        data = result.get('data', {})

        # Handle different response formats
        if isinstance(data, dict):
            domains = data.get('data', [])
        elif isinstance(data, list):
            domains = data
        else:
            domains = []

        logger.info(f"Listed {len(domains)} domains from Resend")

        return {
            'success': True,
            'domains': domains
        }

    except ValueError as e:
        return {'success': False, 'error': str(e), 'domains': []}
    except Exception as e:
        logger.error(f"Failed to list domains from Resend: {e}")
        return {'success': False, 'error': str(e), 'domains': []}


def format_dns_records_for_display(records: List[Dict]) -> List[Dict]:
    """
    Format DNS records for display in the UI.

    Args:
        records: List of DNS record dicts from Resend

    Returns:
        List of formatted record dicts with type, name, value, status
    """
    formatted = []

    for record in records:
        formatted.append({
            'type': record.get('type', record.get('record_type', 'UNKNOWN')),
            'name': record.get('name', record.get('hostname', '')),
            'value': record.get('value', record.get('expected_value', '')),
            'status': record.get('status', 'pending'),
            'priority': record.get('priority')
        })

    return formatted
