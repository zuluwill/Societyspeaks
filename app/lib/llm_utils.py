# app/lib/llm_utils.py
"""
LLM Utilities (Phase 4)

Optional LLM features using user-provided API keys
- API key encryption/decryption
- Summary generation
- Semantic deduplication
- Cluster labeling

Supports: OpenAI, Anthropic (Claude), Mistral
"""
import os
import logging
from typing import Optional, Dict, List, Tuple
from cryptography.fernet import Fernet
from flask import current_app

logger = logging.getLogger(__name__)


# =============================================================================
# API KEY ENCRYPTION
# =============================================================================

def get_encryption_key():
    """
    Get encryption key from environment variable
    Should be set in Replit Secrets as ENCRYPTION_KEY
    
    Generate one with: Fernet.generate_key().decode()
    """
    key = os.environ.get('ENCRYPTION_KEY')
    if not key:
        raise ValueError("ENCRYPTION_KEY not set in environment")
    return key.encode()


def encrypt_api_key(plain_key: str) -> str:
    """
    Encrypt an API key for storage
    
    Returns: Base64-encoded encrypted key
    """
    f = Fernet(get_encryption_key())
    encrypted = f.encrypt(plain_key.encode())
    return encrypted.decode()


def decrypt_api_key(encrypted_key: str) -> str:
    """
    Decrypt an API key for use
    
    Returns: Plain text API key
    """
    f = Fernet(get_encryption_key())
    decrypted = f.decrypt(encrypted_key.encode())
    return decrypted.decode()


def validate_api_key(provider: str, api_key: str) -> Tuple[bool, str]:
    """
    Validate an API key by making a minimal test request
    
    Returns: (is_valid, message)
    """
    try:
        if provider == 'openai':
            import openai
            openai.api_key = api_key
            # Minimal test request
            try:
                openai.models.list()
                return True, "Valid OpenAI API key"
            except Exception as e:
                return False, f"Invalid OpenAI API key: {str(e)}"
        
        elif provider == 'anthropic':
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            # Minimal test request
            try:
                # This is a very small request just to validate the key
                client.messages.create(
                    model="claude-3-haiku-20240307",
                    max_tokens=10,
                    messages=[{"role": "user", "content": "Hi"}]
                )
                return True, "Valid Anthropic API key"
            except Exception as e:
                return False, f"Invalid Anthropic API key: {str(e)}"
        
        elif provider == 'mistral':
            # Mistral validation (if they have a Python client)
            return True, "Mistral validation not yet implemented"
        
        else:
            return False, "Unsupported provider"
    
    except ImportError:
        return False, f"Python client for {provider} not installed"
    except Exception as e:
        logger.error(f"Error validating {provider} API key: {e}")
        return False, f"Validation error: {str(e)}"


# =============================================================================
# SUMMARY GENERATION
# =============================================================================

def generate_discussion_summary(
    discussion_id: int,
    consensus_statements: List[Dict],
    bridge_statements: List[Dict],
    divisive_statements: List[Dict],
    user_id: int,
    db
) -> Optional[str]:
    """
    Generate a human-readable summary of consensus analysis
    Uses user's own API key if available
    
    Returns: Summary text or None if no API key
    """
    from app.models import UserAPIKey
    
    # Get user's API key
    user_key = UserAPIKey.query.filter_by(
        user_id=user_id,
        is_active=True
    ).first()
    
    if not user_key:
        return None
    
    # Decrypt API key
    api_key = decrypt_api_key(user_key.encrypted_api_key)
    
    # Prepare context for LLM
    context = f"""
You are analyzing a civic discussion. Generate a clear, concise summary (200-300 words) covering:

1. Areas of Consensus (where most agree):
{_format_statements_for_llm(consensus_statements)}

2. Bridge Statements (uniting different groups):
{_format_statements_for_llm(bridge_statements)}

3. Points of Division:
{_format_statements_for_llm(divisive_statements)}

Write in a neutral, informative tone. Focus on what participants agree on and where productive dialogue can happen.
"""
    
    try:
        if user_key.provider == 'openai':
            summary = _generate_with_openai(api_key, context)
        elif user_key.provider == 'anthropic':
            summary = _generate_with_anthropic(api_key, context)
        else:
            summary = None
        
        return summary
    
    except Exception as e:
        logger.error(f"Error generating summary: {e}")
        return None


def _format_statements_for_llm(statements: List[Dict]) -> str:
    """
    Format statements for LLM context
    """
    if not statements:
        return "None identified"
    
    formatted = []
    for stmt in statements[:5]:  # Limit to top 5
        formatted.append(f"- {stmt.get('content', 'N/A')}")
    
    return "\n".join(formatted)


def _generate_with_openai(api_key: str, prompt: str, model: str = "gpt-4o-mini") -> str:
    """
    Generate text using OpenAI API
    Uses gpt-4o-mini for cost-effectiveness
    """
    import openai
    
    client = openai.OpenAI(api_key=api_key)
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a neutral civic discussion analyst."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=500,
        temperature=0.7
    )
    
    return response.choices[0].message.content


def _generate_with_anthropic(api_key: str, prompt: str, model: str = "claude-3-haiku-20240307") -> str:
    """
    Generate text using Anthropic Claude API
    Uses Haiku for cost-effectiveness
    """
    import anthropic
    
    client = anthropic.Anthropic(api_key=api_key)
    
    message = client.messages.create(
        model=model,
        max_tokens=500,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    
    return message.content[0].text


# =============================================================================
# SEMANTIC CLUSTERING
# =============================================================================

def get_statement_embeddings(statements: List[str], user_id: int, db) -> Optional[List[List[float]]]:
    """
    Get embeddings for statements using user's API key
    Used for semantic clustering and deduplication
    
    Returns: List of embedding vectors or None
    """
    from app.models import UserAPIKey
    
    # Get user's API key
    user_key = UserAPIKey.query.filter_by(
        user_id=user_id,
        is_active=True,
        provider='openai'  # Currently only OpenAI has embedding endpoint
    ).first()
    
    if not user_key:
        return None
    
    api_key = decrypt_api_key(user_key.encrypted_api_key)
    
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=statements
        )
        
        embeddings = [item.embedding for item in response.data]
        return embeddings
    
    except Exception as e:
        logger.error(f"Error getting embeddings: {e}")
        return None


def find_duplicate_statements(
    new_statement: str,
    existing_statements: List[Dict],
    threshold: float = 0.9,
    user_id: int = None,
    db = None
) -> Optional[List[Dict]]:
    """
    Find duplicate/similar statements using semantic similarity
    
    Returns: List of similar statements or None if LLM not available
    """
    if not user_id or not db:
        return None
    
    # Get embeddings
    all_texts = [new_statement] + [s['content'] for s in existing_statements]
    embeddings = get_statement_embeddings(all_texts, user_id, db)
    
    if not embeddings:
        return None
    
    # Calculate cosine similarity
    import numpy as np
    
    new_embedding = np.array(embeddings[0])
    existing_embeddings = np.array(embeddings[1:])
    
    # Cosine similarity
    similarities = np.dot(existing_embeddings, new_embedding) / (
        np.linalg.norm(existing_embeddings, axis=1) * np.linalg.norm(new_embedding)
    )
    
    # Find similar statements
    similar_indices = np.where(similarities >= threshold)[0]
    
    similar_statements = [
        {
            **existing_statements[i],
            'similarity': float(similarities[i])
        }
        for i in similar_indices
    ]
    
    return similar_statements


def generate_cluster_labels(
    cluster_data: Dict,
    statements: List[Dict],
    user_id: int,
    db
) -> Optional[Dict[int, str]]:
    """
    Generate human-readable labels for user clusters
    
    Returns: Dictionary mapping cluster_id -> label
    """
    from app.models import UserAPIKey
    
    # Get user's API key
    user_key = UserAPIKey.query.filter_by(
        user_id=user_id,
        is_active=True
    ).first()
    
    if not user_key:
        return None
    
    api_key = decrypt_api_key(user_key.encrypted_api_key)
    
    # Get cluster assignments
    cluster_assignments = cluster_data.get('cluster_assignments', {})
    
    # Group users by cluster
    clusters = {}
    for user_id, cluster_id in cluster_assignments.items():
        if cluster_id not in clusters:
            clusters[cluster_id] = []
        clusters[cluster_id].append(user_id)
    
    # Generate labels for each cluster
    labels = {}
    
    for cluster_id, user_ids in clusters.items():
        # Get representative statements for this cluster
        # (statements that this cluster strongly agrees with)
        representative_stmts = _get_cluster_representative_statements(
            cluster_id, user_ids, statements
        )
        
        if not representative_stmts:
            labels[cluster_id] = f"Group {cluster_id + 1}"
            continue
        
        # Generate label using LLM
        prompt = f"""
Based on these statements that a group strongly agrees with, generate a short (2-4 word) label for the group:

{_format_statements_for_llm(representative_stmts)}

Examples: "Climate Action Supporters", "Economic Pragmatists", "Social Conservatives"

Label:"""
        
        try:
            if user_key.provider == 'openai':
                label = _generate_with_openai(api_key, prompt, model="gpt-4o-mini")
            elif user_key.provider == 'anthropic':
                label = _generate_with_anthropic(api_key, prompt, model="claude-3-haiku-20240307")
            else:
                label = f"Group {cluster_id + 1}"
            
            labels[cluster_id] = label.strip()
        
        except Exception as e:
            logger.error(f"Error generating label for cluster {cluster_id}: {e}")
            labels[cluster_id] = f"Group {cluster_id + 1}"
    
    return labels


def _get_cluster_representative_statements(
    cluster_id: int,
    user_ids: List[int],
    statements: List[Dict],
    limit: int = 3
) -> List[Dict]:
    """
    Get statements that best represent a cluster
    """
    # This is a simplified version - in production, would query votes
    # For now, just return a subset
    return statements[:limit]

