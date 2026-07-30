<script setup lang="ts">
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import type { BacktestRun } from '@/types/backtests';
import { engineLabels, formatPct, marketLabels, statusLabels } from '@/utils/backtests';
import { formatDateTimeInDisplayTimezone } from '@/utils/format';
import { RouterLink } from 'vue-router';
import { ExternalLink, MoreHorizontal, RefreshCw } from 'lucide-vue-next';

defineProps<{ runs: BacktestRun[]; loading?: boolean }>();
const emit = defineEmits<{ reuse: [run: BacktestRun] }>();

function statusVariant(status: string): 'default' | 'success' | 'warning' | 'destructive' | 'info' {
  if (status === 'completed') return 'success';
  if (status === 'failed') return 'destructive';
  if (status === 'processing') return 'info';
  if (status === 'pending') return 'warning';
  return 'default';
}
</script>

<template>
  <Card>
    <CardHeader>
      <CardTitle>历史回测</CardTitle>
      <CardDescription>桌面端查看完整数据，移动端使用可操作的摘要卡片。</CardDescription>
    </CardHeader>
    <CardContent
      v-if="loading"
      class="space-y-3"
    >
      <Skeleton
        v-for="index in 4"
        :key="index"
        class="h-14 w-full"
      />
    </CardContent>
    <CardContent
      v-else-if="!runs.length"
      class="py-10 text-center text-sm text-muted-foreground"
    >
      暂无回测记录
    </CardContent>
    <div
      v-else
      class="min-w-0"
    >
      <div class="space-y-3 px-4 pb-4 md:hidden">
        <Card
          v-for="run in runs"
          :key="run.id"
        >
          <CardHeader>
            <CardTitle class="truncate text-base">
              {{ run.strategyName }}
            </CardTitle>
            <CardDescription>{{ marketLabels[run.market] }} · {{ run.code }}</CardDescription>
            <Badge
              :variant="statusVariant(run.status)"
              class="justify-self-end"
            >
              {{ statusLabels[run.status] }}
            </Badge>
          </CardHeader>
          <CardContent>
            <dl class="grid grid-cols-2 gap-3 text-xs">
              <div>
                <dt class="text-muted-foreground">
                  总收益
                </dt>
                <dd class="mt-1 font-medium">
                  {{ formatPct(run.summary.totalReturnPct) }}
                </dd>
              </div>
              <div>
                <dt class="text-muted-foreground">
                  基准收益
                </dt>
                <dd class="mt-1 font-medium">
                  {{ formatPct(run.summary.benchmarkReturnPct) }}
                </dd>
              </div>
              <div>
                <dt class="text-muted-foreground">
                  日期范围
                </dt>
                <dd class="mt-1">
                  {{ run.startDate }} — {{ run.endDate }}
                </dd>
              </div>
              <div>
                <dt class="text-muted-foreground">
                  交易次数
                </dt>
                <dd class="mt-1">
                  {{ run.summary.tradeCount ?? '—' }}
                </dd>
              </div>
            </dl>
          </CardContent>
          <CardFooter class="gap-2">
            <Button
              as-child
              size="sm"
            >
              <RouterLink :to="`/market/backtests/${run.id}`">
                查看结果
              </RouterLink>
            </Button>
            <Button
              variant="outline"
              size="sm"
              @click="emit('reuse', run)"
            >
              <RefreshCw />复用
            </Button>
          </CardFooter>
        </Card>
      </div>
      <div class="hidden px-4 pb-4 md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>创建时间</TableHead><TableHead>引擎</TableHead><TableHead>策略</TableHead><TableHead>市场 / 标的</TableHead><TableHead>日期范围</TableHead><TableHead>状态</TableHead><TableHead>总收益</TableHead><TableHead>交易次数</TableHead><TableHead class="text-right">
                操作
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow
              v-for="run in runs"
              :key="run.id"
            >
              <TableCell>
                {{ formatDateTimeInDisplayTimezone(run.createdAt) }}
              </TableCell>
              <TableCell>
                <Badge :variant="run.engine === 'backtrader' ? 'success' : 'info'">
                  {{ engineLabels[run.engine]
                  }}<span v-if="run.engine === 'backtrader'"> · 推荐</span>
                </Badge>
              </TableCell>
              <TableCell>{{ run.strategyName }}</TableCell>
              <TableCell>{{ marketLabels[run.market] }} · {{ run.code }}</TableCell>
              <TableCell>{{ run.startDate }} — {{ run.endDate }}</TableCell>
              <TableCell>
                <Badge :variant="statusVariant(run.status)">
                  {{ statusLabels[run.status] }}
                </Badge>
                <span
                  v-if="run.status === 'processing' || run.status === 'pending'"
                  class="ml-2"
                >{{ run.progress }}%</span>
              </TableCell>
              <TableCell>{{ formatPct(run.summary.totalReturnPct) }}</TableCell>
              <TableCell>{{ run.summary.tradeCount ?? '—' }}</TableCell>
              <TableCell class="text-right">
                <DropdownMenu>
                  <DropdownMenuTrigger as-child>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="回测操作"
                    >
                      <MoreHorizontal />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem as-child>
                      <RouterLink :to="`/market/backtests/${run.id}`">
                        <ExternalLink />查看结果
                      </RouterLink>
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      v-if="run.taskId"
                      as-child
                    >
                      <RouterLink :to="`/tasks/runs?taskId=${run.taskId}`">
                        打开任务
                      </RouterLink>
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem @select="emit('reuse', run)">
                      <RefreshCw />复用配置
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
                <p
                  v-if="run.status === 'failed' && run.error"
                  class="mt-1 max-w-xs truncate text-destructive"
                  :title="run.error"
                >
                  {{ run.error }}
                </p>
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>
    </div>
  </Card>
</template>
