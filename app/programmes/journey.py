"""
Guided "big questions" programme: progress, ordering, recap, and config helpers.

All recap data is fetched in O(1) batch queries regardless of programme size.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from flask import current_app
from sqlalchemy import func
from app import db
from app.models import ConsensusAnalysis, Discussion, Programme, Statement, StatementVote
from app.programmes.journey_variants import VARIANT_METADATA


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def guided_journey_slug_set() -> set[str]:
    """Canonical set of slugs that qualify as guided flagship programmes."""
    raw = (current_app.config.get("GUIDED_JOURNEY_PROGRAMME_SLUGS") or "").strip()
    if raw:
        return {s.strip().lower() for s in raw.split(",") if s.strip()}
    slugs: set[str] = set()
    for meta in VARIANT_METADATA.values():
        v = (current_app.config.get(meta.config_env_key) or "").strip().lower() or meta.default_slug
        if v:
            slugs.add(v)
    return slugs


def is_guided_journey_programme(programme: Programme) -> bool:
    return programme.slug.lower() in guided_journey_slug_set()


def _build_journey_profile_country_codes() -> dict[str, str]:
    """
    Map variant keys, full country names, and common aliases → Programme.country (lowercase).

    Keeps profile/edition lookup aligned with VARIANT_METADATA so new country variants
    only need updating in journey_variants.py plus Accept-Language region maps below.
    """
    out: dict[str, str] = {}
    for vkey, meta in VARIANT_METADATA.items():
        if not meta.country:
            continue
        norm = meta.country.strip().lower()
        out[vkey] = norm
        out[norm] = norm
    if "uk" in out:
        out["gb"] = out["uk"]
    if "us" in out:
        out["usa"] = out["us"]
    return out


# Profile country SelectField values (see app/profiles/forms.py) → Programme.country (lowercase)
_JOURNEY_PROFILE_COUNTRY_CODES: dict[str, str] = _build_journey_profile_country_codes()

# ISO 3166-1 alpha-2 region subtags → VARIANT_METADATA key (must have meta.country).
# When adding a country journey, add a row here and confirm tests in test_journey_geo.py.
_REGION_SUBTAG_TO_VARIANT: dict[str, str] = {
    "gb": "uk",
    "uk": "uk",
    "us": "us",
    "nl": "nl",
    "ie": "ie",
    "de": "de",
    "fr": "fr",
    "ca": "ca",
    "sg": "sg",
    "jp": "jp",
    "cn": "cn",
}

# Primary language subtag → variant key when region match is insufficient.
_LANG_PRIMARY_TO_VARIANT: dict[str, str] = {
    "nl": "nl",
    "de": "de",
    "fr": "fr",
    "ga": "ie",
    "ja": "jp",
}


def journey_programme_country_lookup_key(raw: Optional[str]) -> Optional[str]:
    """
    Map a user profile country (ISO-style code or full name) to the lowercase
    Programme.country value used on guided journey programmes.
    """
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s:
        return None
    if s in _JOURNEY_PROFILE_COUNTRY_CODES:
        return _JOURNEY_PROFILE_COUNTRY_CODES[s]
    for meta in VARIANT_METADATA.values():
        if meta.country and meta.country.lower() == s:
            return s
    return None


def infer_journey_country_from_accept_language(header: Optional[str]) -> Optional[str]:
    """
    Infer a journey edition from Accept-Language (BCP 47-ish), returning the same
    lowercase key as journey_programme_country_lookup_key.

    Uses region subtags first (e.g. en-GB → UK), then a small language map.
    Does not treat ambiguous bare ``en`` as US/UK.
    """
    if not header or not str(header).strip():
        return None

    def _country_for_variant_key(vkey: str) -> Optional[str]:
        return _JOURNEY_PROFILE_COUNTRY_CODES.get(vkey)

    for part in header.split(","):
        tag = part.split(";")[0].strip().lower()
        if not tag:
            continue
        tag = tag.replace("_", "-")
        subtags = [s for s in tag.split("-") if s]
        if not subtags:
            continue
        primary = subtags[0]
        if primary == "i" or len(primary) > 8:
            continue
        region: Optional[str] = None
        for st in reversed(subtags):
            if len(st) == 2 and st.isalpha():
                region = st.lower()
                break
        if region:
            if primary == "zh" and region in ("tw", "hk", "mo"):
                continue
            vkey = _REGION_SUBTAG_TO_VARIANT.get(region)
            if vkey:
                hit = _country_for_variant_key(vkey)
                if hit:
                    return hit
        if primary == "zh":
            if region in ("tw", "hk", "mo"):
                continue
            if region in ("cn", "sg") or len(subtags) == 1:
                hit_cn = _country_for_variant_key("cn")
                if hit_cn:
                    return hit_cn
            continue
        lang_vkey = _LANG_PRIMARY_TO_VARIANT.get(primary)
        if lang_vkey:
            hit = _country_for_variant_key(lang_vkey)
            if hit:
                return hit
    return None


# ---------------------------------------------------------------------------
# Discussion ordering
# ---------------------------------------------------------------------------

def ordered_journey_discussions(programme: Programme) -> List[Discussion]:
    """Discussions in programme theme order (then title)."""
    themes: Sequence[str] = programme.themes or []
    theme_index = {t: i for i, t in enumerate(themes)}
    discussions = (
        Discussion.query.filter_by(programme_id=programme.id)
        .filter(Discussion.has_native_statements.is_(True))
        .order_by(Discussion.created_at.asc())
        .all()
    )
    discussions.sort(
        key=lambda d: (
            theme_index.get(d.programme_theme or "", 999),
            d.programme_theme or "",
            d.title or "",
        )
    )
    return discussions


# ---------------------------------------------------------------------------
# Batch DB helpers — O(1) queries regardless of discussion count
# ---------------------------------------------------------------------------

def _batch_statement_counts(discussion_ids: List[int]) -> dict[int, int]:
    if not discussion_ids:
        return {}
    rows = (
        db.session.query(Statement.discussion_id, func.count(Statement.id))
        .filter(
            Statement.discussion_id.in_(discussion_ids),
            Statement.is_deleted.is_(False),
            Statement.mod_status >= 0,
        )
        .group_by(Statement.discussion_id)
        .all()
    )
    return {int(did): int(cnt) for did, cnt in rows}


def _batch_user_vote_counts(user_id: int, discussion_ids: List[int]) -> dict[int, int]:
    if not user_id or not discussion_ids:
        return {}
    rows = (
        db.session.query(StatementVote.discussion_id, func.count(StatementVote.id))
        .filter(
            StatementVote.user_id == user_id,
            StatementVote.discussion_id.in_(discussion_ids),
        )
        .group_by(StatementVote.discussion_id)
        .all()
    )
    return {int(did): int(cnt) for did, cnt in rows}


def _batch_unique_participant_counts(discussion_ids: List[int]) -> dict[int, int]:
    """Count distinct voters (by user_id or session_fingerprint) per discussion."""
    if not discussion_ids:
        return {}
    auth_rows = (
        db.session.query(StatementVote.discussion_id, func.count(func.distinct(StatementVote.user_id)))
        .filter(
            StatementVote.discussion_id.in_(discussion_ids),
            StatementVote.user_id.isnot(None),
        )
        .group_by(StatementVote.discussion_id)
        .all()
    )
    anon_rows = (
        db.session.query(StatementVote.discussion_id, func.count(func.distinct(StatementVote.session_fingerprint)))
        .filter(
            StatementVote.discussion_id.in_(discussion_ids),
            StatementVote.user_id.is_(None),
            StatementVote.session_fingerprint.isnot(None),
        )
        .group_by(StatementVote.discussion_id)
        .all()
    )
    result: dict[int, int] = {did: 0 for did in discussion_ids}
    for did, cnt in auth_rows:
        result[int(did)] += int(cnt or 0)
    for did, cnt in anon_rows:
        result[int(did)] += int(cnt or 0)
    return result


def _batch_vote_distributions(discussion_ids: List[int]) -> dict[int, dict[str, int]]:
    if not discussion_ids:
        return {}
    rows = (
        db.session.query(
            StatementVote.discussion_id,
            StatementVote.vote,
            func.count(StatementVote.id),
        )
        .filter(StatementVote.discussion_id.in_(discussion_ids))
        .group_by(StatementVote.discussion_id, StatementVote.vote)
        .all()
    )
    result: dict[int, dict[str, int]] = {
        did: {"agree": 0, "disagree": 0, "unsure": 0} for did in discussion_ids
    }
    for did, val, cnt in rows:
        dist = result[int(did)]
        if val == 1:
            dist["agree"] += int(cnt or 0)
        elif val == -1:
            dist["disagree"] += int(cnt or 0)
        else:
            dist["unsure"] += int(cnt or 0)
    return result


def _batch_latest_analyses(discussion_ids: List[int]) -> dict[int, ConsensusAnalysis]:
    """Latest ConsensusAnalysis per discussion — one grouped query + join (not O(rows) scan)."""
    if not discussion_ids:
        return {}
    # max(id) per discussion_id: analysis ids increase with time in normal operation
    latest_ids = (
        db.session.query(
            ConsensusAnalysis.discussion_id,
            func.max(ConsensusAnalysis.id).label("max_id"),
        )
        .filter(ConsensusAnalysis.discussion_id.in_(discussion_ids))
        .group_by(ConsensusAnalysis.discussion_id)
        .subquery()
    )
    rows = (
        ConsensusAnalysis.query.join(
            latest_ids,
            ConsensusAnalysis.id == latest_ids.c.max_id,
        ).all()
    )
    return {a.discussion_id: a for a in rows}


# ---------------------------------------------------------------------------
# Journey progress
# ---------------------------------------------------------------------------

@dataclass
class JourneyProgressItem:
    discussion: Discussion
    statement_total: int
    user_votes: int
    is_complete: bool

    @property
    def pct(self) -> float:
        if self.statement_total <= 0:
            return 0.0
        return min(100.0, 100.0 * self.user_votes / self.statement_total)


def build_journey_progress(
    programme: Programme,
    user_id: Optional[int],
    discussions: Optional[List[Discussion]] = None,
) -> dict[str, Any]:
    """
    Build per-theme and aggregate progress for the journey banner.

    Accepts an optional pre-fetched `discussions` list to avoid a duplicate
    DB hit when the caller already holds the ordered discussion list.
    """
    if discussions is None:
        discussions = ordered_journey_discussions(programme)
    ids = [d.id for d in discussions]

    stmt_counts = _batch_statement_counts(ids)
    user_vote_counts = _batch_user_vote_counts(user_id or 0, ids) if user_id else {}

    items: List[JourneyProgressItem] = []
    for d in discussions:
        total = stmt_counts.get(d.id, 0)
        votes = user_vote_counts.get(d.id, 0)
        items.append(
            JourneyProgressItem(
                discussion=d,
                statement_total=total,
                user_votes=votes,
                is_complete=total > 0 and votes >= total,
            )
        )

    next_item: Optional[JourneyProgressItem] = next(
        (it for it in items if not it.is_complete), None
    )

    completed_themes = sum(1 for it in items if it.is_complete)
    total_themes = len(items)
    total_user_votes = sum(it.user_votes for it in items)
    total_statements = sum(it.statement_total for it in items)
    # votes_pct gives a smooth 0–100 progress bar even before any theme is fully done
    votes_pct = (100.0 * total_user_votes / total_statements) if total_statements else 0.0
    is_journey_complete = total_themes > 0 and completed_themes == total_themes

    return {
        "theme_items": items,
        "next_item": next_item,
        "completed_themes": completed_themes,
        "total_themes": total_themes,
        "overall_pct": (100.0 * completed_themes / total_themes) if total_themes else 0.0,
        "votes_pct": votes_pct,
        "total_user_votes": total_user_votes,
        "total_statements": total_statements,
        "is_journey_complete": is_journey_complete,
    }


# ---------------------------------------------------------------------------
# Recap payload
# ---------------------------------------------------------------------------

def build_programme_recap_payload(
    programme: Programme,
    user_id: Optional[int],
    discussions: Optional[List[Discussion]] = None,
) -> dict[str, Any]:
    """
    Programme-level recap: per-theme consensus headlines, crowd vote mix, and
    optional signed-in participation stats.

    All DB work is done in 4 batch queries — no N+1.
    Pass `discussions` when the caller already fetched the ordered list (avoids a duplicate query).
    """
    if discussions is None:
        discussions = ordered_journey_discussions(programme)
    ids = [d.id for d in discussions]

    analyses = _batch_latest_analyses(ids)
    vote_dists = _batch_vote_distributions(ids)
    stmt_counts = _batch_statement_counts(ids)
    user_vote_counts = _batch_user_vote_counts(user_id or 0, ids) if user_id else {}
    unique_participant_counts = _batch_unique_participant_counts(ids)

    themes_out: List[dict[str, Any]] = []
    for d in discussions:
        analysis = analyses.get(d.id)
        cluster_data = (analysis.cluster_data or {}) if analysis else {}
        dist = vote_dists.get(d.id, {"agree": 0, "disagree": 0, "unsure": 0})
        stmt_total = stmt_counts.get(d.id, 0)
        user_votes = user_vote_counts.get(d.id, 0)
        total_votes = dist["agree"] + dist["disagree"] + dist["unsure"]
        participant_count = unique_participant_counts.get(d.id, 0)

        # Proportional percentages for the visual bar (integer, sum ≤ 100)
        if total_votes:
            agree_pct = round(100.0 * dist["agree"] / total_votes)
            disagree_pct = round(100.0 * dist["disagree"] / total_votes)
            unsure_pct = 100 - agree_pct - disagree_pct
        else:
            agree_pct = disagree_pct = unsure_pct = 0

        # Dominant crowd stance for personalised copy
        if total_votes:
            crowd_stance = max(
                ("agree", dist["agree"]),
                ("disagree", dist["disagree"]),
                ("unsure", dist["unsure"]),
                key=lambda x: x[1],
            )[0]
        else:
            crowd_stance = None

        themes_out.append(
            {
                "discussion": d,
                "statement_count": int(stmt_total),
                "user_vote_count": int(user_votes),
                "is_theme_complete": stmt_total > 0 and user_votes >= stmt_total,
                "participant_count": participant_count,
                "participant_count_analysis": int(analysis.participants_count or 0) if analysis else 0,
                "consensus_n": len(cluster_data.get("consensus_statements") or []),
                "bridge_n": len(cluster_data.get("bridge_statements") or []),
                "divisive_n": len(cluster_data.get("divisive_statements") or []),
                "vote_distribution": dist,
                "agree_pct": agree_pct,
                "disagree_pct": disagree_pct,
                "unsure_pct": unsure_pct,
                "total_votes": total_votes,
                "crowd_stance": crowd_stance,
                "has_analysis": analysis is not None,
            }
        )

    # Programme-level personalised summary stats
    total_user_votes = sum(t["user_vote_count"] for t in themes_out)
    themes_started = sum(1 for t in themes_out if t["user_vote_count"] > 0)
    themes_completed_by_user = sum(1 for t in themes_out if t["is_theme_complete"])
    total_statements = sum(t["statement_count"] for t in themes_out)
    is_journey_complete = len(themes_out) > 0 and themes_completed_by_user == len(themes_out)

    return {
        "programme": programme,
        "themes": themes_out,
        "total_user_votes": total_user_votes,
        "themes_started": themes_started,
        "themes_completed_by_user": themes_completed_by_user,
        "total_statements": total_statements,
        "total_themes": len(themes_out),
        "is_journey_complete": is_journey_complete,
        "deliberation_space_note": (
            "Each theme uses its own deliberation map. Positions are meaningful within that "
            "theme, not as a single left–right score across every issue."
        ),
    }


# ---------------------------------------------------------------------------
# Per-statement vote detail
# ---------------------------------------------------------------------------

def user_statement_votes_detail_batch(
    user_id: int, discussion_ids: List[int]
) -> dict[int, List[dict[str, Any]]]:
    """Agree/disagree/unsure per statement for multiple discussions — single query."""
    if not user_id or not discussion_ids:
        return {did: [] for did in discussion_ids}
    rows = (
        db.session.query(Statement, StatementVote.vote)
        .join(StatementVote, StatementVote.statement_id == Statement.id)
        .filter(
            StatementVote.user_id == user_id,
            Statement.discussion_id.in_(discussion_ids),
            Statement.is_deleted.is_(False),
        )
        .order_by(Statement.discussion_id, Statement.id.asc())
        .all()
    )
    labels = {-1: "disagree", 0: "unsure", 1: "agree"}
    result: dict[int, List[dict[str, Any]]] = {did: [] for did in discussion_ids}
    for stmt, val in rows:
        result[stmt.discussion_id].append(
            {
                "statement_id": stmt.id,
                "content": stmt.content,
                "vote_label": labels.get(int(val or 0), "unsure"),
            }
        )
    return result


def user_statement_votes_detail(user_id: int, discussion_id: int) -> List[dict[str, Any]]:
    """Single-discussion convenience wrapper around the batch version."""
    return user_statement_votes_detail_batch(user_id, [discussion_id]).get(discussion_id, [])


def discussion_has_linked_source_articles(discussion: Discussion) -> bool:
    """True when at least one source-article link resolves (used for accurate optional-context copy)."""
    links = getattr(discussion, "source_article_links", None) or []
    return any(getattr(link, "article", None) is not None for link in links)


def guided_journey_context_for_discussion(
    discussion: Discussion,
    user_id: Optional[int],
) -> Optional[Dict[str, Any]]:
    """
    When a native discussion belongs to a guided flagship programme, return
    programme-level progress plus this discussion's position in the journey.

    Used for in-discussion orientation (rail UI) and the information-step copy.
    Dict keys include ``has_source_articles`` (whether linked source articles render
    above the optional-reading box), and ``next_theme_in_programme`` (the following
    theme in programme order for navigation — unlike ``progress["next_item"]``,
    which is the first *incomplete* theme and is often the current discussion).
    Returns None if not applicable.
    """
    if not discussion.programme or not discussion.has_native_statements:
        return None
    programme = discussion.programme
    if not is_guided_journey_programme(programme):
        return None
    ordered = ordered_journey_discussions(programme)
    progress = build_journey_progress(programme, user_id, discussions=ordered)
    theme_item = None
    theme_index: Optional[int] = None
    for i, it in enumerate(progress["theme_items"]):
        if it.discussion.id == discussion.id:
            theme_item = it
            theme_index = i + 1
            break
    if theme_item is None:
        return None
    # Next theme in programme order (not ``progress["next_item"]``, which is the
    # first *incomplete* theme — often the current discussion while still voting).
    next_theme_in_programme: Optional[JourneyProgressItem] = None
    items = progress["theme_items"]
    for i, it in enumerate(items):
        if it.discussion.id == discussion.id and i + 1 < len(items):
            next_theme_in_programme = items[i + 1]
            break
    return {
        "programme": programme,
        "progress": progress,
        "theme_item": theme_item,
        "theme_index": theme_index,
        "has_source_articles": discussion_has_linked_source_articles(discussion),
        "next_theme_in_programme": next_theme_in_programme,
    }
