import axios from 'axios';
import { API_BASE_URL } from '../utils/constants';
import { attachParsedApiError } from './error';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 60000,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Concurrent requests that all expire together must trigger only one full-page redirect;
// the reload itself discards every in-memory store.
let redirectingToLogin = false;

export function redirectToLogin() {
  if (redirectingToLogin) return;
  const path = window.location.pathname + window.location.search;
  if (path.startsWith('/login')) return;
  redirectingToLogin = true;
  window.location.assign(`/login?redirect=${encodeURIComponent(path)}`);
}

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) redirectToLogin();
    attachParsedApiError(error);
    return Promise.reject(error);
  }
);

export default apiClient;
