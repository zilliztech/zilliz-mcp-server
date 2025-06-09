"""
Simple example usage of the Zilliz configuration.
"""

# Import the config
from zilliz_mcp_server.settings import config, get_config
from zilliz_mcp_server.common import openapi_client
from zilliz_mcp_server.tools.zilliz import zilliz_tools
from zilliz_mcp_server.tools.milvus import milvus_tools

def example_usage():
    """Example: Using the three Zilliz configuration values."""
    
    # Method 1: Use global config directly
    print("=== Using global config ===")
    print(f"Cloud URI: {config.cloud_uri}")
    print(f"Cluster Endpoint: {config.cluster_endpoint}")
    print(f"Token: {'***' if config.token else 'Not set'}")
    print()
    
    # Method 2: Use get_config() function
    print("=== Using get_config() function ===")
    cfg = get_config()
    print(f"Cloud URI: {cfg.cloud_uri}")
    print(f"Cluster Endpoint: {cfg.cluster_endpoint}")
    print(f"Token: {'***' if cfg.token else 'Not set'}")
    print()
    
    # Check if configuration is complete
    if cfg.token and cfg.cluster_endpoint:
        print("✅ Zilliz Cloud configuration is complete!")
    else:
        print("❌ Missing Zilliz Cloud configuration. Please check your .env file.")

def test_list_projects():
    """Test: Call List Projects API using openapi_client."""
    
    print("\n=== Testing List Projects API ===")
    
    if not config.token:
        print("❌ Token not configured, skipping API test")
        return
    
    # result = zilliz_tools.get_projects_info()
    # print(result)
    # result = zilliz_tools.list_clusters()
    # print(result)
    result = milvus_tools.list_databases(cluster_id="in03-1ee145b380e2e6a", region_id="gcp-us-west1")
    print(result)

if __name__ == "__main__":
    example_usage()
    test_list_projects() 