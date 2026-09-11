import { effectScope, ref } from 'vue';
import { describe, expect, it, vi } from 'vitest';
import { useLazyResearchPreview } from '../useLazyResearchPreview';

const status = (market = 'CN', previewTime = '2026-09-11T06:00:00Z') => ({
  market, previewTime, status: 'completed', tradeDate: '2026-09-11', dataAsOf: null,
  provider: 'yfinance', snapshotCount: 1, warnings: [],
});
const payload = (market = 'CN') => ({ ...status(market), snapshots: [{ code: `${market}-stock` }] });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
function setup() {
  const scope = effectScope();
  const market = ref('CN');
  const api = {
    previewStatus: vi.fn(async (market: string) => status(market)),
    preview: vi.fn(async (market: string): Promise<ReturnType<typeof payload> | null> => payload(market)),
  };
  const state = scope.run(() => useLazyResearchPreview(() => market.value, api))!;
  return { scope, market, api, ...state };
}

describe('lazy research preview', () => {
  it('refreshes only metadata, reuses unchanged payload and invalidates changed metadata', async () => {
    const s = setup();
    await s.refreshPreviewStatus();
    expect(s.api.preview).not.toHaveBeenCalled();
    await s.loadPreview();
    await s.loadPreview();
    await s.refreshPreviewStatus();
    await s.loadPreview();
    expect(s.api.preview).toHaveBeenCalledTimes(1);
    s.api.previewStatus.mockResolvedValueOnce(status('CN', '2026-09-11T07:00:00Z'));
    await s.refreshPreviewStatus();
    expect(s.previewPayload.value).toBeNull();
    expect(s.api.preview).toHaveBeenCalledTimes(1);
    await s.loadPreview();
    expect(s.api.preview).toHaveBeenCalledTimes(2);
    s.scope.stop();
  });

  it('deduplicates downloads and ignores the old market after reset', async () => {
    const s = setup();
    await s.refreshPreviewStatus();
    const pending = deferred<ReturnType<typeof payload>>();
    s.api.preview.mockReturnValueOnce(pending.promise);
    const first = s.loadPreview();
    const second = s.loadPreview();
    expect(s.previewLoading.value).toBe(true);
    expect(s.api.preview).toHaveBeenCalledTimes(1);
    s.market.value = 'US';
    s.resetPreview();
    await s.refreshPreviewStatus();
    await s.loadPreview();
    pending.resolve(payload('CN'));
    await Promise.all([first, second]);
    expect(s.previewPayload.value?.market).toBe('US');
    expect(s.previewLoading.value).toBe(false);
    s.scope.stop();
  });

  it('waits for refreshed status before downloading and cannot restore an outdated response', async () => {
    const s = setup();
    await s.refreshPreviewStatus();
    const old = deferred<ReturnType<typeof payload>>();
    s.api.preview.mockReturnValueOnce(old.promise);
    const oldDownload = s.loadPreview();
    const metadata = deferred<ReturnType<typeof status>>();
    s.api.previewStatus.mockReturnValueOnce(metadata.promise);
    const refresh = s.refreshPreviewStatus(true);
    const freshDownload = s.loadPreview();
    expect(s.api.preview).toHaveBeenCalledTimes(1);
    metadata.resolve(status('CN', '2026-09-11T07:00:00Z'));
    await refresh;
    await freshDownload;
    old.resolve({ ...payload(), snapshots: [{ code: 'outdated' }] });
    await oldDownload;
    expect(s.previewPayload.value?.snapshots[0]?.code).toBe('CN-stock');
    expect(s.api.preview).toHaveBeenCalledTimes(2);
    s.scope.stop();
  });

  it('handles expiration between status and payload and exposes recoverable download errors', async () => {
    const s = setup();
    await s.refreshPreviewStatus();
    s.api.preview.mockRejectedValueOnce(new Error('preview network failure'));
    await s.loadPreview();
    expect(s.previewError.value).not.toBeNull();
    expect(s.previewLoading.value).toBe(false);
    s.api.preview.mockResolvedValueOnce(null);
    await s.loadPreview();
    expect(s.previewStatus.value).toBeNull();
    expect(s.previewPayload.value).toBeNull();
    expect(s.previewError.value).toBeNull();
    s.scope.stop();
  });
});
