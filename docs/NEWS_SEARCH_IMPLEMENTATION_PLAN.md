# News Search & Filter Implementation Plan

**Date:** January 27, 2026  
**Status:** 📋 Planning  
**Priority:** High - Core feature for media transparency

---

## 🎯 **Goal**

Transform `/news` into a powerful search and comparison tool that allows users to:

1. **Search articles** by keywords, topics, publications
2. **Compare coverage** across the political spectrum for the same topic
3. **Filter by** media type, publication, date, geography, political leaning
4. **Discover patterns** in how different publications cover similar topics

---

## 📊 **Current State Analysis**

### **Existing `/news` Page:**

- ✅ Shows articles from last 24 hours
- ✅ Organized in 3 columns: Left, Center, Right (by source political leaning)
- ✅ Basic filters: leaning (all/left/center/right) and content type (all/news/podcast)
- ✅ Coverage balance visualization
- ❌ **No search functionality**
- ❌ **No keyword/topic filtering**
- ❌ **No publication multi-select**
- ❌ **No date range filtering**

### **Available Data:**

- **Articles:** `title`, `summary`, `url`, `published_at`, `source_id`, `geographic_scope`, `geographic_countries`, `sensationalism_score`, `relevance_score`
- **Sources:** `name`, `political_leaning` (-2 to +2), `country`, `source_type`, `source_category` (podcast/newspaper/magazine/broadcaster)
- **Topics:** Articles linked to `TrendingTopic` via `TrendingTopicArticle` with `canonical_tags`

---

## 🎨 **Best Practices for News Search**

### **1. Search Architecture**

#### **Client-Side Filtering (Recommended for Initial Implementation)**

- ✅ **Instant feedback** - no page reloads
- ✅ **Debounced input** (200-300ms) for performance
- ✅ **URL query params** for shareable/bookmarkable searches
- ✅ **Progressive enhancement** - works without JS, enhanced with JS
- ⚠️ **Limitation:** Only works on loaded articles (last 24 hours, ~500 max)

#### **Server-Side Search (Future Enhancement)**

- ✅ **Full-text search** across all articles (not just last 24h)
- ✅ **Database indexing** for performance
- ✅ **Pagination** for large result sets
- ⚠️ **Complexity:** Requires search backend (PostgreSQL full-text, Elasticsearch, or Algolia)

**Recommendation:** Start with **client-side filtering** for MVP, add server-side search later if needed.

---

### **2. Filter Types & UI**

#### **A. Text Search** 🔍

- **Input:** Single search box
- **Searches:** Article title, summary, source name
- **UI:** Large search bar at top, with clear button
- **Debounce:** 200ms
- **Placeholder:** "Search articles, topics, keywords..."

#### **B. Political Spectrum Filter** 🎨

- **Current:** Already exists (All/Left/Center/Right buttons)
- **Enhancement:**
  - Add visual spectrum slider (optional)
  - Show exact leaning values on hover
  - Multi-select capability (e.g., "Left + Center")

#### **C. Publication Filter** 📰

- **Type:** Multi-select dropdown (searchable with Choices.js)
- **Options:** All active sources (140+)
- **UI:**
  - "All Publications" (default)
  - Searchable dropdown with checkboxes
  - Show selected count badge
  - Filter chips showing selected publications

#### **D. Media Type Filter** 📺

- **Current:** Already exists (All Content/News Only/Podcasts Only)
- **Enhancement:**
  - Add more granular types: Newspaper, Magazine, Broadcaster, Podcast, Newsletter
  - Use `source_category` field

#### **E. Topic/Keyword Filter** 🏷️

- **Type:** Multi-select with autocomplete
- **Data Source:**
  - `TrendingTopic.canonical_tags` (e.g., ["uk", "nhs", "junior_doctors"])
  - Extract from article titles/summaries (simple keyword extraction)
- **UI:** Tag-style chips with autocomplete

#### **F. Date Range Filter** 📅

- **Type:** Date picker or preset buttons
- **Presets:**
  - Today (default)
  - Last 24 hours
  - Last 7 days
  - Last 30 days
  - Custom range
- **UI:** Dropdown with calendar picker

#### **G. Geographic Filter** 🌍

- **Type:** Multi-select dropdown
- **Options:** Countries from `geographic_countries` + "Global"
- **UI:** Searchable dropdown

#### **H. Quality Filters** ⭐

- **Sensationalism Score:** Slider (0-1, lower = less clickbait)
- **Relevance Score:** Slider (0-1, higher = more policy-relevant)
- **UI:** Optional advanced filters section (collapsible)

---

### **3. UI/UX Best Practices**

#### **Layout:**

```
┌─────────────────────────────────────────────────────────┐
│  [Search Bar: "Search articles, topics..."] [Clear]    │
├─────────────────────────────────────────────────────────┤
│  Filters:                                               │
│  [All] [Left] [Center] [Right]  [All Content ▼]        │
│  [All Publications ▼]  [Topics ▼]  [Date ▼]            │
│                                                          │
│  Active Filters: [BBC News] [UK] [×] [Politics] [×]   │
│                                                          │
│  Results: 47 articles (showing 1-20)                   │
├─────────────────────────────────────────────────────────┤
│  Left Column          Center Column      Right Column   │
│  ──────────          ────────────      ────────────   │
│  [Article cards...]   [Article cards...] [Article...]  │
└─────────────────────────────────────────────────────────┘
```

#### **Key UX Principles:**

1. **Real-time filtering** - No submit button needed
2. **Filter chips** - Show active filters as removable badges
3. **Clear all filters** button
4. **Results count** - "Showing X of Y articles"
5. **Empty state** - "No articles match your search. Try adjusting filters."
6. **Loading states** - Skeleton loaders if server-side search added
7. **Responsive design** - Mobile-friendly filter UI
8. **Keyboard navigation** - Accessible filter controls
9. **URL persistence** - Filters in query params for sharing
10. **Progressive disclosure** - Basic filters visible, advanced filters collapsible

---

### **4. Comparison Feature** 🔄

#### **Side-by-Side Comparison View:**

- **Toggle:** Switch between "Column View" (current) and "Comparison View"
- **Comparison View:**
  - Group articles by topic/keyword
  - Show same topic from different sources side-by-side
  - Highlight differences in framing/headlines
  - Show political leaning badges

#### **Topic Grouping:**

- Use `TrendingTopic` associations to group related articles
- Show topic title above grouped articles
- Allow expanding/collapsing topic groups

---

## 🛠️ **Implementation Plan**

### **Phase 1: Basic Search & Filters (MVP)** ⏱️ ~4-6 hours

**Priority:** High  
**Goal:** Add search and basic filters to existing page

#### **Tasks:**

1. ✅ **Text Search**
   - Add search input to filter bar
   - Client-side filtering on title, summary, source name
   - Debounced input (200ms)
   - Clear button

2. ✅ **Publication Multi-Select**
   - Add Choices.js multi-select dropdown
   - Filter articles by selected sources
   - Show selected count badge

3. ✅ **Enhanced Media Type Filter**
   - Expand to use `source_category` (newspaper/magazine/broadcaster/podcast)
   - Update filter logic

4. ✅ **Date Range Filter**
   - Add preset buttons (Today, 7 days, 30 days)
   - Filter articles by `published_at`

5. ✅ **Filter Chips & Clear All**
   - Show active filters as removable chips
   - "Clear all filters" button

6. ✅ **Results Count & Empty State**
   - Show "X articles found"
   - Empty state message when no results

**Files to Modify:**

- `app/news/routes.py` - Add filter params, expand date range
- `app/templates/news/dashboard.html` - Add search UI, filter controls
- `app/static/js/news-search.js` (new) - Client-side filtering logic

---

### **Phase 2: Advanced Filters** ⏱️ ~3-4 hours

**Priority:** Medium  
**Goal:** Add topic/keyword and geographic filters

#### **Tasks:**

1. ✅ **Topic/Keyword Filter**
   - Extract unique topics from `TrendingTopic.canonical_tags`
   - Multi-select dropdown with autocomplete
   - Filter articles by associated topics

2. ✅ **Geographic Filter**
   - Extract unique countries from `geographic_countries`
   - Multi-select dropdown
   - Filter by country or "Global"

3. ✅ **URL Query Params**
   - Persist filters in URL
   - Load filters from URL on page load
   - Shareable search URLs

**Files to Modify:**

- `app/news/routes.py` - Extract topics/countries, pass to template
- `app/templates/news/dashboard.html` - Add topic/geo filters
- `app/static/js/news-search.js` - URL param handling

---

### **Phase 3: Comparison View** ⏱️ ~4-5 hours

**Priority:** Medium  
**Goal:** Add topic grouping and comparison view

#### **Tasks:**

1. ✅ **Topic Grouping**
   - Group articles by `TrendingTopic`
   - Show topic title and description
   - Expand/collapse groups

2. ✅ **Comparison View Toggle**
   - Switch between column view and comparison view
   - Side-by-side article comparison
   - Highlight framing differences

**Files to Modify:**

- `app/news/routes.py` - Group articles by topic
- `app/templates/news/dashboard.html` - Add comparison view
- `app/static/js/news-search.js` - View toggle logic

---

### **Phase 4: Server-Side Search (Future)** ⏱️ ~8-10 hours

**Priority:** Low (Future Enhancement)  
**Goal:** Full-text search across all articles

#### **Tasks:**

1. ✅ **Backend Search Endpoint**
   - Create `/api/news/search` endpoint
   - Full-text search using PostgreSQL or Elasticsearch
   - Pagination support

2. ✅ **Search Indexing**
   - Index article titles, summaries
   - Index source names, topics
   - Update index on article fetch

3. ✅ **Hybrid Approach**
   - Client-side for instant feedback
   - Server-side for comprehensive results
   - Progressive enhancement

**Files to Create:**

- `app/news/search.py` - Search backend logic
- `app/api/news.py` - Search API endpoint

---

## 📋 **Technical Details**

### **Client-Side Filtering Implementation:**

```javascript
// Filter structure
const filters = {
  search: '',           // Text search query
  leaning: 'all',       // 'all', 'left', 'center', 'right'
  mediaType: 'all',     // 'all', 'news', 'podcast', 'newspaper', etc.
  publications: [],      // Array of source IDs
  topics: [],           // Array of topic keywords
  countries: [],        // Array of countries
  dateRange: '24h'      // 'today', '24h', '7d', '30d', 'custom'
};

// Article data attributes for filtering
<div class="article-card"
     data-title="..."
     data-summary="..."
     data-source-name="..."
     data-source-id="..."
     data-leaning="left"
     data-media-type="newspaper"
     data-topics="uk,nhs,politics"
     data-country="UK"
     data-published-at="2026-01-27T10:00:00">
```

### **Performance Considerations:**

1. **Debouncing:** 200ms for search input
2. **Virtual Scrolling:** If >100 articles, use virtual scrolling
3. **Lazy Loading:** Load images on scroll
4. **Caching:** Cache filter results in sessionStorage
5. **Indexing:** Use data attributes for fast filtering

---

## 🎯 **Success Metrics**

- ✅ Users can search articles by keyword
- ✅ Users can filter by publication and compare coverage
- ✅ Users can find articles by topic across political spectrum
- ✅ Search is fast (<100ms filter time)
- ✅ Filters are intuitive and discoverable
- ✅ URL sharing works for filtered views

---

## 🚀 **Next Steps**

1. **Review & Approve Plan** - Get feedback on approach
2. **Start Phase 1** - Implement basic search and filters
3. **Test & Iterate** - User testing on MVP
4. **Phase 2** - Add advanced filters
5. **Phase 3** - Add comparison view
6. **Phase 4** - Server-side search (if needed)

---

**Last Updated:** January 27, 2026
