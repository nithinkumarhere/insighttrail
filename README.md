# InsightTrail

[![Python Version](https://img.shields.io/badge/python-3.7%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview
InsightTrail is a lightweight observability package for Python web services. It adds request tracing, structured JSON logs, service metrics, and a built-in dashboard under a dedicated route prefix.

It supports both Flask and FastAPI with a single import:

```python
from insighttrail import InsightTrailMiddleware
```

## What Is New
- Common API for Flask and FastAPI (`InsightTrail(app, ...)`)
- Dashboard is isolated to `url_prefix` (default `/insight`) and no longer collides with host app `/`
- Lightweight UI stack: Milligram + uPlot (removed Bootstrap, DataTables, jQuery, Chart.js)
- Internal dashboard requests can be excluded from logs/metrics (enabled by default)
- Safer defaults for sensitive data capture
- Ultra-light mode for minimal overhead in production

## Key Features
- Request tracing with per-request `trace_id`
- Structured JSON logs with rotation
- Response-time and service-level metrics
- Built-in dashboard at `/insight` (or custom prefix)
- Dependency status table with version chips and stability labels
- Flask + FastAPI support via one API

## Installation

```bash
pip install insighttrail
```

Or from source:

```bash
git clone https://github.com/your-username/insighttrail.git
cd insighttrail
pip install -e .
```

## Quick Start

### Flask

```python
from flask import Flask
from insighttrail import InsightTrailMiddleware

app = Flask(__name__)
InsightTrailMiddleware(app)

@app.route('/')
def home():
    return 'Hello from host app'
```

### FastAPI

```python
from fastapi import FastAPI
from insighttrail import InsightTrailMiddleware

app = FastAPI()
InsightTrailMiddleware(app)

@app.get('/')
def home():
    return {'message': 'Hello from host app'}
```

Open `http://localhost:8000/insight/` (or your configured prefix).

## Configuration

```python
InsightTrailMiddleware(
    app,
    log_file='logs/insighttrail.log',
    log_level='INFO',
    max_file_size=1 * 1024 * 1024,
    backup_count=5,
    enable_ui=True,
    url_prefix='/insight',
    capture_runtime=False,
    capture_system_metrics=False,
    capture_env_vars=False,
    env_allowlist=[],
    dependency_check=None,
    ultra_light_mode=False,
    enable_charts=None,
    ui_refresh_seconds=10,
    track_internal_requests=False,
)
```

### Important Defaults
- `capture_runtime=False`
- `capture_env_vars=False`
- `track_internal_requests=False`
- `ultra_light_mode=False`

### Ultra-Light Mode

```python
InsightTrailMiddleware(app, ultra_light_mode=True)
```

When `ultra_light_mode=True`:
- dependency version network checks are disabled by default
- charts are disabled by default

You can still explicitly override with `dependency_check=True` or `enable_charts=True`.

## Configuration Options

| Parameter | Type | Default | Description |
|---|---|---|---|
| `log_file` | `str \| None` | `None` | Log file path. If `None`, defaults to `../logs/insighttrail.log` for Flask and `./logs/insighttrail.log` for FastAPI. |
| `log_level` | `str` | `'INFO'` | Logging level (`DEBUG`, `INFO`, etc.). |
| `max_file_size` | `int` | `1048576` | Max bytes before rotation. |
| `backup_count` | `int` | `5` | Number of rotated files to keep. |
| `enable_ui` | `bool` | `True` | Enable dashboard routes. |
| `url_prefix` | `str` | `'/insight'` | Dashboard/API route prefix. |
| `capture_runtime` | `bool` | `False` | Include runtime block in logs. |
| `capture_system_metrics` | `bool` | `False` | Include per-request system metrics in logs. |
| `capture_env_vars` | `bool` | `False` | Include environment variables in runtime block. |
| `env_allowlist` | `list[str]` | `[]` | Restrict env keys when `capture_env_vars=True`. |
| `dependency_check` | `bool \| None` | `None` | Enable PyPI latest-version checks; resolved by `ultra_light_mode` if `None`. |
| `ultra_light_mode` | `bool` | `False` | Lightweight preset that disables heavy UI features by default. |
| `enable_charts` | `bool \| None` | `None` | Enable/disable charts; resolved by `ultra_light_mode` if `None`. |
| `ui_refresh_seconds` | `int` | `10` | Dashboard auto-refresh interval (minimum 2). |
| `track_internal_requests` | `bool` | `False` | Include `/insight` internal API calls in logs and metrics. |

## Dashboard
The dashboard includes:
- request metrics (total/error/avg latency/uptime)
- process metrics (pid, workers, threads, connections, cores)
- latency trend and CPU/memory trend charts (when enabled)
- request log table with details modal tabs (Request/Error/Runtime/System)
- dependency status with filters:
  - stable/pre-release
  - required/optional
  - text search

## Log Format

```json
{
  "trace_id": "...",
  "timestamp": "2026-01-01T12:00:00.000000",
  "level": "INFO",
  "request": {
    "method": "GET",
    "path": "/api/users",
    "status": 200,
    "duration_ms": 12.5,
    "client": "127.0.0.1"
  },
  "runtime": {},
  "system": {}
}
```

`runtime` and `system` are present only when enabled by configuration.

## Notes
- InsightTrail UI is intentionally mounted only under `url_prefix`.
- Host application routes (including `/`) remain untouched.

## License
MIT
