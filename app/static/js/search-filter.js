/**
 * Search utilities for SocietySpeaks
 *
 * Two patterns supported:
 * 1. setupServerSearch() - For paginated pages (server-side search with optional auto-submit)
 * 2. createSearchFilter() - For pages where ALL data is loaded (client-side instant filter)
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
   * Setup server-side search with enhanced UX
   * Use this for paginated pages where you need to search ALL data
   *
   * Features:
   * - Clear button appears when input has value
   * - Escape key clears search
   * - Optional: auto-submit after debounce delay
   * - Optional: loading state while searching
   *
   * @param {Object} options Configuration options
   * @param {string} options.inputId - ID of the search input element
   * @param {string} [options.clearBtnId] - ID of the clear button (optional)
   * @param {boolean} [options.autoSubmit=false] - Auto-submit form after typing stops
   * @param {number} [options.debounceMs=400] - Debounce delay for auto-submit
   * @param {string} [options.loadingClass] - Class to add to form during submission
   */
  function setupServerSearch(options) {
    const {
      inputId,
      clearBtnId,
      autoSubmit = false,
      debounceMs = 400,
      loadingClass = 'opacity-70'
    } = options;

    const searchInput = document.getElementById(inputId);
    if (!searchInput) return null;

    const clearButton = clearBtnId ? document.getElementById(clearBtnId) : null;
    const form = searchInput.form;
    let lastValue = searchInput.value;

    // Update clear button visibility
    function updateClearButton() {
      if (clearButton) {
        clearButton.classList.toggle('hidden', !searchInput.value);
      }
    }

    // Clear the search
    function clearSearch(submit = true) {
      searchInput.value = '';
      updateClearButton();
      if (submit && form) {
        form.submit();
      }
    }

    // Submit the form with optional loading state
    function submitForm() {
      if (!form) return;
      if (loadingClass) {
        form.classList.add(loadingClass);
      }
      form.submit();
    }

    // Initial state
    updateClearButton();

    // Input event - update clear button, optionally auto-submit
    if (autoSubmit) {
      const debouncedSubmit = debounce(function() {
        if (searchInput.value !== lastValue) {
          lastValue = searchInput.value;
          submitForm();
        }
      }, debounceMs);

      searchInput.addEventListener('input', function() {
        updateClearButton();
        debouncedSubmit();
      });
    } else {
      searchInput.addEventListener('input', updateClearButton);
    }

    // Escape key - clear search
    searchInput.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && searchInput.value) {
        e.preventDefault();
        clearSearch(true);
      }
    });

    // Clear button - clear and submit
    if (clearButton) {
      clearButton.addEventListener('click', function() {
        clearSearch(true);
      });
    }

    return {
      clear: clearSearch,
      getValue: () => searchInput.value,
      submit: submitForm
    };
  }

  /**
   * Create a client-side search filter for items on the current page
   * Use this ONLY when all data is already loaded (not paginated)
   *
   * @param {Object} options Configuration options
   * @param {string} options.inputId - ID of the search input element
   * @param {string} options.itemSelector - CSS selector for filterable items
   * @param {Function} options.getSearchableText - Function that takes an element and returns searchable text
   * @param {string} [options.clearBtnId] - ID of the clear button (optional)
   * @param {string} [options.statusId] - ID of the status message element (optional)
   * @param {number} [options.debounceMs=200] - Debounce delay in milliseconds
   * @param {Object} [options.messages] - Custom status messages
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

    const defaultMessages = {
      noResults: 'No items match your search',
      showingResults: (visible, total) => `Showing ${visible} of ${total}`
    };
    const statusMessages = { ...defaultMessages, ...messages };

    const searchInput = document.getElementById(inputId);
    const clearButton = clearBtnId ? document.getElementById(clearBtnId) : null;
    const statusEl = statusId ? document.getElementById(statusId) : null;

    if (!searchInput) return null;

    const items = document.querySelectorAll(itemSelector);
    if (items.length === 0) return null;

    let currentQuery = '';

    function applyFilter() {
      const query = currentQuery;
      let visibleCount = 0;
      const totalCount = items.length;

      items.forEach(function(item) {
        const text = getSearchableText(item).toLowerCase();
        const matches = !query || text.includes(query);
        item.style.display = matches ? '' : 'none';
        if (matches) visibleCount++;
      });

      if (statusEl) {
        if (!query) {
          statusEl.classList.add('hidden');
          statusEl.textContent = '';
        } else {
          statusEl.classList.remove('hidden');
          statusEl.textContent = visibleCount === 0
            ? statusMessages.noResults
            : statusMessages.showingResults(visibleCount, totalCount);
        }
      }

      return { visibleCount, totalCount };
    }

    function updateClearButton() {
      if (clearButton) {
        clearButton.classList.toggle('hidden', !currentQuery);
      }
    }

    function clearSearch(refocus = false) {
      searchInput.value = '';
      currentQuery = '';
      updateClearButton();
      applyFilter();
      if (refocus) {
        searchInput.focus();
      } else {
        searchInput.blur();
      }
    }

    const debouncedFilter = debounce(applyFilter, debounceMs);

    searchInput.addEventListener('input', function(e) {
      currentQuery = (e.target.value || '').trim().toLowerCase();
      updateClearButton();
      debouncedFilter();
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

  /**
   * Setup search input that integrates with an existing filter system
   * Use this when you have your own filter logic and just need input handling
   *
   * @param {Object} options Configuration options
   * @param {string} options.inputId - ID of the search input element
   * @param {Function} options.onSearch - Callback when search query changes (receives query string)
   * @param {string} [options.clearBtnId] - ID of the clear button (optional)
   * @param {Function} [options.onClear] - Callback when cleared (optional, defaults to onSearch(''))
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
    if (!searchInput || typeof onSearch !== 'function') return null;

    const clearButton = clearBtnId ? document.getElementById(clearBtnId) : null;
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
      clear: clearSearch,
      getQuery: () => currentQuery,
      setQuery: (q) => {
        currentQuery = (q || '').trim().toLowerCase();
        searchInput.value = q || '';
        updateClearButton();
        onSearch(currentQuery);
      }
    };
  }

  // Expose to global scope
  window.setupServerSearch = setupServerSearch;
  window.setupSearchInput = setupSearchInput;
  window.createSearchFilter = createSearchFilter;
  window.SearchUtils = {
    setupServerSearch,
    setupSearchInput,
    createSearchFilter,
    debounce
  };

})(window);
