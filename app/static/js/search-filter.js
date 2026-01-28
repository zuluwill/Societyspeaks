/**
 * Reusable client-side search filter utility
 * Creates real-time filtering for any list of items on the current page
 *
 * Usage (simple - standalone filter):
 *   createSearchFilter({
 *     inputId: 'my-search',
 *     itemSelector: '.my-card',
 *     getSearchableText: (el) => el.dataset.title + ' ' + el.dataset.description
 *   });
 *
 * Usage (advanced - integrate with existing filter system):
 *   setupSearchInput({
 *     inputId: 'my-search',
 *     clearBtnId: 'my-clear',
 *     onSearch: (query) => { currentSearch = query; applyAllFilters(); },
 *     onClear: () => { currentSearch = ''; applyAllFilters(); }
 *   });
 */

(function(window) {
  'use strict';

  /**
   * Simple debounce utility
   */
  function debounce(fn, delay) {
    let timeoutId;
    return function(...args) {
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      timeoutId = setTimeout(() => fn.apply(this, args), delay);
    };
  }

  /**
   * Setup search input with clear button and keyboard handling
   * Use this when you need to integrate search with an existing filter system
   *
   * @param {Object} options Configuration options
   * @param {string} options.inputId - ID of the search input element
   * @param {Function} options.onSearch - Callback when search query changes (receives query string)
   * @param {string} [options.clearBtnId] - ID of the clear button (optional)
   * @param {Function} [options.onClear] - Callback when search is cleared (optional, defaults to onSearch(''))
   * @param {number} [options.debounceMs=200] - Debounce delay in milliseconds
   */
  function setupSearchInput(options) {
    const {
      inputId,
      onSearch,
      clearBtnId,
      onClear,
      debounceMs = 200
    } = options;

    const searchInput = document.getElementById(inputId);
    const clearButton = clearBtnId ? document.getElementById(clearBtnId) : null;

    if (!searchInput || typeof onSearch !== 'function') {
      return null;
    }

    let currentQuery = '';

    function updateClearButton() {
      if (clearButton) {
        clearButton.classList.toggle('hidden', !currentQuery);
      }
    }

    function clearSearch(refocus = false) {
      searchInput.value = '';
      currentQuery = '';
      updateClearButton();
      if (typeof onClear === 'function') {
        onClear();
      } else {
        onSearch('');
      }
      if (refocus) {
        searchInput.focus();
      } else {
        searchInput.blur();
      }
    }

    const debouncedSearch = debounce(() => onSearch(currentQuery), debounceMs);

    searchInput.addEventListener('input', function(e) {
      currentQuery = (e.target.value || '').trim().toLowerCase();
      updateClearButton();
      debouncedSearch();
    });

    searchInput.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && currentQuery) {
        e.preventDefault();
        clearSearch(false);
      }
    });

    if (clearButton) {
      clearButton.addEventListener('click', function() {
        clearSearch(true);
      });
    }

    return {
      clearSearch,
      getQuery: () => currentQuery,
      setQuery: (q) => {
        currentQuery = (q || '').trim().toLowerCase();
        searchInput.value = q || '';
        updateClearButton();
        onSearch(currentQuery);
      }
    };
  }

  /**
   * Create a search filter for a set of items
   *
   * @param {Object} options Configuration options
   * @param {string} options.inputId - ID of the search input element
   * @param {string} options.itemSelector - CSS selector for filterable items
   * @param {Function} options.getSearchableText - Function that takes an element and returns searchable text
   * @param {string} [options.clearBtnId] - ID of the clear button (optional)
   * @param {string} [options.statusId] - ID of the status message element (optional)
   * @param {number} [options.debounceMs=200] - Debounce delay in milliseconds
   * @param {Object} [options.messages] - Custom status messages
   * @param {string} [options.messages.noResults] - Message when no results match
   * @param {Function} [options.messages.showingResults] - Function(visible, total) returning status text
   */
  function createSearchFilter(options) {
    const {
      inputId,
      itemSelector,
      getSearchableText,
      clearBtnId,
      statusId,
      debounceMs = 200,
      messages = {}
    } = options;

    // Default messages
    const defaultMessages = {
      noResults: 'No items match your search on this page',
      showingResults: (visible, total) => `Showing ${visible} of ${total} on this page`
    };
    const statusMessages = { ...defaultMessages, ...messages };

    // Get DOM elements
    const searchInput = document.getElementById(inputId);
    const clearButton = clearBtnId ? document.getElementById(clearBtnId) : null;
    const statusEl = statusId ? document.getElementById(statusId) : null;

    // Exit early if no search input or no items
    if (!searchInput) {
      return null;
    }

    const items = document.querySelectorAll(itemSelector);
    if (items.length === 0) {
      return null;
    }

    let currentQuery = '';

    /**
     * Apply the filter to all items
     */
    function applyFilter() {
      const query = currentQuery;
      let visibleCount = 0;
      const totalCount = items.length;

      items.forEach(function(item) {
        const text = getSearchableText(item).toLowerCase();
        const matches = !query || text.includes(query);

        // Use empty string to restore CSS default (works with grid/flex)
        item.style.display = matches ? '' : 'none';

        if (matches) {
          visibleCount++;
        }
      });

      // Update status message
      if (statusEl) {
        if (!query) {
          statusEl.classList.add('hidden');
          statusEl.textContent = '';
        } else {
          statusEl.classList.remove('hidden');
          if (visibleCount === 0 && totalCount > 0) {
            statusEl.textContent = statusMessages.noResults;
          } else {
            statusEl.textContent = statusMessages.showingResults(visibleCount, totalCount);
          }
        }
      }

      return { visibleCount, totalCount };
    }

    /**
     * Clear the search
     */
    function clearSearch(refocus = false) {
      searchInput.value = '';
      currentQuery = '';
      if (clearButton) {
        clearButton.classList.add('hidden');
      }
      applyFilter();
      if (refocus) {
        searchInput.focus();
      } else {
        searchInput.blur();
      }
    }

    /**
     * Update clear button visibility
     */
    function updateClearButton() {
      if (clearButton) {
        if (currentQuery) {
          clearButton.classList.remove('hidden');
        } else {
          clearButton.classList.add('hidden');
        }
      }
    }

    // Create debounced filter function
    const debouncedFilter = debounce(applyFilter, debounceMs);

    // Input event - filter as user types
    searchInput.addEventListener('input', function(e) {
      currentQuery = (e.target.value || '').trim().toLowerCase();
      updateClearButton();
      debouncedFilter();
    });

    // Escape key - clear search
    searchInput.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && currentQuery) {
        e.preventDefault();
        clearSearch(false);
      }
    });

    // Clear button click
    if (clearButton) {
      clearButton.addEventListener('click', function() {
        clearSearch(true);
      });
    }

    // Return API for programmatic control
    return {
      applyFilter,
      clearSearch,
      getQuery: () => currentQuery,
      setQuery: (q) => {
        currentQuery = (q || '').trim().toLowerCase();
        searchInput.value = q || '';
        updateClearButton();
        applyFilter();
      }
    };
  }

  // Expose to global scope
  window.createSearchFilter = createSearchFilter;
  window.setupSearchInput = setupSearchInput;
  window.SearchFilter = {
    create: createSearchFilter,
    setupInput: setupSearchInput,
    debounce
  };

})(window);
