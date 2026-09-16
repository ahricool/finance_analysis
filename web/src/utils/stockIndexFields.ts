/**
 * Search configuration
 */
export const SEARCH_CONFIG = {
  DEFAULT_LIMIT: 10,      // Default number of results to return
  DEBOUNCE_MS: 200,       // Debounce delay (milliseconds)
  MIN_QUERY_LENGTH: 2,    // Minimum query length
} as const;
