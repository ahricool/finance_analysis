<script setup lang="ts">
import { Badge } from '@/components/ui/badge';
import ScoreGauge from '@/components/report/ScoreGauge.vue';
import { Card } from '@/components/ui/card';
import { formatDateTime } from '@/utils/format';
import { getReportText, normalizeReportLanguage } from '@/utils/reportLanguage';
import type {
  ReportDetails as ReportDetailsType,
  ReportMeta,
  ReportSummary as ReportSummaryType,
} from '@/types/analysis';
import { computed } from 'vue';
import { CalendarDays, ClipboardCheck, TrendingUp } from 'lucide-vue-next';

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

function getPriceChangeClass(changePct: number | undefined): string {
  if (changePct === undefined || changePct === null) return '';
  if (changePct > 0) return 'text-market-up';
  if (changePct < 0) return 'text-market-down';
  return 'text-muted-foreground';
}

function formatChangePct(changePct: number | undefined): string {
  if (changePct === undefined || changePct === null) return '--';
  const sign = changePct > 0 ? '+' : '';
  return `${sign}${changePct.toFixed(2)}%`;
}

function getBoardStatusLabel(status: BoardStatus): string {
  return status === 'leading' ? text.value.leadingBoard : text.value.laggingBoard;
}

function getBoardStatusVariant(status: BoardStatus): 'success' | 'destructive' {
  return status === 'leading' ? 'success' : 'destructive';
}
</script>

<template>
  <div class="space-y-5">
    <div class="grid grid-cols-1 items-stretch gap-5 lg:grid-cols-3">
      <div class="space-y-5 lg:col-span-2">
        <Card class="p-5">
          <div class="mb-5 flex items-start justify-between">
            <div class="flex-1">
              <div class="flex items-center gap-3">
                <h2 class="text-2xl font-bold leading-tight tracking-tight text-foreground sm:text-3xl">
                  {{ meta.stockName || meta.stockCode }}
                </h2>
                <div
                  v-if="meta.currentPrice != null"
                  class="flex items-baseline gap-2"
                >
                  <span
                    class="font-mono text-xl font-bold"
                    :class="getPriceChangeClass(meta.changePct)"
                  >
                    {{ meta.currentPrice.toFixed(2) }}
                  </span>
                  <span
                    class="font-mono text-sm font-semibold"
                    :class="getPriceChangeClass(meta.changePct)"
                  >
                    {{ formatChangePct(meta.changePct) }}
                  </span>
                </div>
              </div>
              <div class="mt-1.5 flex items-center gap-2">
                <Badge
                  variant="secondary"
                  class="font-mono"
                >
                  {{ meta.stockCode }}
                </Badge>
                <span class="flex items-center gap-1 text-xs text-muted-foreground">
                  <CalendarDays class="size-3.5" />
                  {{ formatDateTime(meta.createdAt) }}
                </span>
              </div>
            </div>
          </div>

          <div class="border-border border-t pt-5">
            <span class="text-xs font-medium uppercase tracking-wider text-muted-foreground">{{
              text.keyInsights
            }}</span>
            <p
              class="mt-2 max-w-prose whitespace-pre-wrap text-left text-sm leading-7 text-foreground sm:text-base"
            >
              {{ summary.analysisSummary || text.noAnalysisSummary }}
            </p>
          </div>
        </Card>

        <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Card class="p-4">
            <div class="flex items-start gap-3">
              <div
                class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-success/10"
              >
                <ClipboardCheck class="size-4 text-success" />
              </div>
              <div class="space-y-1.5">
                <h4 class="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  {{ text.actionAdvice }}
                </h4>
                <p class="text-sm leading-6">
                  {{ summary.operationAdvice || text.noAdvice }}
                </p>
              </div>
            </div>
          </Card>

          <Card class="p-4">
            <div class="flex items-start gap-3">
              <div
                class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-warning/10"
              >
                <TrendingUp class="size-4 text-warning" />
              </div>
              <div class="space-y-1.5">
                <h4 class="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  {{ text.trendPrediction }}
                </h4>
                <p class="text-sm leading-6">
                  {{ summary.trendPrediction || text.noPrediction }}
                </p>
              </div>
            </div>
          </Card>
        </div>

        <Card
          v-if="relatedBoards.length > 0"
          class="p-4 text-left"
        >
          <div class="mb-3 flex items-baseline gap-2">
            <span class="text-xs font-medium uppercase tracking-wider text-muted-foreground">{{
              text.boardLinkage
            }}</span>
            <h3 class="mt-0.5 text-base font-semibold text-foreground">
              {{ text.relatedBoards }}
            </h3>
          </div>

          <div class="space-y-2.5">
            <div
              v-for="(board, index) in relatedBoards"
              :key="`${normalizeBoardName(board.name)}-${board.code || index}`"
              class="flex flex-wrap items-center gap-2 text-sm"
            >
              <Badge variant="secondary">
                {{ normalizeBoardName(board.name) }}
              </Badge>
              <Badge
                v-if="board.type"
                variant="outline"
              >
                {{ board.type }}
              </Badge>
              <template v-if="boardSignals.get(normalizeBoardName(board.name))">
                <Badge
                  :variant="
                    getBoardStatusVariant(boardSignals.get(normalizeBoardName(board.name))!.status)
                  "
                  class="shadow-none"
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
                  :class="
                    getPriceChangeClass(boardSignals.get(normalizeBoardName(board.name))!.changePct)
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
        <Card class="flex min-h-0 flex-1 flex-col !overflow-visible p-5">
          <div class="flex flex-1 flex-col justify-center text-center">
            <h3 class="mb-5 text-sm font-medium tracking-wide text-foreground">
              {{ text.marketSentiment }}
            </h3>
            <ScoreGauge
              :score="summary.sentimentScore"
              size="lg"
              :language="reportLanguage"
            />
          </div>
        </Card>
      </div>
    </div>
  </div>
</template>
