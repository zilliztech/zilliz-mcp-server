import httpx
import json

url = "http://127.0.0.1:8000/mcp/"

headers = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "mcp-session-id": "test-session-from-python-2",
}

data = {
    "jsonrpc": "2.0",
    "method": "list_projects",
    "params": {},
    "id": 1,
}

print(f"Attempting to POST to {url}")
print(f"Headers: {json.dumps(headers, indent=2)}")
print(f"Body: {json.dumps(data, indent=2)}")

try:
    with httpx.Client() as client:
        with client.stream("POST", url, headers=headers, json=data, timeout=30) as response:
            print(f"\n--- Response ---")
            print(f"Status Code: {response.status_code}")
            
            print("\nResponse Headers:")
            for key, value in response.headers.items():
                print(f"  {key}: {value}")

            # Read the response body regardless of status code to get error details
            response_body = response.read()

            # Now check the status code and print the body if it's an error
            if response.status_code >= 400:
                print("\n--- Error Body ---")
                print(response_body.decode())
                print("------------------")
                # Manually raise the error after printing the body
                response.raise_for_status() 
            
            print("\n--- Successful Response Body ---")
            print(response_body.decode(), end='')
            print("\n------------------------------\n")
            
except httpx.HTTPStatusError as exc:
    print(f"\n--- HTTP Error Handled ---")
    print(f"Client error '{exc.response.status_code} {exc.response.reason_phrase}' for url '{exc.request.url}'")
    print("----------------------------\n")
except httpx.RequestError as exc:
    print(f"\n--- Request Error ---")
    print(f"An error occurred while requesting {exc.request.url!r}.")
    print(f"Error details: {exc}")
    print("---------------------\n")
except Exception as e:
    print(f"\n--- An unexpected error occurred ---")
    print(f"{e}")
    print("------------------------------------") 