"""Lightweight Society Speaks Partner API client.

Intended as a reference wrapper for partners integrating from backend services.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

import requests


class PartnerApiError(Exception):
    def __init__(self, status_code: int, error: str, message: str):
        super().__init__(f"{status_code} {error}: {message}")
        self.status_code = status_code
        self.error = error
        self.message = message


class SocietyspeaksPartnerClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 15, max_retries: int = 2):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries

    def _request(self, method: str, path: str, *, json_body: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None):
        url = f"{self.base_url}{path}"
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }
        attempt = 0
        while True:
            attempt += 1
            resp = requests.request(
                method=method,
                url=url,
                headers=headers,
                json=json_body,
                params=params,
                timeout=self.timeout,
            )
            if resp.status_code < 500 or attempt > self.max_retries:
                break
            time.sleep(0.5 * attempt)

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
    ):
        if not article_url and not external_id:
            raise ValueError("Provide at least one identifier: article_url or external_id.")
        if not excerpt and not seed_statements:
            raise ValueError("Provide excerpt or seed_statements.")

        payload = {
            "title": title,
            "article_url": article_url,
            "external_id": external_id,
            "excerpt": excerpt,
            "seed_statements": seed_statements,
            "source_name": source_name,
        }
        payload = {k: v for k, v in payload.items() if v is not None}

        # Set Idempotency-Key by issuing direct request for this one call.
        url = f"{self.base_url}/api/partner/discussions"
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key or f"idem_{uuid.uuid4().hex}",
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        if 200 <= resp.status_code < 300:
            return resp.json()
        body = {}
        try:
            body = resp.json() or {}
        except Exception:
            body = {}
        raise PartnerApiError(
            status_code=resp.status_code,
            error=body.get("error", "request_failed"),
            message=body.get("message", "Request failed."),
        )

    def get_discussion_by_external_id(self, external_id: str, env: Optional[str] = None):
        params = {"external_id": external_id}
        if env:
            params["env"] = env
        return self._request("GET", "/api/partner/discussions/by-external-id", params=params)

    def export_usage(self, *, days: int = 30, env: str = "all", page: int = 1, per_page: int = 100):
        return self._request(
            "GET",
            "/api/partner/analytics/usage-export",
            params={"days": days, "env": env, "format": "json", "page": page, "per_page": per_page},
        )
