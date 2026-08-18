import ipaddress
import requests
from requests.exceptions import HTTPError
from typing import Dict, Any, Optional
from urllib.parse import urljoin, urlparse
from zilliz_mcp_server.settings import config

# Public Zilliz Cloud data-plane host suffixes. A leading dot is required so
# lookalikes such as "notzillizcloud.com" cannot match.
_ALLOWED_DATA_PLANE_HOST_SUFFIXES = (
    ".zillizcloud.com",
    ".zilliz.com.cn",
)


def _get_headers() -> Dict[str, str]:
    """Generate request headers"""
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "X-MCP-TRACE": "true"
    }
    
    if config.token:
        headers["Authorization"] = f"Bearer {config.token}"
    
    return headers


def _parse_response(response) -> Dict[str, Any]:
    """Parse response content safely"""    
    if not response.content:
        return {}
    
    # Try to parse response as JSON, raise exception if parsing fails
    try:
        json_data = response.json()
    except ValueError as e:
        raise Exception(f"Failed to parse response as JSON: {str(e)}") from e
    
    # Check business code, raise business exception if code != 0
    if 'code' in json_data and json_data['code'] != 0:
        error_message = json_data.get('message', 'Unknown business error')
        raise Exception(f"Business error: {error_message}")
    
    return json_data


def _is_ip_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _hostname_is_allowed_zilliz_cloud(hostname: str) -> bool:
    host = hostname.rstrip(".").lower()
    for suffix in _ALLOWED_DATA_PLANE_HOST_SUFFIXES:
        apex = suffix.lstrip(".")
        if host.endswith(suffix) and host != apex:
            return True
    return False


def _assert_safe_data_plane_url(endpoint: str, cluster_id: str) -> str:
    """Validate a resolved data-plane base URL and return a normalized origin.

    Must be called before any credential-bearing data-plane request.
    """
    if not endpoint or not str(endpoint).strip():
        raise ValueError("cluster connectAddress is required and cannot be empty")

    parsed = urlparse(endpoint.strip())
    if parsed.scheme != "https":
        raise ValueError("data-plane endpoint must use https")
    if parsed.username or parsed.password:
        raise ValueError("data-plane endpoint must not contain userinfo")
    if parsed.query or parsed.fragment:
        raise ValueError("data-plane endpoint must not contain query or fragment")
    if parsed.path not in ("", "/"):
        raise ValueError("data-plane endpoint must not contain a path")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("data-plane endpoint hostname is required")

    hostname = hostname.rstrip(".").lower()
    if _is_ip_address(hostname):
        raise ValueError("data-plane endpoint must not be an IP address")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError("data-plane endpoint must not be localhost")
    if not _hostname_is_allowed_zilliz_cloud(hostname):
        raise ValueError("data-plane endpoint hostname is not an allowed Zilliz Cloud host")

    labels = hostname.split(".")
    if cluster_id.strip().lower() not in labels:
        raise ValueError("data-plane endpoint hostname must include the requested cluster_id")

    netloc = hostname
    if parsed.port:
        netloc = f"{hostname}:{parsed.port}"
    return f"https://{netloc}/"


def _resolve_cluster_endpoint(cluster_id: str, region_id: str) -> str:
    """Resolve the data-plane URL from control-plane cluster metadata."""
    response = control_plane_api_request(f"/v2/clusters/{cluster_id}", method="GET")
    data = response.get("data") or {}

    returned_cluster_id = str(data.get("clusterId") or "").strip()
    if returned_cluster_id and returned_cluster_id.lower() != cluster_id.strip().lower():
        raise ValueError("resolved cluster_id does not match the requested cluster")

    returned_region_id = str(data.get("regionId") or "").strip()
    if returned_region_id and returned_region_id.lower() != region_id.strip().lower():
        raise ValueError("region_id does not match the resolved cluster")

    connect_address = data.get("connectAddress")
    if not connect_address or not str(connect_address).strip():
        raise ValueError("cluster connectAddress is missing from control-plane response")

    # Validate even trusted metadata so an unexpected address never receives the token.
    return _assert_safe_data_plane_url(str(connect_address), cluster_id)


def get(url: str, params_map: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """GET request interface"""
    headers = _get_headers()
    response = requests.get(url, params=params_map, headers=headers)
    response.raise_for_status()
    return _parse_response(response)


def post(url: str, params_map: Optional[Dict[str, Any]] = None, body_map: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """POST request interface"""
    headers = _get_headers()
    response = requests.post(url, params=params_map, json=body_map, headers=headers)
    response.raise_for_status()
    return _parse_response(response)


def delete(url: str, params_map: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """DELETE request interface"""
    headers = _get_headers()
    response = requests.delete(url, params=params_map, headers=headers)
    response.raise_for_status()
    return _parse_response(response)


def control_plane_api_request(uri: str, params_map: Optional[Dict[str, Any]] = None, body_map: Optional[Dict[str, Any]] = None, method: str = "GET") -> Dict[str, Any]:
    """Control Plane API request"""
    # Validate required parameters
    if not uri or not uri.strip():
        raise ValueError("uri is required and cannot be empty")
    
    # Ensure proper URL joining by removing leading slash from uri and ensuring base ends with slash
    base_url = config.cloud_uri.rstrip('/') + '/'
    clean_uri = uri.lstrip('/')
    url = urljoin(base_url, clean_uri)
    if method.upper() == "GET":
        return get(url, params_map)
    elif method.upper() == "POST":
        return post(url, params_map, body_map)
    elif method.upper() == "DELETE":
        return delete(url, params_map)
    else:
        raise ValueError(f"Unsupported method: {method}")


def data_plane_api_request(uri: str, cluster_id: str, region_id: str, params_map: Optional[Dict[str, Any]] = None, body_map: Optional[Dict[str, Any]] = None, method: str = "GET") -> Dict[str, Any]:
    """Data Plane API request.

    The data-plane base URL is resolved from control-plane cluster metadata
    and checked against the Zilliz Cloud allowlist before any token is sent.
    """
    if not uri or not uri.strip():
        raise ValueError("uri is required and cannot be empty")
    if not cluster_id or not cluster_id.strip():
        raise ValueError("cluster_id is required and cannot be empty")
    if not region_id or not region_id.strip():
        raise ValueError("region_id is required and cannot be empty")

    method_upper = method.upper()
    if method_upper not in ("GET", "POST", "DELETE"):
        raise ValueError(f"Unsupported method: {method}")

    base_url = _resolve_cluster_endpoint(cluster_id, region_id)
    clean_uri = uri.lstrip('/')
    url = urljoin(base_url, clean_uri)

    if method_upper == "GET":
        return get(url, params_map)
    elif method_upper == "POST":
        return post(url, params_map, body_map)
    return delete(url, params_map) 