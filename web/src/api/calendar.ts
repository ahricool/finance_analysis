import apiClient from './index';
import { getDisplayTimezone } from '../utils/format';

export interface CalendarEntryItem {
  id: number;
  time: string;
  title: string;
  content: string | null;
  type: string | null;
  created_at: string;
  updated_at: string;
}

export interface CalendarEntryListResponse {
  date: string;
  items: CalendarEntryItem[];
  total: number;
}

export interface CalendarEntryCreate {
  time: string;
  title: string;
  content?: string | null;
  type?: string | null;
}

export interface FinanceEventItem {
  id: number;
  provider: string;
  provider_event_id: string | null;
  event_key: string;
  calendar_type: string;
  market: string;
  symbol: string | null;
  counter_name: string | null;
  event_type: string | null;
  activity_type: string | null;
  event_date: string;
  event_datetime: string | null;
  date_type: string | null;
  financial_market_time: string | null;
  title: string;
  content: string;
  star: number | null;
  currency: string | null;
  data_kv_json: string | null;
  importance_score: number | null;
  importance_reason: string | null;
  importance_confidence: number | null;
  importance_model: string | null;
  importance_prompt_version: string | null;
  importance_input_hash: string | null;
  importance_scored_at: string | null;
  first_seen_at: string;
  last_seen_at: string;
  notified_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface FinanceEventListResponse {
  date: string;
  items: FinanceEventItem[];
  total: number;
}

export interface FinanceEventCreate {
  calendar_type: string;
  market: string;
  symbol?: string | null;
  counter_name?: string | null;
  event_type?: string | null;
  activity_type?: string | null;
  event_date: string;
  event_datetime?: string | null;
  date_type?: string | null;
  financial_market_time?: string | null;
  title: string;
  content: string;
  star?: number | null;
  currency?: string | null;
}

export interface CalendarSummaryItem {
  date: string;
  finance_event_count: number;
  calendar_entry_count: number;
}

export interface CalendarSummaryResponse {
  start_date: string;
  end_date: string;
  items: CalendarSummaryItem[];
}

export const calendarApi = {
  async createEntry(payload: CalendarEntryCreate): Promise<CalendarEntryItem> {
    const res = await apiClient.post('/api/v1/calendar', payload);
    return res.data as CalendarEntryItem;
  },
  async createEvent(payload: FinanceEventCreate): Promise<FinanceEventItem> {
    const res = await apiClient.post('/api/v1/calendar/events', payload);
    return res.data as FinanceEventItem;
  },
  async listByDate(date: string): Promise<CalendarEntryListResponse> {
    const res = await apiClient.get('/api/v1/calendar', {
      params: { date, timezone: getDisplayTimezone() },
    });
    return res.data as CalendarEntryListResponse;
  },
  async listEventsByDate(date: string): Promise<FinanceEventListResponse> {
    const res = await apiClient.get('/api/v1/calendar/events', {
      params: { date, timezone: getDisplayTimezone() },
    });
    return res.data as FinanceEventListResponse;
  },
  async getSummary(startDate: string, endDate: string): Promise<CalendarSummaryResponse> {
    const res = await apiClient.get('/api/v1/calendar/summary', {
      params: { start_date: startDate, end_date: endDate, timezone: getDisplayTimezone() },
    });
    return res.data as CalendarSummaryResponse;
  },
};
