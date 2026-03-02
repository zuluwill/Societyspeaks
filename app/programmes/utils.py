from urllib.parse import urlparse
from markupsafe import escape

try:
    import bleach
except ImportError:  # pragma: no cover - optional dependency fallback
    bleach = None

try:
    import markdown as md
except ImportError:  # pragma: no cover - optional dependency fallback
    md = None


ALLOWED_INFORMATION_TAGS = [
    "p", "a", "ul", "ol", "li", "strong", "em", "h3", "h4", "br"
]
ALLOWED_INFORMATION_ATTRIBUTES = {
    "a": ["href", "title", "rel"]
}
ALLOWED_INFORMATION_PROTOCOLS = ["http", "https", "mailto"]


def parse_csv_list(raw_text):
    if not raw_text:
        return []
    parts = [part.strip() for part in raw_text.split(",")]
    return [part for part in parts if part]


def parse_cohorts_csv(raw_text):
    """
    Accepts lines in either format:
    - slug|Label
    - label (slug auto-generated from label)
    """
    from app.models import generate_slug

    if not raw_text:
        return []

    rows = []
    for line in raw_text.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        if "|" in cleaned:
            slug_part, label_part = cleaned.split("|", 1)
            slug = generate_slug(slug_part.strip())
            label = label_part.strip()
        else:
            label = cleaned
            slug = generate_slug(cleaned)
        if slug and label:
            rows.append({"slug": slug, "label": label})
    return rows


def safe_information_links(raw_links):
    safe_links = []
    if not isinstance(raw_links, list):
        return safe_links

    for link in raw_links:
        if not isinstance(link, dict):
            continue
        label = str(link.get("label") or "").strip()
        url = str(link.get("url") or "").strip()
        if not label or not url:
            continue
        parsed = urlparse(url)
        if parsed.scheme in ("http", "https"):
            safe_links.append({"label": label, "url": url})
    return safe_links


def render_safe_information_markdown(markdown_text):
    if not markdown_text:
        return ""
    if md is None or bleach is None:
        # Safe fallback if optional packages are unavailable in local/dev environments.
        return str(escape(markdown_text)).replace("\n", "<br>")
    rendered = md.markdown(markdown_text, extensions=["extra", "nl2br"])
    return bleach.clean(
        rendered,
        tags=ALLOWED_INFORMATION_TAGS,
        attributes=ALLOWED_INFORMATION_ATTRIBUTES,
        protocols=ALLOWED_INFORMATION_PROTOCOLS,
        strip=True
    )


def get_programme_cohort_slugs(programme):
    cohorts = getattr(programme, "cohorts", None) or []
    slugs = set()
    for entry in cohorts:
        if isinstance(entry, dict):
            slug = str(entry.get("slug") or "").strip()
            if slug:
                slugs.add(slug)
    return slugs


def validate_cohort_for_discussion(discussion, cohort_slug):
    """
    Returns normalized cohort slug if valid, otherwise None.
    """
    if not cohort_slug:
        return None
    cleaned = str(cohort_slug).strip()
    if not cleaned:
        return None
    if not discussion.programme:
        return None
    return cleaned if cleaned in get_programme_cohort_slugs(discussion.programme) else None
