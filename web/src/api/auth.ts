import apiClient from './index';

export type AuthStatusResponse = {
  loggedIn: boolean;
  user?: {
    uid: number;
    username: string;
    email: string;
    avatarUrl: string | null;
    role: string;
    extra?: {
      gender: UserGender;
    };
  } | null;
};

export type UserGender = 'male' | 'female' | 'unknown';

export type NotificationSettings = {
  ntfy: Array<{ url: string }>;
  telegram: Array<{ bot_token: string; chat_id: string }>;
};

export type UserProfileResponse = NonNullable<AuthStatusResponse['user']> & {
  extra: {
    gender: UserGender;
    notification: NotificationSettings;
  };
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

  async getProfile(): Promise<UserProfileResponse> {
    const { data } = await apiClient.get<UserProfileResponse>('/api/v1/auth/profile');
    return data;
  },

  async updateProfile(payload: {
    username?: string;
    gender?: UserGender;
    notification?: NotificationSettings;
  }): Promise<UserProfileResponse> {
    const { data } = await apiClient.patch<UserProfileResponse>('/api/v1/auth/profile', payload);
    return data;
  },

  async uploadAvatar(file: File): Promise<AuthStatusResponse['user']> {
    const form = new FormData();
    form.append('file', file);
    const { data } = await apiClient.post<{ ok: boolean; user: AuthStatusResponse['user'] }>(
      '/api/v1/auth/avatar',
      form,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    );
    return data.user;
  },

  async logout(): Promise<void> {
    await apiClient.post('/api/v1/auth/logout');
  },
};
