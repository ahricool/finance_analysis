# LLM 调用验证

当前契约见 [LLM调用层](llm.md)。渠道固定Codex→API，每次尝试默认300秒，无整链总预算。

离线测试覆盖：

- 固定渠道顺序、缺配置跳过、Codex成功不调用API。
- 超时不原地重试，API取得独立完整预算；累计超过旧总预算仍允许后续尝试。
- 网络/限流/格式错误最多三次重试，2/4/8秒退避；额度不足直接切换。
- 远端子进程清理及SSH断开，不影响无关进程；清理未确认不得切换。
- 耗时报告保留失败与重试，跨线程收集，任务间隔离；不暴露prompt或密钥。
- 财报搜索仍要求传输证据，不以模型自述冒充搜索结果。

```bash
uv run pytest tests/test_llm_client.py tests/test_llm_fallback.py tests/test_llm_cli_runner.py tests/test_llm_timing.py -q
```

这里不宣称已执行真实生产模型请求；上线后的实际额度和网络可用性需通过生产日志验证。
