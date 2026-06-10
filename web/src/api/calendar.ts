import apiClient from './index';

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
    const res = await apiClient.get('/api/v1/calendar', { params: { time: date } });
    return res.data as CalendarEntryListResponse;
  },
};
