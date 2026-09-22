# Signal Center v1 自审与龙虎榜修复记录

基于最新 `main`（51028e2c），未覆盖原工作区 Quant 改动。此记录描述代码审查与只读核对，不是策略收益验证。

## 第一轮：持久化、输出契约与幂等

检查 signal_center service/prompt、ORM、migration、repository。

- 输入首次调用前落库，最终市场/日期唯一；session advisory lock 与 DB PK 双重保护。
- 成功初筛批次保存，失败最终调用复用历史输入，不重新查询当前数据。
- 修复 SQL CHECK 的 NULL 三值逻辑缺口，completed 必须显式有 decision。
- 真实调用发现 fenced JSON；允许单围栏，继续拒绝未知 symbol、多对象、重复键与非法 BUY/NO_TRADE 组合。
- 删除重复大诊断上下文；保留实际使用的原始 source 字段，不新增分数。
- CLI 默认模型没有回传名称时明确标记 unreported，不假称已知模型版本。

## 第二轮：来源日期、调度与失败边界

检查源表、TaskRecord、原 Quant callback、Beat 定义、实际 Docker 数据。

- 主动 pull，未修改任一生产者任务或增加 callback；使用原有注册、队列、生命周期。
- exact-day 证据，陈旧 Quant 显式 stale；同日运行中的来源不能算完成。
- 行业必须同日最新且同代次成员；不同日期的成员不用于历史解释。
- CN/US 时区和收盘判断独立，截止前等待、截止后部分输入运行/不足跳过。
- 保留 main 新增盘中确认，它只存 Redis 当日临时状态，不强行接入每日正式决策。
- 合并最新 main 时检查并修复 schedule 定义上下文冲突，更新精确注册集合测试。

## 第三轮：前端、金额口径与整体差异

检查 API camelCase 转换、导航高亮、历史 Dialog、龙虎榜端到端数据链、测试与 PR diff。

- 修复 CN/US 字典键被通用 camelCase 转换的问题，增加真实 snake_case API 响应断言。
- 研究二级导航显式识别 Signal Center，避免回落到 Quant 高亮。
- 历史列表只查摘要列，不反复加载大量输入 JSON。
- 龙虎榜数据库有数据，默认20日窗口却缺3天，309个概念金额全为null；维持严格区间缺失语义，新增默认单日与完整股票浏览。
- 股票净额使用去重后的 symbol/date 原始金额，其他金额加总对应概念分摊；避免把一只股票多概念重复累计。
- 不完整窗口明确标记“已采集日合计”，不是区间总额；机构/游资未知不变为0。
- 全部席位样本有独立入口；仍不把席位样本等同于完整游资。
- 只增加本任务改动，未删除 main 的盘中确认或龙虎榜上游周期解析修复。

## 龙虎榜只读核对证据

来源：本地生产 Docker PostgreSQL `dragon_tiger_flow_batch`，经现有 repository/calculator 读取，没有补写或刷新来源。
最新存储日 2026-09-21：全部源 66 条记录（包含不同榜单周期）。单日1日榜52只股票、86个概念、136条分摊证据、40条席位样本。
5日窗口165只股票、210个概念，完整；20日窗口435只股票、309个概念、2243条分摊证据、727条席位样本，缺2026-08-25/08-28/09-02。
缺日导致严格区间概念金额0个可展示，属于覆盖率与默认视图共同造成的可用性问题，而非前端应将空值补零。
现有快照仍落后于应有收盘日；页面继续提示具体日期，不把旧结果标成今天。

## 验证方式

- 离线契约：候选池、初筛覆盖、跨市场/日期/候选校验、NO_TRADE、坏输出、failed/skip、锁竞争、失败重试、历史只读。
- 独立临时 PostgreSQL 容器：迁移 upgrade/downgrade 对齐 ORM、CHECK/唯一键、同代次行业与前次 Trend 日期边界。
- 生产 CLI dry run：只读正式来源、调用现有 LLMClient；不写生产 signal 表、不通知、不下单，结果只保留临时测试文件。
- Web：类型检查、lint、Vitest，包括市场字典键、历史读取、全部股票守恒与缺失语义。

## 最终验证结果

- 本次相关后端：107 passed / 1 skipped，包含独立 PostgreSQL 迁移与约束测试；最后一次精简查询后再次通过。
- 后端完整离线测试：2357 passed / 28 skipped / 2 deselected / 92 subtests passed，5 failed。syntax、仓库 flake8 与 deterministic 检查通过。
- 5 个失败在干净的同一 main 基线逐一复现：`test_llm_usage::test_removed_api_and_request_surface`、`test_unified_instrument_universe::test_removed_domains_are_absent_from_current_schema_and_api`，以及 `tests/trade_engine/test_market.py` 的 yfinance fallback / Longbridge pull / Fuyao snapshot 时间戳测试；没有为此修改无关行为。
- Web build 通过；lint 0 errors，337 个现有 warnings；完整 Vitest 90 files / 595 tests passed。
- Signal Center / 龙虎榜 Playwright 14 passed，覆盖 1280/1440/1920、light/dark 与详情交互；检查实际截图。最后历史卡片措辞改为“当日不交易”，相关 4 项单测与 6 项浏览器测试再次通过。
- 最终只读生产 DB 查询复核：CN 213 / US 54 候选，现有支持的 source 全部 available；查询精简没有改变候选规模。
- 使用生产现有 CLI 配置完成两市场真实 LLM 测试；结果未写生产业务库。测试用于接口、大小与结构验证，不代表策略收益验证。


## 追加收益回看：三轮自审

1. **时间与计算**：核对 next-open 基准严格晚于实际 completed_at，1D 是该开盘至当日收盘；覆盖周末、US 夏令时/感恩节提前收盘、CN 日历与延迟生成。MFE/MAE 相对入场，收盘回撤相对路径高点，避免混为一个指标。
2. **数据与边界**：单次查询精确 symbol/date 集合；只读已收盘 DB 前复权 OHLC，零成交/非法 OHLC 视为不可用，缺行不导致 horizon 位移。NO_TRADE 不查日线；原始 analysis/snapshot 不修改。日历失败不按周一至周五猜测。
3. **API 与页面**：独立 evaluation 契约，收益小数统一转百分比，区分未到期、缺行情与不适用；详情明确基准/目标日期、观察天数、MFE/MAE/收盘回撤及实际成交限制。检查 1280/1440/1920 明暗主题截图与历史详情；修正浏览器测试 BUY fixture 的理由和各 horizon 日期。

追加验证：相关后端119 passed / 1 skipped（含临时独立 PostgreSQL 精确日期查询）；完整 Web 91 files / 597 tests passed；build 与新增改动 lint、仓库 flake8 通过；Signal Center Playwright 6 passed。
生产 Docker DB 只读联调使用明确标记的合成信号 fixture（并非真实历史推荐），CN/US 均完成10日窗口，正确处理两市场不同休市日；没有写入生产业务数据，也没有调用 LLM。
评价随已入库行情更新，并不冻结为历史决策证据；原始推荐与分析仍不可变。完整后端原有5个基线失败说明保留于上文，本次没有重复修改或运行无关代码来掩盖它们。

## 固定5桶初筛：三轮自审

1. 分配规则：Trend候选按原始rank升序、同rank按代码排序，以排序序号模5轮流入桶；验证0/1/3/5/6/51/210候选、反向代码顺序与同rank，候选不重不漏，人数最多相差1。
2. 历史与重试：首次调用前把5桶完整名单保存到candidate_snapshot；模拟第3桶失败，重试只调用尚未完成的桶且不读当前来源。旧signal-center-v1冻结任务保留原40只批次，已完成输出不重新解释；新版本为signal-center-v1.1-rank-buckets。
3. 调用与最终集合：空桶不调用、非空桶顺序走现有LLMClient；每桶仍选0–5，初筛结果与Quant/行业提名合并终审。分桶完整名单留在原始快照，不额外塞入最终候选上下文。检查文档与PR调用次数同步。

验证：相关后端126 passed / 5 skipped（4项需要独立PostgreSQL的既有测试本轮未启动容器，另1项原有skip）；仓库flake8、diff检查通过。
对之前真实LLM dry run所保存的冻结候选输入运行新分桶：CN为42/42/42/42/42，US为11/10/10/10/10。本次未重复收费LLM调用；初筛输出结构与调用基础设施未改。
