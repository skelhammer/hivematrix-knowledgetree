"""
HiveMatrix Standardized Health Check Library

Provides comprehensive health checking for all HiveMatrix services.
Checks database connectivity, Redis, disk space, and service dependencies.

Usage:
    from health_check import HealthChecker

    health_checker = HealthChecker(
        service_name='codex',
        db=db,
        redis_client=redis_client,
        dependencies=[('core', 'http://localhost:5000')]
    )

    @app.route('/health')
    def health():
        return health_checker.get_health()
"""

from datetime import datetime, timezone
from flask import jsonify
import shutil
import requests
import time

# Conditional imports - only import if needed
try:
    from sqlalchemy import text
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False

try:
    import redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False


class HealthChecker:
    """
    Comprehensive health checker for HiveMatrix services.

    Performs checks on:
    - Database connectivity and query performance
    - Redis connectivity (if configured)
    - Disk space usage
    - Dependent service availability
    - Memory usage (optional)
    """

    def __init__(self, service_name, db=None, redis_client=None, dependencies=None, neo4j_driver=None):
        """
        Initialize health checker.

        Args:
            service_name (str): Name of the service (e.g., 'codex', 'core')
            db (SQLAlchemy): Database instance (optional)
            redis_client (Redis): Redis client instance (optional)
            dependencies (list): List of (name, url) tuples for dependent services
            neo4j_driver (neo4j.Driver): Neo4j driver instance (optional)
        """
        self.service_name = service_name
        self.db = db
        self.redis_client = redis_client
        self.dependencies = dependencies or []
        self.neo4j_driver = neo4j_driver

    def check_database(self):
        """
        Check PostgreSQL database connectivity and performance.

        Returns:
            dict: Status with latency measurement
        """
        if not self.db or not HAS_SQLALCHEMY:
            return None

        try:
            from sqlalchemy import text
            start_time = time.time()
            self.db.session.execute(text('SELECT 1'))
            latency_ms = int((time.time() - start_time) * 1000)

            return {
                'status': 'healthy',
                'latency_ms': latency_ms,
                'type': 'postgresql'
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e),
                'type': 'postgresql'
            }

    def check_redis(self):
        """
        Check Redis connectivity.

        Returns:
            dict: Status of Redis connection
        """
        if not self.redis_client:
            return None

        try:
            start_time = time.time()
            self.redis_client.ping()
            latency_ms = int((time.time() - start_time) * 1000)

            # Get Redis info
            info = self.redis_client.info()

            return {
                'status': 'healthy',
                'latency_ms': latency_ms,
                'connected_clients': info.get('connected_clients', 0),
                'used_memory_mb': round(info.get('used_memory', 0) / (1024**2), 2)
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e)
            }

    def check_neo4j(self):
        """
        Check Neo4j connectivity.

        Returns:
            dict: Status of Neo4j connection
        """
        if not self.neo4j_driver:
            return None

        try:
            start_time = time.time()
            with self.neo4j_driver.session() as session:
                result = session.run("RETURN 1 as test")
                result.single()
            latency_ms = int((time.time() - start_time) * 1000)

            return {
                'status': 'healthy',
                'latency_ms': latency_ms,
                'type': 'neo4j'
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e),
                'type': 'neo4j'
            }

    def check_disk_space(self):
        """
        Check disk space usage.

        Returns:
            dict: Disk usage statistics
        """
        try:
            disk = shutil.disk_usage('/')
            usage_percent = (disk.used / disk.total) * 100
            free_gb = disk.free / (1024**3)

            # Determine status based on usage
            if usage_percent >= 95:
                status = 'unhealthy'
            elif usage_percent >= 85:
                status = 'degraded'
            else:
                status = 'healthy'

            return {
                'status': status,
                'usage_percent': round(usage_percent, 2),
                'free_gb': round(free_gb, 2),
                'total_gb': round(disk.total / (1024**3), 2)
            }
        except Exception as e:
            return {
                'status': 'unknown',
                'error': str(e)
            }

    def check_dependencies(self):
        """
        Check health of dependent services.

        Returns:
            dict: Health status of each dependency
        """
        if not self.dependencies:
            return None

        results = {}
        for dep_name, dep_url in self.dependencies:
            try:
                start_time = time.time()
                response = requests.get(f"{dep_url}/health", timeout=3)
                latency_ms = int((time.time() - start_time) * 1000)

                if response.status_code == 200:
                    results[dep_name] = {
                        'status': 'healthy',
                        'response_time_ms': latency_ms
                    }
                else:
                    results[dep_name] = {
                        'status': 'unhealthy',
                        'http_status': response.status_code
                    }
            except requests.exceptions.Timeout:
                results[dep_name] = {
                    'status': 'unhealthy',
                    'error': 'timeout'
                }
            except requests.exceptions.ConnectionError:
                results[dep_name] = {
                    'status': 'unhealthy',
                    'error': 'connection_refused'
                }
            except Exception as e:
                results[dep_name] = {
                    'status': 'unhealthy',
                    'error': str(e)
                }

        return results

    def get_overall_status(self, checks):
        """
        Determine overall service status based on individual checks.

        Priority:
        - unhealthy: Any critical component is down
        - degraded: Non-critical issues or degraded performance
        - healthy: All checks passing

        Args:
            checks (dict): Dictionary of health check results

        Returns:
            str: 'healthy', 'degraded', or 'unhealthy'
        """
        # Critical components that cause unhealthy status
        if 'database' in checks and checks['database']['status'] == 'unhealthy':
            return 'unhealthy'

        if 'neo4j' in checks and checks['neo4j']['status'] == 'unhealthy':
            return 'unhealthy'

        # Check disk space
        if 'disk' in checks and checks['disk']['status'] == 'unhealthy':
            return 'unhealthy'

        # Check for degraded state
        degraded_checks = []

        if 'redis' in checks and checks['redis']['status'] != 'healthy':
            degraded_checks.append('redis')

        if 'disk' in checks and checks['disk']['status'] == 'degraded':
            degraded_checks.append('disk')

        if 'dependencies' in checks:
            for dep_name, dep_status in checks['dependencies'].items():
                if dep_status['status'] != 'healthy':
                    degraded_checks.append(f"dependency:{dep_name}")

        if degraded_checks:
            return 'degraded'

        return 'healthy'

    def get_health(self):
        """
        Perform all health checks and return comprehensive status.

        Returns:
            tuple: (dict, int) - Health status dictionary and HTTP status code
        """
        health = {
            'service': self.service_name,
            'status': 'healthy',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'checks': {}
        }

        # Database check
        db_health = self.check_database()
        if db_health:
            health['checks']['database'] = db_health

        # Neo4j check
        neo4j_health = self.check_neo4j()
        if neo4j_health:
            health['checks']['neo4j'] = neo4j_health

        # Redis check
        redis_health = self.check_redis()
        if redis_health:
            health['checks']['redis'] = redis_health

        # Disk space check
        health['checks']['disk'] = self.check_disk_space()

        # Dependency checks
        dep_health = self.check_dependencies()
        if dep_health:
            health['checks']['dependencies'] = dep_health

        # Determine overall status
        health['status'] = self.get_overall_status(health['checks'])

        # Set HTTP status code
        # 200 = healthy
        # 503 = unhealthy or degraded (service unavailable)
        status_code = 200 if health['status'] == 'healthy' else 503

        return jsonify(health), status_code

    def get_simple_health(self):
        """
        Get simple health status without detailed checks.
        Useful for liveness probes.

        Returns:
            tuple: (dict, int) - Simple status and HTTP 200
        """
        return jsonify({
            'service': self.service_name,
            'status': 'alive',
            'timestamp': datetime.now(timezone.utc).isoformat()
        }), 200
