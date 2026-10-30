# 前端指南（`web/`）

面向在本目录改 Vue 前端的代理与开发者。仓库根目录的 `AGENTS.md` 管全栈；这里只写 WebUI 的结构、约定和易踩坑点。改前端时**先沿用 `src/` 里已有模式**，不要另起一套目录或组件体系。

## 技术栈

| 层 | 选型 |
| --- | --- |
| 框架 | Vue 3.5（`<script setup lang="ts">`）+ TypeScript（`strict`） |
| 构建 | Vite 7，路径别名 `@/` → `src/` |
| 路由 | `vue-router` 4，`createWebHistory`，页面懒加载 |
| 状态 | Pinia（会话级） |
| UI | Tailwind CSS 4 + shadcn-vue（preset `reka-vega`，底层 Reka UI）+ Lucide |
| HTTP | Axios（Cookie 会话）+ 少量 `fetch`（SSE）/ WebSocket |
| 图表 | KLineChart 10.x（金融 K 线）；ECharts + `vue-echarts`（统计图） |
| 包管理 | `pnpm@11.1.3`（以 `package.json` 的 `packageManager` 为准） |

入口：`index.html` → `src/main.ts` → `App.vue`。`index.html` 在 Vue 挂载前读取 `localStorage.theme`：`light`/`dark` 直接应用；缺失、非法或 `system` 则按 `prefers-color-scheme` 解析后给 `<html>` 打 `light`/`dark`，避免主题闪烁。

## 常用命令

在 `web/` 下执行：

```bash
pnpm run dev            # Vite :5173，把 /api 代理到后端 :8000
pnpm run build          # vue-tsc + vite，产物写到仓库根 static/
pnpm run lint           # ESLint
pnpm run test           # Vitest（jsdom，离线）
pnpm run test:smoke     # Playwright，见下方「冒烟测试」
pnpm run preview        # 预览构建结果
```

开发时后端与前端分开起：后端 `uv run python main.py`（`:8000`），前端 `pnpm run dev`（`:5173`）。不要把生产请求默认打到本机；`API_BASE_URL` 默认同源，只有显式设置 `VITE_API_URL` 才覆盖。

构建产物目录是 **`../static`**（nginx / 后端静态资源），不是 `web/dist`。不要把 `static/` 里的生成文件当源码改。

## 目录怎么放

```
web/
  src/
    api/            # 按领域拆的后端客户端，统一走 apiClient
    pages/          # 路由页；市场/研究子页在 pages/market/
    components/
      ui/           # shadcn-vue 原子组件（Button、Dialog、Table…）
      app/          # 产品级封装（日期选择、确认框、API 错误条）
      forms/        # FieldInput / FieldSelect 等表单字段封装
      layout/       # Shell、PageHeader、ModuleLayout、ModuleSidebar、ModuleTabs
      */            # 业务块：stocks、quant、etf-rotation…
    composables/    # 可复用组合式逻辑
    stores/         # Pinia
    router/         # 路由表与守卫
    config/         # 应用名、主导航
    types/          # 领域类型
    utils/          # 纯函数（格式化、校验、markdown…）
    lib/utils.ts    # shadcn 生成的 cn；业务代码优先用 @/utils/cn
  public/           # 静态资源；股票索引 public/stocks.index.json
  tests/            # 跨模块治理测试（主题、title 禁令等）
  e2e/              # Playwright 冒烟
```

放置规则：

- **新页面**：`src/pages/`（或 `pages/market/`），在 `src/router/index.ts` 注册，需要出现在顶栏时同步改 `src/config/mainNav.ts`。
- **新接口**：`src/api/<domain>.ts`，类型放 `src/types/` 或与 API 同文件。页面不要直接 `axios.get`。
- **新基础控件**：先看 `components/ui/` 和 `components/app/`。没有再用 shadcn-vue 加到 `ui/`，产品语义包装放 `app/`。
- **业务块**：按功能建目录（已有 `quant/`、`stocks/`），不要堆到 `components/` 根上，也不要新建全局 `services/`。
- **纯计算**：`src/utils/`；和 Vue 生命周期/路由绑定的逻辑放 `composables/`。

## 运行时分层

```
路由页 pages/  →  composables / stores  →  api/  →  FastAPI /api/v1/*
       ↓
layout（Shell / PageHeader / ModuleLayout）+ ui/app 组件
```

`App.vue` 负责三件事：主题根节点、鉴权就绪门闩（loading / 错误重试 / `RouterView`）、全局 `Toaster`。已登录后的顶栏、主导航、用户菜单在 `components/layout/Shell.vue`。

二级模块页（市场、研究、加密货币、任务、个人中心）的固定套路：

1. 一级模块容器不展示重复的标题、英文副标题或介绍；具体子页按需使用 `PageHeader` 与操作区
2. `ModuleLayout`：桌面左侧导航 + 右侧内容，窄屏隐藏二级侧栏，通过顶部主导航或用户菜单切换页面，不在主体内容上方重复显示导航按钮；`items` 用 `RouterLink`
   个人中心例外：使用 `keepSidebarOnMobile` 在窄屏保留左侧二级导航，确保资料、密码、通知入口可达。
3. 具体内容页应展示标题和一句简要功能介绍；有三级导航时（如量化），介绍置于横向导航上方，不恢复一级模块介绍。
4. 默认插槽放 `<RouterView />` 或页内内容；`ModuleSidebar` 负责纵向导航链接与当前页面状态；量化等三级导航保留顶部横向 `ModuleTabs`，不要嵌套第二列侧栏

同一页面多子路由时，优先**一个页面组件 + 路由名区分 tab**（`ProfilePage`、`TasksPage`），不要为每个 tab 复制一整页。

## 路由与导航

路由定义在 `src/router/index.ts`。除 `/login` 外全部挂在 `Shell` 下。

| 路径 | 名称 | 含义 |
| --- | --- | --- |
| `/dashboard` | `dashboard` | 公共市场动态（登录后的默认入口） |
| `/timeline` | `timeline` | 投资时间线 |
| `/research/etf-rotation` | `research-etf-rotation` | ETF 动量轮动 |
| `/research/trend-following` | `research-trend-following` | 趋势跟踪 |
| `/research/quant` 及子路径 | `research-quant*` | 量化研究（总览 / 选股 / 数据集 / 模型 / 组合） |
| `/crypto/btc` | `crypto-btc` | BTC 交易 |
| `/market/watch-list` | `market-watch-list` | 自选股 |
| `/market/holdings` | `market-holdings` | 投资组合 |
| `/market/heatmap` | `market-heatmap` | A股/美股行业热力图，后端每15分钟刷新共享缓存 |
| `/profile/info` `/password` `/notification` | `profile-*` | 个人中心（同一页） |
| `/tasks` `/scheduled` `/runs` | `tasks*` | 任务中心（同一页） |

要点：

- `/market/holdings` 使用 `pages/market/HoldingsPage.vue`。DB 是普通股票/ETF 唯一真实持仓来源。现金独立修改，买卖不改变现金；买入复用 instrument 搜索建议并由后端校验证券主数据。API 为 `/api/v1/holdings` 与 `/api/v1/trade-engine`。个股详情可关闭 `trade_engine_enabled`（交易提醒），关闭后该持仓不进 Strategy / 主动 LLM 调仓，但仍计入账户 NAV 与 Portfolio Risk。页面展示最新正式 BUY/ADD/REDUCE/EXIT 与 LLM 最终判断。日K BST 来自 `trade_operation`，BTC BST 来自策略快照。
- `meta.public === true` 才是公开页（目前只有登录）。
- `meta.title` 用于 `document.title`（`「页面名 - Finance Analysis」`）。嵌套路由取最近一层有 title 的记录。
- ETF 轮动和趋势排名的「导出 Excel」在浏览器中导出当前筛选、排序后的完整数据（含虚拟滚动未渲染行），保留数值格式；文件名包含市场、快照日期和 official/preview。导出库按需加载，不调用后端导出接口。
- 研究走 `/research/**`，市场走 `/market/**`。加密货币走 `/crypto/**`。不要把 Quant / ETF / 趋势跟踪 / BTC 再挂到 `/market`。
- 旧 `/market/quant*`、`/market/etf-rotation`、`/market/trend-following`、`/market/crypto/btc` 只作为 compatibility redirect，内部导航必须用 canonical URL。
- 加密货币使用 `CryptoPage` 二级侧栏，BTC 子页保留自身介绍；任务中心顶栏下拉与侧栏共用 `taskNavItems`，定时任务仅向管理员显示。
- BTC 的旧 `/research/crypto/btc` 同样重定向到 `/crypto/btc`；一级“加密货币”菜单位于“任务中心”之前。
- `/chat` 只保留到 `/dashboard` 的 legacy redirect，前端不再有问股或个股分析页面。
- 量化范围用 query `?market=US|CN`。在量化子路由之间跳转时，守卫会保留已有 `market`。读写市场用 `useQuantMarket()`，不要手写丢 query 的 `router.push`。
- 顶栏菜单数据在 `src/config/mainNav.ts`，和路由表分开维护。加入口时两处都要改，并补 `src/config/__tests__/mainNav.test.ts` 一类断言。
- `/tasks` 由 `TasksPage` 按角色转到子页：管理员进入 `/tasks/scheduled`，普通用户进入 `/tasks/runs`。

## 统一证券详情

市场热力图按行业纵向浏览紧密矩形块，宽屏可两列行业；显示快照内全部股票，小块可隐藏文字但保留方块；密集行业向下扩展。块内名称/代码与涨跌幅按尺寸显示，完整信息放悬浮提示。
详情使用 `App.vue` 的唯一 `StockDetailHost`；页面只调用 `useStockDetail().open()`，不要重复挂 Host。

`components/stocks/StockDetailDialog.vue` 是股票/ETF 唯一详情弹窗壳，顶部页签在行情、持仓、期权、趋势、ETF 轮动、共振、盘中确认、量化与龙虎榜之间切换。各研究页仍保留列表与筛选；证券名称/代码入口统一打开首位「行情」；点击行或卡片其余区域保留原研究页签。以 `initialTab` 和 `StockDetailContext` 传来源日期、official/preview、账户/持仓及龙虎榜筛选。量化旧详情 URL 只作同一弹窗的兼容入口。

`StockIdentity` 统一组合显示代码与加粗名称；`StockLink` 的名称与代码均可打开同一详情，阻止冒泡触发行/卡片动作。无页面专用弹窗时通过 `useStockDetail` 复用 App 根组件唯一的 `StockDetailHost`，已有弹窗通过 `onSelect` 保留行情与账户上下文。名称缺失时共享精确主数据查询，不使用模糊匹配补名；查不到明确显示「名称暂缺」。表单选择、当前详情标题及短暂图表悬浮读数保持各自语义。

通用日/周/月 K、蜡烛形态和结构只在「行情」加载，研究面板保留自身指标/排名历史图；「持仓」保留账户专用买卖 BST 日 K。原跨模块研究摘要保存在独立「研究概览」，不在「行情」触发研究接口。图例名称/代码打开详情，独立色标按钮负责隐藏/显示曲线。

CN/US 详情头部通过 `/stocks/{code}/classification` 读取当前行业归属及轮动池关联 ETF；显示观测时间，ETF 名称/代码和可展开的中文代理理由。近似关联不代表实际持仓；切股票/关闭后取消旧请求。

`components/stocks/detail/` 的面板独立读取既有 API，只有当前页签挂载；切证券、日期、页签或关闭后必须作废旧请求。404/不适用显示空态，接口失败保留独立重试。持仓为当前真实账户；盘中确认按 `context.tradeDate` 读取持久化历史，未提供日期时读取当日；缺少历史不回退当日。行情优先使用匹配证券的自选行情，否则激活行情页签时请求既有只读 Redis `/stocks/{code}/quote`；保留时间戳与缺失值，不承诺额外轮询。

## 鉴权

Cookie 会话，`apiClient` 设了 `withCredentials: true`。

登录是两步：查邮箱 `POST /api/v1/auth/lookup` → 设密或输入密码 → `POST /api/v1/auth/login`。未设密账号走 `setup` 步。登出后要 `fetchStatus()` 清本地态。

守卫是双保险：

- `router.beforeEach`：未登录且非 public → `/login?redirect=`
- `App.vue` 的 `watch`：状态变化后再纠一次

`401` 由 Axios 拦截器整页跳到登录。不要在业务页自己实现一套登录跳转。

会话状态用 Pinia `useAuthStore`；组件里可用 `useAuth()`（对 store 的薄封装）。

## API 层

`src/api/index.ts` 是唯一 Axios 实例：`baseURL = API_BASE_URL`（默认 `''`）、超时 60s、JSON、Cookie。响应拦截器会：

1. `401` → 跳登录
2. `attachParsedApiError` 把错误打成 `ParsedApiError`（标题、用户可读说明、category）

页面展示错误用 `getParsedApiError` + `AppApiErrorAlert`，不要把原始 `error.message` 直接丢给用户。分类逻辑在 `src/api/error.ts`（LLM 未配置、本机连不上、上游超时等）。

领域模块：`auth`、`watchList`、`stocks`、`quant`、`etfRotation`、`trendFollowing`、`timeline`、`tasks`、`realtimeMarket`。`portfolio.ts` 仍在源码中，但其后端路由已移除，属于已知前端遗留，不应作为可用 API 范例。后端 `/api/v1/agent/*` 仍存在，但前端不再封装问股 API。个股分析 REST（`/api/v1/analysis`、`/api/v1/history`）已移除，前端不再调用。

约定：

- 请求路径走 `/api/v1/...`。
- 后端 snake_case 时，在 API 模块里用 `toCamelCase()` 再交给页面；**不要在 Vue 里散落 `stock_code` 字段访问**。
- 少数接口（如部分 auth JSON）后端已是 camelCase，保持原样，不要双重转换。
- 行情 WS/SSE 报价与盘中快照在 `realtimeMarket.ts` 的 `parseRealtimeQuoteMessage()` / `toRealtimeQuote()` 统一转换；`trend_1m`/`pattern_1m` 显式映射为 `trend1m`/`pattern1m`，不要对含数字后缀或以证券代码为键的对象直接 deep camelCase。
- 行情推送：`useRealtimeQuotes()` 优先 WebSocket，连续两次连接/快照超时失败后固定回落 HTTP SSE；SSE 断开仅重试 SSE。`4401`/`4403` 或 SSE 401/403 视为未授权，停止重连，其中 `4401`/SSE 401（会话失效）与 HTTP 401 一样跳转登录；页面在后台超过 60 秒断开并显示暂停，回到前台重连；切市场与卸载取消旧连接。

排名显示统一复用 `utils/rank.ts`，保留名次并显示“前 xx%”（名次 ÷ 原始排名范围总数）。
证券排名分母必须匹配日期、市场、策略周期、Universe 和模型批次；搜索、分页或只显示 Top N 不缩小分母。
候选内、推荐内和共振当前结果内的顺序须标明范围；历史/Preview 各用对应批次，分母缺失显示“百分比暂无”，不得用最大名次推算。

## 语言边界

当前没有 `vue-i18n`。全站标签采用「中文为主 + 英文 muted 小号副标题」双语：

- 词汇表与枚举显示：`src/i18n/labels.ts`（`metricLabels` / `enumLabels`）。
- 复用组件：`BilingualLabel`（指标/区块/表头）、`BilingualEnum`（业务枚举展示；**不改 API 字段**）。
- 表头空间紧时用 `compact`：只显示中文，英文只保留在 `aria-label`（禁止原生 `title`）。
- `BilingualEnum` 的 `size="badge"`（Badge/pill/chip）默认 compact；KPI 大字用 `size="large"` 并保证标签在上、数值在下（`w-full` / block）。
- `PageHeader`：中文 `title` 为主，可选 `en` 为小号 muted 副标题（永远在中文下方，禁止英文 eyebrow 压在标题上）。
- 按钮与普通操作文案（刷新、交易日、筛选等）只用中文。
- `IndicatorHelpLabel` 已包装 `BilingualLabel`；新增指标标题优先走 glossary key。
- 术语表见 `glossaryNotes`（原 `provisionalTranslations`）。

`index.html` 当前仍为 `lang="en"`，这是已知的文档/可访问性差距，不应据此判断界面主语言。

## 状态

| Store | 实现 | 用途 |
| --- | --- | --- |
| `authStore` | Pinia | 登录态、当前用户、lookup/login/logout |
| `timezoneStore` | Pinia | 展示时区 `Asia/Shanghai` \| `America/New_York`，写入 `localStorage` |

选择：和壳层/鉴权/时区相关 → Pinia，组件用 `storeToRefs`。

主题不是 store：`useTheme()` 模块级 ref，`ThemeProvider` 在挂载时 `initThemeRuntime()`。默认主题偏好是 `system`（跟随系统）；`resolvedTheme` 才是最终渲染的 `light`/`dark`。已有 `light`/`dark` 存储值会继续生效。系统主题变化时由 `matchMedia('(prefers-color-scheme: dark)')` 同步 `systemPrefersDark`。

## 页面与组合式函数

| 组合式函数 | 作用 |
| --- | --- |
| `useAuth` | 对 `authStore` 的稳定 API |
| `useTheme` | 主题偏好（`system` / `light` / `dark`）与 `documentElement` class |
| `useQuantMarket` | 量化 `market` query |
| `useRealtimeQuotes` | 自选/持仓 WebSocket 与 HTTP SSE 降级 |
| `useAutocomplete` | 证券主数据搜索建议（debounce 请求搜索 API） |
| `useCurrentTime` | 随展示时区走的当前时间 |

股票代码补全请求 `/api/v1/stocks/search`：以前端不再读取静态股票索引，输入时 debounce 请求后端搜索代码、native code 和名称。 <!-- pragma: allowlist secret -->

## UI 与样式

- 设计令牌在 `src/index.css`：shadcn **neutral** 底，品牌粉 `--brand` 只给 Logo、主 CTA、焦点环和少量选中态。涨跌用 `--market-up`（红）/ `--market-down`（绿），A 股习惯，不要改成绿涨红跌。
- 原子组件从 `@/components/ui/<name>` 按 `index.ts` 具名导入。变体用 `class-variance-authority`；主按钮默认即 brand。
- 产品级控件优先复用：`components/app/` 下的 `LoadingButton`、`AppConfirmDialog`、`AppDatePicker` / `AppDateTimePicker` / `AppTimePicker`、`AppCombobox`、`AppPagination`、`AppApiErrorAlert`，以及 `components/forms/` 下的 `FieldInput` / `FieldSelect`。
- 类名合并用 `cn()`（`@/utils/cn`）。`components.json` 的 `utils` 别名指向这里。
- 图标用 `lucide-vue-next`。
- **禁止**给常见可交互元素加原生 `title=`（改用 `Tooltip` 或 `aria-label`）。`tests/ui_governance.test.ts` 会扫全仓。
- **禁止**使用 `input-terminal` 类名（同上治理测试）。
- 弹层不要改 `document.body` 的 `overflow` / `paddingRight` 造成顶栏位移；冒烟测试会查这一点。
- 根滚动条使用 `scrollbar-gutter: stable`，路由切换时不要让页面左右跳。
- WebUI 面向桌面优先，并做基础响应式适配：去掉根 `min-width: 1200px`；`<1024px`（`lg`）顶栏通过点击 Logo 打开左侧抽屉导航，不显示独立汉堡按钮；表格在容器内横向滚动，页面本身不横向溢出；卡片/统计格子可换行；弹窗限制在视口内。验证 390 / 768 / 1024 / 1280 / 1440 / 1920px。
- 标签语言：中文为主、英文 muted 小号副标题。复用 `BilingualLabel` / `BilingualEnum` 与 `i18n/labels.ts`；表头空间紧时用 `compact`（英文只保留在 `aria-label`）。按钮与普通操作文案只用中文。业务枚举仅改展示，不改 API 字段。
- Dashboard 按市场结构、Trend Market Regime、ETF/Trend Changes、Timeline、Quant Signals/BTC overview 排序；市场环境通过 `/trend-following/dashboard` 读取正式 Trend 的 0–100 分数、breakdown、完整变化计数和最多3条变化摘要，不下载 ranking 明细，不请求 Quant Regime 或展示风险敞口。不得读取持仓、自选股、分析历史等私人数据；各模块独立加载和失败。

新增 shadcn 组件：按 `components.json` 生成到 `src/components/ui/`，不要改 aliases，不要另开一套 primitive。

## 测试

| 类型 | 位置 | 怎么跑 |
| --- | --- | --- |
| 单测 | 与源码同目录的 `__tests__/*.test.ts`，以及 `tests/*.test.ts` | `pnpm run test` |
| 治理 | `tests/ui_governance.test.ts`、主题 bootstrap | 同上 |
| 冒烟 | `e2e/*.spec.ts` | `pnpm run test:smoke` |

单测约定：

- 默认离线。用 `vi.mock('@/api/...')` 或 `page.route`，不要打真后端。
- 页面测试用 `createMemoryHistory` + `mount`，需要登录态时挂 `createPinia()`。
- 路由/导航/tab 选择用 `data-testid`（已有 `module-tabs`、`login-email`、`quant-market-switcher` 等），新增关键控件时补上。
- 改了纯函数、store、API 适配、页面契约，就在对应 `__tests__` 补断言。

冒烟测试：

- Playwright 会按 `playwright.config.ts` 启动后端和前端（`:4173`）。配置中的
  `main.py --webui-only --host ... --port ...` 参数目前由兼容入口忽略，后端实际仍读取
  `SERVER_HOST` / `SERVER_PORT`（默认 `0.0.0.0:8000`）；不要把这些 CLI 参数当作受支持的运行时配置。
- Playwright 的 webServer 当前用 `npm run dev` 启前端；运行 smoke 时除 pnpm 外也要确保 npm 可用。
- 需要真登录的用例依赖 `FA_WEB_SMOKE_PASSWORD`（可选 `FA_WEB_SMOKE_EMAIL`）。
- `FA_WEB_SMOKE_BACKEND_CMD` 可覆盖 Playwright 后端启动命令；`VITE_API_URL` 只覆盖浏览器 API base URL。
- 布局/控件可用性用例用 `mockAuthenticatedSession` 拦 `/api/v1/**`，不依赖真实数据。
- 无障碍：关键按钮用可访问名字，不要靠 `title`。

日常 `pnpm run test` 以 `vitest.config.ts` 和 `src/setupTests.ts` 为准；不要依赖
`vite.config.ts` 中使用 `tests/setup.ts` 的内嵌 test 块。不要为了本地方便去改代理目标或把测试改成连外网。

## 改功能时的检查清单

1. 路由、`mainNav`、页面 `ModuleLayout` 三者是否一致。
2. 未登录路径是否仍被守卫拦住；公开页是否标了 `meta.public`。
3. 量化跳转是否带上 `market` query。
4. 错误是否经过 `parseApiError` / `AppApiErrorAlert`。
5. 有没有引入原生 `title` 或 `input-terminal`。
6. 深浅色、桌面顶栏、空态与加载骨架是否还站得住。
7. 单测或治理测试是否覆盖新契约。

## 不要做的事

- 不要在仓库根再建 `api/`、`bot/`、`services/` 之类的前端目录。
- 不要在页面里 new Axios 或写死 `http://localhost:8000`。
- 不要把 Pinia store 改成 Options API。
- 不要把 shadcn `ui/` 组件改成业务耦合实现；业务变体放到 `app/` 或领域目录。
- 不要提交 `node_modules`、`playwright-report`、`test-results`，以及构建生成的 `static/` 内容（除非任务明确要求更新静态资源）。

## BTC 页面

`/crypto/btc` 位于一级“加密货币”导航。`useBinanceBtcMarket()` 直接访问 Binance REST 与单一 WS，支持1m/5m/15m/1h/4h/1D/1W/1M，断线自动重连，无 HTTP 轮询兜底。`useCryptoStrategy()` 独立读取后端策略，传输、错误、加载状态不得与行情混合。
`BtcKlineChart` 使用已加载K线映射BUY/EXIT overlay，点击查看策略详情；Performance由后端快照派生，当前浮盈用浏览器Binance price计算。
`BtcKlineChart` 是 `MarketKLineChart` 的轻量 wrapper，已闭合 history 与单根 current 分开传入。统一图表使用 KLineChart 10.x 的 data loader / subscription API，卸载时 dispose。单证券日 K 使用 `DailyKLineCard` 独立请求 `/api/v1/market-data/daily-bars/{symbol}`；历史策略详情传返回快照的 tradeDate 作为 highlightDate，行情加载至最新并标记查看日；endDate 仅用于明确需要截断的图表。


BTC 多策略以 `strategy_key + symbol` 隔离，代码注册表当前仅 `btc_breakout_v1`。共享 Binance REST 窗口、独立 catch-up 与状态行锁；仓位变化保存于 snapshot，绩效/CAGR/负值回撤动态派生，selector 不影响行情连接。详见 `../docs/crypto-btc.md`。

## 消息中心

`/notifications` 仅从头像菜单进入，使用 `/api/v1/notifications` 列表/详情，不显示 uid 或推送状态。Timeline 仅展示财经事件与新闻，不提供报告消息。

## 行业强度

`/research/industry-strength` 位于一级“加密货币”导航；排行、矩阵、全部行业热力历史通过统一居中详情 Dialog 联动，初次加载不自动打开。
历史快照 Breadth 与最新成分表分开标注；成分表显示任务更新时间，Trend Rank 为物化时最新 CN 正式排名，不随历史日期变化。
成分表所有列复用 SortableTableHeader 本地排序，缺失始终最后，同值按股票代码稳定排序。
仅展示 A 股市场环境，不增加市场切换或交易建议，数据源密钥不得进入 WebUI。

## 龙虎榜资金流向

`/research/dragon-tiger-flow` 在研究导航，复用 ECharts、统一日期/错误/排序/详情组件。
页面概览、详情、正负贡献与导出来自同一响应批次；筛选切换清旧数据并用请求代次防竞态。
3日榜隐藏累计窗口/轨迹；不添加盘中预览。游资缺值不是零，分类可能重叠，不推算“其他”。
管理员可提交收盘采集或最近20交易日补齐，返回任务中心跟踪。见 `../docs/dragon-tiger-flow.md`。

## 股票 K 线周期与范围

`DailyKLineCard` 支持日／周／月 K，统一请求最近 5 年日线，无独立范围选择；切换周期复用已加载数据，不重复请求。
周线按交易日期的周一分组，月线按自然月分组，由前复权日线聚合 OHLCV；缺日不补零，
成交额只要有一天缺失就保留为空。显示实际起止日期与根数，首尾周期可能不完整。
研究查看日映射到所在周期，日线形态和 BST 只在日 K 展示；MA5/10/20 按当前周期计算。
仍复用 daily-bars 的 db_latest 与当天临时日 K 逻辑，可能请求外部数据且不写库。
当天临时日 K 由后端独立请求该股报价后拼接进多日响应，不依赖证券是否在自选／持仓的 Streamer 采集池中；不要将日 K 接口改为 Redis 缓存专用读取。

## 日 K Price Action

`DailyKLineCard` 用 `utils/dailyPatterns.ts` / `dailyStructures.ts` 纯函数分析已加载日线，15种蜡烛形态（十字星中性）与箱体、双顶／底、三角及突破回测结构仅用于研究展示。
独立 `daily-patterns` / `daily-structures` overlay 与 BST / `research-date` 共存；只显示 Quality ≥70，蜡烛同日最多一个，结构历史保留全部状态事件。
图上只画小标记，悬停证据在图下显示；结构边界仅点击后显示并可隐藏。结构状态与日 K 收盘状态分开，拐点需要右侧两根已完成日 K，不允许用未来数据回填识别日期。
当日 K 无可靠收盘标志时保守显示 Preview，不按名义收盘时间自动确认。规则与测试见 `../docs/daily-patterns.md`。

## 用户头像

沿用个人中心裁剪 UI 与 URL 展示，源文件/上传文件上限均为 5 MiB。
后端统一生成 256×256 WebP（quality 82），存独立 `user_avatar` BYTEA 表；上传返回随机版本 URL，
刷新用户资料后自动更新顶栏和个人头像。删除接口 `DELETE /auth/avatar`，不新增 UI。见 `../docs/user-avatars.md`。

## 研究页面性能边界

趋势页通过轻量 `/trend-following/status` 与 `/preview/status` 选择默认模式，
正式 `/ranking/table` 和预演 `/preview/ranking` 使用列名一次传输的完整排名格式，由 API 模块还原类型。
不得恢复预演首屏先下载正式排名的串行流程，或删减完整本地筛选、排序和导出的股票集合。
趋势与 ETF 的 Preview 详情读取 `/preview/stocks/{code}`，必须带来源日期（趋势另带周期），不下载全市场预演。
行业 Preview 列表读取 `/preview/ranking`，成分按行业和列表生成时间读取；版本过期显示刷新提示，不混用正式成分。
首次鉴权共享进行中的状态请求；登录、退出和显式重试会开启新代次，旧响应不得覆盖新会话状态。
统一证券弹窗的行情和期权面板按需加载，避免各研究页首屏引入完整图表依赖。

市场自选与持仓表复用 `IntradayStockPanel`，点名称保留详情、点普通单元格展开。最近交易日分钟图仅展开时增量读取 `/market-data/intraday/{symbol}`，所有报价只读 Redis，无外部取价回退。CN5秒采样、US原生分钟线共用 `intradayDirection.ts`，显示日内方向状态，不再显示0DTE/CALL/PUT。
分钟图用 `intradayPatternOverlay.ts` 仅画 ▴ 多／▾ 空／◇ 中性，同一分钟取最新观测事件；点击后才在图下显示完整证据及关键价位线，同分钟其他事件可切换查看。
自选／持仓表与展开分钟图的日内方向时钟使用 `useCurrentTime(1_000)`；报价／接收时间相对判断时间均允许 ±30 秒（含边界），超出分别显示行情延迟／行情超前，缺失或无效显示时间异常。已完成分钟趋势按起始时间单独使用180秒窗口，超出显示趋势更新延迟。

## 股票策略模拟

一级“策略”位于“研究”后，`/strategies?market=CN|US`为列表，`/strategies/:strategyKey`为详情，跳转保留市场。
复用市场开关、表格、ECharts和StockLink；详情显示规则适配、净值/回撤、模拟持仓、下一开盘计划和分页每日账本。
失败/等待显示对应日期和原因，同时保留最后成功结算日；历史补算计划不能当作当前待执行计划。
字段转换须保留`positions`/`exits`里的canonical证券代码键。见`../docs/stock-strategies.md`。

CN 自选/持仓展开分钟图使用完整原生当日窗口（full_snapshot），更新时替换而非跨源拼接。以 quote.pre_close 绘制昨收0%线，时间轴固定显示09:30/15:00及午休边界，不填未来OHLC；日线与US/HK图不使用此固定时段。见 docs/cn-minute-sources.md（仓库根）。

## 多信号共振 V2

研究共振页分主要/辅助8家族，显示缺失及归一权重。V2.2最多50行研究排行，每页10行；每市场每日最多10个精选，其他为观察，低于保存门槛额外标注。详情复用`components/confluence/ConfluenceEvidence.vue`，显示20/40/60日×趋势/突破/反弹矩阵。V1历史保留原有权重；空榜宏观背景从run manifest读取。不得把期权活跃度展示为看涨信号或将缺失补0。

Confluence V2.1表格“宏观适配”按行业评分，全市场卡片只展示宏观背景；详情列出档案/因子/系数/增减分/缺失原因。
V2历史仍标“宏观环境”并说明统一风险偏好语义，不用V2.1重算历史GET。

信号中心 `/research/signal-center` 每市场0–3只股票/ETF，所有来源统一5桶初筛；逐只展示证据与evaluation，旧单推荐兼容投影，不把首只收益当市场合计。详见`docs/signal-center.md`。
