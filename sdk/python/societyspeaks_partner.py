"""Lightweight Society Speaks Partner API client.

Intended as a reference wrapper for partners integrating from backend services.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

import requests

SDK_VERSION = "0.2.0"


class PartnerApiError(Exception):
    def __init__(self, status_code: int, error: str, message: str, retry_after: Optional[int] = None):
        super().__init__(f"{status_code} {error}: {message}")
        self.status_code = status_code
        self.error = error
        self.message = message
        self.retry_after = retry_after


class SocietyspeaksPartnerClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 15, max_retries: int = 2):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries

    @property
    def sdk_version(self) -> str:
        return SDK_VERSION

    @staticmethod
    def _retry_after_seconds(response: requests.Response) -> Optional[int]:
        raw = response.headers.get("Retry-After")
        if not raw:
            return None
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return None

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ):
        url = f"{self.base_url}{path}"
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)
        attempt = 0
        resp: Optional[requests.Response] = None
        while True:
            attempt += 1
            try:
                resp = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_body,
                    params=params,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                if attempt > self.max_retries:
                    raise PartnerApiError(0, "network_error", str(exc)) from exc
                time.sleep(0.5 * attempt)
                continue
            if resp.status_code < 500 or attempt > self.max_retries:
                break
            time.sleep(0.5 * attempt)

        if resp is None:
            raise PartnerApiError(0, "network_error", "Request failed before receiving a response.")

        if 200 <= resp.status_code < 300:
            if resp.headers.get("Content-Type", "").startswith("application/json"):
                return resp.json()
            return resp.text

        body = {}
        try:
            body = resp.json() or {}
        except Exception:
            body = {}
        raise PartnerApiError(
            status_code=resp.status_code,
            error=body.get("error", "request_failed"),
            message=body.get("message", "Request failed."),
            retry_after=self._retry_after_seconds(resp),
        )

    def lookup_by_article_url(self, url: str):
        return self._request("GET", "/api/discussions/by-article-url", params={"url": url})

    def create_discussion(
        self,
        *,
        title: str,
        article_url: Optional[str] = None,
        external_id: Optional[str] = None,
        excerpt: Optional[str] = None,
        seed_statements: Optional[list] = None,
        source_name: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        embed_statement_submissions_enabled: Optional[bool] = None,
    ):
        if not article_url and not external_id:
            raise ValueError("Provide at least one identifier: article_url or external_id.")
        if not excerpt and not seed_statements:
            raise ValueError("Provide excerpt or seed_statements.")
        if embed_statement_submissions_enabled is not None and not isinstance(embed_statement_submissions_enabled, bool):
            raise ValueError("embed_statement_submissions_enabled must be a boolean when provided.")

        payload = {
            "title": title,
            "article_url": article_url,
            "external_id": external_id,
            "excerpt": excerpt,
            "seed_statements": seed_statements,
            "source_name": source_name,
            "embed_statement_submissions_enabled": embed_statement_submissions_enabled,
        }
        payload = {k: v for k, v in payload.items() if v is not None}

        return self._request(
            "POST",
            "/api/partner/discussions",
            json_body=payload,
            extra_headers={"Idempotency-Key": idempotency_key or f"idem_{uuid.uuid4().hex}"},
        )

    def get_discussion_by_external_id(self, external_id: str, env: Optional[str] = None):
        params = {"external_id": external_id}
        if env:
            params["env"] = env
        return self._request("GET", "/api/partner/discussions/by-external-id", params=params)

    def list_discussions(self, *, env: str = "all", page: int = 1, per_page: int = 30):
        return self._request(
            "GET",
            "/api/partner/discussions",
            params={"env": env, "page": page, "per_page": per_page},
        )

    def patch_discussion(
        self,
        discussion_id: int,
        *,
        is_closed: Optional[bool] = None,
        integrity_mode: Optional[bool] = None,
        embed_statement_submissions_enabled: Optional[bool] = None,
    ):
        payload: Dict[str, Any] = {}
        if is_closed is not None:
            if not isinstance(is_closed, bool):
                raise ValueError("is_closed must be a boolean when provided.")
            payload["is_closed"] = is_closed
        if integrity_mode is not None:
            if not isinstance(integrity_mode, bool):
                raise ValueError("integrity_mode must be a boolean when provided.")
            payload["integrity_mode"] = integrity_mode
        if embed_statement_submissions_enabled is not None:
            if not isinstance(embed_statement_submissions_enabled, bool):
                raise ValueError("embed_statement_submissions_enabled must be a boolean when provided.")
            payload["embed_statement_submissions_enabled"] = embed_statement_submissions_enabled
        if not payload:
            raise ValueError("Provide at least one field to patch.")
        return self._request("PATCH", f"/api/partner/discussions/{discussion_id}", json_body=payload)

    def list_webhooks(self):
        return self._request("GET", "/api/partner/webhooks")

    def create_webhook(self, *, url: str, event_types: List[str]):
        return self._request(
            "POST",
            "/api/partner/webhooks",
            json_body={"url": url, "event_types": event_types},
        )

    def update_webhook(
        self,
        endpoint_id: int,
        *,
        status: Optional[str] = None,
        event_types: Optional[List[str]] = None,
    ):
        payload: Dict[str, Any] = {}
        if status is not None:
            payload["status"] = status
        if event_types is not None:
            payload["event_types"] = event_types
        if not payload:
            raise ValueError("Provide status and/or event_types to update.")
        return self._request("PATCH", f"/api/partner/webhooks/{endpoint_id}", json_body=payload)

    def delete_webhook(self, endpoint_id: int):
        return self._request("DELETE", f"/api/partner/webhooks/{endpoint_id}")

    def rotate_webhook_secret(self, endpoint_id: int):
        return self._request("POST", f"/api/partner/webhooks/{endpoint_id}/rotate-secret")

    def export_usage(self, *, days: int = 30, env: str = "all", page: int = 1, per_page: int = 100):
        return self._request(
            "GET",
            "/api/partner/analytics/usage-export",
            params={"days": days, "env": env, "format": "json", "page": page, "per_page": per_page},
        )
