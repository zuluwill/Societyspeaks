"""
Collect HTTP(S) URLs from guided-journey optional-reading content.

Country packs live in ``journey_reading_enrichment.READING_PACKS``; the global
curriculum is merged in via :func:`reading_packs_for_link_audit` so CI checks
all seeded reference URLs, not only country editions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterator, List, Mapping, Optional
from urllib.parse import urlparse, urlunparse

# Inline Markdown links in optional-reading bodies: [label](https://...)
MARKDOWN_HTTPS_LINK_RE = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)")

Pack = Mapping[str, object]


@dataclass(frozen=True)
class ReadingPackUrlRef:
    """One occurrence of a URL inside a country reading pack."""

    variant: str
    theme: str
    url: str
    source: str  # "markdown" | "information_link"
    detail: str  # link label or short markdown snippet

    def context_line(self) -> str:
        return f"{self.variant}/{self.theme} [{self.source}] {self.detail}"


def normalize_url_for_dedup(url: str) -> str:
    """Stable key for deduplicating network checks (scheme/host lowercased, no fragment)."""
    raw = (url or "").strip()
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw
    netloc = parsed.netloc.lower()
    if netloc.endswith(":80") and parsed.scheme == "http":
        netloc = netloc[:-3]
    if netloc.endswith(":443") and parsed.scheme == "https":
        netloc = netloc[:-4]
    # Drop fragment; keep path + query as authored
    return urlunparse(
        (parsed.scheme.lower(), netloc, parsed.path or "", "", parsed.query, "")
    )


def iter_reading_pack_url_refs(packs: Optional[Dict[str, Dict[str, Pack]]] = None) -> Iterator[ReadingPackUrlRef]:
    """
    Yield every https? URL from Markdown bodies and information_links.

    If packs is None, imports READING_PACKS from journey_reading_enrichment.
    """
    if packs is None:
        from app.programmes.journey_reading_enrichment import READING_PACKS

        packs = READING_PACKS

    for variant, themes in packs.items():
        for theme, pack in themes.items():
            body = str((pack or {}).get("body") or "")
            for m in MARKDOWN_HTTPS_LINK_RE.finditer(body):
                url = m.group(1).rstrip(").,;")
                snippet = m.group(0)
                if len(snippet) > 100:
                    snippet = snippet[:97] + "..."
                yield ReadingPackUrlRef(
                    variant=variant,
                    theme=theme,
                    url=url,
                    source="markdown",
                    detail=snippet,
                )
            links_obj = (pack or {}).get("links") or []
            if not isinstance(links_obj, list):
                continue
            for item in links_obj:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "").strip()
                if not url:
                    continue
                label = str(item.get("label") or "").strip() or "(no label)"
                yield ReadingPackUrlRef(
                    variant=variant,
                    theme=theme,
                    url=url,
                    source="information_link",
                    detail=label,
                )


def refs_by_normalized_url(
    packs: Optional[Dict[str, Dict[str, Pack]]] = None,
) -> Dict[str, List[ReadingPackUrlRef]]:
    """Group all refs by normalize_url_for_dedup(url) for a single HTTP probe per unique URL."""
    out: Dict[str, List[ReadingPackUrlRef]] = {}
    for ref in iter_reading_pack_url_refs(packs):
        key = normalize_url_for_dedup(ref.url)
        out.setdefault(key, []).append(ref)
    return out


def reading_packs_for_link_audit() -> Dict[str, Dict[str, Pack]]:
    """
    Country reading packs plus the global curriculum, in the same dict shape as READING_PACKS.

    Used by ``verify_journey_reading_links`` so automated checks cover **all** seeded
    optional-reading URLs (global inline curriculum + per-country enrichment), not only
    country packs — important for intellectual QA parity.
    """
    from app.programmes.journey_reading_enrichment import READING_PACKS
    from app.programmes.journey_seed import get_curriculum

    merged: Dict[str, Dict[str, Pack]] = {variant: dict(themes) for variant, themes in READING_PACKS.items()}
    global_themes: Dict[str, Pack] = {}
    for spec in get_curriculum("global"):
        theme = spec.get("theme")
        if not theme or not isinstance(theme, str):
            continue
        global_themes[theme] = {
            "body": spec.get("information_body"),
            "links": spec.get("information_links"),
        }
    merged["global"] = global_themes
    return merged
