import { beforeEach, describe, expect, it, vi } from 'vitest';
import { systemConfigApi } from '../systemConfig';

const get = vi.hoisted(() => vi.fn());

vi.mock('../index', () => ({
  default: {
    get,
  },
}));

describe('systemConfigApi', () => {
  beforeEach(() => {
    get.mockReset();
  });

  it('loads first-run setup status with camelCase fields', async () => {
    get.mockResolvedValueOnce({
      data: {
        is_complete: false,
        ready_for_smoke: false,
        required_missing_keys: ['llm_primary'],
        next_step_key: 'llm_primary',
        checks: [
          {
            key: 'llm_primary',
            title: 'LLM 主渠道',
            category: 'ai_model',
            required: true,
            status: 'needs_action',
            message: '缺少主模型配置',
            next_step: '打开系统设置',
          },
        ],
      },
    });

    const result = await systemConfigApi.getSetupStatus();

    expect(get).toHaveBeenCalledWith('/api/v1/system/config/setup/status');
    expect(result.isComplete).toBe(false);
    expect(result.nextStepKey).toBe('llm_primary');
    expect(result.checks[0].nextStep).toBe('打开系统设置');
  });
});
