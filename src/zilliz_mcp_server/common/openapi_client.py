import requests
from requests.exceptions import HTTPError
from typing import Dict, Any, Optional
from urllib.parse import urljoin
from zilliz_mcp_server.settings import config


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


def data_plane_api_request(endpoint:str, uri: str, cluster_id: str, region_id: str, params_map: Optional[Dict[str, Any]] = None, body_map: Optional[Dict[str, Any]] = None, method: str = "GET") -> Dict[str, Any]:
    """Data Plane API request"""
    # Validate required parameters
    if not uri or not uri.strip():
        raise ValueError("uri is required and cannot be empty")
    if not cluster_id or not cluster_id.strip():
        raise ValueError("cluster_id is required and cannot be empty")
    if not region_id or not region_id.strip():
        raise ValueError("region_id is required and cannot be empty")
    
    # Ensure proper URL joining by removing leading slash from uri and ensuring base ends with slash
    base_url = endpoint.rstrip('/') + '/'
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