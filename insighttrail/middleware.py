from flask import request, g, jsonify, render_template, Blueprint
import time
import os
import json
from .logger import setup_logger, log_request, log_error
from .metrics import record_metrics, get_metrics
from .traces import trace_request
import pkg_resources
import requests
from datetime import datetime

class InsightTrailMiddleware:
    def __init__(self, app, log_file=None, log_level='INFO', max_file_size=1 * 1024 * 1024, backup_count=5,
                 enable_ui=True, url_prefix='/insight', capture_runtime=False,
                 capture_system_metrics=False, capture_env_vars=False, env_allowlist=None,
                 dependency_check=None, ultra_light_mode=False, enable_charts=None,
                 ui_refresh_seconds=10, track_internal_requests=False):
        """
        Initialize InsightTrail middleware.

        Args:
            app: Flask application instance
            log_file: Path to log file. Defaults to 'insighttrail.log' in the parent directory of the app's root path.
            log_level: The logging level to use, e.g., 'INFO', 'DEBUG'.
            max_file_size: Maximum size of log file before rotation
            backup_count: Number of backup files to keep
            enable_ui: Whether to enable the web UI (default: True)
            url_prefix: URL prefix for InsightTrail routes (default: /insight)
        """
        self.app = app
        self.capture_runtime = capture_runtime
        self.capture_system_metrics = capture_system_metrics
        self.capture_env_vars = capture_env_vars
        self.env_allowlist = env_allowlist or []
        self.url_prefix = '/' + url_prefix.strip('/') if url_prefix else '/insight'
        self.track_internal_requests = track_internal_requests
        self.ultra_light_mode = ultra_light_mode
        self.dependency_check = (not ultra_light_mode) if dependency_check is None else dependency_check
        self.enable_charts = (not ultra_light_mode) if enable_charts is None else enable_charts
        self.ui_refresh_seconds = max(2, int(ui_refresh_seconds))
        self.required_packages = self._load_required_packages(app.root_path)
        
        if log_file is None:
            # Default to a 'logs' directory in the parent of the app's root path
            app_parent_dir = os.path.dirname(app.root_path)
            log_file = os.path.join(app_parent_dir, 'logs', 'insighttrail.log')

        setup_logger(log_file, log_level, max_file_size, backup_count)
        self.log_file = log_file
        self._init_app(app)

        if enable_ui:
            self._setup_ui(self.url_prefix)

    def _load_required_packages(self, start_path):
        """
        Traverse up from start_path to find and parse a requirements.txt file.
        This helps identify the host application's dependencies.
        """
        current_path = start_path
        # Limit search to 5 levels up to avoid scanning the whole filesystem
        for _ in range(5):
            requirements_file = os.path.join(current_path, 'requirements.txt')
            if os.path.exists(requirements_file):
                try:
                    with open(requirements_file, 'r') as f:
                        packages = []
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith('#'):
                                # Basic parsing: remove version specifiers and comments
                                package_name = line.split('#')[0].strip()
                                package_name = package_name.split('==')[0].split('>=')[0].split('<=')[0].split('~=')[0].split('<')[0].split('>')[0].split('!=')[0].strip()
                                if package_name:
                                    packages.append(package_name.lower())
                        return packages
                except IOError:
                    return []  # Return empty list on read error
            
            parent = os.path.dirname(current_path)
            if parent == current_path:  # Reached the filesystem root
                break
            current_path = parent
            
        return []  # Return empty list if no requirements.txt is found

    def _get_package_info(self):
        """
        Gathers information about installed packages, highlighting those required
        by the host application and InsightTrail itself.
        """
        packages = []
        # Combine app's requirements with InsightTrail's key dependencies for highlighting
        insighttrail_deps = {'flask', 'waitress', 'psutil', 'requests'}
        app_deps = set(self.required_packages)
        required_set = app_deps.union(insighttrail_deps)

        for dist in pkg_resources.working_set:
            try:
                # Get package metadata
                is_prerelease = any(tag in dist.version.lower() for tag in ('a', 'b', 'rc', 'dev', 'alpha', 'beta'))
                package = {
                    'name': dist.key,
                    'current_version': dist.version,
                    'latest_version': dist.version,  # Will be updated if PyPI info is available
                    'required': dist.key.lower() in required_set,
                    'description': dist._get_metadata('Summary') if dist.has_metadata('Summary') else None,
                    'stability': 'pre-release' if is_prerelease else 'stable'
                }

                # Try to get latest version from PyPI
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

        # Sort packages: required first, then alphabetically
        return sorted(packages, key=lambda x: (not x['required'], x['name'].lower()))

    def _init_app(self, app):
        @app.before_request
        def before_request():
            g.start_time = time.time()
            trace_request(request)

        @app.after_request
        def after_request(response):
            if not self.track_internal_requests and request.path.startswith(self.url_prefix):
                return response
            duration = time.time() - g.start_time
            record_metrics(request, response, duration)
            log_request(
                request,
                response,
                duration,
                capture_runtime=self.capture_runtime,
                capture_system_metrics=self.capture_system_metrics,
                capture_env_vars=self.capture_env_vars,
                env_allowlist=self.env_allowlist,
            )
            return response

        @app.teardown_request
        def teardown_request(exception=None):
            if exception is not None:
                if not self.track_internal_requests and request.path.startswith(self.url_prefix):
                    return
                duration = time.time() - g.start_time
                log_error(
                    request,
                    exception,
                    duration,
                    capture_runtime=self.capture_runtime,
                    capture_system_metrics=self.capture_system_metrics,
                    capture_env_vars=self.capture_env_vars,
                    env_allowlist=self.env_allowlist,
                )

    def _parse_log_file(self):
        logs = []
        try:
            with open(self.log_file, 'r') as f:
                for line in f:
                    try:
                        log_entry = json.loads(line)
                        # Convert timestamp to datetime for sorting
                        log_entry['request_time'] = datetime.strptime(log_entry['timestamp'], '%Y-%m-%dT%H:%M:%S.%f')
                        logs.append(log_entry)
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        print(f"Error parsing log line: {e}")
                        continue
            
            # Sort logs in descending order by request_time
            logs.sort(key=lambda log: log['request_time'], reverse=True)
            return logs
        except Exception as e:
            print(f"Error reading log file: {e}")
            return []

    def _setup_ui(self, normalized_prefix):
        # Create a blueprint for InsightTrail UI
        insight_bp = Blueprint('insighttrail', __name__,
                               template_folder='templates',
                               static_folder='static',
                               url_prefix=normalized_prefix)

        @insight_bp.route('/')
        def index():
            return render_template(
                "insighttrail_dashboard.html",
                insight_base_url=normalized_prefix,
                ui_refresh_seconds=self.ui_refresh_seconds,
                enable_charts=self.enable_charts,
                dependency_check=self.dependency_check,
            )

        @insight_bp.route('/api/packages')
        def get_packages():
            return jsonify(self._get_package_info())

        @insight_bp.route('/api/logs')
        def get_logs():
            try:
                # Return all logs in JSON format
                logs = self._parse_log_file()
                return jsonify(logs)
            except Exception as e:
                print(f"Error in get_logs: {e}")
                return jsonify({"error": str(e)}), 500

        @insight_bp.route('/api/analytics/logs', methods=['GET'])
        def fetch_logs():
            try:
                logs = self._parse_log_file()
                metrics = get_metrics()
                return jsonify({
                    'logs': logs,
                    'metrics': metrics
                })
            except Exception as e:
                print(f"Error in fetch_logs: {e}")
                return jsonify({"error": str(e)}), 500

        @insight_bp.route('/api/analytics/search', methods=['GET'])
        def search_by_trace_id():
            try:
                trace_id = request.args.get('trace_id')
                logs = self._parse_log_file()
                result = [log for log in logs if log.get("trace_id") == trace_id]
                metrics = get_metrics()
                return jsonify({
                    'logs': result,
                    'metrics': metrics
                })
            except Exception as e:
                print(f"Error in search_by_trace_id: {e}")
                return jsonify({"error": str(e)}), 500

        # Register the blueprint with the main app
        self.app.register_blueprint(insight_bp)

