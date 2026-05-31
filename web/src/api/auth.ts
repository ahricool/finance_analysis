import apiClient from './index';

export type AuthStatusResponse = {
  authEnabled: boolean;
  loggedIn: boolean;
  passwordChangeable?: boolean;
  setupState: 'enabled';
  user?: {
    uid: string;
    username: string;
    email: string;
    avatarUrl: string | null;
    role: string;
  } | null;
};

export const authApi = {
  async getStatus(): Promise<AuthStatusResponse> {
    const { data } = await apiClient.get<AuthStatusResponse>('/api/v1/auth/status');
    return data;
  },

  async login(password: string, email: string): Promise<void> {
    await apiClient.post('/api/v1/auth/login', { email, password });
  },

  async changePassword(
    currentPassword: string,
    newPassword: string,
    newPasswordConfirm: string
  ): Promise<void> {
    await apiClient.post('/api/v1/auth/change-password', {
      currentPassword,
      newPassword,
      newPasswordConfirm,
    });
  },

  async logout(): Promise<void> {
    await apiClient.post('/api/v1/auth/logout');
  },
};
