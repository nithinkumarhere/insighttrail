import json
import os
import time
import uuid
from datetime import datetime
from typing import Optional

import pkg_resources
import requests
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, PackageLoader, select_autoescape
from starlette.middleware.base import BaseHTTPMiddleware

from .logger import get_runtime_info, get_system_metrics as get_log_system_metrics, logger, setup_logger
from .metrics import get_metrics, record_metrics


class _FastAPIInsightMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, capture_runtime=False, capture_system_metrics=False,
                 capture_env_vars=False, env_allowlist=None, url_prefix='/insight',
                 track_internal_requests=False):
        super().__init__(app)
        self.capture_runtime = capture_runtime
        self.capture_system_metrics = capture_system_metrics
        self.capture_env_vars = capture_env_vars
        self.env_allowlist = env_allowlist or []
        self.url_prefix = '/' + url_prefix.strip('/') if url_prefix else '/insight'
        self.track_internal_requests = track_internal_requests

    async def dispatch(self, request, call_next):
        start_time = time.time()
        trace_id = str(uuid.uuid4())
        request.state.trace_id = trace_id
        is_internal = request.url.path.startswith(self.url_prefix)

        try:
            response = await call_next(request)
            duration = time.time() - start_time
            if not self.track_internal_requests and is_internal:
                return response

            record_metrics(request, response, duration)
            logger.info("Request completed", extra={
                "trace_id": trace_id,
                "request_method": request.method,
                "request_path": request.url.path,
                "status": response.status_code,
                "duration": duration,
                "client": request.client.host if request.client else None,
                "runtime_info": get_runtime_info(
                    capture_env_vars=self.capture_env_vars,
                    env_allowlist=self.env_allowlist,
                ) if self.capture_runtime else None,
                "system_metrics": get_log_system_metrics() if self.capture_system_metrics else None,
            })
            return response
        except Exception as exc:
            duration = time.time() - start_time
            if not self.track_internal_requests and is_internal:
                raise

            logger.error("Request failed", extra={
                "trace_id": trace_id,
                "request_method": request.method,
                "request_path": request.url.path,
                "status": 500,
                "duration": duration,
                "client": request.client.host if request.client else None,
                "error": str(exc),
                "error_type": exc.__class__.__name__,
                "runtime_info": get_runtime_info(
                    capture_env_vars=self.capture_env_vars,
                    env_allowlist=self.env_allowlist,
                ) if self.capture_runtime else None,
                "system_metrics": get_log_system_metrics() if self.capture_system_metrics else None,
            })
            raise


class FastAPIInsightTrail:
    def __init__(self, app, log_file=None, log_level='INFO', max_file_size=1 * 1024 * 1024, backup_count=5,
                 enable_ui=True, url_prefix='/insight', capture_runtime=False,
                 capture_system_metrics=False, capture_env_vars=False, env_allowlist=None,
                 dependency_check=None, ultra_light_mode=False, enable_charts=None,
                 ui_refresh_seconds=10, track_internal_requests=False):
        self.app = app
        self.capture_runtime = capture_runtime
        self.capture_system_metrics = capture_system_metrics
        self.capture_env_vars = capture_env_vars
        self.env_allowlist = env_allowlist or []
        self.track_internal_requests = track_internal_requests
        self.ultra_light_mode = ultra_light_mode
        self.dependency_check = (not ultra_light_mode) if dependency_check is None else dependency_check
        self.enable_charts = (not ultra_light_mode) if enable_charts is None else enable_charts
        self.ui_refresh_seconds = max(2, int(ui_refresh_seconds))
        self.required_packages = self._load_required_packages(os.getcwd())

        if log_file is None:
            log_file = os.path.join(os.getcwd(), 'logs', 'insighttrail.log')

        setup_logger(log_file, log_level, max_file_size, backup_count)
        self.log_file = log_file
        self.url_prefix = '/' + url_prefix.strip('/') if url_prefix else '/insight'

        app.add_middleware(
            _FastAPIInsightMiddleware,
            capture_runtime=self.capture_runtime,
            capture_system_metrics=self.capture_system_metrics,
            capture_env_vars=self.capture_env_vars,
            env_allowlist=self.env_allowlist,
            url_prefix=self.url_prefix,
            track_internal_requests=self.track_internal_requests,
        )

        if enable_ui:
            self._setup_ui()

    def _load_required_packages(self, start_path):
        current_path = start_path
        for _ in range(5):
            requirements_file = os.path.join(current_path, 'requirements.txt')
            if os.path.exists(requirements_file):
                try:
                    with open(requirements_file, 'r') as req_file:
                        packages = []
                        for line in req_file:
                            line = line.strip()
                            if line and not line.startswith('#'):
                                package_name = line.split('#')[0].strip()
                                package_name = package_name.split('==')[0].split('>=')[0].split('<=')[0].split('~=')[0].split('<')[0].split('>')[0].split('!=')[0].strip()
                                if package_name:
                                    packages.append(package_name.lower())
                        return packages
                except IOError:
                    return []
            parent = os.path.dirname(current_path)
            if parent == current_path:
                break
            current_path = parent
        return []

    def _parse_log_file(self):
        logs = []
        try:
            with open(self.log_file, 'r') as log_file:
                for line in log_file:
                    try:
                        log_entry = json.loads(line)
                        log_entry['request_time'] = datetime.strptime(log_entry['timestamp'], '%Y-%m-%dT%H:%M:%S.%f')
                        logs.append(log_entry)
                    except (json.JSONDecodeError, KeyError, ValueError):
                        continue
            logs.sort(key=lambda log: log['request_time'], reverse=True)
            return logs
        except Exception:
            return []

    def _get_package_info(self):
        packages = []
        insighttrail_deps = {'fastapi', 'starlette', 'psutil', 'requests'}
        app_deps = set(self.required_packages)
        required_set = app_deps.union(insighttrail_deps)

        for dist in pkg_resources.working_set:
            try:
                is_prerelease = any(tag in dist.version.lower() for tag in ('a', 'b', 'rc', 'dev', 'alpha', 'beta'))
                package = {
                    'name': dist.key,
                    'current_version': dist.version,
                    'latest_version': dist.version,
                    'required': dist.key.lower() in required_set,
                    'description': dist._get_metadata('Summary') if dist.has_metadata('Summary') else None,
                    'stability': 'pre-release' if is_prerelease else 'stable'
                }
                try:
                    pypi_url = f"https://pypi.org/pypi/{dist.key}/json"
                    if self.dependency_check:
                        response = requests.get(pypi_url, timeout=2)
                        if response.status_code == 200:
                            pypi_data = response.json()
                            package['latest_version'] = pypi_data['info']['version']
                            if not package['description']:
                                package['description'] = pypi_data['info']['summary']
                            latest = str(package['latest_version']).lower()
                            package['stability'] = 'pre-release' if any(tag in latest for tag in ('a', 'b', 'rc', 'dev', 'alpha', 'beta')) else 'stable'
                except (requests.RequestException, KeyError, ValueError):
                    pass
                packages.append(package)
            except Exception:
                continue

        return sorted(packages, key=lambda x: (not x['required'], x['name'].lower()))

    def _setup_ui(self):
        router = APIRouter(prefix=self.url_prefix)
        templates = Environment(
            loader=PackageLoader('insighttrail', 'templates'),
            autoescape=select_autoescape(['html', 'xml'])
        )

        @router.get('/', response_class=HTMLResponse)
        async def index():
            template = templates.get_template('insighttrail_dashboard.html')
            return HTMLResponse(template.render(
                insight_base_url=self.url_prefix,
                ui_refresh_seconds=self.ui_refresh_seconds,
                enable_charts=self.enable_charts,
                dependency_check=self.dependency_check,
            ))

        @router.get('/api/packages')
        async def get_packages():
            return JSONResponse(self._get_package_info())

        @router.get('/api/logs')
        async def get_logs():
            return JSONResponse(self._parse_log_file())

        @router.get('/api/analytics/logs')
        async def fetch_logs():
            return JSONResponse({'logs': self._parse_log_file(), 'metrics': get_metrics()})

        @router.get('/api/analytics/search')
        async def search_by_trace_id(trace_id: Optional[str] = None):
            logs = self._parse_log_file()
            result = [log for log in logs if log.get('trace_id') == trace_id] if trace_id else logs
            return JSONResponse({'logs': result, 'metrics': get_metrics()})

        self.app.include_router(router)
