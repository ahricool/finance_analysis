import { computed, ref } from 'vue';
import { createParsedApiError, getParsedApiError, type ParsedApiError } from '@/api/error';
import { systemConfigApi, SystemConfigConflictError, SystemConfigValidationError } from '@/api/systemConfig';
import type {
  ConfigValidationIssue,
  SystemConfigCategorySchema,
  SystemConfigItem,
  SystemConfigUpdateItem,
} from '@/types/systemConfig';

type ToastState =
  | {
      type: 'success';
      message: string;
    }
  | {
      type: 'error';
      error: ParsedApiError;
    }
  | null;

type RetryAction = 'load' | 'save' | null;

type SaveResult = {
  success: boolean;
  message?: string;
  issues?: ConfigValidationIssue[];
};

const CATEGORY_DISPLAY_ORDER: Record<string, number> = {
  base: 10,
  ai_model: 20,
  data_source: 30,
  notification: 40,
  system: 50,
  agent: 55,
  backtest: 60,
  uncategorized: 99,
};

function sortItemsByOrder(items: SystemConfigItem[]): SystemConfigItem[] {
  return [...items].sort((a, b) => {
    const left = a.schema?.displayOrder ?? 9999;
    const right = b.schema?.displayOrder ?? 9999;
    if (left !== right) {
      return left - right;
    }
    return a.key.localeCompare(b.key);
  });
}

function isMultiValueSchema(schema: SystemConfigItem['schema'] | undefined): boolean {
  const validation = (schema?.validation ?? {}) as Record<string, unknown>;
  return Boolean(validation.multiValue ?? validation.multi_value);
}

function normalizeFieldValue(value: string, schema: SystemConfigItem['schema'] | undefined): string {
  if (!isMultiValueSchema(schema)) {
    return value;
  }

  return value
    .split(',')
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0)
    .join(',');
}

export function useSystemConfig() {
  const configVersion = ref('');
  const maskToken = ref('******');
  const serverItems = ref<SystemConfigItem[]>([]);
  const draftValues = ref<Record<string, string>>({});
  const activeCategory = ref('base');
  const validationIssues = ref<ConfigValidationIssue[]>([]);
  const toast = ref<ToastState>(null);
  const isLoading = ref(false);
  const isSaving = ref(false);
  const loadError = ref<ParsedApiError | null>(null);
  const saveError = ref<ParsedApiError | null>(null);
  const retryAction = ref<RetryAction>(null);
  const serverItemByKeyRef = ref<Record<string, SystemConfigItem>>({});

  const mergedItems = computed(() => {
    return sortItemsByOrder(
      serverItems.value.map((item) => ({
        ...item,
        value: draftValues.value[item.key] ?? item.value,
      })),
    );
  });

  const serverItemByKey = computed(() => {
    const map: Record<string, SystemConfigItem> = {};
    for (const item of serverItems.value) {
      map[item.key] = item;
    }
    serverItemByKeyRef.value = map;
    return map;
  });

  const categories = computed<SystemConfigCategorySchema[]>(() => {
    const categoryMap = new Map<string, SystemConfigCategorySchema>();
    for (const item of mergedItems.value) {
      if (!item.schema) {
        continue;
      }

      const category = item.schema.category;
      if (!categoryMap.has(category)) {
        categoryMap.set(category, {
          category,
          title: category.replace('_', ' ').replace(/\b\w/g, (char) => char.toUpperCase()),
          description: '',
          displayOrder: CATEGORY_DISPLAY_ORDER[category] ?? 999,
          fields: [],
        });
      }
      categoryMap.get(category)?.fields.push(item.schema);
    }

    return [...categoryMap.values()].sort((a, b) => a.displayOrder - b.displayOrder);
  });

  const itemsByCategory = computed(() => {
    const map: Record<string, SystemConfigItem[]> = {};
    for (const item of mergedItems.value) {
      const category = item.schema?.category ?? 'uncategorized';
      if (!map[category]) {
        map[category] = [];
      }
      map[category].push(item);
    }
    return map;
  });

  const dirtyKeys = computed(() => {
    const keys: string[] = [];
    for (const item of serverItems.value) {
      const draftRaw = draftValues.value[item.key];
      if (draftRaw === undefined) {
        continue;
      }

      const normalizedDraft = normalizeFieldValue(draftRaw, item.schema);
      const normalizedCurrent = normalizeFieldValue(item.value, item.schema);
      if (normalizedDraft !== normalizedCurrent) {
        keys.push(item.key);
      }
    }
    return keys;
  });

  const hasDirty = computed(() => dirtyKeys.value.length > 0);

  const issueByKey = computed(() => {
    const map: Record<string, ConfigValidationIssue[]> = {};
    for (const issue of validationIssues.value) {
      if (!map[issue.key]) {
        map[issue.key] = [];
      }
      map[issue.key].push(issue);
    }
    return map;
  });

  function applyServerPayload(
    items: SystemConfigItem[],
    version: string,
    token: string,
    options?: { preserveDirty?: boolean; committedKeys?: string[] },
  ) {
    const sorted = sortItemsByOrder(items);
    const previousServerMap = serverItemByKeyRef.value;
    const committedKeys = new Set(options?.committedKeys ?? []);
    const preserveDirty = options?.preserveDirty ?? false;

    serverItems.value = sorted;
    configVersion.value = version;
    maskToken.value = token || '******';

    const prevDraft = draftValues.value;
    const nextDraft: Record<string, string> = {};
    for (const item of sorted) {
      if (committedKeys.has(item.key)) {
        nextDraft[item.key] = item.value;
        continue;
      }

      if (preserveDirty) {
        const previousServerValue = previousServerMap[item.key]?.value;
        const hasDraft = prevDraft[item.key] !== undefined;
        const wasDirty = hasDraft && prevDraft[item.key] !== previousServerValue;
        nextDraft[item.key] = wasDirty ? prevDraft[item.key] : item.value;
        continue;
      }

      nextDraft[item.key] = item.value;
    }
    draftValues.value = nextDraft;

    const defaultCategory = sorted[0]?.schema?.category || 'base';
    const exists = sorted.some((item) => item.schema?.category === activeCategory.value);
    activeCategory.value = exists ? activeCategory.value : defaultCategory;
    validationIssues.value = [];
  }

  async function load(): Promise<boolean> {
    isLoading.value = true;
    loadError.value = null;
    retryAction.value = null;

    try {
      const config = await systemConfigApi.getConfig(true);
      applyServerPayload(config.items, config.configVersion, config.maskToken);
      toast.value = null;
      return true;
    } catch (error: unknown) {
      loadError.value = getParsedApiError(error);
      retryAction.value = 'load';
      return false;
    } finally {
      isLoading.value = false;
    }
  }

  function resetDraft() {
    const next: Record<string, string> = {};
    for (const item of serverItems.value) {
      next[item.key] = item.value;
    }
    draftValues.value = next;
    validationIssues.value = [];
    saveError.value = null;
  }

  function applyPartialUpdate(updatedItems: Array<{ key: string; value: string }>) {
    const nextDraft = { ...draftValues.value };
    for (const item of updatedItems) {
      nextDraft[item.key] = item.value;
    }
    draftValues.value = nextDraft;
  }

  async function refreshAfterExternalSave(committedKeys: string[]) {
    const config = await systemConfigApi.getConfig(true);
    applyServerPayload(config.items, config.configVersion, config.maskToken, {
      preserveDirty: true,
      committedKeys,
    });
  }

  function setDraftValue(key: string, value: string) {
    draftValues.value = {
      ...draftValues.value,
      [key]: value,
    };
  }

  function getChangedItems(): SystemConfigUpdateItem[] {
    const map = serverItemByKey.value;
    return dirtyKeys.value
      .map((key) => {
        const serverItem = map[key];
        const normalizedValue = normalizeFieldValue(draftValues.value[key] ?? '', serverItem?.schema);
        return {
          key,
          value: normalizedValue,
        };
      })
      .filter((item) => {
        const serverItem = map[item.key];
        const normalizedCurrent = normalizeFieldValue(serverItem?.value ?? '', serverItem?.schema);
        return item.value !== normalizedCurrent;
      });
  }

  async function save(): Promise<SaveResult> {
    if (!hasDirty.value) {
      toast.value = { type: 'success', message: '当前没有可保存的修改。' };
      return { success: true, message: '当前没有可保存的修改' };
    }

    isSaving.value = true;
    saveError.value = null;
    retryAction.value = null;

    const changedItems = getChangedItems();

    try {
      const validateResult = await systemConfigApi.validate({ items: changedItems });
      validationIssues.value = validateResult.issues || [];

      if (!validateResult.valid) {
        saveError.value = createParsedApiError({
          title: '配置校验未通过',
          message: '请先修正表单错误后再保存。',
          rawMessage: '配置校验未通过，请先修正表单错误。',
          category: 'http_error',
        });
        retryAction.value = 'save';
        return {
          success: false,
          message: '配置校验未通过',
          issues: validateResult.issues,
        };
      }

      const updateResult = await systemConfigApi.update({
        configVersion: configVersion.value,
        maskToken: maskToken.value,
        reloadNow: true,
        items: changedItems,
      });

      const refreshed = await systemConfigApi.getConfig(true);
      applyServerPayload(refreshed.items, refreshed.configVersion, refreshed.maskToken);

      const warningText = updateResult.warnings?.length
        ? `；警告：${updateResult.warnings.join('；')}`
        : '';
      toast.value = { type: 'success', message: `配置已更新${warningText}` };
      return { success: true };
    } catch (error: unknown) {
      if (error instanceof SystemConfigValidationError) {
        validationIssues.value = error.issues;
        saveError.value = error.parsedError;
      } else if (error instanceof SystemConfigConflictError) {
        saveError.value = createParsedApiError({
          title: '配置版本冲突',
          message: `${error.message}，请先重新加载配置。`,
          rawMessage: error.parsedError.rawMessage,
          status: error.parsedError.status,
          category: error.parsedError.category,
        });
      } else {
        saveError.value = getParsedApiError(error);
      }

      toast.value = { type: 'error', error: getParsedApiError(error) };
      retryAction.value = 'save';
      return { success: false, message: '保存失败' };
    } finally {
      isSaving.value = false;
    }
  }

  async function retry() {
    if (retryAction.value === 'load') {
      await load();
      return;
    }
    if (retryAction.value === 'save') {
      await save();
    }
  }

  function clearToast() {
    toast.value = null;
  }

  function setActiveCategory(next: string) {
    activeCategory.value = next;
  }

  return {
    configVersion,
    maskToken,
    serverItems,
    categories,
    itemsByCategory,
    issueByKey,
    activeCategory,
    setActiveCategory,
    hasDirty,
    dirtyCount: computed(() => dirtyKeys.value.length),
    toast,
    clearToast,
    isLoading,
    isSaving,
    loadError,
    saveError,
    retryAction,
    load,
    retry,
    save,
    resetDraft,
    setDraftValue,
    applyPartialUpdate,
    refreshAfterExternalSave,
    mergedItems,
  };
}
