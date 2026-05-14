<script setup lang="ts">
import { use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { PieChart } from 'echarts/charts';
import { LegendComponent, TooltipComponent } from 'echarts/components';
import VChart from 'vue-echarts';
import { usePortfolioPage } from '@/composables/portfolio/usePortfolioPage';
import {
  PORTFOLIO_FILE_PICKER_CLASS,
  PORTFOLIO_INPUT_CLASS,
  PORTFOLIO_SELECT_CLASS,
} from '@/composables/portfolio/portfolioHelpers';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import Badge from '@/components/common/Badge.vue';
import Card from '@/components/common/Card.vue';
import ConfirmDialog from '@/components/common/ConfirmDialog.vue';
import EmptyState from '@/components/common/EmptyState.vue';
import InlineAlert from '@/components/common/InlineAlert.vue';

use([CanvasRenderer, PieChart, TooltipComponent, LegendComponent]);

const {
  accounts,
  selectedAccountModel,
  showCreateAccount,
  accountCreating,
  accountCreateError,
  accountCreateSuccess,
  accountForm,
  costMethod,
  snapshot,
  risk,
  isLoading,
  fxRefreshing,
  fxRefreshFeedback,
  error,
  riskWarning,
  writeWarning,
  brokers,
  selectedBroker,
  csvFile,
  csvDryRun,
  csvParsing,
  csvCommitting,
  csvParseResult,
  csvCommitResult,
  brokerLoadWarning,
  eventType,
  eventDateFrom,
  eventDateTo,
  eventSymbol,
  eventSide,
  eventDirection,
  eventActionType,
  eventPage,
  eventLoading,
  tradeEvents,
  cashEvents,
  corporateEvents,
  pendingDelete,
  deleteLoading,
  tradeForm,
  cashForm,
  corpForm,
  hasAccounts,
  writableAccount,
  writableAccountId,
  writeBlocked,
  totalEventPages,
  positionRows,
  concentrationPieData,
  concentrationMode,
  concentrationPieChartOption,
  formatMoney,
  formatPct,
  formatSignedPct,
  formatPositionPrice,
  formatPositionMoney,
  getPositionPriceLabel,
  hasPositionPrice,
  formatSideLabel,
  formatCashDirectionLabel,
  formatCorporateActionLabel,
  formatBrokerLabel,
  getFxRefreshFeedbackVariant,
  getCsvParseVariant,
  getCsvCommitVariant,
  loadEvents,
  handleTradeSubmit,
  handleCashSubmit,
  handleCorporateSubmit,
  handleParseCsv,
  handleCommitCsv,
  openDeleteDialog,
  handleConfirmDelete,
  handleCreateAccount,
  handleRefresh,
  handleRefreshFx,
  toggleCreateAccountPanel,
  closeCreateAccountPanel,
  dismissError,
  cancelPendingDelete,
  onCsvFileChange,
  prevEventPage,
  nextEventPage,
} = usePortfolioPage();
</script>

<template>
  <div class="portfolio-page min-h-screen space-y-4 p-4 md:p-6">
    <section class="space-y-3">
      <div class="space-y-2">
        <h1 class="text-xl md:text-2xl font-semibold text-foreground">
          持仓管理
        </h1>
        <p class="text-xs md:text-sm text-secondary">
          组合快照、手工录入、CSV 导入与风险分析（支持全组合 / 单账户切换）
        </p>
      </div>
      <div
        v-if="hasAccounts"
        class="rounded-xl border border-white/10 bg-white/[0.02] p-3"
      >
        <div class="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_220px_280px] gap-2 items-end">
          <div>
            <p class="text-xs text-secondary mb-1">
              账户视图
            </p>
            <select
              v-model="selectedAccountModel"
              :class="PORTFOLIO_SELECT_CLASS"
            >
              <option value="all">
                全部账户
              </option>
              <option
                v-for="account in accounts"
                :key="account.id"
                :value="String(account.id)"
              >
                {{ account.name }} (#{{ account.id }})
              </option>
            </select>
          </div>
          <div>
            <p class="text-xs text-secondary mb-1">
              成本口径
            </p>
            <select
              v-model="costMethod"
              :class="PORTFOLIO_SELECT_CLASS"
            >
              <option value="fifo">
                先进先出（FIFO）
              </option>
              <option value="avg">
                均价成本（AVG）
              </option>
            </select>
          </div>
          <div class="flex gap-2">
            <button
              type="button"
              class="btn-secondary text-sm flex-1"
              @click="toggleCreateAccountPanel"
            >
              {{ showCreateAccount ? '收起新建' : '新建账户' }}
            </button>
            <button
              type="button"
              :disabled="isLoading || fxRefreshing"
              class="btn-secondary text-sm flex-1"
              @click="handleRefresh"
            >
              {{ isLoading ? '刷新中...' : '刷新数据' }}
            </button>
          </div>
        </div>
      </div>
      <InlineAlert
        v-else
        variant="warning"
        class="inline-block rounded-lg px-3 py-2 text-xs shadow-none"
        message="还没有可用账户，请先创建账户后再录入交易或导入 CSV。"
      />
    </section>

    <ApiErrorAlert
      v-if="error"
      :error="error"
      @dismiss="dismissError"
    />
    <InlineAlert
      v-if="riskWarning"
      variant="warning"
      title="风险模块降级"
      :message="riskWarning"
    />
    <InlineAlert
      v-if="writeWarning"
      variant="warning"
      title="操作提示"
      :message="writeWarning"
    />

    <Card
      v-if="showCreateAccount || !hasAccounts"
      padding="md"
    >
      <div class="flex items-center justify-between gap-2">
        <h2 class="text-sm font-semibold text-foreground">
          新建账户
        </h2>
        <button
          v-if="hasAccounts"
          type="button"
          class="btn-secondary text-xs px-3 py-1"
          @click="closeCreateAccountPanel"
        >
          收起
        </button>
        <span
          v-else
          class="text-xs text-secondary"
        >创建后自动切换到该账户</span>
      </div>
      <InlineAlert
        v-if="accountCreateError"
        variant="danger"
        class="mt-2 rounded-lg px-2 py-1 text-xs shadow-none"
        title="创建账户失败"
        :message="accountCreateError"
      />
      <InlineAlert
        v-if="accountCreateSuccess"
        variant="success"
        class="mt-2 rounded-lg px-2 py-1 text-xs shadow-none"
        title="创建账户成功"
        :message="accountCreateSuccess"
      />
      <form
        class="mt-3 grid grid-cols-1 md:grid-cols-2 gap-2"
        @submit="handleCreateAccount"
      >
        <input
          v-model="accountForm.name"
          :class="`${PORTFOLIO_INPUT_CLASS} md:col-span-2`"
          placeholder="账户名称（必填）"
        >
        <input
          v-model="accountForm.broker"
          :class="PORTFOLIO_INPUT_CLASS"
          placeholder="券商（可选，如 Demo/华泰）"
        >
        <input
          :value="accountForm.baseCurrency"
          :class="PORTFOLIO_INPUT_CLASS"
          placeholder="基准币（如 CNY/USD/HKD）"
          @input="accountForm.baseCurrency = ($event.target as HTMLInputElement).value.toUpperCase()"
        >
        <select
          v-model="accountForm.market"
          :class="PORTFOLIO_SELECT_CLASS"
        >
          <option value="cn">
            市场：A 股（cn）
          </option>
          <option value="hk">
            市场：港股（hk）
          </option>
          <option value="us">
            市场：美股（us）
          </option>
        </select>
        <button
          type="submit"
          class="btn-secondary text-sm"
          :disabled="accountCreating"
        >
          {{ accountCreating ? '创建中...' : '创建账户' }}
        </button>
      </form>
    </Card>

    <section class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
      <Card
        variant="gradient"
        padding="md"
      >
        <p class="text-xs text-secondary">
          总权益
        </p>
        <p class="mt-1 text-xl font-semibold text-foreground">
          {{ formatMoney(snapshot?.totalEquity, snapshot?.currency || 'CNY') }}
        </p>
      </Card>
      <Card
        variant="gradient"
        padding="md"
      >
        <p class="text-xs text-secondary">
          总市值
        </p>
        <p class="mt-1 text-xl font-semibold text-foreground">
          {{ formatMoney(snapshot?.totalMarketValue, snapshot?.currency || 'CNY') }}
        </p>
      </Card>
      <Card
        variant="gradient"
        padding="md"
      >
        <p class="text-xs text-secondary">
          总现金
        </p>
        <p class="mt-1 text-xl font-semibold text-foreground">
          {{ formatMoney(snapshot?.totalCash, snapshot?.currency || 'CNY') }}
        </p>
      </Card>
      <Card
        variant="gradient"
        padding="md"
      >
        <div class="flex items-start justify-between gap-3">
          <p class="text-xs text-secondary">
            汇率状态
          </p>
          <button
            type="button"
            class="btn-secondary !px-3 !py-1 !text-xs shrink-0"
            :disabled="!hasAccounts || isLoading || fxRefreshing"
            @click="handleRefreshFx"
          >
            {{ fxRefreshing ? '刷新中...' : '刷新汇率' }}
          </button>
        </div>
        <div class="mt-2">
          <Badge
            v-if="snapshot?.fxStale"
            variant="warning"
          >
            过期
          </Badge>
          <Badge
            v-else
            variant="success"
          >
            最新
          </Badge>
        </div>
        <InlineAlert
          v-if="fxRefreshFeedback"
          :variant="getFxRefreshFeedbackVariant(fxRefreshFeedback.tone)"
          title="汇率刷新结果"
          :message="fxRefreshFeedback.text"
          class="mt-3 rounded-xl px-3 py-2 text-xs shadow-none"
        />
      </Card>
    </section>

    <section class="grid grid-cols-1 xl:grid-cols-3 gap-3">
      <Card
        class="xl:col-span-2"
        padding="md"
      >
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-sm font-semibold text-foreground">
            持仓明细
          </h2>
          <span class="text-xs text-secondary">共 {{ positionRows.length }} 项</span>
        </div>
        <EmptyState
          v-if="positionRows.length === 0"
          title="当前无持仓数据"
          description="录入交易或导入 CSV 后，这里会展示按账户汇总的持仓明细。"
          class="border-none bg-transparent px-4 py-8 shadow-none"
        />
        <div
          v-else
          class="overflow-x-auto"
        >
          <table class="w-full text-sm">
            <thead class="text-xs text-secondary border-b border-white/10">
              <tr>
                <th class="text-left py-2 pr-2">
                  账户
                </th>
                <th class="text-left py-2 pr-2">
                  代码
                </th>
                <th class="text-right py-2 pr-2">
                  数量
                </th>
                <th class="text-right py-2 pr-2">
                  均价
                </th>
                <th class="text-right py-2 pr-2">
                  现价
                </th>
                <th class="text-right py-2 pr-2">
                  市值
                </th>
                <th class="text-right py-2">
                  未实现盈亏
                </th>
                <th class="text-right py-2">
                  收益率
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in positionRows"
                :key="`${row.accountId}-${row.symbol}-${row.market}`"
                class="border-b border-white/5"
              >
                <td class="py-2 pr-2 text-secondary">
                  {{ row.accountName }}
                </td>
                <td class="py-2 pr-2 font-mono text-foreground">
                  {{ row.symbol }}
                </td>
                <td class="py-2 pr-2 text-right">
                  {{ row.quantity.toFixed(2) }}
                </td>
                <td class="py-2 pr-2 text-right">
                  {{ row.avgCost.toFixed(4) }}
                </td>
                <td class="py-2 pr-2 text-right">
                  <div>{{ formatPositionPrice(row) }}</div>
                  <div
                    :class="`text-[11px] ${hasPositionPrice(row) ? 'text-secondary' : 'text-warning'}`"
                  >
                    {{ getPositionPriceLabel(row) }}
                  </div>
                </td>
                <td class="py-2 pr-2 text-right">
                  {{ formatPositionMoney(row.marketValueBase, row) }}
                </td>
                <td
                  :class="`py-2 text-right ${
                    hasPositionPrice(row)
                      ? row.unrealizedPnlBase >= 0
                        ? 'text-success'
                        : 'text-danger'
                      : 'text-secondary'
                  }`"
                >
                  {{ formatPositionMoney(row.unrealizedPnlBase, row) }}
                </td>
                <td
                  :class="`py-2 text-right ${
                    hasPositionPrice(row) && row.unrealizedPnlPct !== null && row.unrealizedPnlPct !== undefined
                      ? row.unrealizedPnlPct >= 0
                        ? 'text-success'
                        : 'text-danger'
                      : 'text-secondary'
                  }`"
                >
                  {{ formatSignedPct(row.unrealizedPnlPct) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>

      <Card padding="md">
        <h2 class="text-sm font-semibold text-foreground mb-3">
          {{ concentrationMode === 'sector' ? '行业集中度分布' : '行业数据暂不可用，当前展示个股集中度' }}
        </h2>
        <div
          v-if="concentrationPieData.length > 0"
          class="h-64"
        >
          <VChart
            class="h-full w-full"
            :option="concentrationPieChartOption"
            autoresize
          />
        </div>
        <EmptyState
          v-else
          title="暂无集中度数据"
          description="风险模块完成计算后，这里会展示行业或个股维度的集中度分布。"
          class="border-none bg-transparent px-4 py-10 shadow-none"
        />
        <div class="mt-3 text-xs text-secondary space-y-1">
          <div>展示口径: {{ concentrationMode === 'sector' ? '行业维度' : '个股维度（降级显示）' }}</div>
          <div>板块集中度告警: {{ risk?.sectorConcentration?.alert ? '是' : '否' }}</div>
          <div>Top1 权重: {{ formatPct(risk?.sectorConcentration?.topWeightPct ?? risk?.concentration?.topWeightPct) }}</div>
        </div>
      </Card>
    </section>

    <InlineAlert
      v-if="writeBlocked && hasAccounts"
      variant="warning"
      class="rounded-lg px-3 py-2 text-xs shadow-none"
      message="当前处于“全部账户”视图。为避免误写，请先选择一个具体账户后再进行手工录入或 CSV 提交。"
    />

    <section class="grid grid-cols-1 md:grid-cols-3 gap-3">
      <Card padding="md">
        <h3 class="text-sm font-semibold text-foreground mb-2">
          回撤监控
        </h3>
        <div class="text-xs text-secondary space-y-1">
          <div>最大回撤: {{ formatPct(risk?.drawdown?.maxDrawdownPct) }}</div>
          <div>当前回撤: {{ formatPct(risk?.drawdown?.currentDrawdownPct) }}</div>
          <div>告警: {{ risk?.drawdown?.alert ? '是' : '否' }}</div>
        </div>
      </Card>
      <Card padding="md">
        <h3 class="text-sm font-semibold text-foreground mb-2">
          止损接近预警
        </h3>
        <div class="text-xs text-secondary space-y-1">
          <div>触发数: {{ risk?.stopLoss?.triggeredCount ?? 0 }}</div>
          <div>接近数: {{ risk?.stopLoss?.nearCount ?? 0 }}</div>
          <div>告警: {{ risk?.stopLoss?.nearAlert ? '是' : '否' }}</div>
        </div>
      </Card>
      <Card padding="md">
        <h3 class="text-sm font-semibold text-foreground mb-2">
          口径
        </h3>
        <div class="text-xs text-secondary space-y-1">
          <div>账户数: {{ snapshot?.accountCount ?? 0 }}</div>
          <div>计价币种: {{ snapshot?.currency || 'CNY' }}</div>
          <div>成本法: {{ (snapshot?.costMethod || costMethod).toUpperCase() }}</div>
        </div>
      </Card>
    </section>

    <section class="grid grid-cols-1 xl:grid-cols-3 gap-3">
      <Card padding="md">
        <h3 class="text-sm font-semibold text-foreground mb-3">
          手工录入：交易
        </h3>
        <form
          class="space-y-2"
          @submit="handleTradeSubmit"
        >
          <input
            v-model="tradeForm.symbol"
            required
            :class="PORTFOLIO_INPUT_CLASS"
            placeholder="股票代码（例如 600519）"
          >
          <div class="grid grid-cols-2 gap-2">
            <input
              v-model="tradeForm.tradeDate"
              required
              :class="PORTFOLIO_INPUT_CLASS"
              type="date"
            >
            <select
              v-model="tradeForm.side"
              :class="PORTFOLIO_SELECT_CLASS"
            >
              <option value="buy">
                买入
              </option>
              <option value="sell">
                卖出
              </option>
            </select>
          </div>
          <div class="grid grid-cols-2 gap-2">
            <input
              v-model="tradeForm.quantity"
              required
              :class="PORTFOLIO_INPUT_CLASS"
              type="number"
              min="0"
              step="0.0001"
              placeholder="数量（必填）"
            >
            <input
              v-model="tradeForm.price"
              required
              :class="PORTFOLIO_INPUT_CLASS"
              type="number"
              min="0"
              step="0.0001"
              placeholder="成交价（必填）"
            >
          </div>
          <div class="grid grid-cols-2 gap-2">
            <input
              v-model="tradeForm.fee"
              :class="PORTFOLIO_INPUT_CLASS"
              type="number"
              min="0"
              step="0.0001"
              placeholder="手续费（可选）"
            >
            <input
              v-model="tradeForm.tax"
              :class="PORTFOLIO_INPUT_CLASS"
              type="number"
              min="0"
              step="0.0001"
              placeholder="税费（可选）"
            >
          </div>
          <p class="text-xs text-secondary">
            手续费和税费可留空，系统将按 0 处理。
          </p>
          <button
            type="submit"
            class="btn-secondary w-full"
            :disabled="!writableAccountId"
          >
            提交交易
          </button>
        </form>
      </Card>

      <Card padding="md">
        <h3 class="text-sm font-semibold text-foreground mb-3">
          手工录入：资金流水
        </h3>
        <form
          class="space-y-2"
          @submit="handleCashSubmit"
        >
          <div class="grid grid-cols-2 gap-2">
            <input
              v-model="cashForm.eventDate"
              required
              :class="PORTFOLIO_INPUT_CLASS"
              type="date"
            >
            <select
              v-model="cashForm.direction"
              :class="PORTFOLIO_SELECT_CLASS"
            >
              <option value="in">
                流入
              </option>
              <option value="out">
                流出
              </option>
            </select>
          </div>
          <input
            v-model="cashForm.amount"
            required
            :class="PORTFOLIO_INPUT_CLASS"
            type="number"
            min="0"
            step="0.0001"
            placeholder="金额"
          >
          <input
            v-model="cashForm.currency"
            :class="PORTFOLIO_INPUT_CLASS"
            :placeholder="`币种（可选，默认 ${writableAccount?.baseCurrency || '账户基准币'}）`"
          >
          <button
            type="submit"
            class="btn-secondary w-full"
            :disabled="!writableAccountId"
          >
            提交资金流水
          </button>
        </form>
      </Card>

      <Card padding="md">
        <h3 class="text-sm font-semibold text-foreground mb-3">
          手工录入：公司行为
        </h3>
        <form
          class="space-y-2"
          @submit="handleCorporateSubmit"
        >
          <input
            v-model="corpForm.symbol"
            required
            :class="PORTFOLIO_INPUT_CLASS"
            placeholder="股票代码"
          >
          <div class="grid grid-cols-2 gap-2">
            <input
              v-model="corpForm.effectiveDate"
              required
              :class="PORTFOLIO_INPUT_CLASS"
              type="date"
            >
            <select
              v-model="corpForm.actionType"
              :class="PORTFOLIO_SELECT_CLASS"
            >
              <option value="cash_dividend">
                现金分红
              </option>
              <option value="split_adjustment">
                拆并股调整
              </option>
            </select>
          </div>
          <input
            v-if="corpForm.actionType === 'cash_dividend'"
            v-model="corpForm.cashDividendPerShare"
            required
            :class="PORTFOLIO_INPUT_CLASS"
            type="number"
            min="0"
            step="0.000001"
            placeholder="每股分红"
            @input="corpForm.splitRatio = ''"
          >
          <input
            v-else
            v-model="corpForm.splitRatio"
            required
            :class="PORTFOLIO_INPUT_CLASS"
            type="number"
            min="0"
            step="0.000001"
            placeholder="拆并股比例"
            @input="corpForm.cashDividendPerShare = ''"
          >
          <button
            type="submit"
            class="btn-secondary w-full"
            :disabled="!writableAccountId"
          >
            提交企业行为
          </button>
        </form>
      </Card>
    </section>

    <section class="grid grid-cols-1 xl:grid-cols-2 gap-3">
      <Card padding="md">
        <h3 class="text-sm font-semibold text-foreground mb-3">
          券商 CSV 导入
        </h3>
        <div class="space-y-2">
          <InlineAlert
            v-if="brokerLoadWarning"
            variant="warning"
            class="rounded-lg px-2 py-1 text-xs shadow-none"
            :message="brokerLoadWarning"
          />
          <div class="grid grid-cols-2 gap-2">
            <select
              v-model="selectedBroker"
              :class="PORTFOLIO_SELECT_CLASS"
            >
              <template v-if="brokers.length > 0">
                <option
                  v-for="item in brokers"
                  :key="item.broker"
                  :value="item.broker"
                >
                  {{ formatBrokerLabel(item.broker, item.displayName) }}
                </option>
              </template>
              <option
                v-else
                value="huatai"
              >
                huatai（华泰）
              </option>
            </select>
            <label :class="PORTFOLIO_FILE_PICKER_CLASS">
              选择 CSV
              <input
                type="file"
                accept=".csv"
                class="hidden"
                @change="onCsvFileChange"
              >
            </label>
          </div>
          <div class="flex items-center gap-2 text-xs text-secondary">
            <input
              id="csv-dry-run"
              v-model="csvDryRun"
              type="checkbox"
            >
            <label for="csv-dry-run">仅预演（不写入）</label>
          </div>
          <div class="flex gap-2">
            <button
              type="button"
              class="btn-secondary flex-1"
              :disabled="!csvFile || csvParsing"
              @click="handleParseCsv"
            >
              {{ csvParsing ? '解析中...' : '解析文件' }}
            </button>
            <button
              type="button"
              class="btn-secondary flex-1"
              :disabled="!csvFile || !writableAccountId || csvCommitting"
              @click="handleCommitCsv"
            >
              {{ csvCommitting ? '提交中...' : '提交导入' }}
            </button>
          </div>
          <InlineAlert
            v-if="csvParseResult"
            :variant="getCsvParseVariant(csvParseResult)"
            title="CSV 解析结果"
            :message="`有效 ${csvParseResult.recordCount} 条，跳过 ${csvParseResult.skippedCount} 条，错误 ${csvParseResult.errorCount} 条。`"
            class="rounded-lg px-3 py-2 text-xs shadow-none"
          />
          <InlineAlert
            v-if="csvCommitResult"
            :variant="getCsvCommitVariant(csvCommitResult, csvDryRun)"
            :title="csvDryRun ? 'CSV 预演结果' : 'CSV 提交结果'"
            :message="`${csvDryRun ? '预演检查' : '实际写入'}：写入 ${csvCommitResult.insertedCount} 条，重复 ${csvCommitResult.duplicateCount} 条，失败 ${csvCommitResult.failedCount} 条。`"
            class="rounded-lg px-3 py-2 text-xs shadow-none"
          />
        </div>
      </Card>

      <Card padding="md">
        <h3 class="text-sm font-semibold text-foreground mb-3">
          事件记录
        </h3>
        <div class="space-y-2">
          <div class="grid grid-cols-2 gap-2">
            <select
              v-model="eventType"
              :class="PORTFOLIO_SELECT_CLASS"
            >
              <option value="trade">
                交易流水
              </option>
              <option value="cash">
                资金流水
              </option>
              <option value="corporate">
                公司行为
              </option>
            </select>
            <button
              type="button"
              class="btn-secondary text-sm"
              :disabled="eventLoading"
              @click="loadEvents"
            >
              {{ eventLoading ? '加载中...' : '刷新流水' }}
            </button>
          </div>
          <div class="grid grid-cols-2 gap-2">
            <input
              v-model="eventDateFrom"
              :class="PORTFOLIO_INPUT_CLASS"
              type="date"
            >
            <input
              v-model="eventDateTo"
              :class="PORTFOLIO_INPUT_CLASS"
              type="date"
            >
          </div>
          <input
            v-if="eventType === 'trade' || eventType === 'corporate'"
            v-model="eventSymbol"
            :class="PORTFOLIO_INPUT_CLASS"
            placeholder="按股票代码筛选"
          >
          <select
            v-if="eventType === 'trade'"
            v-model="eventSide"
            :class="PORTFOLIO_SELECT_CLASS"
          >
            <option value="">
              全部买卖方向
            </option>
            <option value="buy">
              买入
            </option>
            <option value="sell">
              卖出
            </option>
          </select>
          <select
            v-if="eventType === 'cash'"
            v-model="eventDirection"
            :class="PORTFOLIO_SELECT_CLASS"
          >
            <option value="">
              全部资金方向
            </option>
            <option value="in">
              流入
            </option>
            <option value="out">
              流出
            </option>
          </select>
          <select
            v-if="eventType === 'corporate'"
            v-model="eventActionType"
            :class="PORTFOLIO_SELECT_CLASS"
          >
            <option value="">
              全部公司行为
            </option>
            <option value="cash_dividend">
              现金分红
            </option>
            <option value="split_adjustment">
              拆并股调整
            </option>
          </select>
          <div class="text-[11px] text-secondary">
            {{ writeBlocked ? '删除修正仅在单账户视图可用。请先选择具体账户后再删除错误流水。' : '如有错误流水，可直接删除后重新录入。' }}
          </div>
          <div class="max-h-64 overflow-auto rounded-lg border border-white/10 p-2">
            <template v-if="eventType === 'trade'">
              <div
                v-for="item in tradeEvents"
                :key="`t-${item.id}`"
                class="flex items-start justify-between gap-3 border-b border-white/5 py-2 text-xs text-secondary"
              >
                <div class="min-w-0">
                  {{ item.tradeDate }} {{ formatSideLabel(item.side) }} {{ item.symbol }} 数量={{ item.quantity }} 价格={{ item.price }}
                </div>
                <button
                  v-if="!writeBlocked"
                  type="button"
                  class="btn-secondary shrink-0 !px-3 !py-1 !text-[11px]"
                  @click="openDeleteDialog({
                    eventType: 'trade',
                    id: item.id,
                    message: `确认删除 ${item.tradeDate} 的${formatSideLabel(item.side)}流水 ${item.symbol}（数量 ${item.quantity}，价格 ${item.price}）吗？`,
                  })"
                >
                  删除
                </button>
              </div>
            </template>
            <template v-if="eventType === 'cash'">
              <div
                v-for="item in cashEvents"
                :key="`c-${item.id}`"
                class="flex items-start justify-between gap-3 border-b border-white/5 py-2 text-xs text-secondary"
              >
                <div class="min-w-0">
                  {{ item.eventDate }} {{ formatCashDirectionLabel(item.direction) }} {{ item.amount }} {{ item.currency }}
                </div>
                <button
                  v-if="!writeBlocked"
                  type="button"
                  class="btn-secondary shrink-0 !px-3 !py-1 !text-[11px]"
                  @click="openDeleteDialog({
                    eventType: 'cash',
                    id: item.id,
                    message: `确认删除 ${item.eventDate} 的资金流水（${formatCashDirectionLabel(item.direction)} ${item.amount} ${item.currency}）吗？`,
                  })"
                >
                  删除
                </button>
              </div>
            </template>
            <template v-if="eventType === 'corporate'">
              <div
                v-for="item in corporateEvents"
                :key="`ca-${item.id}`"
                class="flex items-start justify-between gap-3 border-b border-white/5 py-2 text-xs text-secondary"
              >
                <div class="min-w-0">
                  {{ item.effectiveDate }} {{ formatCorporateActionLabel(item.actionType) }} {{ item.symbol }}
                </div>
                <button
                  v-if="!writeBlocked"
                  type="button"
                  class="btn-secondary shrink-0 !px-3 !py-1 !text-[11px]"
                  @click="openDeleteDialog({
                    eventType: 'corporate',
                    id: item.id,
                    message: `确认删除 ${item.effectiveDate} 的公司行为 ${formatCorporateActionLabel(item.actionType)}（${item.symbol}）吗？`,
                  })"
                >
                  删除
                </button>
              </div>
            </template>
            <EmptyState
              v-if="
                !eventLoading
                  && (
                    (eventType === 'trade' && tradeEvents.length === 0)
                      || (eventType === 'cash' && cashEvents.length === 0)
                      || (eventType === 'corporate' && corporateEvents.length === 0)
                  )
              "
              title="暂无流水"
              description="调整筛选条件或先录入一笔交易、资金流水或公司行为。"
              class="border-none bg-transparent px-3 py-6 shadow-none"
            />
          </div>
          <div class="flex items-center justify-between text-xs text-secondary">
            <span>第 {{ eventPage }} / {{ totalEventPages }} 页</span>
            <div class="flex gap-2">
              <button
                type="button"
                class="btn-secondary text-xs px-3 py-1"
                :disabled="eventPage <= 1"
                @click="prevEventPage"
              >
                上一页
              </button>
              <button
                type="button"
                class="btn-secondary text-xs px-3 py-1"
                :disabled="eventPage >= totalEventPages"
                @click="nextEventPage"
              >
                下一页
              </button>
            </div>
          </div>
        </div>
      </Card>
    </section>

    <ConfirmDialog
      :is-open="Boolean(pendingDelete)"
      title="删除错误流水"
      :message="pendingDelete?.message || '确认删除这条流水吗？'"
      :confirm-text="deleteLoading ? '删除中...' : '确认删除'"
      cancel-text="取消"
      :is-danger="true"
      @confirm="handleConfirmDelete"
      @cancel="cancelPendingDelete"
    />
  </div>
</template>
