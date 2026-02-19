#!/usr/bin/env python3
"""
Test Data Generator for Native Statement System

Generates realistic test data for a discussion:
- Multiple test users
- Diverse statements
- Realistic voting patterns (to create clusters)
- Responses with evidence
- Flags for moderation testing

Usage:
    python scripts/generate_test_data.py

Or from Flask shell:
    from scripts.generate_test_data import generate_test_discussion
    generate_test_discussion(num_users=20, num_statements=30)
"""
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app import create_app, db
from app.models import User, Discussion, Statement, StatementVote, Response, Evidence, StatementFlag
from datetime import datetime, timedelta
from app.lib.time import utcnow_naive
import random


# Sample statements for a test discussion on climate action
SAMPLE_STATEMENTS = [
    # Consensus statements (most should agree)
    "Climate change is a real and urgent problem",
    "We need to invest more in renewable energy",
    "Protecting the environment benefits everyone",
    
    # Bridge statements (different groups agree)
    "Economic growth and environmental protection can coexist",
    "Local communities should have a say in environmental policies",
    "We need practical solutions, not just rhetoric",
    
    # Divisive statements (splits opinions)
    "We should ban all fossil fuels within 10 years",
    "Individual actions matter more than government policies",
    "Nuclear energy is essential for fighting climate change",
    "We should prioritize economic growth over environmental regulations",
    
    # Additional nuanced statements
    "Carbon taxes are an effective way to reduce emissions",
    "Electric vehicles should receive government subsidies",
    "Corporations should be held accountable for environmental damage",
    "We need stricter regulations on industrial emissions",
    "Tree planting initiatives are the best way to combat climate change",
    "International cooperation is essential for climate action",
    "Climate education should be mandatory in schools",
    "Wealthy nations should pay more for climate action",
    "We need to focus on adaptation as much as mitigation",
    "Technology alone cannot solve the climate crisis"
]


SAMPLE_RESPONSES = {
    'pro': [
        "This is absolutely right. The evidence is overwhelming.",
        "I completely agree. We need to act now.",
        "This makes economic sense in the long run.",
        "This would create jobs and improve public health.",
        "Multiple studies support this approach."
    ],
    'con': [
        "This is too extreme and not practical.",
        "The economic costs would be too high.",
        "This ignores the needs of working families.",
        "There are better alternatives to consider.",
        "This would hurt small businesses."
    ],
    'neutral': [
        "We need more data before deciding.",
        "It depends on how this is implemented.",
        "Both sides have valid points here.",
        "This needs more nuanced discussion.",
        "The devil is in the details."
    ]
}


def create_test_users(num_users=20):
    """
    Create test users with diverse profiles
    """
    print(f"Creating {num_users} test users...")
    users = []
    
    for i in range(num_users):
        username = f"testuser{i+1}"
        email = f"testuser{i+1}@example.com"
        
        # Check if user already exists
        existing = User.query.filter_by(email=email).first()
        if existing:
            users.append(existing)
            continue
        
        user = User(
            username=username,
            email=email,
            profile_type='individual'
        )
        user.set_password('testpassword123')
        
        db.session.add(user)
        users.append(user)
    
    db.session.commit()
    print(f"✓ Created {len(users)} test users")
    return users


def create_test_discussion(creator_user):
    """
    Create a test discussion on climate action
    """
    print("Creating test discussion...")
    
    discussion = Discussion(
        title="Climate Action: Finding Common Ground",
        description="A test discussion exploring different perspectives on climate action and environmental policy. This is sample data for testing the consensus clustering system.",
        topic="Environment",
        country="United Kingdom",
        geographic_scope="country",
        creator_id=creator_user.id,
        has_native_statements=True,
        embed_code=None
    )
    
    db.session.add(discussion)
    db.session.commit()
    
    print(f"✓ Created discussion: {discussion.title} (ID: {discussion.id})")
    return discussion


def create_statements(discussion, users, num_statements=20):
    """
    Create diverse statements in the discussion
    """
    print(f"Creating {num_statements} statements...")
    statements = []
    
    # Use provided statements (limited by num_statements)
    sample_set = SAMPLE_STATEMENTS[:num_statements]
    
    for i, content in enumerate(sample_set):
        author = random.choice(users)
        
        statement = Statement(
            discussion_id=discussion.id,
            user_id=author.id,
            content=content,
            statement_type='claim',
            created_at=utcnow_naive() - timedelta(days=random.randint(0, 7))
        )
        
        db.session.add(statement)
        statements.append(statement)
    
    db.session.commit()
    print(f"✓ Created {len(statements)} statements")
    return statements


def create_voting_patterns(statements, users):
    """
    Create realistic voting patterns that will form 2-3 clusters
    
    Strategy:
    - Group 1 (Activists): Strongly pro-climate action
    - Group 2 (Pragmatists): Moderate, balance economy and environment
    - Group 3 (Skeptics): Prioritize economy, skeptical of extreme measures
    """
    print("Creating voting patterns (this creates user clusters)...")
    
    # Divide users into groups
    num_users = len(users)
    group1 = users[:num_users//3]  # Activists
    group2 = users[num_users//3:2*num_users//3]  # Pragmatists
    group3 = users[2*num_users//3:]  # Skeptics
    
    vote_count = 0
    
    for statement in statements:
        content_lower = statement.content.lower()
        
        # Determine how each group votes based on statement content
        
        # Group 1 (Activists) - pro-climate action
        for user in group1:
            if any(word in content_lower for word in ['climate', 'renewable', 'environment', 'protect']):
                vote = 1  # Agree
            elif any(word in content_lower for word in ['ban', 'fossil', 'stricter']):
                vote = 1  # Agree with strong action
            elif 'economic growth' in content_lower and 'over' in content_lower:
                vote = -1  # Disagree with prioritizing economy over environment
            else:
                vote = random.choice([0, 1])  # Mostly agree or pass
            
            confidence = random.choice([3, 4, 5])  # High confidence
            
            _create_vote(statement, user, vote, confidence)
            vote_count += 1
        
        # Group 2 (Pragmatists) - balanced approach
        for user in group2:
            if 'coexist' in content_lower or 'practical' in content_lower:
                vote = 1  # Agree with balance
            elif 'ban all fossil' in content_lower:
                vote = -1  # Too extreme
            elif any(word in content_lower for word in ['climate', 'renewable']):
                vote = random.choice([0, 1])  # Sometimes agree
            else:
                vote = random.choice([-1, 0, 1])  # Mixed
            
            confidence = random.choice([2, 3, 4])  # Medium confidence
            
            _create_vote(statement, user, vote, confidence)
            vote_count += 1
        
        # Group 3 (Skeptics) - economy-focused
        for user in group3:
            if 'economic growth' in content_lower or 'practical' in content_lower:
                vote = 1  # Agree with economy focus
            elif any(word in content_lower for word in ['ban', 'stricter', 'regulations']):
                vote = -1  # Disagree with restrictions
            elif 'technology' in content_lower:
                vote = 1  # Support tech solutions
            else:
                vote = random.choice([-1, 0])  # Often disagree or pass
            
            confidence = random.choice([3, 4, 5])  # High confidence
            
            _create_vote(statement, user, vote, confidence)
            vote_count += 1
    
    db.session.commit()
    print(f"✓ Created {vote_count} votes across {len(statements)} statements")
    print(f"  This should create 3 distinct opinion groups:")
    print(f"  - Group 1 ({len(group1)} users): Climate activists")
    print(f"  - Group 2 ({len(group2)} users): Pragmatists")
    print(f"  - Group 3 ({len(group3)} users): Economic priority")


def _create_vote(statement, user, vote, confidence=None):
    """Helper to create a vote"""
    vote_obj = StatementVote(
        statement_id=statement.id,
        user_id=user.id,
        discussion_id=statement.discussion_id,
        vote=vote,
        confidence=confidence
    )
    db.session.add(vote_obj)
    
    # Update denormalized counts
    if vote == 1:
        statement.vote_count_agree += 1
    elif vote == -1:
        statement.vote_count_disagree += 1
    elif vote == 0:
        statement.vote_count_unsure += 1


def create_responses(statements, users, num_responses=30):
    """
    Create sample responses to statements
    """
    print(f"Creating {num_responses} responses...")
    
    # Select random statements to respond to
    popular_statements = random.sample(statements, min(10, len(statements)))
    
    responses_created = 0
    
    for statement in popular_statements:
        # 2-4 responses per popular statement
        num_stmt_responses = random.randint(2, 4)
        
        for _ in range(num_stmt_responses):
            if responses_created >= num_responses:
                break
            
            author = random.choice(users)
            position = random.choice(['pro', 'con', 'neutral'])
            content = random.choice(SAMPLE_RESPONSES[position])
            
            response = Response(
                statement_id=statement.id,
                user_id=author.id,
                position=position,
                content=content,
                created_at=utcnow_naive() - timedelta(days=random.randint(0, 5))
            )
            
            db.session.add(response)
            responses_created += 1
        
        if responses_created >= num_responses:
            break
    
    db.session.commit()
    print(f"✓ Created {responses_created} responses")


def create_sample_flags(statements, users):
    """
    Create a few sample flags for moderation testing
    """
    print("Creating sample flags for moderation testing...")
    
    # Flag 1-2 statements
    flagged_statements = random.sample(statements, min(2, len(statements)))
    
    for statement in flagged_statements:
        flagger = random.choice(users)
        
        flag = StatementFlag(
            statement_id=statement.id,
            flagger_user_id=flagger.id,
            flag_reason='off_topic',
            additional_context="This seems off-topic or potentially misleading",
            status='pending'
        )
        
        db.session.add(flag)
    
    db.session.commit()
    print(f"✓ Created {len(flagged_statements)} sample flags")


def generate_test_discussion(num_users=20, num_statements=20, num_responses=30):
    """
    Main function to generate a complete test discussion
    """
    print("\n" + "="*60)
    print("GENERATING TEST DATA FOR NATIVE STATEMENT SYSTEM")
    print("="*60 + "\n")
    
    # Create users
    users = create_test_users(num_users)
    creator = users[0]
    
    # Create discussion
    discussion = create_test_discussion(creator)
    
    # Create statements
    statements = create_statements(discussion, users, num_statements)
    
    # Create voting patterns (forms clusters)
    create_voting_patterns(statements, users)
    
    # Create responses
    create_responses(statements, users, num_responses)
    
    # Create sample flags
    create_sample_flags(statements, users)
    
    print("\n" + "="*60)
    print("✓ TEST DATA GENERATION COMPLETE!")
    print("="*60)
    print(f"\nDiscussion ID: {discussion.id}")
    print(f"Discussion Slug: {discussion.slug}")
    print(f"URL: /discussions/{discussion.id}/{discussion.slug}")
    print(f"\nTest users: testuser1 - testuser{num_users}")
    print(f"Password: testpassword123")
    print(f"\nNext steps:")
    print(f"1. Log in as any test user")
    print(f"2. View the discussion")
    print(f"3. Run consensus analysis (as discussion creator)")
    print(f"4. View clustering results and visualizations")
    print("\n")
    
    return discussion


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        try:
            discussion = generate_test_discussion()
        except Exception as e:
            print(f"\n❌ Error generating test data: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

