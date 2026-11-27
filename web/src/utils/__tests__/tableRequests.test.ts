import { expect, it, vi } from 'vitest';
import { queueTableRequest } from '../tableRequests';

it('limits concurrent reads and skips work cancelled while waiting', async () => {
  let release!: () => void;
  const firstGroup = new Promise<void>(resolve => { release = resolve; });
  const request = new AbortController();
  const wait = vi.fn(() => firstGroup);
  const reads = Array.from({ length: 4 }, () => queueTableRequest(request.signal, wait));
  const cancelled = new AbortController();
  const skipped = vi.fn(async () => {});
  const pending = queueTableRequest(cancelled.signal, skipped);
  const last = vi.fn(async () => {});
  const final = queueTableRequest(request.signal, last);
  cancelled.abort();
  await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
  expect(wait).toHaveBeenCalledTimes(4);
  expect(last).not.toHaveBeenCalled();
  release();
  await Promise.all([...reads, final]);
  expect(skipped).not.toHaveBeenCalled();
  expect(last).toHaveBeenCalledOnce();
});
