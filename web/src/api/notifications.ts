import apiClient from './index';
import { toCamelCase } from './utils';

export interface NotificationPreview {
  id: number;
  uid: number | null;
  title: string;
  contentPreview: string;
  routeType: string;
  severity: string;
  createdAt: string;
}
export interface NotificationDetail extends Omit<NotificationPreview, 'uid' | 'contentPreview'> {
  content: string;
}
export interface NotificationQuery {
  page?: number;
  page_size?: number;
  keyword?: string;
  route_type?: string;
  severity?: string;
  start_time?: string;
  end_time?: string;
}
export interface NotificationList {
  items: NotificationPreview[];
  total: number;
  page: number;
  pageSize: number;
}
export const notificationsApi = {
  async list(params: NotificationQuery = {}) {
    const { data } = await apiClient.get('/api/v1/notifications', { params });
    return toCamelCase<NotificationList>(data);
  },
  async detail(id: number) {
    const { data } = await apiClient.get(`/api/v1/notifications/${id}`);
    return toCamelCase<NotificationDetail>(data);
  },
};
