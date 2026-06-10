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

export const calendarApi = {
  async listByDate(date: string): Promise<CalendarEntryListResponse> {
    const res = await apiClient.get('/api/v1/calendar', {
      params: { date, timezone: getDisplayTimezone() },
    });
    return res.data as CalendarEntryListResponse;
  },
};
