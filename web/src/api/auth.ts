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

export type EmailLookupResponse = {
  ok: boolean;
  needsPasswordSetup: boolean;
};

export type LoginResponse = {
  ok: boolean;
  requiresRelogin?: boolean;
};

export const authApi = {
  async getStatus(): Promise<AuthStatusResponse> {
    const { data } = await apiClient.get<AuthStatusResponse>('/api/v1/auth/status');
    return data;
  },

  async lookupEmail(email: string): Promise<EmailLookupResponse> {
    const { data } = await apiClient.post<EmailLookupResponse>('/api/v1/auth/lookup', { email });
    return data;
  },

  async login(
    email: string,
    password: string,
    passwordConfirm?: string,
  ): Promise<LoginResponse> {
    const body: Record<string, string> = { email, password };
    if (passwordConfirm !== undefined) {
      body.passwordConfirm = passwordConfirm;
    }
    const { data } = await apiClient.post<LoginResponse>('/api/v1/auth/login', body);
    return data;
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
