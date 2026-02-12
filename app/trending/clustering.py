"""
Topic Clustering Service

Groups similar articles into topics using semantic embeddings.
Handles question-level deduplication against existing discussions.
"""

import os
import logging
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

from collections import Counter

from app import db
from app.models import NewsArticle, TrendingTopic, TrendingTopicArticle, Discussion

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
            logger.error(f"Embedding error after {attempt + 1} attempts: {e}")
            return None
        
        except openai.APIConnectionError as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.warning(f"Embedding connection error (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {e}")
                time.sleep(wait_time)
                continue
            logger.error(f"Embedding connection error after {attempt + 1} attempts: {e}")
            return None
        
        except Exception as e:
            logger.error(f"Embedding error: {e}")
            return None
    
    return None


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
    
    from sklearn.metrics.pairwise import cosine_similarity
    from sklearn.cluster import AgglomerativeClustering
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


def find_duplicate_topic(topic_embedding: List[float], days: int = 30) -> Optional[TrendingTopic]:
    """
    Check if a similar topic already exists in the last N days.
    Returns the existing topic if found.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    recent_topics = TrendingTopic.query.filter(
        TrendingTopic.created_at >= cutoff,
        TrendingTopic.topic_embedding.isnot(None),
        TrendingTopic.status.in_(['published', 'pending_review', 'approved'])
    ).all()
    
    if not recent_topics:
        return None
    
    new_embedding = np.array(topic_embedding)
    
    for topic in recent_topics:
        if topic.topic_embedding:
            existing_embedding = np.array(topic.topic_embedding)
            similarity = np.dot(new_embedding, existing_embedding) / (
                np.linalg.norm(new_embedding) * np.linalg.norm(existing_embedding)
            )
            
            if similarity >= 0.78:  # Lowered from 0.85 to catch more related articles
                return topic
    
    return None


def find_similar_discussion(topic_embedding: List[float], days: int = 30) -> Optional[Discussion]:
    """
    Check if a similar discussion already exists.
    Looks at discussion titles.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    recent_discussions = Discussion.query.filter(
        Discussion.created_at >= cutoff,
        Discussion.has_native_statements == True,
        Discussion.partner_env != 'test'
    ).all()
    
    if not recent_discussions:
        return None
    
    titles = [d.title for d in recent_discussions]
    embeddings = get_embeddings(titles)
    
    if not embeddings:
        return None
    
    new_embedding = np.array(topic_embedding)
    
    for i, discussion in enumerate(recent_discussions):
        existing_embedding = np.array(embeddings[i])
        similarity = np.dot(new_embedding, existing_embedding) / (
            np.linalg.norm(new_embedding) * np.linalg.norm(existing_embedding)
        )
        
        if similarity >= 0.8:
            return discussion
    
    return None


def create_topic_from_cluster(
    articles: List[NewsArticle],
    hold_minutes: int = 60
) -> Optional[TrendingTopic]:
    """
    Create a TrendingTopic from a cluster of articles.
    Applies hold window for cooldown.
    """
    if not articles:
        return None
    
    title = generate_neutral_question(articles)
    if not title:
        title = f"Discussion: {articles[0].title[:100]}"
    
    texts = [f"{a.title}. {a.summary or ''}" for a in articles]
    combined_text = " ".join(texts)[:2000]
    
    embeddings = get_embeddings([combined_text])
    topic_embedding = embeddings[0] if embeddings else None
    
    if topic_embedding:
        existing = find_duplicate_topic(topic_embedding)
        if existing:
            logger.info(f"Topic duplicate found: {existing.title}")
            for article in articles:
                existing_link = TrendingTopicArticle.query.filter_by(
                    topic_id=existing.id,
                    article_id=article.id
                ).first()
                if not existing_link:
                    link = TrendingTopicArticle(
                        topic_id=existing.id,
                        article_id=article.id
                    )
                    db.session.add(link)
            
            existing.source_count = len(set(
                ta.article.source_id for ta in existing.articles if ta.article
            ))
            db.session.commit()
            return existing
    
    unique_sources = len(set(a.source_id for a in articles))
    
    # Extract geographic info from source articles
    geographic_scope, geographic_countries = extract_geographic_info_from_articles(articles)
    
    topic = TrendingTopic(
        title=title,
        description=articles[0].summary or '',
        topic_embedding=topic_embedding,
        source_count=unique_sources,
        geographic_scope=geographic_scope,
        geographic_countries=geographic_countries,
        status='pending',
        hold_until=datetime.utcnow() + timedelta(minutes=hold_minutes)
    )
    
    db.session.add(topic)
    db.session.flush()
    
    for article in articles:
        link = TrendingTopicArticle(
            topic_id=topic.id,
            article_id=article.id
        )
        db.session.add(link)
    
    db.session.commit()
    
    return topic


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
        logger.error(f"Question generation failed: {e}")
        return None
