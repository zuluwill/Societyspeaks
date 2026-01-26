# Protecting Paid Features in an Open Source Repository

## Current Situation

- **License**: AGPL-3.0 (very permissive - allows copying, modification, commercial use)
- **Paid Product**: Custom briefing system (multi-tenant briefs with sources, recipients, scheduling)
- **Open Source Goal**: Keep core platform open, protect paid briefing features
- **Challenge**: With AGPL, anyone can copy the entire codebase including paid features

---

## Common Strategies (Ranked by Practicality)

### ✅ **Strategy 1: Separate Repositories (RECOMMENDED)**

**How it works:**
- **Public repo**: Core platform (discussions, profiles, daily brief, etc.) - fully open source
- **Private repo**: Premium briefing features - closed source
- Premium features are loaded as plugins/modules at runtime

**Implementation:**
```python
# In public repo
try:
    from briefing_premium import premium_features
    PREMIUM_ENABLED = True
except ImportError:
    PREMIUM_ENABLED = False
    premium_features = None

# Routes check for premium
@briefing_bp.route('/create')
def create_briefing():
    if not PREMIUM_ENABLED:
        return redirect(url_for('briefing.landing'))
    # Premium code here
```

**Pros:**
- ✅ Clean separation
- ✅ Core platform stays fully open
- ✅ Easy to maintain
- ✅ Can license premium separately (commercial license)

**Cons:**
- ⚠️ Requires refactoring to extract premium code
- ⚠️ Need to manage two repos

**Best for:** Your situation - you want most code open, protect specific features

---

### ✅ **Strategy 2: Dual Licensing**

**How it works:**
- Keep AGPL-3.0 for open source version
- Offer commercial license for premium features
- Premium features are in the same repo but require commercial license to use

**Implementation:**
```python
# LICENSE file
"""
Core Platform: AGPL-3.0
Briefing Premium Features: Commercial License Required
Contact: licensing@societyspeaks.io
"""

# In code
if not has_commercial_license():
    return render_template('upgrade_required.html')
```

**Pros:**
- ✅ Single codebase
- ✅ Legal protection via licensing
- ✅ Common in open source (MySQL, MongoDB, etc.)

**Cons:**
- ⚠️ Hard to enforce (people can ignore license)
- ⚠️ Legal complexity
- ⚠️ Doesn't prevent copying code, just use

**Best for:** When you have legal resources and want single repo

---

### ✅ **Strategy 3: Service/API Separation**

**How it works:**
- Open source: Frontend + basic features
- Closed service: Premium briefing API/service
- Premium features call external API (your hosted service)

**Implementation:**
```python
# Open source code
def create_briefing():
    if plan.is_premium:
        # Call your hosted API
        response = requests.post(
            'https://api.societyspeaks.io/v1/briefings',
            headers={'Authorization': f'Bearer {api_key}'}
        )
    else:
        # Basic features only
        pass
```

**Pros:**
- ✅ Premium logic never in open source
- ✅ Can update premium features without open source changes
- ✅ Forces users to use your service for premium

**Cons:**
- ⚠️ Requires separate service infrastructure
- ⚠️ More complex architecture
- ⚠️ Users can't self-host premium features

**Best for:** When premium features require your infrastructure (AI, data processing)

---

### ⚠️ **Strategy 4: Feature Flags + Environment Variables**

**How it works:**
- Premium code is in repo but disabled by default
- Requires specific environment variables/secrets to enable
- Document that premium features require commercial license

**Implementation:**
```python
# .env.example (public)
PREMIUM_FEATURES_ENABLED=false

# In code
if not os.getenv('PREMIUM_FEATURES_ENABLED') == 'true':
    return redirect(url_for('briefing.landing'))
```

**Pros:**
- ✅ Single repo
- ✅ Easy to implement

**Cons:**
- ❌ **Doesn't actually protect** - code is visible, can be enabled
- ❌ People can just set the env var
- ❌ Not a real protection strategy

**Best for:** Not recommended for actual protection

---

### ✅ **Strategy 5: SaaS Model (What You're Doing Now)**

**How it works:**
- Code is open source (AGPL)
- But you provide the hosted service
- Users pay for your hosted instance, not the code

**Pros:**
- ✅ Code can be fully open
- ✅ Revenue from service, not code
- ✅ Users get updates, support, hosting

**Cons:**
- ⚠️ Competitors can copy and host their own
- ⚠️ Need to compete on service quality, not just code

**Best for:** When service quality is your differentiator

---

## 🎯 **Recommended Approach for Your Situation**

### **Hybrid: Separate Repos + SaaS Model**

1. **Public Repo** (`Societyspeaks` - current repo):
   - Core platform (discussions, profiles, daily brief)
   - Basic briefing features (maybe 1 brief, limited sources)
   - AGPL-3.0 license
   - Fully open source

2. **Private Repo** (`Societyspeaks-Premium`):
   - Premium briefing features (multi-tenant, unlimited briefs, advanced features)
   - Commercial license
   - Loaded as optional module

3. **Your Hosted Service**:
   - Runs both public + premium code
   - Users pay for your hosted instance
   - Premium features require subscription

### **Implementation Steps**

#### Step 1: Refactor to Extract Premium Code

```python
# app/briefing/__init__.py (public repo)
from flask import Blueprint

briefing_bp = Blueprint('briefing', __name__, url_prefix='/briefings')

# Load premium features if available
try:
    from briefing_premium import register_premium_routes
    register_premium_routes(briefing_bp)
    PREMIUM_AVAILABLE = True
except ImportError:
    PREMIUM_AVAILABLE = False

from .routes import *  # Basic routes
```

#### Step 2: Create Premium Module Structure

```
briefing_premium/
├── __init__.py
├── routes.py          # Premium routes
├── models.py          # Premium models (if separate)
├── services.py        # Premium business logic
└── templates/         # Premium templates
```

#### Step 3: Update License

```markdown
# LICENSE (public repo)
Core Platform: AGPL-3.0

Premium Briefing Features: Available under commercial license.
Contact: licensing@societyspeaks.io

Self-hosting with premium features requires commercial license.
```

#### Step 4: Update README

```markdown
## Open Source vs Premium

This repository contains the core SocietySpeaks platform, licensed under AGPL-3.0.

**Premium Briefing Features** (multi-tenant briefs, unlimited sources, etc.) are available:
- Via our hosted service: https://societyspeaks.io (subscription required)
- For self-hosting: Commercial license required (contact us)

See [LICENSING.md](LICENSING.md) for details.
```

---

## 🛡️ **Additional Protection Strategies**

### 1. **Trademark Protection**
- Trademark "SocietySpeaks" and "Briefing" branding
- Prevents competitors from using your name
- Doesn't protect code, but protects brand

### 2. **Terms of Service**
- Hosted service ToS can restrict commercial use
- Can't prevent self-hosting, but can restrict competitive use
- Legal protection for your hosted service

### 3. **Competitive Advantages (Beyond Code)**
- **Data/Content**: Your curated sources, analysis
- **Service Quality**: Reliability, support, updates
- **Network Effects**: User base, discussions, community
- **Brand Trust**: Reputation, testimonials

### 4. **Monitoring & Enforcement**
- Monitor GitHub for forks using premium features
- Send DMCA takedowns if commercial license violated
- Legal action for commercial use without license

---

## 📊 **Real-World Examples**

### **GitLab** (Similar Model)
- **Open Source**: Core platform (MIT)
- **Premium**: Enterprise features (commercial license)
- **Strategy**: Separate tiers, same repo, different licensing

### **MongoDB**
- **Open Source**: Community edition (SSPL - similar to AGPL)
- **Premium**: Enterprise features (commercial)
- **Strategy**: Dual licensing

### **WordPress**
- **Open Source**: Core (GPL)
- **Premium**: Plugins/themes (various licenses)
- **Strategy**: Core open, ecosystem monetized

### **Supabase**
- **Open Source**: Core platform (Apache 2.0)
- **Premium**: Hosted service, enterprise features
- **Strategy**: Open code, paid service

---

## ⚖️ **Legal Considerations**

1. **AGPL-3.0 Requirements**:
   - If you modify AGPL code, you must share modifications
   - If you use AGPL code in a service, you must share source
   - Premium features in separate module can have different license

2. **Commercial License**:
   - Can restrict commercial use
   - Can require payment for commercial deployment
   - Can restrict redistribution

3. **Enforcement**:
   - Hard to enforce against individuals
   - Easier to enforce against companies
   - DMCA for clear violations

---

## 🎯 **My Recommendation**

**For your situation, I recommend:**

1. **Short-term** (Now):
   - Keep current setup (AGPL, all code open)
   - Focus on service quality and user acquisition
   - Don't worry about copying yet (you're early stage)

2. **Medium-term** (6-12 months):
   - Extract premium briefing features to separate module
   - Move premium module to private repo
   - Update public repo to load premium as optional dependency
   - Add commercial licensing for premium

3. **Long-term** (12+ months):
   - If copying becomes a problem, consider:
     - Service/API separation for premium features
     - Stronger legal protections
     - Focus on competitive advantages beyond code

**Remember**: Most successful open source companies make money from:
- **Service** (hosting, support) - 70%
- **Enterprise features** (commercial license) - 20%
- **Consulting** - 10%

Code protection is less important than service quality and user trust.

---

## 📝 **Action Items**

1. ✅ Document current licensing strategy
2. ⏳ Plan refactoring to extract premium features
3. ⏳ Set up private repo for premium module
4. ⏳ Update LICENSE and README with dual licensing
5. ⏳ Consider trademark registration
6. ⏳ Focus on service quality and user acquisition

---

## Questions to Consider

1. **How much revenue comes from self-hosted vs hosted?**
   - If mostly hosted, code protection less critical

2. **Are competitors actually copying?**
   - If not, don't over-engineer protection

3. **What's your competitive moat?**
   - Code? Service? Data? Brand?
   - Protect what matters most

4. **Legal budget?**
   - Commercial licensing requires legal review
   - Enforcement requires resources

---

**Bottom line**: Start simple, focus on product-market fit. Add protection as you scale and if copying becomes a real problem. Most open source companies succeed through service quality, not code protection.
