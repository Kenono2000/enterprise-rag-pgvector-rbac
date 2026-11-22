"""
Test script to verify the enhanced HITL approval flow.
"""
import asyncio
import json
from agent.workflow import LangGraphSDLCWorkflow
from agent.parser import parse_github_webhook


def test_hitl_approval_flow():
    """Test that HITL generates pending_approval status instead of blocking."""
    
    # Sample webhook payload (GitHub issue opened)
    # Force high-risk by using a high-risk file path pattern
    payload = {
        "action": "opened",
        "issue": {
            "number": 1,
            "title": "Create a hello world script 1",
            "body": "Add a new file named hello_world.py that prints Hello from Autonomous Agent 1."
        },
        "repository": {
            "full_name": "Kenono2000/enterprise-rag-pgvector-rbac"
        }
    }
    
    # Parse the webhook
    event = parse_github_webhook(payload)
    print(f"✓ Parsed webhook event: {event}")
    
    # Create workflow with HITL enabled
    async def run_workflow():
        workflow = LangGraphSDLCWorkflow(require_hitl_for_high_risk=True)
        result = await workflow.run(payload)
        return result
    
    # Run the workflow
    result = asyncio.run(run_workflow())
    
    # Verify the results
    print("\n" + "="*60)
    print("HITL FLOW TEST RESULTS")
    print("="*60)
    
    status = result.get("status")
    checkpoint_id = result.get("checkpoint_id")
    checkpoint_backend = result.get("checkpoint_backend")
    interrupted = result.get("interrupted")
    approval_card = result.get("approval_card")
    requires_human = result.get("requires_human_approval")
    message = result.get("message")
    
    print(f"\n1. Workflow Status: {status}")
    print(f"   - Expected: 'pending_approval' (was blocking before)")
    print(f"   - Actual: '{status}' {'✓' if status == 'pending_approval' else '✗'}")
    
    print(f"\n2. Checkpoint ID: {checkpoint_id}")
    print(f"   - Should exist for later resume: {checkpoint_id is not None}")
    
    print(f"\n3. Checkpoint Backend: {checkpoint_backend}")
    print(f"   - Should be PostgresSaver: {checkpoint_backend}")
    
    print(f"\n4. Interrupted: {interrupted}")
    print(f"   - Should be True (HITL triggered): {interrupted is True}")
    
    print(f"\n5. Requires Human Approval: {requires_human}")
    print(f"   - Should be True: {requires_human is True}")
    
    print(f"\n6. Approval Card:")
    if approval_card:
        print(f"   - risk_tier: {approval_card.get('risk_tier')}")
        print(f"   - requires_human_approval: {approval_card.get('requires_human_approval')}")
        print(f"   - status: {approval_card.get('status')}")
        print(f"   - affected_files: {approval_card.get('affected_files')}")
        print(f"   - reason: {approval_card.get('reason')}")
    else:
        print(f"   - No approval card (None)")
    
    print(f"\n7. Message: {message}")
    print(f"   - Should guide human on how to approve: '{message}'")
    
    # Validate results
    print("\n" + "="*60)
    print("VALIDATION")
    print("="*60)
    
    errors = []
    if status != "pending_approval":
        errors.append(f"✗ Status should be 'pending_approval', got '{status}'")
    else:
        print("✓ Status is 'pending_approval' (enhanced HITL works!)")
    
    if interrupted is not True:
        errors.append("✗ interrupted should be True")
    else:
        print("✓ interrupted is True")
    
    if requires_human is not True:
        errors.append("✗ requires_human_approval should be True")
    else:
        print("✓ requires_human_approval is True")
    
    if errors:
        print("\nErrors found:")
        for error in errors:
            print(f"  {error}")
        return False
    else:
        print("\n✓ ALL TESTS PASSED - Enhanced HITL is working correctly!")
        print("\nHuman can now:")
        print("  1. Check the approval card details above")
        print("  2. Use /api/v1/approval/decision endpoint to submit decision")
        print("  3. Or use any external notification system")
        return True


if __name__ == "__main__":
    success = test_hitl_approval_flow()
    exit(0 if success else 1)