export interface SetupStatusCheck {
  key: string;
  title: string;
  category: 'base' | 'ai_model' | 'agent' | 'notification' | 'system';
  required: boolean;
  status: 'configured' | 'inherited' | 'optional' | 'needs_action';
  message: string;
  nextStep?: string | null;
}

export interface SetupStatusResponse {
  isComplete: boolean;
  readyForSmoke: boolean;
  requiredMissingKeys: string[];
  nextStepKey?: string | null;
  checks: SetupStatusCheck[];
}
