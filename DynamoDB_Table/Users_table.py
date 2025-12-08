# create_users_table.py
import boto3

dynamodb = boto3.client('dynamodb', region_name='us-east-1')

try:
    response = dynamodb.create_table(
        TableName='langgraph-users',
        KeySchema=[
            {'AttributeName': 'user_id', 'KeyType': 'HASH'}
        ],
        AttributeDefinitions=[
            {'AttributeName': 'user_id', 'AttributeType': 'S'}
        ],
        BillingMode='PAY_PER_REQUEST'
    )
    print("✓ Users table created successfully!")
except Exception as e:
    print(f"Error: {e}")