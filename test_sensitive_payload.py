import json
from agent.parser import parse_github_webhook, SDLCEvent

# Load the sensitive RBAC payload
with open('validate/sensitive_rbac_webhook_payload.json', 'r') as f:
    payload = json.load(f)

print('=== Payload loaded successfully ===')
print('Action:', payload["action"])
print('Issue number:', payload["issue"]["number"])
print('Issue title:', payload["issue"]["title"])
print('Issue body:', payload["issue"]["body"][:100] + "...")
print('Repository:', payload["repository"]["full_name"])
print('Sender:', payload["sender"]["login"])

# Parse the webhook
event = parse_github_webhook(payload)
print()
print('=== Parsed SDLCEvent ===')
print('Source:', event.source)
print('Event Type:', event.event_type)
print('Issue ID:', event.issue_id)
print('Title:', event.title)
print('Description:', event.description)
print('Repository:', event.repository)

# Verify it's the right type
assert isinstance(event, SDLCEvent), 'Failed to parse as SDLCEvent'
print()
print('=== Validation PASSED ===')