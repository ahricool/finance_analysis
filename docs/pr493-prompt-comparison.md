# PR #493：证据投影与完整 Prompt 对比

## 方法与样本

基线为提交 `998372a4`。使用同一份 `scripts/compare_prompt_examples.py` 的**合成样本**分别调用基线和本轮实现，拼接完整 system + 两个换行 + user Prompt 后统计；没有调用真实模型或外部行情。
数字反映这四份示例，不代表生产分布、实际模型效果或账单用量。Token 使用本机可用的 `tiktoken/o200k_base`，实际模型分词可能不同。
表格数只计 CSV 数据块，行数为 CSV 记录数（不含表头；单元格换行不算额外行）。Prompt 中的说明文字和 Markdown 用途表计入字符和 Token。

| 合成场景 | 输入构成 | 字符：前→后 | Token：前→后 | CSV 表：前→后 | 数据行：前→后 |
| --- | --- | --- | --- | --- | --- |
| 期权解释 | 1条证券级倒挂、15条合约活跃事件、15个异常合约、前后期限IV | 4,943 → 5,480 | 2,066 → 3,018 | 5 → 7 | 38 → 36 |
| 财报前瞻 | 1条指引在context两处及research重复、2个来源 | 3,590 → 2,915 | 1,509 → 1,385 | 8 → 3 | 12 → 4 |
| 持仓复盘 | 6笔持仓，各20根日线与12根闭合5分钟线 | 3,627 → 4,690 | 1,853 → 2,459 | 2 → 2 | 7 → 7 |
| 信号中心V2初筛 | 20个候选、Trend10指标 | 4,533 → 4,541 | 2,545 → 2,545 | 8 → 8 | 41 → 41 |

## 关键证据核对

- **期权**：基线投影无 `IV_TERM_INVERSION`、无顶层事件；本轮保留16条事件的类型/严重度/value/reference/来源/时间，以及倒挂的前后到期日、DTE、IV。合约从成交量排序前12个改为15个异常相关合约，不再用成交量筛掉其他风险。普通合约不发送。长度增加是补回证据，来源与限制改为共享定义、标量列表内联后关联行反而减少。
- **财报**：完整 Prompt 中该条指引由3份变为唯一1份；其余位置使用内容稳定的fact_id，source_ids仍能解析。不同财季、口径、时间、来源和相反判断的保留由独立回归测试覆盖；本样本没有模拟全部冲突场景。
- **持仓**：保留全部6笔及原窗口边界，新增最近1/3根变化、末收盘对5根均价/窗口高点偏离、最近3根量与此前3根量比值。增长主要来自这些必要指标和口径说明。额外回归样本验证旧摘要完全相同但近期转弱/反弹的序列可区分。
- **V2**：候选、显示精度和字段引用不变；8字符差异来自CSV块前的Markdown空行。反引号数据的额外样本验证围栏动态加长，不破坏证券名称和screening.reason。
- **长输入**：单独的通用持仓与V2服务测试将输入构造成超过原限制，验证请求到达客户端且不丢候选/持仓；未恢复任何应用层固定长度拒绝。供应商真实限制仍可能导致正常调用失败。

## 复现与完整文本

使用当前虚拟环境和同一脚本，基线源码通过独立worktree加载：

```bash
git worktree add --detach /tmp/fa-pr493-before 998372a4
PYTHONPATH=/tmp/fa-pr493-before/src uv run python scripts/compare_prompt_examples.py before --output-dir /tmp/fa-pr493-comparison
uv run python scripts/compare_prompt_examples.py after --output-dir /tmp/fa-pr493-comparison
git worktree remove /tmp/fa-pr493-before
```

输出为 `before/after-{options,earnings,holdings,signal_v2}.md` 的完整 Prompt、`*-metrics.json` 和 `*-evidence.json`。当前任务已实际生成并核对两版完整文本。
脚本没有字符拒绝条件；无tiktoken时Token列为null，不虚构估算。实际质量仍需后续真实模型评测，不能由格式/引用测试通过推断效果提升。
