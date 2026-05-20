import apiClient from './index';

export interface CalendarSignalItem {
  id: number;
  signal_date: string;
  title: string;
  content: string | null;
  signal_type: string | null;
  created_at: string;
  updated_at: string;
}

export interface CalendarSignalListResponse {
  date: string;
  items: CalendarSignalItem[];
  total: number;
}

export const calendarApi = {
  async listByDate(signalDate: string): Promise<CalendarSignalListResponse> {
    const res = await apiClient.get('/api/v1/calendar', { params: { signal_date: signalDate } });
    return res.data as CalendarSignalListResponse;
  },
};
