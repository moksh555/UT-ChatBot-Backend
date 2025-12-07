from dotenv import load_dotenv
import boto3
from botocore.exceptions import ClientError
import uuid

load_dotenv()

TABLE_NAME = "langgraph-checkpoints"

# session = boto3.Session()
# print("Using AWS region from boto3 session:", session.region_name)

def test_aws_credentials():
    """Verify AWS credentials are valid."""
    try:
        sts = boto3.client("sts")
        identity = sts.get_caller_identity()
        print("AWS credentials OK. User ARN:", identity["Arn"])
    except ClientError as e:
        print("AWS credentials failed:", e)
        return


def test_table_exists():
    """Check if DynamoDB table exists."""
    dynamodb = boto3.client("dynamodb")
    try:
        response = dynamodb.describe_table(TableName=TABLE_NAME)
        print("DynamoDB table exists:", response["Table"]["TableName"])
    except dynamodb.exceptions.ResourceNotFoundException:
        print(f"Table `{TABLE_NAME}` does NOT exist.")
        return


def test_table_key_schema():
    """Check table has correct partition/sort keys."""
    dynamodb = boto3.client("dynamodb")
    response = dynamodb.describe_table(TableName=TABLE_NAME)
    key_schema = response["Table"]["KeySchema"]

    expected = [
        {"AttributeName": "thread_id", "KeyType": "HASH"},
        {"AttributeName": "checkpoint_id", "KeyType": "RANGE"},
    ]

    if key_schema == expected:
        print("Key schema is correct.")
    else:
        print("Incorrect DynamoDB key schema.")
        print("Actual:", key_schema)
        print("Expected:", expected)


def test_put_and_get_item():
    """Write and read an item from DynamoDB to validate R/W permissions."""
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TABLE_NAME)

    test_thread = "test-thread"
    test_checkpoint = str(uuid.uuid4())
    test_data = {"hello": "world"}

    # PUT
    try:
        table.put_item(
            Item={
                "thread_id": test_thread,
                "checkpoint_id": test_checkpoint,
                "data": test_data,
            }
        )
        print("PutItem succeeded.")
    except ClientError as e:
        print("PutItem failed:", e)
        return

    # GET
    try:
        result = table.get_item(
            Key={
                "thread_id": test_thread,
                "checkpoint_id": test_checkpoint,
            }
        )
        print("GetItem returned:", result.get("Item"))
    except ClientError as e:
        print("GetItem failed:", e)

    # CLEANUP (optional)
    try:
        table.delete_item(
            Key={
                "thread_id": test_thread,
                "checkpoint_id": test_checkpoint,
            }
        )
        print("Cleanup succeeded.")
    except Exception:
        print("Cleanup failed (safe to ignore).")


if __name__ == "__main__":
    print("\nTESTING AWS + DYNAMODB SETUP...\n")
    test_aws_credentials()
    print("")
    test_table_exists()
    print("")
    test_table_key_schema()
    print("")
    test_put_and_get_item()
    print("\nTEST COMPLETE\n")
