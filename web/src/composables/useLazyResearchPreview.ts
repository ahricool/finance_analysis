import { onScopeDispose, ref, shallowRef } from 'vue';
import { getParsedApiError, type ParsedApiError } from '@/api/error';

interface PreviewIdentity {
  market: string;
  status: string;
  tradeDate: string;
  previewTime: string | null;
  dataAsOf: string | null;
  provider?: string | null;
  snapshotCount?: number;
  warnings?: string[];
}

function identity(value: PreviewIdentity | null) {
  return value ? JSON.stringify([value.market, value.status, value.tradeDate, value.previewTime, value.dataAsOf,
    value.provider, value.snapshotCount, value.warnings]) : '';
}

/** Independently cache metadata and lazily downloaded rows for the current market. */
export function useLazyResearchPreview<Market extends string, Status extends PreviewIdentity, Payload extends PreviewIdentity>(
  market: () => Market,
  api: { previewStatus: (market: Market) => Promise<Status | null>; preview: (market: Market) => Promise<Payload | null> },
) {
  const previewStatus = shallowRef<Status | null>(null);
  const previewPayload = shallowRef<Payload | null>(null);
  const previewLoading = ref(false);
  const previewError = shallowRef<ParsedApiError | null>(null);
  let statusGeneration = 0;
  let payloadGeneration = 0;
  let statusTask: Promise<void> | null = null;
  let payloadTask: Promise<void> | null = null;

  function resetPreview() {
    statusGeneration++;
    payloadGeneration++;
    statusTask = null;
    payloadTask = null;
    previewStatus.value = null;
    previewPayload.value = null;
    previewError.value = null;
    previewLoading.value = false;
  }
  onScopeDispose(resetPreview);

  function refreshPreviewStatus(invalidatePayload = false): Promise<void> {
    const current = ++statusGeneration;
    const requestedMarket = market();
    // Supersede an older download so it cannot overwrite a refreshed cache version.
    payloadGeneration++;
    payloadTask = null;
    previewLoading.value = false;
    previewError.value = null;
    const task = api.previewStatus(requestedMarket).then(status => {
      if (current !== statusGeneration || requestedMarket !== market()) return;
      if (invalidatePayload || identity(status) !== identity(previewStatus.value)) previewPayload.value = null;
      previewStatus.value = status;
    }).catch(reason => {
      if (current !== statusGeneration || requestedMarket !== market()) return;
      previewStatus.value = null;
      previewPayload.value = null;
      previewError.value = getParsedApiError(reason);
    }).finally(() => {
      if (current === statusGeneration) statusTask = null;
    });
    statusTask = task;
    return task;
  }

  async function loadPreview(): Promise<void> {
    const requestedMarket = market();
    const statusAtStart = statusGeneration;
    if (statusTask) await statusTask;
    if (requestedMarket !== market() || statusAtStart !== statusGeneration) return;
    // A failed/incomplete status already contains everything needed for its message.
    if (previewStatus.value?.status !== 'completed') return;
    if (previewPayload.value) return;
    if (payloadTask) return payloadTask;
    const current = ++payloadGeneration;
    previewLoading.value = true;
    previewError.value = null;
    const task = api.preview(requestedMarket).then(payload => {
      if (current !== payloadGeneration || requestedMarket !== market()) return;
      previewPayload.value = payload;
      if (!payload) previewStatus.value = null; // Cache expired between status and full read.
    }).catch(reason => {
      if (current === payloadGeneration && requestedMarket === market()) previewError.value = getParsedApiError(reason);
    }).finally(() => {
      if (current === payloadGeneration) {
        previewLoading.value = false;
        payloadTask = null;
      }
    });
    payloadTask = task;
    return task;
  }
  return { previewStatus, previewPayload, previewLoading, previewError, refreshPreviewStatus, loadPreview, resetPreview };
}
