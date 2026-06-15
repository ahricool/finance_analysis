import apiClient from './index';
import { toCamelCase } from './utils';
import type { SetupStatusResponse } from '../types/systemConfig';

export const systemConfigApi = {
  async getSetupStatus(): Promise<SetupStatusResponse> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/system/config/setup/status');
    return toCamelCase<SetupStatusResponse>(response.data);
  },
};
