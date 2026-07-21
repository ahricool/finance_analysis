import apiClient from '../index';
import { quantApi } from '../quant';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../index', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

describe('quant API market scope', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        trade_date: null,
        market: 'CN',
        universe: 'cn_csi300',
        market_regime: null,
        max_equity_exposure: null,
        items: [],
      },
    });
  });

  it('selects signal ranking by market without exposing a universe selector', async () => {
    await quantApi.signals('CN');

    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/quant/signals/ranking', {
      params: { market: 'CN' },
    });
  });

  it('serializes dataset and model training requests with backend field names', async () => {
    vi.mocked(apiClient.post)
      .mockResolvedValueOnce({ data: { task_id: 'dataset-task', status: 'pending', market: 'CN', universe: 'cn_csi300' } })
      .mockResolvedValueOnce({ data: { model_run_id: 19, task_id: 'training-task', status: 'draft', market: 'CN' } });

    const dataset = await quantApi.buildDataset('CN', '2021-01-01', '2026-07-21');
    const training = await quantApi.createModelRun({
      market: 'CN',
      modelKey: 'cross_section_lgbm',
      modelVersion: 'cn-cross-section-20260721',
      datasetSnapshotId: 8,
    });

    expect(apiClient.post).toHaveBeenNthCalledWith(1, '/api/v1/quant/datasets/build', {
      market: 'CN',
      date_from: '2021-01-01',
      date_to: '2026-07-21',
    });
    expect(apiClient.post).toHaveBeenNthCalledWith(2, '/api/v1/quant/model-runs', {
      market: 'CN',
      model_key: 'cross_section_lgbm',
      model_version: 'cn-cross-section-20260721',
      dataset_snapshot_id: 8,
    });
    expect(dataset.taskId).toBe('dataset-task');
    expect(training.modelRunId).toBe(19);
  });
});
