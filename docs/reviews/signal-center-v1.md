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
