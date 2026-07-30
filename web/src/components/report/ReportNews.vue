<script setup lang="ts">
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import DashboardStateBlock from '@/components/dashboard/DashboardStateBlock.vue';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { historyApi } from '@/api/history';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import type { NewsIntelItem, ReportLanguage } from '@/types/analysis';
import { getReportText, normalizeReportLanguage } from '@/utils/reportLanguage';
import { ref, watch } from 'vue';
import { ArrowUp, ExternalLink } from 'lucide-vue-next';

const props = withDefaults(
  defineProps<{
    recordId?: number;
    limit?: number;
    language?: ReportLanguage;
  }>(),
  {
    recordId: undefined,
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
  <Card v-if="recordId">
    <CardHeader>
      <CardTitle>{{ text.relatedNews }}</CardTitle>
      <CardAction>
        <div class="flex items-center gap-2">
          <div
            v-if="isLoading"
            class="size-3.5 animate-spin rounded-full border-2 border-muted-foreground/30 border-t-foreground"
            aria-hidden="true"
          />
          <Button
            variant="ghost"
            size="xs"
            :aria-label="text.refresh"
            @click="fetchNews"
          >
            {{ text.refresh }}
          </Button>
        </div>
      </CardAction>
    </CardHeader>
    <CardContent class="space-y-3">
      <ApiErrorAlert
        v-if="error && !isLoading"
        :error="error"
        :action-label="text.retry"
        :dismiss-label="text.dismiss"
        @action="fetchNews"
      />

      <DashboardStateBlock
        v-if="isLoading && !error"
        compact
        loading
        :title="text.loadingNews"
      />

      <DashboardStateBlock
        v-else-if="!isLoading && !error && items.length === 0"
        compact
        :title="text.noNews"
        :description="text.noNewsDescription"
      >
        <template #icon>
          <ArrowUp class="size-4" />
        </template>
      </DashboardStateBlock>

      <template v-else-if="!isLoading && !error && items.length > 0">
        <div
          v-for="(item, index) in items"
          :key="`${item.title}-${index}`"
          class="rounded-lg border bg-muted/40 p-4"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 flex-1 text-left">
              <p class="text-left text-sm font-medium leading-6 text-foreground">
                {{ item.title }}
              </p>
              <p
                v-if="item.snippet"
                class="mt-2 line-clamp-3 text-left text-sm leading-6 text-muted-foreground"
              >
                {{ item.snippet }}
              </p>
            </div>
            <a
              v-if="item.url"
              :href="item.url"
              target="_blank"
              rel="noopener noreferrer"
              class="inline-flex shrink-0 items-center gap-1 whitespace-nowrap text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
              :aria-label="text.openLink"
            >
              {{ text.openLink }}
              <ExternalLink class="size-3.5" />
            </a>
          </div>
        </div>
      </template>
    </CardContent>
  </Card>
</template>
