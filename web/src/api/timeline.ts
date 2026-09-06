import apiClient from './index';
import { toCamelCase } from './utils';
import { getDisplayTimezone } from '@/utils/format';

export type Importance = 'low' | 'normal' | 'high' | 'critical';
export type Actionability = 'none' | 'watch' | 'consider' | 'action_required';
export type Category = 'event' | 'news' | 'analysis' | 'note';
export interface TimelineItem {
  id: string; sourceType: 'finance_event' | 'news' | 'report' | 'note'; sourceId: number;
  eventTime: string; category: Category; market: string | null; title: string; summary: string;
  symbol: string | null; relatedSymbols: string[]; importance: Importance; actionability: Actionability;
  impact: string | null; impactScore: number | null; importanceScore: number | null;
  eventType: string | null; detailType: string; detailPayload: Record<string, unknown>;
}
export interface TimelineQuery {
  date?: string; start_date?: string; end_date?: string;
  market?: string; category?: Category; importance?: Importance; actionability?: Actionability;
  cursor?: string; limit?: number;
}
export interface TimelineSummary {
  date: string; total: number; critical: number; high: number;
  eventCount: number; newsCount: number; analysisCount: number; noteCount: number;
}
export interface NoteInput {
  event_time: string; title: string; summary: string; content: string; market: 'CN' | 'US' | null;
  importance: Importance; actionability: Actionability; related_symbols: string[];
}
export const timelineApi = {
  async list(query: TimelineQuery) {
    const { data } = await apiClient.get('/api/v1/timeline', { params: { ...query, timezone: getDisplayTimezone() } });
    return toCamelCase<{ items: TimelineItem[]; total: number; nextCursor: string | null; hasMore: boolean; limit: number }>(data);
  },
  async summary(query: TimelineQuery) {
    const { data } = await apiClient.get('/api/v1/timeline/summary', { params: { ...query, timezone: getDisplayTimezone() } });
    return toCamelCase<TimelineSummary[]>(data);
  },
  async saveNote(note: NoteInput, id?: number) {
    if (id !== undefined) await apiClient.put(`/api/v1/timeline/notes/${id}`, note);
    else await apiClient.post('/api/v1/timeline/notes', note);
  },
  async deleteNote(id: number) { await apiClient.delete(`/api/v1/timeline/notes/${id}`); },
};
