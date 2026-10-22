-- QUERY: Recent scans
SELECT id,created_at,score,band,scoring_method,fallback_reason FROM scan ORDER BY id DESC LIMIT 10;
-- QUERY: Count and average score per band
SELECT band,count(*) AS scans,round(avg(score),1) AS average_score FROM scan GROUP BY band;
-- QUERY: Usage per scoring method and fallback reason
SELECT scoring_method,coalesce(fallback_reason,'none') AS fallback_reason,count(*) AS scans FROM scan GROUP BY scoring_method,fallback_reason;
-- QUERY: Most flagged ingredients
SELECT i.canonical,count(*) AS appearances FROM scan_ingredient si JOIN ingredient i ON i.id=si.ingredient_id WHERE si.flag IS NOT NULL GROUP BY i.id ORDER BY appearances DESC LIMIT 10;
-- QUERY: Ingredients in High Risk scans only
SELECT i.canonical,count(*) AS appearances FROM scan s JOIN scan_ingredient si ON si.scan_id=s.id JOIN ingredient i ON i.id=si.ingredient_id WHERE s.band='High Risk' GROUP BY i.id ORDER BY appearances DESC;
-- QUERY: Average points per flag
SELECT fr.flag,round(avg(si.points),2) AS average_points FROM scan_ingredient si JOIN flag_rule fr ON fr.flag=si.flag GROUP BY fr.flag ORDER BY average_points;
-- QUERY: Low-coverage scans
SELECT id,created_at,score,kb_coverage FROM scan WHERE kb_coverage<0.60 ORDER BY id DESC;
-- QUERY: Ingredients never seen
SELECT i.id,i.canonical FROM ingredient i LEFT JOIN scan_ingredient si ON si.ingredient_id=i.id WHERE si.id IS NULL ORDER BY i.canonical;
-- QUERY: Scans below the overall average
SELECT id,created_at,score,band FROM scan WHERE score<(SELECT avg(score) FROM scan) ORDER BY score;
-- QUERY: Aliases per ingredient
SELECT i.canonical,count(a.id) AS aliases FROM ingredient i LEFT JOIN ingredient_alias a ON a.ingredient_id=i.id GROUP BY i.id HAVING count(a.id)>1 ORDER BY aliases DESC;
-- QUERY: Unverified ingredient count
SELECT count(*) AS unverified_ingredients FROM ingredient WHERE verified=0;
-- QUERY: Scan totals by month
SELECT substr(created_at,1,7) AS month,count(*) AS scans,round(avg(score),1) AS average_score FROM scan GROUP BY month ORDER BY month DESC;
-- QUERY: Scans per day
SELECT date(created_at) AS scan_date,count(*) AS scans FROM scan GROUP BY date(created_at) ORDER BY scan_date DESC;
-- QUERY: Most scanned ingredients with concern level
SELECT i.canonical,ii.concern_level,count(*) AS appearances FROM scan_ingredient si JOIN ingredient i ON i.id=si.ingredient_id LEFT JOIN ingredient_info ii ON ii.name_norm=lower(trim(i.canonical)) GROUP BY i.id,ii.concern_level ORDER BY appearances DESC LIMIT 10;
-- QUERY: Cache hits by source
SELECT source,sum(hit_count) AS cache_hits FROM (SELECT source,hit_count FROM ingredient_info UNION ALL SELECT source,hit_count FROM alternative_cache) GROUP BY source ORDER BY cache_hits DESC;
-- QUERY: Best score per day (CTE and window function)
WITH daily AS (SELECT date(created_at) AS scan_date,id,score,band,row_number() OVER(PARTITION BY date(created_at) ORDER BY score DESC) AS rank FROM scan) SELECT scan_date,id,score,band FROM daily WHERE rank=1 ORDER BY scan_date DESC;
