import boto3
from datetime import datetime

dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
table = dynamodb.Table('langgraph-user-personal-history')

# Test 1: Create a new user
print("Test 1: Creating new user...")
table.put_item(
    Item={
        'user_id': 'test@example.com',
        'personal_history': [
            {
                'thread_id': 'thread-001',
                'title': 'What are the fees',
                'created_at': datetime.utcnow().isoformat(),
                'updated_at': datetime.utcnow().isoformat()
            }
        ],
        'created_at': datetime.utcnow().isoformat(),
        'updated_at': datetime.utcnow().isoformat()
    }
)
print("User created")

# Test 2: Get user data
print("\nTest 2: Getting user data...")
response = table.get_item(Key={'user_id': 'test@example.com'})
print(f"User data: {response.get('Item')}")

# Test 3: Update user history
print("\nTest 3: Updating user history...")
response = table.get_item(Key={'user_id': 'test@example.com'})
item = response.get('Item', {})
history = item.get('personal_history', [])

history.append({
    'thread_id': 'thread-002',
    'title': 'Tell me about scholarships',
    'created_at': datetime.utcnow().isoformat(),
    'updated_at': datetime.utcnow().isoformat()
})

table.update_item(
    Key={'user_id': 'test@example.com'},
    UpdateExpression='SET personal_history = :ph, updated_at = :ua',
    ExpressionAttributeValues={
        ':ph': history,
        ':ua': datetime.utcnow().isoformat()
    }
)
print("History updated")

# Test 4: Verify update
print("\nTest 4: Verifying update...")
response = table.get_item(Key={'user_id': 'test@example.com'})
print(f"Updated data: {response.get('Item')}")

# # Cleanup
# print("\nCleaning up...")
# table.delete_item(Key={'user_id': 'test@example.com'})
# print("Test data deleted")