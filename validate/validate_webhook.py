import hmac
import hashlib
import json
import requests
import os

# Configuration
URL = "http://localhost:8000/webhooks/github"
SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "") # Must match the env var in your app

# Mock GitHub Issue Payload (enhanced with full GitHub webhook structure)
# This payload includes all fields that GitHub sends for the "issues" event "opened" action,
# making it suitable for realistic SDLC workflow testing and signature verification.
payload = {
    "action": "opened",
    "issue": {
        "url": "https://api.github.com/repos/Kenono2000/enterprise-rag-pgvector-rbac/issues/1",
        "repository_url": "https://api.github.com/repos/Kenono2000/enterprise-rag-pgvector-rbac",
        "labels_url": "https://api.github.com/repos/Kenono2000/enterprise-rag-pgvector-rbac/issues/1/labels{/name}",
        "comments_url": "https://api.github.com/repos/Kenono2000/enterprise-rag-pgvector-rbac/issues/1/comments",
        "events_url": "https://api.github.com/repos/Kenono2000/enterprise-rag-pgvector-rbac/issues/1/events",
        "number": 1,
        "state": "open",
        "title": "Create a hello world script 1",
        "body": "Add a new file named hello_world.py that prints 'Hello from Autonomous Agent 1'.",
        "number": 1,
        "milestone": None,
        "labels": [
            {
                "id": 9643,
                "url": "https://api.github.com/repos/Kenono2000/enterprise-rag-pgvector-rbac/labels/enhancement",
                "name": "enhancement",
                "color": "a2eeef"
            }
        ],
        "assignee": None,
        "requested_reviewers": [],
        "requested_teams": [],
        "closed_by": None,
        "created_at": "2024-01-15T10:30:00Z",
        "updated_at": "2024-01-15T10:30:00Z",
        "closed_at": None,
        "timeline_type": "creation",
        "author_association": "owner",
        "body_html": "<p>Add a new file named hello_world.py that prints 'Hello from Autonomous Agent 1'.</p>",
        "reactions": {
            "url": "https://api.github.com/repos/Kenono2000/enterprise-rag-pgvector-rbac/issues/1/reactions",
            "total_count": 0,
            "+1": 0,
            "-1": 0,
            "laugh": 0,
            "hooray": 0,
            "confused": 0,
            "heart": 0,
            "rocket": 0
        },
        "pull_request": None,
        "closed_at": None,
        "pull_request_commits_url": "https://api.github.com/repos/Kenono2000/enterprise-rag-pgvector-rbac/issues/1/commits{/sha}",
        "pull_request_review_comments_url": "https://api.github.com/repos/Kenono2000/enterprise-rag-pgvector-rbac/issues/1/pull_request_review_comments",
        "pull_request_reviews_url": "https://api.github.com/repos/Kenono2000/enterprise-rag-pgvector-rbac/issues/1/pull_request_reviews",
        "pull_request_review_comments_total_count": 0,
        "maintainer_can_modify": True,
        "template": None
    },
    "repository": {
        "id": 12345678,
        "node_id": "MDEwOlJlcG9zaXRvcnkxMjM0NTY3OA==",
        "name": "enterprise-rag-pgvector-rbac",
        "full_name": "Kenono2000/enterprise-rag-pgvector-rbac",
        "private": False,
        "owner": {
            "login": "Kenono2000",
            "id": 12345678,
            "node_id": "MDQ6VXNlcjEyMzQ1Njc4",
            "avatar_url": "https://github.com/images/error/octocat_happy_avatar.png",
            "gravatar_id": "",
            "url": "https://api.github.com/users/Kenono2000",
            "html_url": "https://github.com/Kenono2000",
            "followers_url": "https://api.github.com/users/Kenono2000/followers",
            "following_url": "https://api.github.com/users/Kenono2000/following{/other_user}",
            "gists_url": "https://api.github.com/users/Kenono2000/gists{/gist_id}",
            "starred_url": "https://api.github.com/users/Kenono2000/starred{/owner}{/repo}",
            "subscriptions_url": "https://api.github.com/users/Kenono2000/subscriptions",
            "organizations_url": "https://api.github.com/users/Kenono2000/organizations",
            "repos_url": "https://api.github.com/users/Kenono2000/repos",
            "events_url": "https://api.github.com/users/Kenono2000/events{/type}",
            "received_events_url": "https://api.github.com/users/Kenono2000/received_events",
            "type": "User",
            "site_admin": False
        },
        "html_url": "https://github.com/Kenono2000/enterprise-rag-pgvector-rbac",
        "description": "Enterprise RAG pipeline with pgvector and RBAC security",
        "fork": False,
        "url": "https://api.github.com/repos/Kenono2000/enterprise-rag-pgvector-rbac",
        "forks_url": "https://api.github.com/repos/Kenono2000/enterprise-rag-pgvector-rbac/forks",
        "keys_url": "https://api.github.com/repos/Kenono2000/enterprise-rag-pgvector-rbac/keys{/key_id}",
        "collaborators_url": "https://api.github.com/repos/Kenono2000/enterprise-rag-pgvector-rbac/collaborators{/username}",
        "teams_url": "https://api.github.com/repos/Kenono2000/enterprise-rag-pgvector-rbac/teams",
        "hooks_url": "https://api.github.com/repos/Kenono2000/enterprise-rag-pgvector-rbac/hooks",
        "git_url": "https://github.com/Kenono2000/enterprise-rag-pgvector-rbac",
        "ssh_url": "https://github.com/Kenono2000/enterprise-rag-pgvector-rbac",
        "clone_url": "https://github.com/Kenono2000/enterprise-rag-pgvector-rbac",
        "svn_url": "https://github.com/Kenono2000/enterprise-rag-pgvector-rbac",
        "subscribers_count": 42,
        "stargazers_count": 125,
        "watchers_count": 125,
        "language": "Python",
        "has_issues": True,
        "has_projects": True,
        "has_wiki": True,
        "has_pages": False,
        "has_downloads": True,
        "archived": False,
        "disabled": False,
        "open_issues_count": 15,
        "topics": ["rag", "pgvector", "rbac", "automation"],
        "default_branch": "main",
        "score": None
    },
    "sender": {
        "login": "Kenono2000",
        "id": 12345678,
        "node_id": "MDQ6VXNlcjEyMzQ1Njc4",
        "avatar_url": "https://github.com/images/error/octocat_happy_avatar.png",
        "gravatar_id": "",
        "url": "https://api.github.com/users/Kenono2000",
        "html_url": "https://github.com/Kenono2000",
        "followers_url": "https://api.github.com/users/Kenono2000/followers",
        "following_url": "https://api.github.com/users/Kenono2000/following{/other_user}",
        "gists_url": "https://api.github.com/users/Kenono2000/gists{/gist_id}",
        "starred_url": "https://api.github000/enterprise-rag-pgvector-rbac/starred{/owner}{/repo}",
        "subscriptions_url": "https://api.github.com/users/Kenono2000/subscriptions",
        "organizations_url": "https://api.github.com/users/Kenono2000/organizations",
        "repos_url": "https://api.github.com/users/Kenono2000/repos",
        "events_url": "https://api.github.com/users/Kenono2000/events{/type}",
        "received_events_url": "https://api.github.com/users/Kenono2000/received_events",
        "type": "User",
        "site_admin": False
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

if __name__ == "__main__":
    # Send Request
    print(f"Sending request to {URL}...")
    response = requests.post(URL, data=body, headers=headers)

    print(f"Status Code: {response.status_code}")
    print("Response Body:")
    print(json.dumps(response.json(), indent=2))