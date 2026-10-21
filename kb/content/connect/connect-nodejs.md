---
title: چطور از Node.js با node-postgres به PostGIS وصل شوم؟
summary: از بسته pg یک Pool با ssl و حداکثر ۳ اتصال بسازید و کوئری مکانی را پارامتری اجرا کنید. هرگز رمز پایگاه داده را در کد سمت مرورگر نگذارید؛ برای مرورگر لایه منتشرشده یا REST API استفاده کنید.
kind: howto
keywords: nodejs, node, pg, node-postgres, pool, express, اتصال node, ssl rejectUnauthorized
related: connection-info, connect-web-app-pooling, no-direct-browser-connection, rest-api-overview
order: 50
reviewed: 2026-10-21
---
## نمونه

```javascript
import pg from "pg";

const pool = new pg.Pool({
  connectionString: "postgresql://USER:PASS@HOST:PORT/DB",
  ssl: { rejectUnauthorized: false },
  max: 3,
});

const { rows } = await pool.query(
  `SELECT id, ST_AsGeoJSON(geom)::json AS geometry
   FROM places
   WHERE ST_DWithin(geom::geography, ST_MakePoint($1, $2)::geography, 1000)`,
  [51.389, 35.689]
);
```

## نکته‌ها

- `max: 3` را نگه دارید تا از سقف اتصال همزمان پلن عبور نکنید.
- مقدارها را همیشه با پارامتر (`$1`، `$2`) بدهید، نه با چسباندن رشته، تا از SQL injection در امان بمانید.
- این کد باید روی **سرور** شما اجرا شود، نه در مرورگر ([چرا؟](kb:no-direct-browser-connection)).
- برای ترافیک زیاد، [PgBouncer](kb:pgbouncer) را بررسی کنید.
