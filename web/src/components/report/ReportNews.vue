<script setup lang="ts">
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import Card from '@/components/common/Card.vue';
import DashboardPanelHeader from '@/components/dashboard/DashboardPanelHeader.vue';
import DashboardStateBlock from '@/components/dashboard/DashboardStateBlock.vue';
import { historyApi } from '@/api/history';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import type { NewsIntelItem, ReportLanguage } from '@/types/analysis';
import { getReportText, normalizeReportLanguage } from '@/utils/reportLanguage';
import { ref, watch } from 'vue';

const props = withDefaults(
  defineProps<{
    recordId?: number;
    limit?: number;
    language?: ReportLanguage;
  }>(),
  {
    limit: 8,
    language: 'zh',
  },
);

const reportLanguage = normalizeReportLanguage(props.language);
const text = getReportText(reportLanguage);

const isLoading = ref(false);
const items = ref<NewsIntelItem[]>([]);
const error = ref<ParsedApiError | null>(null);

async function fetchNews() {
  if (!props.recordId) return;
  isLoading.value = true;
  error.value = null;

  try {
    const response = await historyApi.getNews(props.recordId, props.limit);
    items.value = response.items || [];
  } catch (err: unknown) {
    error.value = getParsedApiError(err);
  } finally {
    isLoading.value = false;
  }
}

watch(
  () => props.recordId,
  () => {
    items.value = [];
    error.value = null;
    if (props.recordId) {
      void fetchNews();
    }
  },
  { immediate: true },
);
</script>

<template>
  <Card v-if="recordId" variant="bordered" padding="md" class="home-panel-card">
    <DashboardPanelHeader>
      <template #eyebrow>{{ text.newsFeed }}</template>
      <template #title>{{ text.relatedNews }}</template>
      <template #actions>
        <div class="flex items-center gap-2">
          <div v-if="isLoading" class="home-spinner h-3.5 w-3.5 animate-spin border-2" aria-hidden="true" />
          <button
            type="button"
            class="home-accent-link text-xs"
            :aria-label="text.refresh"
            @click="fetchNews"
          >
            {{ text.refresh }}
          </button>
        </div>
      </template>
    </DashboardPanelHeader>

    <ApiErrorAlert
      v-if="error && !isLoading"
      :error="error"
      :action-label="text.retry"
      :dismiss-label="text.dismiss"
      @action="fetchNews"
    />

    <DashboardStateBlock v-if="isLoading && !error" compact loading :title="text.loadingNews" />

    <DashboardStateBlock
      v-else-if="!isLoading && !error && items.length === 0"
      compact
      :title="text.noNews"
      :description="text.noNewsDescription"
    >
      <template #icon>
        <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="1.5"
            d="M19 14l-7-7m0 0l-7 7m7-7v18"
          />
        </svg>
      </template>
    </DashboardStateBlock>

    <div v-else-if="!isLoading && !error && items.length > 0" class="space-y-3 text-left">
      <div
        v-for="(item, index) in items"
        :key="`${item.title}-${index}`"
        class="home-subpanel home-news-item group p-4"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0 flex-1 text-left">
            <p class="home-news-title text-left text-sm font-medium leading-6 text-foreground">
              {{ item.title }}
            </p>
            <p
              v-if="item.snippet"
              class="home-news-snippet mt-2 overflow-hidden text-left text-sm leading-6 text-secondary-text [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:3]"
            >
              {{ item.snippet }}
            </p>
          </div>
          <a
            v-if="item.url"
            :href="item.url"
            target="_blank"
            rel="noopener noreferrer"
            class="home-accent-pill-link shrink-0 whitespace-nowrap px-2.5 py-1 text-xs"
            :aria-label="text.openLink"
          >
            {{ text.openLink }}
            <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M14 3h7m0 0v7m0-7L10 14"
              />
            </svg>
          </a>
        </div>
      </div>
    </div>
  </Card>
</template>
