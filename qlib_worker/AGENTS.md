# Qlib Worker 指南（`qlib_worker/`）

本目录是刻意隔离的 Python 3.12 包，用于运行 `pyqlib==0.9.7`、LightGBM 和 scikit-learn。主应用要求 Python 3.13，不能把 Qlib 依赖加到根 `pyproject.toml`。

## 安全边界

Qlib Worker：

- 只消费 Redis Celery 的 `qlib` 队列。
- 只接收版本化、JSON 可序列化 payload。
- 只读取/写入 `QUANT_ARTIFACT_ROOT` 下的 dataset/model artifact。
- 不接收 `DATABASE_URL`，不导入 `src/finance_analysis`，不直接访问 PostgreSQL。 <!-- pragma: allowlist secret -->
- 不运行 FastAPI，不承担业务信号融合、模型发布或组合持久化。
- Docker 固定 `linux/amd64`；当前 Qlib 版本未在本项目验证 ARM64。

主应用负责准备数据集、校验 Universe/覆盖率、发布任务、处理 callback、写 PostgreSQL。跨边界只传 artifact URI、模型/日期标识、版本化配置及 JSON 结果。 <!-- pragma: allowlist secret -->

## 运行拓扑

```text
主应用 PostgreSQL <!-- pragma: allowlist secret -->
  → 主应用导出 data/quant dataset
  → Redis qlib task
  → Qlib Worker 训练/预测
  → model artifact + JSON result
  → 主应用 Celery callback
  → PostgreSQL signals/models/portfolios <!-- pragma: allowlist secret -->
```

普通主 Worker 不消费 `qlib`；Qlib Worker 不消费 `celery,alerts,analysis,ingestion,maintenance`。Compose 中 Qlib Worker concurrency=1、prefetch=1、`max-tasks-per-child=1`，避免 Qlib provider/cache 状态跨任务泄漏。

## 目录地图

```text
qlib_worker/
  celery_app.py       仅 qlib queue 的 Celery app 与 routes
  config.py           REDIS_URL、QUANT_ARTIFACT_ROOT 等最小配置
  protocol.py         schema version 与 Train/Predict/Artifact payload 校验
  price_modes.py      价格模式约束
  datasets/
    loader.py         加载主应用生成的 Qlib 数据集
    validator.py      manifest/文件/字段校验
  models/
    registry.py       支持模型注册
    cross_section.py  横截面 LightGBM
    time_series.py    时间序列 LightGBM
    training.py       walk-forward 训练编排
    splits.py         purge/embargo 时间切分
    targets.py        标签构造
    metrics.py        模型指标
  artifacts/store.py  URI 解析、digest、原子提交
  tasks/
    train.py          `qlib.model.train`
    predict.py        `qlib.model.predict`、`qlib.daily.predict`
    artifact.py       dataset/artifact 校验与检查
  tests/              本包独立 pytest
  pyproject.toml      Python 3.12 依赖
  uv.lock             独立锁文件
  Dockerfile          linux/amd64 Worker 镜像
```

## 协议

`protocol.py` 当前 `SCHEMA_VERSION = 1`。基础约束：

- `model_run_id` 为正整数。
- URI、模型键、版本和交易日期为非空字符串。
- 可选配置必须为 JSON object。
- 未知 schema version 立即失败，不能猜测或静默兼容。
- 日频预测使用 `DailyPredictPayload`：一份 dataset + Cross Section / Time Series 两个 model artifact。Worker 只 `qlib.init()` / `Alpha158.load_features()` 一次，再分别预测。

主应用对应生产者/消费者在：

- `src/finance_analysis/quant/pipeline/service.py` <!-- pragma: allowlist secret -->
- `src/finance_analysis/tasks/celery/jobs/quant_training/tasks.py` <!-- pragma: allowlist secret -->
- `src/finance_analysis/tasks/celery/jobs/quant_daily/tasks.py` <!-- pragma: allowlist secret -->
- `src/finance_analysis/tasks/celery/schedule/constants.py` <!-- pragma: allowlist secret -->

修改 payload 或 result 时必须两侧原子更新，并增加边界测试。不要通过共享 Python object、pickle、HTTP sidecar 或同步 `.get()` 绕过 JSON Celery 协议。

## Dataset 与 artifact

主应用导出的 dataset 包含 calendar、instrument、Qlib float32 feature binaries、`source/daily.csv`、`manifest.json` 和 `validation.json`。Worker 必须把 manifest 视为输入契约：

- 价格来自 PostgreSQL canonical 前复权 `stock_daily`，Worker 不再复权。 <!-- pragma: allowlist secret -->
- Qlib `factor.day.bin` 保持 `1.0`，避免双重复权。
- `Alpha158` 只加载 manifest 股票 universe；benchmark 可存在于 source，但不能进入训练/横截面排名。
- VWAP 二进制是 HLC3 proxy（`(high+low+close)/3`），不是成交额/成交量真实 VWAP。Worker 不重新计算该字段。

`cross_section_lgbm` 预测 T+1 open → T+5 close 相对市场超额收益；`time_series_lgbm` 预测同一窗口绝对上涨概率。Worker 用 `TargetConfig.for_model()` 强制该语义，忽略 payload 里冲突的 benchmark/excess_return。

横截面评价指标以每日 Rank IC / ICIR / TopK 超额为主；时间序列用 ROC AUC、balanced accuracy、Brier、方向命中率等分类指标。单类 test fold 的 AUC 记为 `None` 并 warning，不让训练失败。最终模型 `n_estimators` 取各 fold `best_iteration_` 的中位数。

模型工件写入临时目录，计算 digest、验证后原子 rename。相同重试可复用已提交结果；不要直接覆盖已发布目录。

支持模型以 `models/registry.py` 为准。新增模型需要：

1. 实现现有 model 接口。
2. 在 registry 显式注册稳定 `model_key`。
3. 定义 JSON 可序列化参数、指标和 feature importance。
4. 保持时间序列切分、prediction horizon purge 与 embargo。
5. 同步主应用 model definition/capability 和 WebUI 展示。

## 安装、运行与测试

从仓库根运行：

```bash
uv sync --project qlib_worker
uv run --project qlib_worker pytest qlib_worker/tests -q
```

启动 Worker：

```bash
uv run --project qlib_worker celery \
  -A qlib_worker.celery_app:celery_app worker \
  -Q qlib --loglevel=INFO --concurrency=1 \
  --prefetch-multiplier=1 --max-tasks-per-child=1
```

通常用 Compose 构建并运行：

```bash
docker compose -f docker-compose.dev.yml up --build qlib-worker
```

同时运行主应用边界测试：

```bash
uv run pytest tests/test_qlib_boundary.py tests/test_quant_core.py tests/test_quant_daily_pipeline.py -q
```

## 改动检查表

1. 仍使用 Python 3.12 独立 lock，未污染主应用依赖。
2. 仍只消费 `qlib`，未添加业务队列。
3. 容器未收到数据库凭据或完整 `.env`。
4. payload/result 仍为 versioned JSON，主应用和 Worker 同步更新。
5. 输入路径只能落在配置的 artifact root 内。
6. 模型训练/预测不直接写业务状态。
7. artifact 提交保持校验、digest 和原子性。
8. Worker 单测及主应用 boundary 测试通过。
