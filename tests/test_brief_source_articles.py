"""Source articles resolve via trending topic when brief-sourced."""

from datetime import date

from app import db
from app.lib.time import utcnow_naive
from app.models import DailyQuestion, TrendingTopic, TrendingTopicArticle, NewsArticle, NewsSource
from app.daily.routes import get_source_articles


def test_get_source_articles_from_trending_topic(db):
    topic = TrendingTopic(
        title='Grid investment',
        status='published',
        primary_topic='Infrastructure',
        civic_score=0.8,
        seed_statements=[{'content': 'Invest now.', 'position': 'pro'}],
    )
    db.session.add(topic)
    db.session.flush()

    source = NewsSource(
        name='Test Wire',
        feed_url='https://example.com/rss',
        source_type='wire',
        reputation_score=0.9,
    )
    db.session.add(source)
    db.session.flush()

    article = NewsArticle(
        title='Grid story headline',
        url='https://example.com/grid',
        source_id=source.id,
        published_at=utcnow_naive(),
    )
    db.session.add(article)
    db.session.flush()

    db.session.add(TrendingTopicArticle(topic_id=topic.id, article_id=article.id, similarity_score=0.9))

    question = DailyQuestion(
        question_date=date(2026, 7, 15),
        question_number=99,
        question_text='Should grid investment accelerate?',
        source_type='brief',
        source_trending_topic_id=topic.id,
        status='scheduled',
    )
    db.session.add(question)
    db.session.commit()

    articles = get_source_articles(question, limit=3)
    assert len(articles) == 1
    assert articles[0].title == 'Grid story headline'
