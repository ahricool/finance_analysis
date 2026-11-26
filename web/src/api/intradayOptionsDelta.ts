import type { IntradayOptionsSnapshot } from './intradayOptions';
import { toCamelCase } from './utils';

export interface SnapshotOperation {
  op: 'set' | 'remove' | 'insert';
  path: Array<string | number>;
  value?: unknown;
}
export interface IntradayOptionsDelta {
  base_revision: number;
  revision: number;
  operations: SnapshotOperation[];
}

const keys = new Map<string, string>();
function camelKey(key: string): string {
  const cached = keys.get(key);
  if (cached !== undefined) return cached;
  const converted = Object.keys(toCamelCase<Record<string, unknown>>({ [key]: null }))[0]!;
  keys.set(key, converted);
  return converted;
}
function convertedValue(value: unknown): unknown {
  return value !== null && typeof value === 'object' ? toCamelCase(value) : value;
}

/** Apply an ordered frame atomically; only touched branches are copied. */
function applyOperation(node: unknown, operation: SnapshotOperation, depth: number): unknown {
  const part = operation.path[depth];
  const last = depth === operation.path.length - 1;
  if (Array.isArray(node)) {
    if (typeof part !== 'number' || !Number.isInteger(part) || part < 0 || part > node.length
      || (part === node.length && !(last && operation.op === 'insert'))) throw new Error('Invalid array path');
    const copy = node.slice();
    if (!last) copy[part] = applyOperation(copy[part], operation, depth + 1);
    else if (operation.op === 'insert') copy.splice(part, 0, convertedValue(operation.value));
    else if (operation.op === 'remove') copy.splice(part, 1);
    else copy[part] = convertedValue(operation.value);
    return copy;
  }
  if (!node || typeof node !== 'object' || typeof part !== 'string') throw new Error('Invalid object path');
  const key = camelKey(part);
  if (['__proto__', 'prototype', 'constructor'].includes(part) || ['__proto__', 'prototype', 'constructor'].includes(key)) {
    throw new Error('Invalid object key');
  }
  const record = node as Record<string, unknown>;
  const copy = { ...record };
  if (!last) {
    if (!Object.hasOwn(record, key)) throw new Error('Missing path');
    copy[key] = applyOperation(record[key], operation, depth + 1);
  } else if (operation.op === 'remove') {
    if (!Object.hasOwn(record, key)) throw new Error('Missing removal');
    delete copy[key];
  } else if (operation.op === 'set') copy[key] = convertedValue(operation.value);
  else throw new Error('Insert requires array');
  return copy;
}

export function applyIntradayOptionsDelta(snapshot: IntradayOptionsSnapshot, delta: IntradayOptionsDelta, generatedAt: string): IntradayOptionsSnapshot {
  let next: unknown = snapshot;
  for (const operation of delta.operations) {
    if (!Array.isArray(operation.path) || operation.path.length === 0
      || !['set', 'remove', 'insert'].includes(operation.op)
      || (operation.op !== 'remove' && !Object.hasOwn(operation, 'value'))) throw new Error('Invalid snapshot operation');
    next = applyOperation(next, operation, 0);
  }
  const result = next as IntradayOptionsSnapshot;
  // A date/version change must be delivered as a new full baseline. Reject
  // invalid collections before committing anything to the reactive snapshot.
  if (result.tradingDate !== snapshot.tradingDate || result.version !== snapshot.version
    || !Array.isArray(result.items) || !['open', 'preopen', 'closed'].includes(result.marketStatus)
    || (result.simulation != null && (!Array.isArray(result.simulation.states) || !Array.isArray(result.simulation.trades)
      || !Array.isArray(result.simulation.events) || !Array.isArray(result.simulation.statistics)
      || result.simulation.events.some(event => !event || !Number.isSafeInteger(event.id))))) throw new Error('Invalid snapshot shape');
  return { ...result, generatedAt };
}
