from app.models import Discussion

def get_recent_activity(user_id):
    """
    Get recent activity for the dashboard
    Returns a list of activity items with type, content, and timestamp
    """
    activity = []

    # Get recent discussions
    recent_discussions = Discussion.query\
        .filter_by(creator_id=user_id)\
        .order_by(Discussion.created_at.desc())\
        .limit(5)\
        .all()

    for discussion in recent_discussions:
        activity.append({
            'type': 'discussion_created',
            'content': f"Created discussion: {discussion.title}",
            'timestamp': discussion.created_at
        })

    return activity