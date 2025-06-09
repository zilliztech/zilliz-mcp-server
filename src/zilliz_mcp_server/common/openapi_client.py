import requests
from typing import Dict, Any, Optional
from ..settings import config


def _get_headers() -> Dict[str, str]:
    """Generate request headers"""
    headers = {
        "accept": "application/json",
        "content-type": "application/json"
    }
    
    if config.token:
        headers["Authorization"] = f"Bearer {config.token}"
    
    return headers


def get(url: str, params_map: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """GET request interface"""
    headers = _get_headers()
    response = requests.get(url, params=params_map, headers=headers)
    return response.json()


def post(url: str, params_map: Optional[Dict[str, Any]] = None, body_map: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """POST request interface"""
    headers = _get_headers()
    response = requests.post(url, params=params_map, json=body_map, headers=headers)
    return response.json()


def delete(url: str, params_map: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """DELETE request interface"""
    headers = _get_headers()
    response = requests.delete(url, params=params_map, headers=headers)
    return response.json()


def control_plane_api_request(uri: str, params_map: Optional[Dict[str, Any]] = None, body_map: Optional[Dict[str, Any]] = None, method: str = "GET") -> Dict[str, Any]:
    """Control Plane API request"""
    url = config.cloud_uri + uri
    
    if method.upper() == "GET":
        return get(url, params_map)
    elif method.upper() == "POST":
        return post(url, params_map, body_map)
    elif method.upper() == "DELETE":
        return delete(url, params_map)
    else:
        raise ValueError(f"Unsupported method: {method}")


def data_plane_api_request(uri: str, cluster_id: str, region_id: str, params_map: Optional[Dict[str, Any]] = None, body_map: Optional[Dict[str, Any]] = None, method: str = "GET") -> Dict[str, Any]:
    """Data Plane API request"""
    cluster_endpoint = config.cluster_endpoint.replace("${CLUSTER_ID}", cluster_id).replace("${CLOUD_REGION}", region_id)
    url = cluster_endpoint + uri
    
    if method.upper() == "GET":
        return get(url, params_map)
    elif method.upper() == "POST":
        return post(url, params_map, body_map)
    elif method.upper() == "DELETE":
        return delete(url, params_map)
    else:
        raise ValueError(f"Unsupported method: {method}") 