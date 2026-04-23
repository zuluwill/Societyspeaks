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
                    model="claude-haiku-4-5-20251001",
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


def _generate_with_anthropic(api_key: str, prompt: str, model: str = "claude-haiku-4-5-20251001") -> str:
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
) -> Optional[Dict[int, Dict]]:
    """
    Generate human-readable labels for opinion groups, grounded in the
    group's representative statements.

    Returns a dict mapping cluster_id → {
        'label': str,                       # short human-readable label
        'supporting_statement_ids': [int],  # statements the LLM cited
    }

    The route-level grounding check in app/discussions/consensus.py
    verifies that the cited statement IDs actually belong to that
    cluster's representative list, and withholds labels that cannot be
    traced back to the underlying data (e.g. hallucinated themes).
    """
    import json
    import re
    from app.models import UserAPIKey

    user_key = UserAPIKey.query.filter_by(
        user_id=user_id,
        is_active=True
    ).first()
    if not user_key:
        return None

    api_key = decrypt_api_key(user_key.encrypted_api_key)

    # Prefer the engine-provided representative statements over the local
    # heuristic — they are already filtered / significance-ranked and carry
    # the statement IDs we need for grounding.
    rep_by_cluster = cluster_data.get('representative_statements', {}) or {}
    statements_by_id = {int(s['id']): s for s in statements if 'id' in s}
    cluster_assignments = cluster_data.get('cluster_assignments', {})

    clusters: Dict = {}
    for _, cid in cluster_assignments.items():
        clusters.setdefault(cid, None)

    labels: Dict[int, Dict] = {}

    for cluster_id in clusters.keys():
        key_variants = (cluster_id, str(cluster_id))
        rep_entries = []
        for k in key_variants:
            if k in rep_by_cluster:
                rep_entries = rep_by_cluster[k]
                break
        # Attach content so the LLM sees the actual statements, not IDs.
        rep_with_content = []
        for e in rep_entries:
            sid = int(e.get('statement_id'))
            stmt = statements_by_id.get(sid)
            if stmt and stmt.get('content'):
                rep_with_content.append({'id': sid, 'content': stmt['content']})

        try:
            cid_int = int(cluster_id)
        except (TypeError, ValueError):
            cid_int = cluster_id  # leave non-int keys intact

        if not rep_with_content:
            # Nothing to ground a label on — return a generic fallback with
            # empty citations so the grounding check can mark it unverified.
            labels[cid_int] = {
                'label': f"Group {int(cluster_id) + 1}" if isinstance(cluster_id, (int, str)) and str(cluster_id).lstrip('-').isdigit() else str(cluster_id),
                'supporting_statement_ids': [],
            }
            continue

        numbered = "\n".join(f"[{r['id']}] {r['content']}" for r in rep_with_content)
        prompt = f"""You are labelling one opinion group in a civic discussion.

The group MOST STRONGLY AGREES WITH these statements (id in brackets):
{numbered}

Produce a short (2–4 word) descriptive label plus the IDs of statements that
best justify the label. Return ONLY valid JSON of this shape, no prose:

{{"label": "<2-4 words>", "supporting_statement_ids": [<int>, <int>]}}

Rules:
- supporting_statement_ids MUST be drawn from the bracketed IDs above.
- If you cannot ground the label in at least one statement, return
  {{"label": "Group", "supporting_statement_ids": []}}.
"""

        try:
            if user_key.provider == 'openai':
                raw = _generate_with_openai(api_key, prompt, model="gpt-4o-mini")
            elif user_key.provider == 'anthropic':
                raw = _generate_with_anthropic(api_key, prompt, model="claude-haiku-4-5-20251001")
            else:
                labels[cid_int] = {'label': f"Group {cid_int + 1}", 'supporting_statement_ids': []}
                continue

            parsed = _parse_label_json(raw)
            # Defence in depth: drop any supporting IDs not actually present
            # in the representative set.
            rep_ids = {r['id'] for r in rep_with_content}
            cited = [int(i) for i in (parsed.get('supporting_statement_ids') or []) if int(i) in rep_ids]
            label = (parsed.get('label') or '').strip() or f"Group {cid_int + 1}"
            labels[cid_int] = {'label': label, 'supporting_statement_ids': cited}

        except Exception as e:
            logger.error(f"Error generating label for cluster {cluster_id}: {e}")
            labels[cid_int] = {'label': f"Group {cid_int + 1}", 'supporting_statement_ids': []}

    return labels


def _parse_label_json(raw: str) -> Dict:
    """Extract the first JSON object from an LLM response, tolerating
    trailing whitespace, code fences, or preamble text."""
    import json
    import re
    if not raw:
        return {}
    text = raw.strip()
    # Strip ```json fences if present.
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


