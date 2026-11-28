WITH
motion AS (
  SELECT value AS obj FROM json_each(:db, '$.motions')
  WHERE key = json_extract(:req, '$.motion')
    AND json_extract(value, '$.repository') = json_extract(:req, '$.repository')
),
registered AS (
  SELECT value AS obj, json_extract(value, '$.role') AS role
  FROM json_each(:db, '$.records')
  WHERE json_extract(value, '$.motion') = json_extract(:req, '$.motion')
),
received AS (
  SELECT CASE WHEN type = 'object' THEN value ELSE '{}' END AS obj
  FROM json_each(:req, '$.packet')
),
roles AS (
  SELECT o.obj AS opening, c.obj AS closing
  FROM registered AS o CROSS JOIN registered AS c
  WHERE o.role = 'opening' AND c.role = 'result'
    AND json_type(o.obj, '$.url') = 'text' AND json_extract(o.obj, '$.url') <> ''
    AND json_type(c.obj, '$.url') = 'text' AND json_extract(c.obj, '$.url') <> ''
    AND json_extract(o.obj, '$.url') <> json_extract(c.obj, '$.url')
),
matched AS (
  SELECT r.role FROM registered AS r JOIN received AS s ON r.obj = s.obj
  WHERE r.role IN ('opening', 'result')
),
pins AS (
  SELECT p.key AS ref, json_extract(p.value, '$.commit') AS oid
  FROM motion, json_each(motion.obj, '$.refs') AS p
),
observations AS (
  SELECT CASE WHEN type = 'object' THEN value ELSE '{}' END AS obj
  FROM json_each(:req, '$.snapshots')
),
resolved AS (
  SELECT pins.oid FROM observations JOIN pins
    ON json_type(observations.obj, '$.ref') = 'text'
    AND json_extract(observations.obj, '$.ref') = pins.ref
    AND json_extract(observations.obj, '$.commit') = pins.oid
  WHERE typeof(pins.oid) = 'text' AND length(pins.oid) = 40
    AND pins.oid NOT GLOB '*[^0-9a-f]*'
),
vote AS (
  SELECT json_extract(opening, '$.candidate_commit') AS oid,
         json_extract(closing, '$.outcome') AS status FROM roles
)
SELECT CASE
  WHEN NOT EXISTS (SELECT 1 FROM motion) THEN 'Defer'
  WHEN json_type(:req, '$.packet') IS NOT 'array'
    OR (SELECT count(*) FROM received) <> 2 THEN 'Defer'
  WHEN (SELECT count(*) FROM registered WHERE role = 'opening') <> 1
    OR (SELECT count(*) FROM registered WHERE role = 'result') <> 1 THEN 'Defer'
  WHEN (SELECT count(*) FROM roles) <> 1 OR (SELECT count(DISTINCT role) FROM matched) <> 2 THEN 'Defer'
  WHEN (SELECT status FROM vote) IN ('failed', 'withdrawn') THEN 'DoNotReuse'
  WHEN (SELECT status FROM vote) IS NOT 'passed' THEN 'Defer'
  WHEN NOT EXISTS (
    SELECT 1 FROM vote WHERE typeof(oid) = 'text' AND length(oid) = 40 AND oid NOT GLOB '*[^0-9a-f]*'
  ) THEN 'Defer'
  WHEN json_type(:req, '$.snapshots') IS NOT 'array'
    OR (SELECT count(*) FROM observations) <> 2 OR (SELECT count(*) FROM resolved) <> 2 THEN 'Defer'
  WHEN EXISTS (SELECT 1 FROM resolved CROSS JOIN vote WHERE resolved.oid <> vote.oid) THEN 'Review'
  ELSE 'Reuse'
END;
