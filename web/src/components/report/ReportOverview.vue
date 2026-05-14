<script setup lang="ts">
import Badge from '@/components/common/Badge.vue';
import Card from '@/components/common/Card.vue';
import ScoreGauge from '@/components/common/ScoreGauge.vue';
import { formatDateTime } from '@/utils/format';
import { getReportText, normalizeReportLanguage } from '@/utils/reportLanguage';
import type {
  ReportDetails as ReportDetailsType,
  ReportMeta,
  ReportSummary as ReportSummaryType,
} from '@/types/analysis';
import { computed } from 'vue';

type BoardStatus = 'leading' | 'lagging';

type BoardSignal = {
  status: BoardStatus;
  changePct?: number;
};

const props = defineProps<{
  meta: ReportMeta;
  summary: ReportSummaryType;
  details?: ReportDetailsType;
  isHistory?: boolean;
}>();

const normalizeBoardName = (value?: string): string => (value || '').trim().replace(/\s+/g, ' ');

function coerceFiniteNumber(value: unknown): number | undefined {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : undefined;
  }
  if (typeof value === 'string') {
    const trimmed = value.trim().replace(/%$/, '');
    if (!trimmed) return undefined;
    const parsed = Number(trimmed);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
}

function buildBoardSignalMap(details?: ReportDetailsType): Map<string, BoardSignal> {
  const signalMap = new Map<string, BoardSignal>();
  const topBoards = Array.isArray(details?.sectorRankings?.top) ? details.sectorRankings.top : [];
  const bottomBoards = Array.isArray(details?.sectorRankings?.bottom)
    ? details.sectorRankings.bottom
    : [];

  topBoards.forEach((item) => {
    const normalizedName = normalizeBoardName(item?.name);
    if (!normalizedName) return;
    signalMap.set(normalizedName, {
      status: 'leading',
      changePct: coerceFiniteNumber(item.changePct),
    });
  });

  bottomBoards.forEach((item) => {
    const normalizedName = normalizeBoardName(item?.name);
    if (!normalizedName) return;
    signalMap.set(normalizedName, {
      status: 'lagging',
      changePct: coerceFiniteNumber(item.changePct),
    });
  });

  return signalMap;
}

const reportLanguage = computed(() => normalizeReportLanguage(props.meta.reportLanguage));
const text = computed(() => getReportText(reportLanguage.value));

const relatedBoards = computed(() =>
  (Array.isArray(props.details?.belongBoards) ? props.details!.belongBoards : [])
    .filter((board) => normalizeBoardName(board?.name).length > 0)
    .slice(0, 3),
);

const boardSignals = computed(() => buildBoardSignalMap(props.details));

function getPriceChangeStyle(changePct: number | undefined): Record<string, string> | undefined {
  if (changePct === undefined || changePct === null) return undefined;
  if (changePct > 0) return { color: 'var(--home-price-up)' };
  if (changePct < 0) return { color: 'var(--home-price-down)' };
  return undefined;
}

function formatChangePct(changePct: number | undefined): string {
  if (changePct === undefined || changePct === null) return '--';
  const sign = changePct > 0 ? '+' : '';
  return `${sign}${changePct.toFixed(2)}%`;
}

function getBoardStatusLabel(status: BoardStatus): string {
  return status === 'leading' ? text.value.leadingBoard : text.value.laggingBoard;
}

function getBoardStatusVariant(status: BoardStatus): 'success' | 'danger' {
  return status === 'leading' ? 'success' : 'danger';
}
</script>

<template>
  <div class="space-y-5">
    <div class="grid grid-cols-1 items-stretch gap-5 lg:grid-cols-3">
      <div class="space-y-5 lg:col-span-2">
        <Card variant="gradient" padding="md" class="home-report-hero">
          <div class="mb-5 flex items-start justify-between">
            <div class="flex-1">
              <div class="flex items-center gap-3">
                <h2 class="text-[28px] font-bold leading-tight text-foreground">
                  {{ meta.stockName || meta.stockCode }}
                </h2>
                <div v-if="meta.currentPrice != null" class="flex items-baseline gap-2">
                  <span class="font-mono text-xl font-bold" :style="getPriceChangeStyle(meta.changePct)">
                    {{ meta.currentPrice.toFixed(2) }}
                  </span>
                  <span
                    class="font-mono text-sm font-semibold"
                    :style="getPriceChangeStyle(meta.changePct)"
                  >
                    {{ formatChangePct(meta.changePct) }}
                  </span>
                </div>
              </div>
              <div class="mt-1.5 flex items-center gap-2">
                <span class="home-accent-chip px-2 py-0.5 font-mono text-xs">
                  {{ meta.stockCode }}
                </span>
                <span class="flex items-center gap-1 text-xs text-muted-text">
                  <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      stroke-width="2"
                      d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"
                    />
                  </svg>
                  {{ formatDateTime(meta.createdAt) }}
                </span>
              </div>
            </div>
          </div>

          <div class="home-divider border-t pt-5">
            <span class="label-uppercase">{{ text.keyInsights }}</span>
            <p
              class="mt-2 max-w-[62ch] whitespace-pre-wrap text-left text-[15px] leading-7 text-foreground"
            >
              {{ summary.analysisSummary || text.noAnalysisSummary }}
            </p>
          </div>
        </Card>

        <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Card
            variant="bordered"
            padding="sm"
            hoverable
            class="home-panel-card home-insight-card"
            :root-style="{ '--home-insight-tone': 'var(--home-strategy-buy)' }"
          >
            <div class="flex items-start gap-3">
              <div
                class="home-insight-icon flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-success/10"
              >
                <svg class="h-4 w-4 text-success" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="1.5"
                    d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"
                  />
                </svg>
              </div>
              <div class="space-y-1.5">
                <h4 class="home-insight-title text-[11px] font-medium uppercase tracking-[0.16em]">
                  {{ text.actionAdvice }}
                </h4>
                <p class="home-insight-body text-sm leading-6">
                  {{ summary.operationAdvice || text.noAdvice }}
                </p>
              </div>
            </div>
          </Card>

          <Card
            variant="bordered"
            padding="sm"
            hoverable
            class="home-panel-card home-insight-card"
            :root-style="{ '--home-insight-tone': 'var(--home-strategy-take)' }"
          >
            <div class="flex items-start gap-3">
              <div
                class="home-insight-icon flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-warning/10"
              >
                <svg class="h-4 w-4 text-warning" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="1.5"
                    d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"
                  />
                </svg>
              </div>
              <div class="space-y-1.5">
                <h4 class="home-insight-title text-[11px] font-medium uppercase tracking-[0.16em]">
                  {{ text.trendPrediction }}
                </h4>
                <p class="home-insight-body text-sm leading-6">
                  {{ summary.trendPrediction || text.noPrediction }}
                </p>
              </div>
            </div>
          </Card>
        </div>

        <Card
          v-if="relatedBoards.length > 0"
          variant="bordered"
          padding="sm"
          class="home-panel-card text-left"
        >
          <div class="mb-3 flex items-baseline gap-2">
            <span class="label-uppercase">{{ text.boardLinkage }}</span>
            <h3 class="mt-0.5 text-base font-semibold text-foreground">{{ text.relatedBoards }}</h3>
          </div>

          <div class="space-y-2.5">
            <div
              v-for="(board, index) in relatedBoards"
              :key="`${normalizeBoardName(board.name)}-${board.code || index}`"
              class="flex flex-wrap items-center gap-2 text-sm"
            >
              <span class="home-accent-chip px-2 py-0.5 text-xs font-medium">
                {{ normalizeBoardName(board.name) }}
              </span>
              <span v-if="board.type" class="home-board-pill rounded-full px-2 py-0.5 text-xs">
                {{ board.type }}
              </span>
              <template v-if="boardSignals.get(normalizeBoardName(board.name))">
                <Badge
                  :variant="getBoardStatusVariant(boardSignals.get(normalizeBoardName(board.name))!.status)"
                  class="home-board-status-badge shadow-none"
                >
                  {{
                    getBoardStatusLabel(boardSignals.get(normalizeBoardName(board.name))!.status)
                  }}
                </Badge>
                <span
                  v-if="
                    boardSignals.get(normalizeBoardName(board.name))!.changePct !== undefined &&
                    boardSignals.get(normalizeBoardName(board.name))!.changePct !== null
                  "
                  class="font-mono text-xs"
                  :style="
                    getPriceChangeStyle(boardSignals.get(normalizeBoardName(board.name))!.changePct)
                  "
                >
                  {{ formatChangePct(boardSignals.get(normalizeBoardName(board.name))!.changePct) }}
                </span>
              </template>
            </div>
          </div>
        </Card>
      </div>

      <div class="flex min-h-full flex-col self-stretch">
        <Card
          variant="bordered"
          padding="md"
          class="home-panel-card home-rail-card flex min-h-0 !overflow-visible flex-1 flex-col"
        >
          <div class="flex flex-1 flex-col justify-center text-center">
            <h3 class="mb-5 text-sm font-medium tracking-wide text-foreground">
              {{ text.marketSentiment }}
            </h3>
            <ScoreGauge :score="summary.sentimentScore" size="lg" :language="reportLanguage" />
          </div>
        </Card>
      </div>
    </div>
  </div>
</template>
