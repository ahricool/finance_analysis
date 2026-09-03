# 前端指南（`web/`）

面向在本目录改 Vue 前端的代理与开发者。仓库根目录的 `AGENTS.md` 管全栈；这里只写 WebUI 的结构、约定和易踩坑点。改前端时**先沿用 `src/` 里已有模式**，不要另起一套目录或组件体系。

## 技术栈

| 层 | 选型 |
| --- | --- |
| 框架 | Vue 3.5（`<script setup lang="ts">`）+ TypeScript（`strict`） |
| 构建 | Vite 7，路径别名 `@/` → `src/` |
| 路由 | `vue-router` 4，`createWebHistory`，页面懒加载 |
| 状态 | Pinia（会话级）+ `vue-zustand`（跨页业务态） |
| UI | Tailwind CSS 4 + shadcn-vue（`reka-vega` / Reka UI）+ Lucide |
| HTTP | Axios（Cookie 会话）+ 少量 `fetch`（SSE）/ WebSocket |
| 图表 | ECharts + `vue-echarts` |
| 包管理 | `pnpm@11.1.3`（以 `package.json` 的 `packageManager` 为准） |

入口：`index.html` → `src/main.ts` → `App.vue`。`index.html` 在 Vue 挂载前用 `localStorage.theme` 给 `<html>` 打 `light`/`dark`，避免主题闪烁。

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
      layout/       # Shell、PageHeader、ModuleTabs
      */            # 业务块：chat、report、stocks、quant、history…
    composables/    # 可复用组合式逻辑
    stores/         # Pinia / zustand
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
- **业务块**：按功能建目录（已有 `chat/`、`report/`、`quant/`、`stocks/`），不要堆到 `components/` 根上，也不要新建全局 `services/`。
- **纯计算**：`src/utils/`；和 Vue 生命周期/路由绑定的逻辑放 `composables/`。

## 运行时分层

```
路由页 pages/  →  composables / stores  →  api/  →  FastAPI /api/v1/*
       ↓
layout（Shell / PageHeader / ModuleTabs）+ ui/app 组件
```

`App.vue` 负责三件事：主题根节点、鉴权就绪门闩（loading / 错误重试 / `RouterView`）、全局 `Toaster`。已登录后的顶栏、主导航、用户菜单在 `components/layout/Shell.vue`。

子模块页（市场、研究、量化、任务、个人中心）的固定套路：

1. `PageHeader`：标题 + 描述 + 可选 `actions` 插槽
2. `ModuleTabs`：二级导航，`items` 用 `RouterLink`
3. `Separator` + `<RouterView />` 或页内 tab 内容

同一页面多子路由时，优先**一个页面组件 + 路由名区分 tab**（`ProfilePage`、`TasksPage`），不要为每个 tab 复制一整页。

## 路由与导航

路由定义在 `src/router/index.ts`。除 `/login` 外全部挂在 `Shell` 下。

| 路径 | 名称 | 含义 |
| --- | --- | --- |
| `/analysis` | `analysis` | 个股分析（默认首页，`/` 重定向到这里） |
| `/chat` | `chat` | 问股 Agent |
| `/market/watch-list` | `market-watch-list` | 自选股 |
| `/market/holdings` | `market-holdings` | 投资组合 |
| `/market/signals` | `market-signals` | 信号评估 |
| `/market/quant` 及子路径 | `market-quant*` | 量化研究（总览 / 选股 / 数据集 / 模型 / 组合） |
| `/market/etf-rotation` | `market-etf-rotation` | ETF 动量轮动 |
| `/market/trend-following` | `market-trend-following` | 趋势跟踪 |
| `/calendar` | `calendar` | 日历记录 |
| `/profile/info` `/password` `/notification` | `profile-*` | 个人中心（同一页） |
| `/tasks` `/scheduled` `/runs` | `tasks*` | 任务中心（同一页） |

要点：

- `meta.public === true` 才是公开页（目前只有登录）。
- `meta.title` 用于 `document.title`（`「页面名 - Finance Analysis」`）。嵌套路由取最近一层有 title 的记录。
- 市场与研究是**两套并列的 `/market` 子树**，分别由 `MarketPage` 和 `ResearchPage` 提供 `ModuleTabs`。量化、ETF、趋势跟踪走研究树，不要塞进市场 tab。
- 量化范围用 query `?market=US|CN`。在量化子路由之间跳转时，守卫会保留已有 `market`。读写市场用 `useQuantMarket()`，不要手写丢 query 的 `router.push`。
- 顶栏菜单数据在 `src/config/mainNav.ts`，和路由表分开维护。加入口时两处都要改，并补 `src/config/__tests__/mainNav.test.ts` 一类断言。

## 鉴权

Cookie 会话，`apiClient` 设了 `withCredentials: true`。

登录是两步：查邮箱 `POST /api/v1/auth/lookup` → 设密或输入密码 → `POST /api/v1/auth/login`。未设密账号走 `setup` 步。登出后要 `fetchStatus()` 清本地态。

守卫是双保险：

- `router.beforeEach`：未登录且非 public → `/login?redirect=`
- `App.vue` 的 `watch`：状态变化后再纠一次

`401` 由 Axios 拦截器整页跳到登录。不要在业务页自己实现一套登录跳转。

会话状态用 Pinia `useAuthStore`；组件里可用 `useAuth()`（对 store 的薄封装）。登出或未登录时会 `stockPoolStore.resetDashboardState()`。

## API 层

`src/api/index.ts` 是唯一 Axios 实例：`baseURL = API_BASE_URL`（默认 `''`）、超时 30s、JSON、Cookie。响应拦截器会：

1. `401` → 跳登录
2. `attachParsedApiError` 把错误打成 `ParsedApiError`（标题、用户可读说明、category）

页面展示错误用 `getParsedApiError` + `AppApiErrorAlert`，不要把原始 `error.message` 直接丢给用户。分类逻辑在 `src/api/error.ts`（LLM 未配置、本机连不上、上游超时等）。

领域模块：`auth`、`analysis`、`history`、`agent`、`watchList`、`portfolio`、`stocks`、`signals`、`quant`、`etfRotation`、`trendFollowing`、`calendar`、`tasks`、`realtimeMarket`。

约定：

- 请求路径走 `/api/v1/...`。
- 后端 snake_case 时，在 API 模块里用 `toCamelCase()` 再交给页面；**不要在 Vue 里散落 `stock_code` 字段访问**。
- 少数接口（如部分 auth JSON）后端已是 camelCase，保持原样，不要双重转换。
- 问股流式接口 `agentApi.chatStream` 用 `fetch` + `credentials: 'include'`，因为要读 SSE，不走 Axios。
- 行情推送：`useRealtimeQuotes()` 连 WebSocket，指数退避重连；`4401`/`4403` 视为未授权，停止重连。

## 状态：Pinia 还是 zustand

| Store | 实现 | 用途 |
| --- | --- | --- |
| `authStore` | Pinia | 登录态、当前用户、lookup/login/logout |
| `timezoneStore` | Pinia | 展示时区 `Asia/Shanghai` \| `America/New_York`，写入 `localStorage` |
| `stockPoolStore` | vue-zustand | 分析页查询、历史列表、当前报告、重复任务错误 |
| `agentChatStore` | vue-zustand | 问股会话、流式消息、完成角标；`session_id` 在 `localStorage` |

选择：

- 和壳层/鉴权/时区相关 → Pinia，组件用 `storeToRefs`。
- 跨路由、带请求序号、需要在非组件里 `getState()` → zustand（分析看板、问股）。
- 分析页不要直接碰 `stockPoolStore` 的全部字段，走 `useHomeDashboardState()`；轮询/可见性刷新走 `useDashboardLifecycle()`。

主题不是 store：`useTheme()` 模块级 ref，`ThemeProvider` 在挂载时 `initThemeRuntime()`。默认偏好是 `light`（不是 `system`）。

## 页面与组合式函数

| 组合式函数 | 作用 |
| --- | --- |
| `useAuth` | 对 `authStore` 的稳定 API |
| `useTheme` | 主题读写与 `documentElement` class |
| `useQuantMarket` | 量化 `market` query |
| `useRealtimeQuotes` | 行情 WebSocket |
| `useHomeDashboardState` / `useDashboardLifecycle` | 分析首页状态与 30s 轮询 |
| `useStockIndex` / `useAutocomplete` | 本地股票索引与搜索建议 |
| `useCurrentTime` | 随展示时区走的当前时间 |

股票代码补全读 `/stocks.index.json`（`public/`，构建后由后端/静态服务器提供），不要为自动完成再打搜索 API。

## UI 与样式

- 设计令牌在 `src/index.css`：shadcn **neutral** 底，品牌粉 `--brand` 只给 Logo、主 CTA、焦点环和少量选中态。涨跌用 `--market-up`（红）/ `--market-down`（绿），A 股习惯，不要改成绿涨红跌。
- 原子组件从 `@/components/ui/<name>` 按 `index.ts` 具名导入。变体用 `class-variance-authority`；主按钮默认即 brand。
- 产品级控件优先复用：`LoadingButton`、`AppConfirmDialog`、`AppDatePicker` / `AppDateTimePicker` / `AppTimePicker`、`AppCombobox`、`AppPagination`、`AppApiErrorAlert`、`FieldInput` / `FieldSelect`。
- 类名合并用 `cn()`（`@/utils/cn`）。`components.json` 的 `utils` 别名指向这里。
- 图标用 `lucide-vue-next`。
- **禁止**给常见可交互元素加原生 `title=`（改用 `Tooltip` 或 `aria-label`）。`tests/ui_governance.test.ts` 会扫全仓。
- **禁止**使用 `input-terminal` 类名（同上治理测试）。
- 弹层不要改 `document.body` 的 `overflow` / `paddingRight` 造成顶栏位移；冒烟测试会查这一点。
- 根滚动条使用 `scrollbar-gutter: stable`，路由切换时不要让页面左右跳。
- 移动端：窄屏走 `Sheet` 主导航（`打开主导航`），宽屏走 `desktop-main-nav`。布局改动至少考虑 360 与 1280 两种宽度，避免横向溢出。

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

- Playwright 会自己拉后端（`main.py --webui-only`）和前端（`:4173`）。
- 需要真登录的用例依赖 `FA_WEB_SMOKE_PASSWORD`（可选 `FA_WEB_SMOKE_EMAIL`）。
- 布局/控件可用性用例用 `mockAuthenticatedSession` 拦 `/api/v1/**`，不依赖真实数据。
- 无障碍：关键按钮用可访问名字，不要靠 `title`。

`vite.config.ts` 和 `vitest.config.ts` 都配了测试。日常 `pnpm run test` 走 Vitest 自己的 config（`src/setupTests.ts`）。不要为了本地方便去改代理目标或把测试改成连外网。

## 改功能时的检查清单

1. 路由、`mainNav`、页面 `ModuleTabs` 三者是否一致。
2. 未登录路径是否仍被守卫拦住；公开页是否标了 `meta.public`。
3. 量化跳转是否带上 `market` query。
4. 错误是否经过 `parseApiError` / `AppApiErrorAlert`。
5. 有没有引入原生 `title` 或 `input-terminal`。
6. 深浅色、窄屏顶栏/Sheet、空态与加载骨架是否还站得住。
7. 单测或治理测试是否覆盖新契约。

## 不要做的事

- 不要在仓库根再建 `api/`、`bot/`、`services/` 之类的前端目录。
- 不要在页面里 new Axios 或写死 `http://localhost:8000`。
- 不要把 Pinia store 改成 Options API，或把 zustand store 无故迁到 Pinia（两套并存是有意的）。
- 不要把 shadcn `ui/` 组件改成业务耦合实现；业务变体放到 `app/` 或领域目录。
- 不要提交 `node_modules`、`playwright-report`、`test-results`，以及构建生成的 `static/` 内容（除非任务明确要求更新静态资源）。
