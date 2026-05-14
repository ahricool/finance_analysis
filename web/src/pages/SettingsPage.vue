<script setup lang="ts">
import { createParsedApiError, getParsedApiError, type ParsedApiError } from '@/api/error';
import { systemConfigApi } from '@/api/systemConfig';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import Button from '@/components/common/Button.vue';
import ConfirmDialog from '@/components/common/ConfirmDialog.vue';
import EmptyState from '@/components/common/EmptyState.vue';
import AuthSettingsCard from '@/components/settings/AuthSettingsCard.vue';
import ChangePasswordCard from '@/components/settings/ChangePasswordCard.vue';
import IntelligentImport from '@/components/settings/IntelligentImport.vue';
import LLMChannelEditor from '@/components/settings/LLMChannelEditor.vue';
import NotificationTestPanel from '@/components/settings/NotificationTestPanel.vue';
import SettingsAlert from '@/components/settings/SettingsAlert.vue';
import SettingsCategoryNav from '@/components/settings/SettingsCategoryNav.vue';
import SettingsField from '@/components/settings/SettingsField.vue';
import SettingsLoading from '@/components/settings/SettingsLoading.vue';
import SettingsSectionCard from '@/components/settings/SettingsSectionCard.vue';
import { useAuth } from '@/composables/useAuth';
import { useSystemConfig } from '@/composables/useSystemConfig';
import type { SystemConfigCategory } from '@/types/systemConfig';
import { WEB_BUILD_INFO } from '@/utils/constants';
import { getCategoryDescriptionZh } from '@/utils/systemConfigI18n';
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';

type DesktopWindow = Window & {
  dsaDesktop?: {
    version?: unknown;
    getUpdateState?: () => Promise<RawDesktopUpdateState>;
    checkForUpdates?: () => Promise<RawDesktopUpdateState>;
    installDownloadedUpdate?: () => Promise<boolean>;
    openReleasePage?: (releaseUrl?: string) => Promise<boolean>;
    onUpdateStateChange?: (listener: (state: RawDesktopUpdateState) => void) => (() => void) | void;
  };
};

type DesktopUpdateState = {
  status?: string;
  updateMode?: string;
  currentVersion?: string;
  latestVersion?: string;
  releaseUrl?: string;
  checkedAt?: string;
  publishedAt?: string;
  message?: string;
  releaseName?: string;
  tagName?: string;
  downloadPercent?: number | null;
  downloadedBytes?: number | null;
  totalBytes?: number | null;
};

type RawDesktopUpdateState = {
  status?: unknown;
  updateMode?: unknown;
  currentVersion?: unknown;
  latestVersion?: unknown;
  releaseUrl?: unknown;
  checkedAt?: unknown;
  publishedAt?: unknown;
  message?: unknown;
  releaseName?: unknown;
  tagName?: unknown;
  downloadPercent?: unknown;
  downloadedBytes?: unknown;
  totalBytes?: unknown;
};

type DesktopUpdateNotice = {
  title: string;
  message: string;
  variant: 'error' | 'success' | 'warning';
  actionLabel?: string;
  actionKind?: 'release' | 'install';
};

function trimDesktopRuntimeString(value: unknown) {
  return typeof value === 'string' ? value.trim() : '';
}

function normalizeDesktopRuntimeNumber(value: unknown) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const numberValue = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(numberValue) ? numberValue : null;
}

function getDesktopRuntimeApi() {
  if (typeof window === 'undefined') {
    return undefined;
  }
  return (window as DesktopWindow).dsaDesktop;
}

function getDesktopAppVersion() {
  return trimDesktopRuntimeString(getDesktopRuntimeApi()?.version);
}

function normalizeDesktopUpdateState(state: RawDesktopUpdateState | null | undefined) {
  if (!state || typeof state !== 'object') {
    return null;
  }
  return {
    status: trimDesktopRuntimeString(state.status) || 'idle',
    updateMode: trimDesktopRuntimeString(state.updateMode) || 'manual',
    currentVersion: trimDesktopRuntimeString(state.currentVersion),
    latestVersion: trimDesktopRuntimeString(state.latestVersion),
    releaseUrl: trimDesktopRuntimeString(state.releaseUrl),
    checkedAt: trimDesktopRuntimeString(state.checkedAt),
    publishedAt: trimDesktopRuntimeString(state.publishedAt),
    message: trimDesktopRuntimeString(state.message),
    releaseName: trimDesktopRuntimeString(state.releaseName),
    tagName: trimDesktopRuntimeString(state.tagName),
    downloadPercent: normalizeDesktopRuntimeNumber(state.downloadPercent),
    downloadedBytes: normalizeDesktopRuntimeNumber(state.downloadedBytes),
    totalBytes: normalizeDesktopRuntimeNumber(state.totalBytes),
  };
}

function getDesktopUpdateNotice(state: DesktopUpdateState | null): DesktopUpdateNotice | null {
  if (!state) {
    return null;
  }
  if (state.status === 'update-available') {
    const latestLabel = state.latestVersion || state.tagName || '最新版本';
    const currentLabel = state.currentVersion || getDesktopAppVersion() || '当前版本';
    return {
      title: '发现新版本',
      message: `当前 ${currentLabel}，最新 ${latestLabel}。${state.message || '可前往 GitHub Releases 下载更新。'}`,
      variant: 'warning',
      actionLabel: state.updateMode === 'auto' ? undefined : '前往下载',
      actionKind: state.updateMode === 'auto' ? undefined : 'release',
    };
  }
  if (state.status === 'downloading') {
    const percentText = typeof state.downloadPercent === 'number' ? `（${state.downloadPercent}%）` : '';
    return {
      title: '正在下载更新',
      message: state.message || `正在后台下载桌面端更新${percentText}。`,
      variant: 'warning',
    };
  }
  if (state.status === 'update-downloaded') {
    return {
      title: '更新已下载',
      message: state.message || '新版本已下载，可重启应用完成安装。',
      variant: 'success',
      actionLabel: '重启安装',
      actionKind: 'install',
    };
  }
  if (state.status === 'installing') {
    return {
      title: '正在安装更新',
      message: state.message || '正在重启并安装更新。',
      variant: 'warning',
    };
  }
  if (state.status === 'up-to-date') {
    return {
      title: '已是最新版本',
      message: state.message || '当前桌面端已是最新版本。',
      variant: 'success',
    };
  }
  if (state.status === 'checking') {
    return {
      title: '正在检查更新',
      message: state.message || '正在检查 GitHub Releases 中是否有可用新版本。',
      variant: 'warning',
    };
  }
  if (state.status === 'error') {
    return {
      title: '检查更新失败',
      message: state.message || '无法完成更新检查，请稍后重试。',
      variant: 'error',
      actionLabel: state.updateMode === 'auto' && state.releaseUrl ? '前往下载' : undefined,
      actionKind: state.updateMode === 'auto' && state.releaseUrl ? 'release' : undefined,
    };
  }
  return null;
}

function formatEnvBackupFilename(isDesktopRuntime: boolean) {
  const now = new Date();
  const pad = (value: number) => value.toString().padStart(2, '0');
  const date = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`;
  const time = `${pad(now.getHours())}${pad(now.getMinutes())}`;
  return `${isDesktopRuntime ? 'dsa-desktop-env' : 'dsa-env'}_${date}_${time}.env`;
}

const { authEnabled, passwordChangeable } = useAuth();

const envBackupActionError = ref<ParsedApiError | null>(null);
const envBackupActionSuccess = ref('');
const isExportingEnv = ref(false);
const isImportingEnv = ref(false);
const showImportConfirm = ref(false);
const desktopUpdateState = ref<DesktopUpdateState | null>(null);
const isCheckingDesktopUpdate = ref(false);
const envBackupImportRef = ref<HTMLInputElement | null>(null);

const desktopRuntimeApi = getDesktopRuntimeApi();
const isDesktopRuntime = Boolean(desktopRuntimeApi);
const canCheckDesktopUpdate = Boolean(
  desktopRuntimeApi?.getUpdateState && desktopRuntimeApi?.checkForUpdates && desktopRuntimeApi?.openReleasePage,
);
const desktopAppVersion = getDesktopAppVersion();
const shouldShowDesktopVersionCard = Boolean(desktopAppVersion);

const {
  categories,
  itemsByCategory,
  issueByKey,
  activeCategory,
  setActiveCategory,
  hasDirty,
  dirtyCount,
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
  refreshAfterExternalSave,
  configVersion,
  maskToken,
} = useSystemConfig();

function retryLoadError() {
  void retry();
}

function retrySaveError() {
  if (retryAction.value === 'save') {
    void retry();
  }
}

let toastTimer: number | null = null;
let desktopCleanup: (() => void) | undefined;

watch(toast, (t) => {
  if (toastTimer !== null) {
    window.clearTimeout(toastTimer);
    toastTimer = null;
  }
  if (!t) return;
  toastTimer = window.setTimeout(() => {
    clearToast();
    toastTimer = null;
  }, 3200);
});

onMounted(() => {
  document.title = '系统设置 - DSA';
  void load();

  if (!canCheckDesktopUpdate) {
    desktopUpdateState.value = null;
    isCheckingDesktopUpdate.value = false;
    return;
  }

  let active = true;
  void (async () => {
    try {
      const state = await desktopRuntimeApi?.getUpdateState?.();
      if (active) {
        desktopUpdateState.value = normalizeDesktopUpdateState(state);
      }
    } catch (error: unknown) {
      if (!active) return;
      desktopUpdateState.value = {
        status: 'error',
        message: error instanceof Error ? error.message : '读取桌面端更新状态失败。',
      };
    }
  })();

  const unsubscribe = desktopRuntimeApi?.onUpdateStateChange?.((state) => {
    if (!active) return;
    desktopUpdateState.value = normalizeDesktopUpdateState(state);
    isCheckingDesktopUpdate.value = false;
  });

  desktopCleanup = () => {
    active = false;
    if (typeof unsubscribe === 'function') {
      unsubscribe();
    }
  };
});

onUnmounted(() => {
  if (toastTimer !== null) {
    window.clearTimeout(toastTimer);
  }
  desktopCleanup?.();
});

const rawActiveItems = computed(() => itemsByCategory.value[activeCategory.value] || []);
const rawActiveItemMap = computed(() => new Map(rawActiveItems.value.map((item) => [item.key, String(item.value ?? '')])));
const hasConfiguredChannels = computed(() => Boolean((rawActiveItemMap.value.get('LLM_CHANNELS') || '').trim()));
const hasLitellmConfig = computed(() => Boolean((rawActiveItemMap.value.get('LITELLM_CONFIG') || '').trim()));

const LLM_CHANNEL_KEY_RE = /^LLM_[A-Z0-9]+_(PROTOCOL|BASE_URL|API_KEY|API_KEYS|MODELS|EXTRA_HEADERS|ENABLED)$/;
const AI_MODEL_HIDDEN_KEYS = new Set([
  'LLM_CHANNELS', 'LLM_TEMPERATURE', 'LITELLM_MODEL', 'AGENT_LITELLM_MODEL', 'LITELLM_FALLBACK_MODELS',
  'AIHUBMIX_KEY', 'DEEPSEEK_API_KEY', 'DEEPSEEK_API_KEYS', 'GEMINI_API_KEY', 'GEMINI_API_KEYS', 'GEMINI_MODEL',
  'GEMINI_MODEL_FALLBACK', 'GEMINI_TEMPERATURE', 'ANTHROPIC_API_KEY', 'ANTHROPIC_API_KEYS', 'ANTHROPIC_MODEL',
  'ANTHROPIC_TEMPERATURE', 'ANTHROPIC_MAX_TOKENS', 'OPENAI_API_KEY', 'OPENAI_API_KEYS', 'OPENAI_BASE_URL',
  'OPENAI_MODEL', 'OPENAI_VISION_MODEL', 'OPENAI_TEMPERATURE', 'VISION_MODEL',
]);
const SYSTEM_HIDDEN_KEYS = new Set(['ADMIN_AUTH_ENABLED']);
const AGENT_HIDDEN_KEYS = new Set<string>();

const activeItems = computed(() => {
  const raw = rawActiveItems.value;
  const cat = activeCategory.value;
  if (cat === 'ai_model') {
    return raw.filter((item) => {
      if (hasConfiguredChannels.value && LLM_CHANNEL_KEY_RE.test(item.key)) {
        return false;
      }
      if (hasConfiguredChannels.value && !hasLitellmConfig.value && AI_MODEL_HIDDEN_KEYS.has(item.key)) {
        return false;
      }
      return true;
    });
  }
  if (cat === 'system') {
    return raw.filter((item) => !SYSTEM_HIDDEN_KEYS.has(item.key));
  }
  if (cat === 'agent') {
    return raw.filter((item) => !AGENT_HIDDEN_KEYS.has(item.key));
  }
  return raw;
});

const isEnvBackupAllowed = computed(() => isDesktopRuntime || authEnabled.value);
const envBackupActionDisabled = computed(
  () => isLoading.value || isSaving.value || isExportingEnv.value || isImportingEnv.value || !isEnvBackupAllowed.value,
);

async function downloadEnvBackup() {
  envBackupActionError.value = null;
  envBackupActionSuccess.value = '';
  isExportingEnv.value = true;
  try {
    const payload = await systemConfigApi.exportEnv();
    const blob = new Blob([payload.content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = formatEnvBackupFilename(isDesktopRuntime);
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
    envBackupActionSuccess.value = '已导出当前已保存的 .env 备份。';
  } catch (error: unknown) {
    envBackupActionError.value = getParsedApiError(error);
  } finally {
    isExportingEnv.value = false;
  }
}

function beginEnvBackupImport() {
  envBackupActionError.value = null;
  envBackupActionSuccess.value = '';
  if (hasDirty.value) {
    showImportConfirm.value = true;
    return;
  }
  envBackupImportRef.value?.click();
}

async function handleEnvBackupImportFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = '';
  showImportConfirm.value = false;
  if (!file) return;

  envBackupActionError.value = null;
  envBackupActionSuccess.value = '';
  isImportingEnv.value = true;
  try {
    const content = await file.text();
    await systemConfigApi.importEnv({
      configVersion: configVersion.value,
      content,
      reloadNow: true,
    });
    const reloaded = await load();
    if (!reloaded) {
      envBackupActionError.value = createParsedApiError({
        title: '配置已导入但刷新失败',
        message: '备份已导入，但重新加载配置失败，请手动重载页面。',
        rawMessage: 'Env import succeeded but config refresh failed',
        category: 'http_error',
      });
      return;
    }
    envBackupActionSuccess.value = '已导入 .env 备份并重新加载配置。';
  } catch (error: unknown) {
    envBackupActionError.value = getParsedApiError(error);
  } finally {
    isImportingEnv.value = false;
  }
}

async function handleDesktopUpdateCheck() {
  if (!desktopRuntimeApi?.checkForUpdates) return;
  isCheckingDesktopUpdate.value = true;
  desktopUpdateState.value = {
    ...(desktopUpdateState.value || {}),
    status: 'checking',
    message: '正在检查 GitHub Releases 中是否有可用新版本。',
  };
  try {
    const state = await desktopRuntimeApi.checkForUpdates();
    desktopUpdateState.value = normalizeDesktopUpdateState(state);
  } catch (error: unknown) {
    desktopUpdateState.value = {
      status: 'error',
      message: error instanceof Error ? error.message : '检查更新失败，请稍后重试。',
    };
  } finally {
    isCheckingDesktopUpdate.value = false;
  }
}

async function openDesktopReleasePage() {
  if (!desktopRuntimeApi?.openReleasePage) return;
  await desktopRuntimeApi.openReleasePage(desktopUpdateState.value?.releaseUrl);
}

async function installDesktopUpdate() {
  if (!desktopRuntimeApi?.installDownloadedUpdate) {
    desktopUpdateState.value = {
      ...(desktopUpdateState.value || {}),
      status: 'error',
      message: '当前桌面端不支持自动安装更新，请前往发布页手动更新。',
    };
    return;
  }
  try {
    desktopUpdateState.value = {
      ...(desktopUpdateState.value || {}),
      status: 'installing',
      message: '正在重启并安装更新...',
    };
    await desktopRuntimeApi.installDownloadedUpdate();
  } catch (error: unknown) {
    desktopUpdateState.value = {
      ...(desktopUpdateState.value || {}),
      status: 'error',
      message: error instanceof Error ? error.message : '自动安装更新失败，请前往发布页手动更新。',
    };
  }
}

const desktopUpdateNotice = computed(() => getDesktopUpdateNotice(desktopUpdateState.value));

function onDesktopUpdateAction() {
  const n = desktopUpdateNotice.value;
  if (!n?.actionLabel) return;
  if (n.actionKind === 'install') {
    void installDesktopUpdate();
    return;
  }
  void openDesktopReleasePage();
}

function confirmEnvImport() {
  showImportConfirm.value = false;
  envBackupImportRef.value?.click();
}

function onEnvBackupErrorAction() {
  if (envBackupActionError.value?.status === 409) {
    void load();
  }
}

const stockListDraft = computed(
  () => (activeItems.value.find((i) => i.key === 'STOCK_LIST')?.value as string) ?? '',
);
</script>

<template>
  <div class="settings-page min-h-full px-4 pb-6 pt-4 md:px-6">
    <div class="mb-5 rounded-[1.5rem] border settings-border bg-card/94 px-5 py-5 shadow-soft-card-strong backdrop-blur-sm">
      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 class="text-xl font-semibold tracking-tight text-foreground">系统设置</h1>
          <p class="text-xs leading-6 text-muted-text">统一管理模型、数据源、通知、安全认证与导入能力。</p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <Button type="button" variant="settings-secondary" :disabled="isLoading || isSaving" @click="resetDraft">
            重置
          </Button>
          <Button
            type="button"
            variant="settings-primary"
            :disabled="!hasDirty || isSaving || isLoading"
            :is-loading="isSaving"
            loading-text="保存中..."
            @click="void save()"
          >
            {{ isSaving ? '保存中...' : `保存配置${dirtyCount ? ` (${dirtyCount})` : ''}` }}
          </Button>
        </div>
      </div>
      <ApiErrorAlert
        v-if="saveError"
        class="mt-3"
        :error="saveError"
        :action-label="retryAction === 'save' ? '重试保存' : undefined"
        @action="retrySaveError"
      />
    </div>

    <ApiErrorAlert
      v-if="loadError"
      :error="loadError"
      :action-label="retryAction === 'load' ? '重试加载' : '重新加载'"
      class="mb-4"
      @action="retryLoadError"
    />

    <SettingsLoading v-if="isLoading" />
    <div v-else class="grid grid-cols-1 gap-5 lg:grid-cols-[280px_1fr]">
      <aside class="lg:sticky lg:top-4 lg:self-start">
        <SettingsCategoryNav
          :categories="categories"
          :items-by-category="itemsByCategory"
          :active-category="activeCategory"
          @select="setActiveCategory"
        />
      </aside>

      <section class="space-y-4">
        <AuthSettingsCard v-if="activeCategory === 'system'" />

        <SettingsSectionCard
          v-if="activeCategory === 'system'"
          title="版本信息"
          description="用于确认当前 WebUI 静态资源是否已经切换到最新构建。"
        >
          <div :class="`grid grid-cols-1 gap-3 ${shouldShowDesktopVersionCard ? 'md:grid-cols-4' : 'md:grid-cols-3'}`">
            <div class="rounded-2xl border settings-border bg-background/40 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-text">WebUI 版本</p>
              <p class="mt-2 break-all font-mono text-sm text-foreground">{{ WEB_BUILD_INFO.version }}</p>
            </div>
            <div class="rounded-2xl border settings-border bg-background/40 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-text">构建标识</p>
              <p class="mt-2 break-all font-mono text-sm text-foreground">{{ WEB_BUILD_INFO.buildId }}</p>
            </div>
            <div class="rounded-2xl border settings-border bg-background/40 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-text">构建时间</p>
              <p class="mt-2 break-all font-mono text-sm text-foreground">{{ WEB_BUILD_INFO.buildTime }}</p>
            </div>
            <div v-if="shouldShowDesktopVersionCard" class="rounded-2xl border settings-border bg-background/40 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-text">桌面端版本</p>
              <p class="mt-2 break-all font-mono text-sm text-foreground">{{ desktopAppVersion }}</p>
            </div>
          </div>
          <p class="text-xs leading-6 text-muted-text">
            重新执行前端构建或 Docker 镜像构建后，此处的构建标识和构建时间会更新，可用来确认当前页面资源是否已切换。
          </p>
          <div v-if="canCheckDesktopUpdate" class="mt-4 space-y-3 rounded-2xl border settings-border bg-background/30 px-4 py-4">
            <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div>
                <p class="text-sm font-medium text-foreground">桌面端更新</p>
                <p class="text-xs leading-6 text-muted-text">
                  启动后会自动检查 GitHub Releases 最新正式版；Windows 安装版会后台下载更新并提示重启安装。
                </p>
              </div>
              <Button
                type="button"
                variant="settings-secondary"
                :disabled="isCheckingDesktopUpdate"
                :is-loading="isCheckingDesktopUpdate"
                loading-text="检查中..."
                @click="void handleDesktopUpdateCheck()"
              >
                检查更新
              </Button>
            </div>
            <SettingsAlert
              v-if="desktopUpdateNotice"
              :title="desktopUpdateNotice.title"
              :message="desktopUpdateNotice.message"
              :variant="desktopUpdateNotice.variant"
              :action-label="desktopUpdateNotice.actionLabel"
              @action="onDesktopUpdateAction"
            />
            <p v-else class="text-xs leading-6 text-muted-text">当前尚无更新状态，应用启动后会在后台自动检查。</p>
          </div>
          <p v-if="WEB_BUILD_INFO.isFallbackVersion" class="text-xs leading-6 text-amber-700 dark:text-amber-300">
            当前 package.json 仍为占位版本 0.0.0，页面已自动回退展示构建标识，避免误判旧资源仍在生效。
          </p>
        </SettingsSectionCard>

        <SettingsSectionCard
          v-if="activeCategory === 'system'"
          title="配置备份"
          description="导出当前已保存的 .env 备份，或从备份文件恢复配置。导入会覆盖备份中出现的键并立即重载。"
        >
          <div class="space-y-4">
            <p v-if="!isEnvBackupAllowed" class="text-xs leading-6 text-amber-700 dark:text-amber-300">
              当前 Web 端未开启管理员鉴权，导出/导入 `.env` 备份功能已停用；请先将 `ADMIN_AUTH_ENABLED` 设为 `true`
              并完成管理员登录后再使用。
            </p>
            <div class="flex flex-wrap items-center gap-3">
              <Button
                type="button"
                variant="settings-secondary"
                :disabled="envBackupActionDisabled"
                :is-loading="isExportingEnv"
                loading-text="导出中..."
                @click="void downloadEnvBackup()"
              >
                导出 .env
              </Button>
              <Button
                type="button"
                variant="settings-primary"
                :disabled="envBackupActionDisabled"
                :is-loading="isImportingEnv"
                loading-text="导入中..."
                @click="beginEnvBackupImport"
              >
                导入 .env
              </Button>
              <input
                ref="envBackupImportRef"
                type="file"
                accept=".env,.txt"
                class="hidden"
                @change="void handleEnvBackupImportFile($event)"
              />
            </div>
            <p class="text-xs leading-6 text-muted-text">
              导出内容仅包含当前已保存配置，不包含页面上尚未保存的本地草稿。
            </p>
            <ApiErrorAlert
              v-if="envBackupActionError"
              :error="envBackupActionError"
              :action-label="envBackupActionError.status === 409 ? '重新加载' : undefined"
              @action="onEnvBackupErrorAction"
            />
            <SettingsAlert
              v-if="!envBackupActionError && envBackupActionSuccess"
              title="操作成功"
              :message="envBackupActionSuccess"
              variant="success"
            />
          </div>
        </SettingsSectionCard>

        <SettingsSectionCard
          v-if="activeCategory === 'base'"
          title="智能导入"
          description="从图片、文件或剪贴板中提取股票代码，并合并到自选股列表。"
        >
          <IntelligentImport
            :stock-list-value="stockListDraft"
            :config-version="configVersion"
            :mask-token="maskToken"
            :disabled="isSaving || isLoading"
            @merged="void refreshAfterExternalSave(['STOCK_LIST'])"
          />
        </SettingsSectionCard>

        <SettingsSectionCard
          v-if="activeCategory === 'ai_model'"
          title="AI 模型接入"
          description="统一管理模型渠道、基础地址、API Key、主模型与备选模型。"
        >
          <LLMChannelEditor
            :items="rawActiveItems.map((i) => ({ key: i.key, value: String(i.value ?? '') }))"
            :config-version="configVersion"
            :mask-token="maskToken"
            :disabled="isSaving || isLoading"
            @saved="void refreshAfterExternalSave($event.map((item) => item.key))"
          />
        </SettingsSectionCard>

        <ChangePasswordCard v-if="activeCategory === 'system' && passwordChangeable" />

        <NotificationTestPanel
          v-if="activeCategory === 'notification'"
          :items="rawActiveItems.map((item) => ({ key: item.key, value: String(item.value ?? '') }))"
          :mask-token="maskToken"
          :disabled="isSaving || isLoading"
        />

        <SettingsSectionCard
          v-if="activeItems.length"
          title="当前分类配置项"
          :description="
            getCategoryDescriptionZh(activeCategory as SystemConfigCategory, '')
            || '使用统一字段卡片维护当前分类的系统配置。'
          "
        >
          <SettingsField
            v-for="item in activeItems"
            :key="item.key"
            :item="item"
            :value="item.value"
            :disabled="isSaving"
            :issues="issueByKey[item.key] || []"
            @change="setDraftValue"
          />
        </SettingsSectionCard>

        <EmptyState
          v-else
          title="当前分类下暂无配置项"
          description="当前分类没有可编辑字段；可切换左侧分类继续查看其它系统配置。"
          class="settings-surface-panel settings-border-strong border-none bg-transparent shadow-none"
        />
      </section>
    </div>

    <div v-if="toast" class="fixed bottom-5 right-5 z-50 w-[320px] max-w-[calc(100vw-24px)]">
      <SettingsAlert
        v-if="toast.type === 'success'"
        title="操作成功"
        :message="toast.message"
        variant="success"
        presentation="toast"
      />
      <ApiErrorAlert v-else :error="toast.error" />
    </div>

    <ConfirmDialog
      :is-open="showImportConfirm"
      title="导入会覆盖当前草稿"
      message="当前页面还有未保存修改。继续导入会丢弃这些本地草稿，并立即用备份文件中的键值更新已保存配置。"
      confirm-text="继续导入"
      cancel-text="取消"
      @confirm="confirmEnvImport"
      @cancel="showImportConfirm = false"
    />
  </div>
</template>
