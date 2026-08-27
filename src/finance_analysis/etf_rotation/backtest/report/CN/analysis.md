# CN ETF Momentum Rotation 策略对比

## Baseline 年化低的主要原因
Entry#1 隔夜收益均值为 -0.03%，开盘执行并非主要拖累；更可能来自高频换仓、赢家回吐或动量衰减。
Baseline CAGR=-19.25%，换手=43.87%，平均持仓天数=3.425，年化交易次数=106.458。若换手高、持仓短，说明 Entry Rank 前二过滤仍过于敏感，容易在噪声排名上反复换仓。
Entry#1 次日开盘到收盘均值 0.17%，可用于判断日内是否还能兑现动量。

## Top1 还是 Top3
Top1 代表：A_baseline cagr=-19.25%, B_entry1_mom10 cagr=-11.73%, C_entry1_mom20 cagr=4.65%。最佳 C_entry1_mom20。
Top3 代表：D_top3_mom10 cagr=-7.20%, E_top3_mom20 cagr=3.44%, F_top3_absolute cagr=15.79%。最佳 F_top3_absolute。
Top1 最佳 C_entry1_mom20 Sharpe=0.373；Top3 最佳 F_top3_absolute Sharpe=0.633。当前样本更看好Top3 最佳（F_top3_absolute）。

## Momentum 10 vs 20 退出
单票：B_entry1_mom10 cagr=-11.73%，C_entry1_mom20 为 4.65%。按该指标更优的是 C_entry1_mom20。 Sharpe：B_entry1_mom10 sharpe=-0.019，C_entry1_mom20 为 0.373。按该指标更优的是 C_entry1_mom20。 回撤：B_entry1_mom10 max_drawdown=-59.84%，C_entry1_mom20 为 -61.85%。按该指标更优的是 B_entry1_mom10。 换手：B_entry1_mom10 turnover=13.52%，C_entry1_mom20 为 5.96%。按该指标更优的是 C_entry1_mom20。
Top3：D_top3_mom10 cagr=-7.20%，E_top3_mom20 为 3.44%。按该指标更优的是 E_top3_mom20。 Sharpe：D_top3_mom10 sharpe=-0.086，E_top3_mom20 为 0.274。按该指标更优的是 E_top3_mom20。 回撤：D_top3_mom10 max_drawdown=-48.53%，E_top3_mom20 为 -47.56%。按该指标更优的是 E_top3_mom20。 换手：D_top3_mom10 turnover=14.93%，E_top3_mom20 为 6.46%。按该指标更优的是 E_top3_mom20。
若 Momentum 10 换手明显更高而收益没有更好，则 20 作为退出阈值更合理；反之说明动量衰减很快，应更早离场。

## Absolute Filter 是否有效
F_top3_absolute cagr=15.79%，E_top3_mom20 为 3.44%。按该指标更优的是 F_top3_absolute。 Sharpe F_top3_absolute sharpe=0.633，E_top3_mom20 为 0.274。按该指标更优的是 F_top3_absolute。 回撤 F_top3_absolute max_drawdown=-31.15%，E_top3_mom20 为 -47.56%。按该指标更优的是 F_top3_absolute。 胜率 F_top3_absolute win_rate=37.33%，E_top3_mom20 为 34.20%。按该指标更优的是 F_top3_absolute。
若 F 相对 E 提高胜率或降低回撤，说明 ret_5d>0 且站上 MA20 的过滤有效；若收益下降很多，则过滤过严、错过主升。

## Risk-Off 是否改善回撤
H_f_riskoff max_drawdown=-45.28%，F_top3_absolute 为 -31.15%。按该指标更优的是 F_top3_absolute。 CAGR H_f_riskoff cagr=5.80%，F_top3_absolute 为 15.79%。按该指标更优的是 F_top3_absolute。 现金比例 H_f_riskoff cash_ratio=4.72%，F_top3_absolute 为 0.65%。按该指标更优的是 H_f_riskoff。
若 H 回撤更小且现金比例更高，说明 30% 广度过滤起到避险作用；若回撤几乎不变，则该样本里系统性下跌不够集中。

## Stop 是否改善 downside
回撤 G_f_stop max_drawdown=-46.89%，F_top3_absolute 为 -31.15%。按该指标更优的是 F_top3_absolute。 MAE G_f_stop mae=-3.62%，F_top3_absolute 为 -4.53%。按该指标更优的是 G_f_stop。 CAGR G_f_stop cagr=-0.40%，F_top3_absolute 为 15.79%。按该指标更优的是 F_top3_absolute。
止损只上移、以 T+1 开盘成交价为锚。若 MAE/回撤改善但 CAGR 明显变差，说明止损在正常波动里被扫出。

## Hysteresis 是否减少无效换仓
换手 I_hysteresis turnover=5.50%，D_top3_mom10 为 14.93%。按该指标更优的是 I_hysteresis。 相对 D；相对 E：I_hysteresis turnover=5.50%，E_top3_mom20 为 6.46%。按该指标更优的是 I_hysteresis。 持仓天数 I_hysteresis avg_holding_days=25.964，E_top3_mom20 为 22.307。按该指标更优的是 I_hysteresis。
若 I 换手下降而 Sharpe 不差，说明 16-20 观察带减少了噪声退出。

## 推荐继续使用
按 Sharpe 优先（同分看 CAGR），推荐 **F_top3_absolute** (Top3 + absolute momentum filter)：CAGR=15.79%，Sharpe=0.633，MaxDD=-31.15%，换手=5.95%。
以上均为固定规则对比，没有做参数搜索。
