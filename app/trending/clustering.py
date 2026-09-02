"""
Topic Clustering Service

Groups similar articles into topics using semantic embeddings.
Deduplicates new clusters against recent topics (find_duplicate_topic).
"""

import os
import logging
import numpy as np
from datetime import datetime, timedelta
from app.lib.time import utcnow_naive
from typing import List, Dict, Optional, Tuple

from collections import Counter
from sqlalchemy import func

from app import db
from app.models import NewsArticle, TrendingTopic, TrendingTopicArticle
from app.lib.llm_transient_errors import log_llm_error
from app.lib.sklearn_compat import (
    SKLEARN_AVAILABLE,
    cosine_similarity,
    AgglomerativeClustering,
)

logger = logging.getLogger(__name__)


def extract_geographic_info_from_articles(articles: List[NewsArticle]) -> tuple:
    """
    Extract geographic scope and countries from a list of articles.
    
    Returns (geographic_scope, geographic_countries_string)
    """
    scopes = []
    countries_list = []
    
    for article in articles:
        if article.geographic_scope and article.geographic_scope != 'unknown':
            scopes.append(article.geographic_scope)
        if article.geographic_countries:
            countries_list.append(article.geographic_countries)
        elif article.source and article.source.country:
            countries_list.append(article.source.country)
    
    # Determine scope
    if scopes:
        scope_counts = Counter(scopes)
        most_common_scope = scope_counts.most_common(1)[0][0]
        if most_common_scope in ('national', 'local', 'regional'):
            geographic_scope = 'country'
        else:
            geographic_scope = 'global'
    else:
        geographic_scope = 'global'
    
    # Determine countries
    if countries_list:
        all_countries = []
        for c in countries_list:
            all_countries.extend([x.strip() for x in c.split(',')])
        
        if 'Global' in all_countries:
            geographic_countries = None
        else:
            # Take top 3 most common countries
            country_counts = Counter(all_countries)
            top_countries = [c for c, _ in country_counts.most_common(3)]
            geographic_countries = ', '.join(top_countries) if top_countries else None
    else:
        geographic_countries = None
    
    return geographic_scope, geographic_countries


def recount_topic_source_count(topic_id: int) -> int:
    """
    Count distinct news sources linked to a topic (all article links, not one cluster).
    """
    return (
        db.session.query(func.count(func.distinct(NewsArticle.source_id)))
        .join(TrendingTopicArticle, NewsArticle.id == TrendingTopicArticle.article_id)
        .filter(TrendingTopicArticle.topic_id == topic_id)
        .scalar()
        or 0
    )


def get_embeddings(texts: List[str], max_retries: int = 3) -> Optional[List[List[float]]]:
    """Get embeddings for texts using OpenAI with retry logic for transient errors."""
    import time
    
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        logger.warning("OPENAI_API_KEY not set, skipping embeddings")
        return None
    
    import openai
    client = openai.OpenAI(api_key=api_key)
    
    for attempt in range(max_retries):
        try:
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=texts
            )
            return [item.embedding for item in response.data]
        
        except openai.APIStatusError as e:
            if e.status_code in (500, 502, 503, 529) and attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.warning(f"Embedding API error (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {e}")
                time.sleep(wait_time)
                continue
            log_llm_error(logger, e, context=f"Embedding error after {attempt + 1} attempts")
            return None
        
        except openai.APIConnectionError as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.warning(f"Embedding connection error (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {e}")
                time.sleep(wait_time)
                continue
            log_llm_error(logger, e, context=f"Embedding connection error after {attempt + 1} attempts")
            return None
        
        except Exception as e:
            log_llm_error(logger, e, context="Embedding error")
            return None
    
    return None


def _numpy_cluster_articles(
    articles: List[NewsArticle],
    embeddings_array: "np.ndarray",
    threshold: float,
) -> List[List[NewsArticle]]:
    """
    Pure-numpy fallback for article clustering using Union-Find on cosine distance.
    Used when scikit-learn is unavailable (see app.lib.sklearn_compat).
    """
    norms = np.linalg.norm(embeddings_array, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    normed = embeddings_array / norms
    distance_matrix = 1 - np.dot(normed, normed.T)

    n = len(articles)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        for j in range(i + 1, n):
            if distance_matrix[i][j] < (1 - threshold):
                union(i, j)

    clusters_dict: Dict[int, List[NewsArticle]] = {}
    for i in range(n):
        root = find(i)
        clusters_dict.setdefault(root, []).append(articles[i])

    logger.info(
        "Numpy fallback clustering: %d articles -> %d clusters",
        n,
        len(clusters_dict),
    )
    return list(clusters_dict.values())


def cluster_articles(articles: List[NewsArticle], threshold: float = 0.7) -> List[List[NewsArticle]]:
    """
    Cluster articles by semantic similarity.
    Returns list of article clusters.
    """
    if len(articles) < 2:
        return [[a] for a in articles]
    
    texts = [f"{a.title}. {a.summary or ''}" for a in articles]
    embeddings = get_embeddings(texts)
    
    if not embeddings:
        return [[a] for a in articles]
    
    for i, article in enumerate(articles):
        article.title_embedding = embeddings[i]
    db.session.commit()
    
    embeddings_array = np.array(embeddings)

    if not SKLEARN_AVAILABLE:
        return _numpy_cluster_articles(articles, embeddings_array, threshold)

    try:
        distance_matrix = 1 - cosine_similarity(embeddings_array)
        clustering = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=1 - threshold,
            metric='precomputed',
            linkage='average'
        )
        labels = clustering.fit_predict(distance_matrix)
        clusters = {}
        for i, label in enumerate(labels):
            if label not in clusters:
                clusters[label] = []
            clusters[label].append(articles[i])
        return list(clusters.values())
    except (OSError, ImportError) as e:
        logger.warning(
            "sklearn clustering runtime failed (%s), using numpy fallback: %s",
            type(e).__name__,
            e,
        )
        return _numpy_cluster_articles(articles, embeddings_array, threshold)


# Lowered from 0.85 to catch more related articles.
DUPLICATE_SIMILARITY_THRESHOLD = 0.78

# Topic statuses that a new cluster can be deduplicated against.
DUPLICATE_CANDIDATE_STATUSES = ('published', 'pending_review', 'approved')


class TopicEmbeddingIndex:
    """Recent topic embeddings held in memory for duplicate detection.

    find_duplicate_topic() runs once per cluster and the 30-day pool is ~1,700
    topics of ~16 KB vector each, so re-querying it per cluster re-downloaded
    tens of MB per cluster for information that had not changed. A pipeline run
    builds this index once and passes it down.

    Topics created during the run can be appended via add() when they are
    actually dedupe candidates. create_topic_from_cluster writes status
    ``pending``, which is *not* in DUPLICATE_CANDIDATE_STATUSES, so the
    pipeline's append is normally a no-op — matching the previous per-cluster
    query, which never saw pending rows. Do not append unconditionally: that
    would silently widen dedup and merge clusters that previously stayed
    separate.

    Only (id, topic_embedding) is fetched and vectors are kept as plain numpy
    arrays, so the index is unaffected by the session commit/rollback that
    create_topic_from_cluster performs between clusters.
    """

    def __init__(self, days: int = 30, load: bool = True):
        self.days = days
        self._ids: List[int] = []
        self._vectors: List[np.ndarray] = []
        self._dim: Optional[int] = None
        self._matrix: Optional[np.ndarray] = None
        self._norms: Optional[np.ndarray] = None
        if load:
            self._load()

    def _load(self) -> None:
        cutoff = utcnow_naive() - timedelta(days=self.days)
        rows = db.session.query(
            TrendingTopic.id, TrendingTopic.topic_embedding
        ).filter(
            TrendingTopic.created_at >= cutoff,
            TrendingTopic.topic_embedding.isnot(None),
            TrendingTopic.status.in_(DUPLICATE_CANDIDATE_STATUSES),
        ).all()

        skipped = 0
        for topic_id, embedding in rows:
            if not self.add(topic_id, embedding):
                skipped += 1

        logger.info(
            "Topic embedding index: %d topic(s) over %d days (%d skipped)",
            len(self._ids), self.days, skipped,
        )

    def add(self, topic_id: int, embedding) -> bool:
        """Register a topic. Returns False if the vector is unusable."""
        if not embedding:
            return False

        vector = np.asarray(embedding, dtype=float)
        if vector.ndim != 1 or vector.size == 0:
            return False
        if self._dim is None:
            self._dim = vector.size
        elif vector.size != self._dim:
            # Mixed embedding models would make the similarity meaningless.
            return False
        if np.linalg.norm(vector) == 0:
            return False

        self._ids.append(topic_id)
        self._vectors.append(vector)
        self._matrix = None  # invalidate the stacked cache
        self._norms = None
        return True

    def find_duplicate_id(
        self, embedding, threshold: float = DUPLICATE_SIMILARITY_THRESHOLD
    ) -> Optional[int]:
        """Return the id of the most similar topic above threshold, or None.

        Note: this returns the *best* match. The previous per-cluster loop
        returned the first row above threshold in whatever order Postgres
        happened to return, which was not deterministic between runs.
        """
        if not self._ids or not embedding:
            return None

        vector = np.asarray(embedding, dtype=float)
        if vector.ndim != 1 or vector.size != self._dim:
            return None
        norm = np.linalg.norm(vector)
        if norm == 0:
            return None

        if self._matrix is None:
            self._matrix = np.vstack(self._vectors)
            self._norms = np.linalg.norm(self._matrix, axis=1)

        similarities = (self._matrix @ vector) / (self._norms * norm)
        best = int(np.argmax(similarities))
        if float(similarities[best]) >= threshold:
            return self._ids[best]
        return None

    def __len__(self) -> int:
        return len(self._ids)


def find_duplicate_topic(
    topic_embedding: List[float],
    days: int = 30,
    index: Optional[TopicEmbeddingIndex] = None,
) -> Optional[TrendingTopic]:
    """
    Check if a similar topic already exists in the last N days.
    Returns the existing topic if found.

    Pass an index to reuse one load across a whole pipeline run; without one a
    fresh index is built for this call alone (the original behaviour).
    """
    if index is None:
        index = TopicEmbeddingIndex(days=days)

    topic_id = index.find_duplicate_id(topic_embedding)
    if topic_id is None:
        return None

    return db.session.get(TrendingTopic, topic_id)


def create_topic_from_cluster(
    articles: List[NewsArticle],
    hold_minutes: int = 60,
    topic_index: Optional[TopicEmbeddingIndex] = None
) -> Optional[TrendingTopic]:
    """
    Create a TrendingTopic from a cluster of articles.
    Applies hold window for cooldown.

    IMPORTANT - connection hygiene
    --------------------------------
    This function makes slow external LLM API calls (title generation,
    embeddings).  Holding a DB connection open during those calls risks an
    "SSL connection has been closed unexpectedly" error from Neon/PgBouncer
    when the idle connection is timed-out server-side.

    To avoid this we:
    1. Extract all required data from ORM objects into plain Python values
       (triggering any lazy loads while the connection is still healthy).
    2. Call db.session.rollback() to release the connection back to the pool.
       In SQLAlchemy 2.x, rollback() returns the connection immediately.
       Objects remain in the session (not detached), just marked expired, so
       later iterations of the cluster loop can still lazy-load them safely.
    3. Run all LLM API calls with no connection held.
    4. Re-enter the DB with a fresh connection (pool_pre_ping validates it).
    """
    if not articles:
        return None

    # --- Step 1: snapshot all ORM data into plain Python --------------------
    # Access every attribute (including lazy-loaded relationships) NOW, while
    # we still have a valid connection, before we release it.
    article_ids = [a.id for a in articles]
    article_source_ids = [a.source_id for a in articles]
    article_titles = [a.title for a in articles]
    article_summaries = [a.summary or '' for a in articles]
    first_description = articles[0].summary or ''

    # geographic info may need source.country (lazy relationship)
    geo_data = []
    for a in articles:
        source_country = None
        try:
            if a.source:
                source_country = a.source.country
        except Exception:
            pass  # detached or unloaded — geographic fallback is fine
        geo_data.append({
            'geographic_scope': a.geographic_scope,
            'geographic_countries': a.geographic_countries,
            'source_country': source_country,
        })

    # --- Step 2: release the connection before slow API calls ---------------
    # rollback() ends the implicit read transaction and returns the connection
    # to the pool in SQLAlchemy 2.x.  Unlike close(), objects stay in the
    # session (just expired), so subsequent cluster iterations can still
    # lazy-load their own articles without DetachedInstanceError.
    db.session.rollback()

    # --- Step 3: slow LLM API calls (no DB connection held) -----------------
    title = _generate_neutral_question_from_titles(article_titles)
    if not title:
        title = f"Discussion: {article_titles[0][:100]}"

    texts = [f"{t}. {s}" for t, s in zip(article_titles, article_summaries)]
    combined_text = " ".join(texts)[:2000]

    embeddings = get_embeddings([combined_text])
    topic_embedding = embeddings[0] if embeddings else None

    # --- Step 4: DB operations with a fresh, pre-pinged connection ----------
    geographic_scope, geographic_countries = _extract_geographic_info_from_data(geo_data)
    unique_sources = len(set(article_source_ids))

    if topic_embedding:
        existing = find_duplicate_topic(topic_embedding, index=topic_index)
        if existing:
            logger.info(f"Topic duplicate found: {existing.title}")
            for article_id in article_ids:
                existing_link = TrendingTopicArticle.query.filter_by(
                    topic_id=existing.id,
                    article_id=article_id
                ).first()
                if not existing_link:
                    link = TrendingTopicArticle(
                        topic_id=existing.id,
                        article_id=article_id
                    )
                    db.session.add(link)

            # Flush so the count query below sees the newly added rows.
            db.session.flush()
            existing.source_count = recount_topic_source_count(existing.id)
            db.session.commit()
            return existing

    topic = TrendingTopic(
        title=title,
        description=first_description,
        topic_embedding=topic_embedding,
        source_count=unique_sources,
        geographic_scope=geographic_scope,
        geographic_countries=geographic_countries,
        status='pending',
        hold_until=utcnow_naive() + timedelta(minutes=hold_minutes)
    )

    db.session.add(topic)
    db.session.flush()

    for article_id in article_ids:
        link = TrendingTopicArticle(
            topic_id=topic.id,
            article_id=article_id
        )
        db.session.add(link)

    db.session.commit()

    # Keep the shared index current so the next cluster in this run sees
    # exactly what a fresh per-cluster query would have returned. Note the
    # status gate: topics are created 'pending', which is not a dedupe
    # candidate status, so this is normally a no-op — matching the previous
    # behaviour rather than silently widening it.
    if (
        topic_index is not None
        and topic_embedding
        and topic.status in DUPLICATE_CANDIDATE_STATUSES
    ):
        topic_index.add(topic.id, topic_embedding)

    return topic


def _generate_neutral_question_from_titles(titles: List[str]) -> Optional[str]:
    """
    Generate a neutral framing question from a list of article titles.
    Works on plain strings so it can be called after the DB session is closed.
    """
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return None

    headlines = titles[:5]

    prompt = f"""Based on these news headlines about the same topic, generate a neutral,
open-ended question suitable for public deliberation. The question should:
- Be neutral, not leading
- Invite multiple perspectives
- Focus on policy/civic implications where possible
- Use simple, direct language a 12-year-old could understand
- Avoid bureaucratic jargon and complex terminology
- Maximum 2 clauses (keep it concise)
- Be under 150 characters

Headlines:
{chr(10).join(f'- {h}' for h in headlines)}

Return ONLY the question, nothing else."""

    try:
        import openai
        client = openai.OpenAI(api_key=api_key)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a civic discourse facilitator."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=100,
            temperature=0.7
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        log_llm_error(logger, e, context="Question generation failed")
        return None


def _extract_geographic_info_from_data(geo_data: List[dict]) -> tuple:
    """
    Extract geographic scope and countries from pre-loaded article geo data.
    Accepts plain dicts so it works after the DB session has been closed.
    """
    scopes = []
    countries_list = []

    for item in geo_data:
        scope = item.get('geographic_scope')
        if scope and scope != 'unknown':
            scopes.append(scope)
        countries = item.get('geographic_countries')
        if countries:
            countries_list.append(countries)
        elif item.get('source_country'):
            countries_list.append(item['source_country'])

    if scopes:
        scope_counts = Counter(scopes)
        most_common_scope = scope_counts.most_common(1)[0][0]
        geographic_scope = 'country' if most_common_scope in ('national', 'local', 'regional') else 'global'
    else:
        geographic_scope = 'global'

    if countries_list:
        all_countries = []
        for c in countries_list:
            all_countries.extend([x.strip() for x in c.split(',')])

        if 'Global' in all_countries:
            geographic_countries = None
        else:
            country_counts = Counter(all_countries)
            top_countries = [c for c, _ in country_counts.most_common(3)]
            geographic_countries = ', '.join(top_countries) if top_countries else None
    else:
        geographic_countries = None

    return geographic_scope, geographic_countries


def generate_neutral_question(articles: List[NewsArticle]) -> Optional[str]:
    """
    Generate a neutral framing question for the topic.
    Uses LLM if available.
    """
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return None
    
    headlines = [a.title for a in articles[:5]]
    
    prompt = f"""Based on these news headlines about the same topic, generate a neutral,
open-ended question suitable for public deliberation. The question should:
- Be neutral, not leading
- Invite multiple perspectives
- Focus on policy/civic implications where possible
- Use simple, direct language a 12-year-old could understand
- Avoid bureaucratic jargon and complex terminology
- Maximum 2 clauses (keep it concise)
- Be under 150 characters

Headlines:
{chr(10).join(f'- {h}' for h in headlines)}

Return ONLY the question, nothing else."""

    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a civic discourse facilitator."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=100,
            temperature=0.7
        )
        
        return response.choices[0].message.content.strip()
    
    except Exception as e:
        log_llm_error(logger, e, context="Question generation failed")
        return None
