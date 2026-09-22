-- Read-only profiling used to choose the v1 candidate scope; no forward return evaluation.
-- Run against the existing database with a read-only role/transaction.
BEGIN READ ONLY;
SELECT market, trade_date, count(*) AS stocks, ceil(count(*) * 0.05) AS top_five_percent
FROM trend_following_snapshot
WHERE trade_date >= DATE '2026-09-09' AND trade_date <= DATE '2026-09-22'
GROUP BY market, trade_date ORDER BY market, trade_date DESC;

WITH ranked AS (
  SELECT *, count(*) OVER (PARTITION BY market, trade_date) AS n
  FROM trend_following_snapshot
  WHERE trade_date >= DATE '2026-09-09' AND trade_date <= DATE '2026-09-22'
), buckets AS (
  SELECT *, CASE WHEN rank <= ceil(n * .01) THEN '0-1%'
    WHEN rank <= ceil(n * .03) THEN '1-3%'
    WHEN rank <= ceil(n * .05) THEN '3-5%'
    WHEN rank <= ceil(n * .10) THEN '5-10%' ELSE 'rest' END AS bucket
  FROM ranked
)
SELECT market, bucket, count(*) AS samples,
  round(avg(alpha_score)::numeric, 1) AS alpha,
  round(avg(rs_score)::numeric, 1) AS relative_strength,
  round(avg(fragility_score)::numeric, 1) AS fragility,
  round(100. * count(*) FILTER (WHERE state IN ('WEAKENING', 'BROKEN', 'IDLE')) / count(*), 1) AS weak_pct,
  round((percentile_cont(.5) WITHIN GROUP (ORDER BY (features->>'distance_from_ma20')::float) * 100)::numeric, 1) AS median_ma20_distance_pct
FROM buckets WHERE bucket <> 'rest' GROUP BY market, bucket ORDER BY market, bucket;

SELECT trade_date, payload->'boards' AS boards, payload->'errors' AS errors
FROM dragon_tiger_flow_batch ORDER BY trade_date DESC LIMIT 25;

SELECT trade_date, s.key AS board, jsonb_array_length(s.value->'rows') AS rows,
       s.value->'quality' AS quality
FROM dragon_tiger_flow_batch b CROSS JOIN LATERAL jsonb_each(b.payload->'sources') s
WHERE trade_date = (SELECT max(trade_date) FROM dragon_tiger_flow_batch);
COMMIT;
