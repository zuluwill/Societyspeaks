# pol.is Code Review & Analysis

**Date:** October 26, 2025  
**Reviewer:** AI Assistant (Phase 0 of Native Debate System Plan)  
**Repository:** https://github.com/compdemocracy/polis (AGPL-3.0)

## Executive Summary

pol.is is a mature, battle-tested platform for large-scale consensus finding. Their architecture centers around **vote-based user clustering** (not text clustering), using PCA for dimensionality reduction and k-means for grouping users by voting patterns. The system is built with **Clojure** for math/clustering, **Node.js/TypeScript** for the API server, and **PostgreSQL** for data storage.

**Key Insight:** pol.is clusters USERS based on how they vote, not STATEMENTS based on text content. This is fundamentally different from typical comment systems and is the source of their value proposition.

---

## 1. Architecture Overview

### System Components

```
┌─────────────────────────────────────────────────────────┐
│  Client (React/TypeScript)                              │
│  - client-participation: Voting interface              │
│  - client-report: Results visualization                 │
│  - client-admin: Conversation management                │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Server (Node.js/TypeScript)                            │
│  - REST API                                              │
│  - Authentication                                        │
│  - Comment/Vote endpoints                               │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Database (PostgreSQL)                                   │
│  - conversations, comments, votes tables                 │
│  - Stores raw voting data                                │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Math Engine (Clojure)                                   │
│  - Polls database for new votes                          │
│  - PCA dimensionality reduction                          │
│  - K-means clustering                                    │
│  - Stores results back to DB (math_main table)          │
└─────────────────────────────────────────────────────────┘
```

### Key Design Pattern: Polling + Conversation Manager

The math engine uses a **polling mechanism** that:
1. Queries the database at regular intervals for new votes
2. Routes data to a "conversation manager" (Clojure agent)
3. Queues updates so they're processed serially (prevents race conditions)
4. Runs clustering asynchronously when conversation is very active

This design handles high-velocity conversations where votes come in faster than clustering can complete.

---

## 2. Database Schema Analysis

### Core Tables

#### **conversations**
```sql
CREATE TABLE conversations(
    zid SERIAL PRIMARY KEY,  -- conversation id
    topic VARCHAR(1000),
    description VARCHAR(50000),
    owner INTEGER REFERENCES users(uid),
    participant_count INTEGER DEFAULT 0,
    is_anon BOOLEAN DEFAULT TRUE,
    strict_moderation BOOLEAN DEFAULT FALSE,
    ...
);
```

#### **comments** (aka "statements" in our terminology)
```sql
CREATE TABLE comments(
    tid INTEGER NOT NULL,  -- comment id (per-conversation auto-increment)
    zid INTEGER NOT NULL REFERENCES conversations(zid),
    pid INTEGER NOT NULL,  -- participant id
    uid INTEGER NOT NULL REFERENCES users(uid),
    txt VARCHAR(1000) NOT NULL,
    mod INTEGER NOT NULL DEFAULT 0,  -- moderation status
    active BOOLEAN NOT NULL DEFAULT TRUE,
    is_seed BOOLEAN NOT NULL DEFAULT false,
    created BIGINT DEFAULT now_as_millis(),
    UNIQUE(zid, txt),  -- No duplicate statements per conversation
    UNIQUE(zid, tid)
);
```

**Key insights:**
- `tid` is per-conversation auto-incremented (not global)
- `txt` limited to 1000 chars (we should use 500)
- UNIQUE constraint on `(zid, txt)` prevents duplicates
- `mod` field: -1 = reject, 0 = no action, 1 = accept
- `is_seed` flag for moderator-created seed comments

#### **votes** (THE CORE DATA FOR CLUSTERING)
```sql
CREATE TABLE votes(
    zid INTEGER NOT NULL,
    pid INTEGER NOT NULL,  -- participant id
    tid INTEGER NOT NULL,  -- comment id
    vote SMALLINT,  -- -1 (disagree), 0 (pass), 1 (agree)
    weight_x_32767 SMALLINT DEFAULT 0,  -- for weighting (-1.0 to 1.0)
    created BIGINT DEFAULT now_as_millis()
);

CREATE TABLE votes_latest_unique (
    -- Same fields but with UNIQUE (zid, pid, tid) constraint
    -- Updated via trigger when votes table is inserted
);
```

**Key insights:**
- Vote values: **-1 = disagree, 0 = pass, 1 = agree** (SMALLINT)
- Full history stored in `votes`, latest state in `votes_latest_unique`
- `weight_x_32767` allows soft weighting (divide by 32767 to get -1.0 to 1.0)
- Users can change their votes (all history preserved)
- NO UNIQUE constraint on votes table (allows history)

#### **participants**
```sql
CREATE TABLE participants(
    pid INTEGER NOT NULL,  -- per-conversation id
    uid INTEGER NOT NULL REFERENCES users(uid),
    zid INTEGER NOT NULL REFERENCES conversations(zid),
    vote_count INTEGER NOT NULL DEFAULT 0,
    last_interaction BIGINT NOT NULL DEFAULT 0,
    mod INTEGER NOT NULL DEFAULT 0,  -- moderation status for participant
    UNIQUE (zid, pid),
    UNIQUE (zid, uid)
);
```

**Key insights:**
- `pid` is per-conversation (like `tid`)
- Maps global `uid` to conversation-specific `pid`
- Tracks `vote_count` and `last_interaction` for engagement metrics

### Data Model Comparison

| pol.is | Society Speaks (Current Plan) | Notes |
|--------|-------------------------------|-------|
| `comments` (tid, txt) | `Statement` (id, content) | ✅ Aligned |
| `votes` (pid, tid, vote) | `StatementVote` (user_id, statement_id, vote_type) | ✅ Very similar |
| `votes_latest_unique` | Not planned | ⚠️ Consider adding for performance |
| Per-conversation `tid`/`pid` | Global `id` | ⚠️ Their approach scales better |
| `weight_x_32767` | `confidence` (1-5) | ⚠️ Their approach more flexible |

---

## 3. Clustering Algorithm Deep Dive

### Location: `/math/src/polismath/math/`

The clustering is implemented in **Clojure** (not Python as initially thought). Core files:

1. **`pca.clj`** - Principal Component Analysis
2. **`clusters.clj`** - K-means clustering implementation
3. **`conversation.clj`** - Orchestrates the full analysis pipeline

### Algorithm Flow

```clojure
;; Simplified from actual code

1. Build Vote Matrix
   ;; Matrix where rows = participants, cols = comments
   ;; Values: 1 (agree), -1 (disagree), 0 (pass), NaN (no vote)
   
2. Run PCA (dimensionality reduction)
   (powerit-pca vote-matrix n-comps)
   ;; Uses custom power iteration algorithm
   ;; Typically n-comps = 2 (for 2D visualization)
   
3. K-means Clustering
   (kmeans pca-projected-data k)
   ;; k typically 2-5 clusters
   ;; Uses cosine distance metric
   ;; Iterates until convergence or max-iters (20)
   
4. Find Consensus & Bridges
   ;; Consensus: statements with >70% agreement across ALL clusters
   ;; Bridges: statements with high agreement + low variance across clusters
   ;; Divisive: statements with ~50/50 splits
```

### Custom PCA Implementation

```clojure
;; From pca.clj
(defn power-iteration [data & [iters start-vector]]
  ;; Finds first eigenvector using power iteration
  ;; Default 100 iterations
  ;; Iteratively computes X^T * X * v until convergence
  )

(defn powerit-pca [data n-comps]
  ;; 1. Center the data (subtract mean)
  ;; 2. For each component:
  ;;    - Run power-iteration to find eigenvector
  ;;    - Factor out (remove) that component from data
  ;;    - Repeat for next component
  )
```

### K-means Implementation

```clojure
;; From clusters.clj
(defn kmeans [data k & {:keys [last-clusters max-iters weights]}]
  ;; 1. Initialize clusters (from last-clusters or random)
  ;; 2. For each iteration:
  ;;    - Assign each point to closest cluster (euclidean/cosine distance)
  ;;    - Recompute cluster centers (weighted mean)
  ;;    - Check convergence (are centers stable?)
  ;; 3. Return final clusters with {:id :members :center}
  )

(defn silhouette [distmat clusters]
  ;; Computes silhouette score to measure cluster quality
  ;; Score ranges from -1 (poor) to +1 (excellent)
  ;; Used to determine optimal k
  )
```

### Sparsity Handling

```clojure
;; From pca.clj - handles users who haven't voted on all comments
(defn sparsity-aware-project-ptpt [votes pca]
  ;; Only projects based on non-null votes
  ;; Scales projection by sqrt(n_comments / n_votes)
  ;; Pushes sparse voters away from center (less confident placement)
  )
```

---

## 4. Key Algorithmic Insights

### Why User Clustering (Not Text Clustering)?

pol.is's innovation is **finding opinion groups**, not topic groups:

- **Traditional approach**: Cluster comments by text similarity
- **pol.is approach**: Cluster USERS by voting pattern similarity

Example:
```
Conversation: "Should we raise minimum wage?"

Comment 1: "We should raise it to $15/hr"
Comment 2: "Small businesses can't afford that"
Comment 3: "Workers deserve living wages"

Traditional clustering: Group comments 1 & 3 together (similar text)
pol.is clustering: Group USERS who vote similarly across ALL comments

User A: Agrees with 1,3; Disagrees with 2 → "Pro-raise" cluster
User B: Disagrees with 1,3; Agrees with 2 → "Anti-raise" cluster
User C: Agrees with 1,2,3 → "Nuanced/bridge" position
```

### Consensus Detection

```clojure
;; Consensus statement: High agreement across ALL clusters
;; Pseudo-code from conversation.clj

(defn find-consensus-statements [vote-matrix clusters]
  (filter
    (fn [statement-id]
      (let [overall-agree-rate (compute-overall-agreement statement-id)
            cluster-agree-rates (map #(compute-cluster-agreement statement-id %) clusters)]
        (and
          (>= overall-agree-rate 0.70)  ; 70% overall agreement
          (every? #(>= % 0.60) cluster-agree-rates))))  ; 60% in EACH cluster
    all-statement-ids))
```

### Bridge Detection

```clojure
;; Bridge statement: High mean agreement + low variance across clusters

(defn find-bridge-statements [vote-matrix clusters]
  (filter
    (fn [statement-id]
      (let [cluster-agreements (map #(compute-cluster-agreement statement-id %) clusters)
            mean-agreement (mean cluster-agreements)
            variance (variance cluster-agreements)]
        (and
          (>= mean-agreement 0.65)  ; High average agreement
          (< variance 0.15))))  ; Low variance across clusters
    all-statement-ids))
```

---

## 5. Performance & Scaling

### Optimizations Used

1. **Per-conversation auto-increment** (`tid`, `pid`)
   - Faster lookups within a conversation
   - No global sequence contention

2. **Advisory locks** for comment/vote inserts
   - Prevents race conditions
   - Scoped to conversation level (not global lock)

3. **votes_latest_unique table**
   - Materialized view of current vote state
   - Updated via trigger on votes insert
   - Speeds up queries (no need for MAX(created) GROUP BY)

4. **Polling with backpressure**
   - Math engine polls database at intervals
   - Queues updates if previous clustering still running
   - Prevents system overload during high activity

5. **Caching of clustering results**
   - `math_main` table stores JSONB clustering data
   - `math_tick` tracks when last recomputed
   - Client can fetch cached results instead of recomputing

### Clustering Thresholds

From `conversation.clj`:
```clojure
:opts' (merge 
         {:n-comps 2           ; PCA components
          :pca-iters 100        ; PCA iterations
          :base-iters 100       ; K-means iterations
          :base-k 100           ; Max participants for base clustering
          :max-k 5              ; Max number of clusters
          :max-ptpts 100000     ; Max participants per conversation
          :max-cmts 10000       ; Max comments per conversation
          :group-k-buffer 4}    ; Buffer for group cluster count
         opts)
```

**Implications for Society Speaks:**
- They handle conversations with up to 100K participants and 10K comments
- Our initial limits should be more conservative (start with 10K participants, 1K statements)
- Clustering becomes expensive with large matrices; need background jobs

---

## 6. UX Patterns

### Progressive Disclosure

From observing client-participation:
- Shows **1-3 statements at a time** (not all at once)
- Prioritizes statements with fewer votes (ensures even coverage)
- Shuffles order to avoid bias

### Vote Interface

- **Three buttons**: Agree / Disagree / Pass
- Big touch targets for mobile
- Immediate visual feedback
- Vote can be changed (updates `votes` table)

### Moderation Flow

- **Strict moderation mode**: Comments hidden until approved (`mod = 1`)
- **Standard mode**: Comments visible unless rejected (`mod >= 0`)
- Moderators can:
  - Accept (`mod = 1`)
  - Reject (`mod = -1`)
  - Pin (`mod = 2`) - always show
  - Hide from visualization (`mod = -1` on participants table)

---

## 7. What We Can Reuse

### ✅ Directly Adaptable

1. **Data model patterns**
   - Votes table structure
   - Per-conversation ID scheme (tid, pid)
   - votes_latest_unique optimization
   - Moderation status fields

2. **Vote matrix construction**
   - User x Statement matrix
   - Values: 1 (agree), -1 (disagree), 0 (pass/unsure)
   - Handle sparse matrices (not all users vote on all statements)

3. **Clustering approach**
   - PCA for dimensionality reduction
   - K-means with cosine distance
   - Silhouette scoring for optimal k
   - Weighted means for cluster centers

4. **Consensus definitions**
   - Consensus: ≥70% overall AND ≥60% in each cluster
   - Bridge: High mean (≥65%) + low variance (<0.15)
   - Divisive: ~50/50 split (controversy score)

### ⚠️ Requires Translation (Clojure → Python)

Their math engine is in Clojure. We have two options:

**Option A: Reimplement in Python**
- Use `scikit-learn` for PCA and K-means
- Translate their sparsity handling logic
- Implement consensus/bridge detection ourselves
- **Pros**: Native Python, easier to maintain
- **Cons**: Need to validate against pol.is results

**Option B: Adapt their Clojure code**
- Run Clojure math engine as separate service
- Call it from Flask via HTTP/gRPC
- **Pros**: Proven algorithms, exact pol.is compatibility
- **Cons**: Another language/runtime to maintain

**Recommendation**: **Option A** (Python reimplementation)
- pol.is algorithms are well-documented in code
- Python ML ecosystem is mature (sklearn, numpy)
- Easier for contributors to understand/modify
- Can validate against their published results

### ❌ Don't Copy (Build Better)

1. **Client architecture** - We're using Flask/Jinja, not React
2. **Auth system** - We have our own (Flask-Login)
3. **Deployment** - They use Docker Compose; we use Replit
4. **Real-time updates** - They don't have WebSockets; we can do better

---

## 8. Python Implementation Strategy

### Clustering Engine (to build)

```python
# app/lib/consensus_engine.py

import numpy as np
from sklearn.decomposition import PCA
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import silhouette_score

def build_vote_matrix(discussion_id):
    """
    Build user x statement vote matrix
    Returns: pandas DataFrame or numpy array
    - Rows: users (pids)
    - Cols: statements (tids)
    - Values: 1 (agree), -1 (disagree), 0 (unsure), NaN (no vote)
    """
    # Query votes from database
    # Pivot into matrix format
    # Handle sparse data (NaN for missing votes)
    pass

def cluster_users_by_votes(discussion_id, k_range=(2, 5)):
    """
    Cluster users based on voting patterns (THE pol.is APPROACH)
    
    Returns:
    {
        'user_clusters': array of cluster assignments,
        'consensus': list of statement_ids with ≥70% overall + ≥60% each cluster,
        'bridges': list of statement_ids with high agreement + low variance,
        'divisive': list of statement_ids with ~50/50 splits,
        'silhouette': quality score,
        'n_clusters': optimal k chosen
    }
    """
    # 1. Build vote matrix
    vote_matrix = build_vote_matrix(discussion_id)
    
    # 2. Handle sparsity (like pol.is sparsity_aware_project_ptpts)
    # Fill NaN with 0 for PCA, but track sparsity for scaling
    vote_matrix_filled = vote_matrix.fillna(0)
    
    # 3. PCA dimensionality reduction
    pca = PCA(n_components=min(10, vote_matrix.shape[1]))
    reduced = pca.fit_transform(vote_matrix_filled)
    
    # 4. Find optimal k using silhouette scores
    best_k = 2
    best_score = -1
    for k in range(*k_range):
        clustering = AgglomerativeClustering(
            n_clusters=k,
            metric='cosine',
            linkage='average'
        )
        labels = clustering.fit_predict(reduced)
        score = silhouette_score(reduced, labels, metric='cosine')
        if score > best_score:
            best_k = k
            best_score = score
    
    # 5. Final clustering with best k
    clustering = AgglomerativeClustering(n_clusters=best_k, metric='cosine', linkage='average')
    user_clusters = clustering.fit_predict(reduced)
    
    # 6. Find consensus, bridges, divisive statements
    consensus = find_consensus_statements(vote_matrix, user_clusters)
    bridges = find_bridge_statements(vote_matrix, user_clusters)
    divisive = find_divisive_statements(vote_matrix)
    
    return {
        'user_clusters': user_clusters,
        'consensus': consensus,
        'bridges': bridges,
        'divisive': divisive,
        'silhouette': best_score,
        'n_clusters': best_k
    }

def find_consensus_statements(vote_matrix, user_clusters):
    """
    Consensus: ≥70% agree overall AND ≥60% agree in EACH cluster
    """
    consensus_statements = []
    for statement_id in vote_matrix.columns:
        votes = vote_matrix[statement_id].dropna()  # Exclude NaN (no votes)
        
        # Overall agreement rate
        agree_votes = (votes == 1).sum()
        total_votes = len(votes)
        overall_rate = agree_votes / total_votes if total_votes > 0 else 0
        
        if overall_rate < 0.70:
            continue  # Doesn't meet overall threshold
        
        # Check each cluster
        cluster_rates = []
        for cluster_id in np.unique(user_clusters):
            cluster_votes = votes[user_clusters == cluster_id]
            cluster_agree = (cluster_votes == 1).sum()
            cluster_total = len(cluster_votes)
            cluster_rate = cluster_agree / cluster_total if cluster_total > 0 else 0
            cluster_rates.append(cluster_rate)
        
        # Must have ≥60% in EACH cluster
        if all(rate >= 0.60 for rate in cluster_rates):
            consensus_statements.append(statement_id)
    
    return consensus_statements

def find_bridge_statements(vote_matrix, user_clusters):
    """
    Bridge: High mean agreement (≥65%) + low variance (<0.15) across clusters
    """
    bridge_statements = []
    for statement_id in vote_matrix.columns:
        votes = vote_matrix[statement_id].dropna()
        
        cluster_rates = []
        for cluster_id in np.unique(user_clusters):
            cluster_votes = votes[user_clusters == cluster_id]
            cluster_agree = (cluster_votes == 1).sum()
            cluster_total = len(cluster_votes)
            if cluster_total > 0:
                cluster_rates.append(cluster_agree / cluster_total)
        
        if len(cluster_rates) > 0:
            mean_rate = np.mean(cluster_rates)
            variance = np.var(cluster_rates)
            
            if mean_rate >= 0.65 and variance < 0.15:
                bridge_statements.append(statement_id)
    
    return bridge_statements

def find_divisive_statements(vote_matrix):
    """
    Divisive: Controversy score high = 1 - |agree_rate - 0.5| * 2
    (High score means close to 50/50 split)
    """
    divisive_statements = []
    for statement_id in vote_matrix.columns:
        votes = vote_matrix[statement_id].dropna()
        if len(votes) < 10:  # Skip if too few votes
            continue
        
        agree_votes = (votes == 1).sum()
        total_votes = len(votes)
        agree_rate = agree_votes / total_votes
        
        # Controversy score
        controversy = 1 - abs(agree_rate - 0.5) * 2
        
        if controversy >= 0.7:  # High controversy (close to 50/50)
            divisive_statements.append(statement_id)
    
    return divisive_statements
```

---

## 9. Recommendations for Society Speaks

### Phase 1: Data Model

**Adopt these patterns:**
1. ✅ `Statement` model with `tid` (per-discussion auto-increment)
2. ✅ `StatementVote` with vote values: -1 (disagree), 0 (unsure), 1 (agree)
3. ⚠️ **Consider**: `votes_latest_unique` table for performance
4. ⚠️ **Consider**: `weight` field for confidence weighting (instead of 1-5 scale)
5. ✅ `participant_count` on Discussion for quick stats

**Database indexes:**
```sql
CREATE INDEX statement_vote_discussion_user_idx ON statement_vote(discussion_id, user_id);
CREATE INDEX statement_vote_discussion_statement_idx ON statement_vote(discussion_id, statement_id);
```

### Phase 2: Clustering

**Use Python scikit-learn instead of Clojure:**
- `sklearn.decomposition.PCA` for dimensionality reduction
- `sklearn.cluster.AgglomerativeClustering` with cosine metric
- `sklearn.metrics.silhouette_score` for cluster quality

**Start simple:**
1. Require ≥10 users with ≥5 votes each before clustering
2. Try k in range (2, 5), pick best silhouette score
3. Store results in `ConsensusAnalysis` model (JSONB)
4. Recompute when discussion reaches +50 new votes

### Phase 3: UX

**Copy these patterns:**
1. ✅ Progressive disclosure (1-3 statements at a time)
2. ✅ Prioritize statements with fewer votes
3. ✅ Shuffle order to avoid bias
4. ✅ Big touch targets (Agree / Disagree / Skip buttons)
5. ✅ Allow vote changes (store history like pol.is)

### Phase 4: Background Processing

**Use APScheduler (not Celery):**
```python
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()

@scheduler.scheduled_job('interval', minutes=10)
def refresh_clustering():
    # Find discussions needing refresh
    # Run cluster_users_by_votes()
    # Store in ConsensusAnalysis table
    pass

scheduler.start()
```

### Phase 5: What We're Adding (Beyond pol.is)

These are our unique features:
1. ✅ **Threaded responses** - pol.is statements are flat
2. ✅ **Evidence linking** - pol.is has no citation system
3. ✅ **Pro/con structure** - pol.is just has agree/disagree votes
4. ✅ **LLM enhancements** - pol.is has no AI features
5. ✅ **Wilson scoring** - pol.is doesn't rank statements by quality

---

## 10. Dependencies to Add

Based on pol.is analysis, our refined dependency list:

```txt
# Existing (keep)
Flask==2.3.3
Flask-SQLAlchemy==3.0.5
psycopg2-binary==2.9.10
# ... other existing deps

# Add for clustering (Phase 3)
scikit-learn==1.4.0  # PCA, K-means, metrics
numpy==1.26.0  # Matrix operations
pandas==2.1.0  # DataFrame for vote matrix

# Add for background tasks (Phase 3)
APScheduler==3.10.4  # Background clustering jobs

# Add for Wilson score (Phase 1)
scipy==1.11.0  # stats.norm.ppf for Wilson score

# Add LATER if needed (defer for now)
# umap-learn==0.5.5  # Only if >500 users/discussion
# hdbscan==0.8.33  # Only if poor cluster quality
# plotly==5.18.0  # Only if server-side plots needed
```

**Start minimal, add later if proven necessary.**

---

## 11. AGPL-3.0 Compliance

Since pol.is is AGPL-3.0 and we're adapting their clustering approach:

### Required Actions

1. **Update footer:**
```html
<footer>
  Consensus clustering powered by algorithms adapted from
  <a href="https://github.com/compdemocracy/polis">pol.is</a> (AGPL-3.0)
</footer>
```

2. **Add copyright to clustering files:**
```python
# app/lib/consensus_engine.py
"""
Consensus clustering engine for Society Speaks.

Clustering algorithms adapted from pol.is:
https://github.com/compdemocracy/polis
Copyright (c) 2012-present, The Computational Democracy Project

Licensed under AGPL-3.0
"""
```

3. **Keep GitHub repo public** (already is)

4. **Document modifications** in this file and code comments

---

## 12. Next Steps

### Immediate (This Week)

1. ✅ Complete this analysis document
2. ⬜ Update plan based on findings
3. ⬜ Create refined database schema incorporating pol.is patterns
4. ⬜ Build Python clustering proof-of-concept

### Phase 1 (Weeks 2-4)

1. ⬜ Implement Statement/StatementVote models with pol.is patterns
2. ⬜ Build vote matrix construction
3. ⬜ Create basic clustering engine (PCA + K-means)
4. ⬜ Test with synthetic data (generate clustered voting patterns)

### Phase 2 (Weeks 5-8)

1. ⬜ Add consensus/bridge/divisive detection
2. ⬜ Build visualization (user opinion map)
3. ⬜ Implement background clustering with APScheduler
4. ⬜ Add caching (ConsensusAnalysis model)

---

## 13. Conclusion

pol.is is an excellent foundation to build upon. Their core innovation—**clustering users by voting patterns rather than clustering text**—is sound and battle-tested. By adapting their approach to Python/scikit-learn and adding our own enhancements (threading, evidence, LLMs), we can create a superior system that maintains pol.is's strengths while offering richer deliberation features.

**Key Takeaways:**
- ✅ Reuse their data model patterns (votes table, per-conversation IDs)
- ✅ Reimplement their clustering in Python (not Clojure)
- ✅ Adopt their consensus/bridge definitions (≥70%/≥60%, etc.)
- ✅ Use their UX patterns (progressive disclosure, 3-button voting)
- ✅ Add our unique features (threading, evidence, LLM, pro/con)
- ✅ Comply with AGPL-3.0 (attribution, open source)

**The plan is solid. Let's build it.**

