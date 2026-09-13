import hmac
import hashlib
import json
import requests
import os

# Configuration
URL = "http://localhost:8000/webhooks/github"
SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "") # Must match the env var in your app

# Mock GitHub Issue Payload
payload = {
    "action": "opened",
    "issue": {
        "number": 5,
        "title": "Create a hello world script",
        "body": "Add a new file named hello_world.py that prints 'Hello from Autonomous Agent'."
    },
    "repository": {
        "full_name": "test-user/test-repo"
    }
}

body = json.dumps(payload).encode()

# Prepare Headers
headers = {
    "Content-Type": "application/json",
    "X-GitHub-Event": "issues",
}

# Add signature if secret is provided
if SECRET:
    signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    headers["X-Hub-Signature-256"] = signature

# Send Request
def run_test():
    print(f"Sending request to {URL}...")
    try:
        response = requests.post(URL, data=body, headers=headers)
        print(f"Status Code: {response.status_code}")
        print("Response Body:")
        print(json.dumps(response.json(), indent=2))
    except requests.exceptions.ConnectionError:
        print(f"Error: Could not connect to the server at {URL}.")
        print("Make sure the server is running (e.g., run 'python sdlc_harness_main.py').")

if __name__ == "__main__":
    run_test()
