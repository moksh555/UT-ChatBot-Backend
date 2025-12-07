"""
FastAPI application with proper exception handling.
"""

from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
import boto3
from pydantic import BaseModel
from langchain_core.messages import HumanMessage

# Import your custom exceptions and utilities
from .core.exceptions import (
    ChatHistoryBaseException,
    InvalidThreadIDError,
    ThreadNotFoundError,
    DeserializationError,
    DatabaseError
)
from .utils.validators import ThreadIDValidator
from .utils.serializers import CheckpointSerializer, extract_messages
import os
from dotenv import load_dotenv
from ChatBot.LangGraph_workflow import app as langgraph_app

load_dotenv()

app = FastAPI(title="Chat History API")

# Your existing DynamoDB setup
dynamodb = boto3.resource('dynamodb', region_name=os.getenv("AWS_REGION", "us-east-1"))
check_pointer_table = os.getenv("CHECKPOINTER_TABLE", "langgraph-checkpoints")
user_personal_history_table = os.getenv("USER_PERSONAL_HISTORY", "user-personal-history")

# ============================================================================
# Global Exception Handlers
# ============================================================================

@app.exception_handler(ChatHistoryBaseException)
async def chat_history_exception_handler(request: Request, exc: ChatHistoryBaseException):
    """Handle all custom exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict()
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions."""
    return JSONResponse(
        status_code=500,
        content={
            "error": "InternalServerError",
            "message": "An unexpected error occurred",
            "details": {"error_type": type(exc).__name__}
        }
    )


# ============================================================================
# API Endpoints
# ============================================================================


# ---------------------------------------------------------------------------------------------------------------------
# GET Chat History
# ---------------------------------------------------------------------------------------------------------------------
@app.get("/chats/{thread_id}")
async def get_chat_history(thread_id: str, max_messages: int = 1000):
    """
    Retrieve chat history for a thread.
    
    Args:
        thread_id: Unique conversation identifier
        max_messages: Maximum number of messages to return
        
    Returns:
        JSON with thread_id, message_count, and messages
        
    Raises:
        InvalidThreadIDError: If thread_id format is invalid (400)
        ThreadNotFoundError: If thread doesn't exist (404)
        DatabaseError: If DynamoDB operation fails (503)
        DeserializationError: If checkpoint can't be parsed (500)
    """

    # Validate thread_id
    thread_id = ThreadIDValidator.validate(thread_id)
    
    try:
        # Query DynamoDB
        table = dynamodb.Table(check_pointer_table)
        response = table.query(
            KeyConditionExpression=Key("PK").eq(thread_id),
            ScanIndexForward=False,
            Limit=1,
            ConsistentRead=True
        )
        
        items = response.get("Items", [])
        
        # Check if thread exists
        if not items:
            return {
                "thread_id": thread_id,
                "message_count": 0,
                "messages": []
            }
        
        # Get checkpoint blob
        latest_checkpoint = items[0]
        checkpoint_blob = latest_checkpoint.get("checkpoint")
        
        if not checkpoint_blob:
            raise DeserializationError("Checkpoint blob is missing")
        
        # Deserialize checkpoint
        checkpoint_data = CheckpointSerializer.deserialize(checkpoint_blob)
        
        # Extract messages
        messages = extract_messages(checkpoint_data)
        
        # Limit messages
        # if len(messages) > max_messages:
        #     messages = messages[:max_messages]
        
        return {
            "thread_id": thread_id,
            "message_count": len(messages),
            "messages": messages
        }
        
    except ChatHistoryBaseException:
        # Re-raise our custom exceptions (handled by exception handler)
        raise
    
    except ClientError as e:
        # Handle DynamoDB errors
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        raise DatabaseError(f"DynamoDB query failed: {error_code}", e)
    
    except Exception as e:
        # Catch any unexpected errors
        raise DeserializationError(f"Unexpected error: {str(e)}", e)

#---------------------------------------------------------------------------------------------------------------------


#-----------------------------------------------------------------------------------------------------------------------------
# GET Personal Chat History(Stiill need to implement fully)
# ---------------------------------------------------------------------------------------------------------------------
class PersonalChatHistoryResponse(BaseModel):
    user_id: str
    personal_history: list

@app.get("/chats/personal-history/{user_id}", response_model=PersonalChatHistoryResponse)
def get_personal_chat_history(user_id: str):
    """
    Retrieve personal chat history for a user.
    
    Args:
        user_id: Unique user identifier
        
    Returns:
        JSON with user_id and personal chat history
    """
    # This is a placeholder implementation.
    # In a real application, you would integrate with your chat history storage here.
    try:
        table = dynamodb.Table(user_personal_history_table)
        response = table.get_item(Key={"user_id": user_id})
        item = response.get("Item", {})
        personal_history = item.get("personal_history", [])

        return PersonalChatHistoryResponse(
            user_id=user_id,
            personal_history=personal_history,
        )
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        raise DatabaseError(f"DynamoDB operation failed: {error_code}", e)
    except Exception as e:
        raise DatabaseError(f"Unexpected error: {str(e)}", e)
#---------------------------------------------------------------------------------------------------------------------



# ---------------------------------------------------------------------------------------------------------------------
# Chat with the ChatBot Model
#----------------------------------------------------------------------------------------------------------------------
class ChatRequest(BaseModel):
    user_message: str
    user: str

class ChatResponse(BaseModel):
    thread_id: str
    user_message: str
    model_response: str

@app.post("/chats/{thread_id}", response_model=ChatResponse)
def chat_with_model(thread_id: str, item: ChatRequest):
    """
    Endpoint to send a message to the chat model and receive a response.
    
    Args:
        thread_id: Unique conversation identifier
        user_message: Message from the user
        
    Returns:
        JSON with thread_id, user_message, and model_response
    """
    try:
        user_message = item.user_message
        user= item.user
        thread_id = ThreadIDValidator.validate(thread_id)

        #check and upodate personal history
        update_personal_history(thread_id, user, user_message)

        #setting up LangGraph workflow input
        config = {"configurable": {"thread_id": thread_id}}
        state = langgraph_app.invoke(
            {"messages": [HumanMessage(content=user_message)]},
            config=config
        )

        messages = state.get("messages", [])
        if messages:
            last_message = messages[-1]
            if hasattr(last_message, "content"):
                content = last_message.content

                if isinstance(content, list):
                    # If content is a list (structured), extract text parts
                    text_parts = []
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
                    ai_response = " ".join(text_parts) if text_parts else ""
                elif isinstance(content, str):
                    ai_response = content
                else:
                    ai_response = str(content)
            else:
                ai_response = str(last_message)
        else:
            ai_response = "No response from model."
        
        return ChatResponse(    
            thread_id=thread_id,
            user_message=user_message,
            model_response=ai_response
        )
    except ChatHistoryBaseException:
        # Re-raise our custom exceptions (handled by exception handler)
        raise
    except ClientError as e:    
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        raise DatabaseError(f"DynamoDB operation failed: {error_code}", e)
    except Exception as e:
        raise DatabaseError(f"Unexpected error: {str(e)}", e)

def update_personal_history(thread_id, user, user_message):
    try:
        table = dynamodb.Table(user_personal_history_table)
        response = table.get_item(Key={"user_id": user})
        item = response.get("Item", {})

        if item:
            personal_history = item.get("personal_history", [])

            #check for thread_id in personal history to pop it and append to very end for latest
            already_there = False
            for i, history in enumerate(personal_history):
                if history.get('thread_id') == thread_id:
                    already_there = True
                    personal_history.pop(i)
                    history['updated_at'] = datetime.utcnow().isoformat()
                    personal_history.append(history)
                    break
            
            if not already_there:
                personal_history.append({
                    "thread_id": thread_id,
                    "title": " ".join(user_message.split(" ")[:8]),
                    "created_at":  datetime.utcnow().isoformat(),
                    "updated_at": datetime.utcnow().isoformat()
                })
            
            if len(personal_history) > 20:
                personal_history = personal_history[-20:]
            
            #Updateing table with new personal history 
            table.update_item(  
                Key={"user_id": user},
                UpdateExpression="SET personal_history = :ph",
                ExpressionAttributeValues={":ph": personal_history}
            )
        else:
            # Create new user entry
            table.put_item(
                Item={
                    "user_id": user,
                    "personal_history": [
                        {
                            "thread_id": thread_id,
                            "title": " ".join(user_message.split(" ")[:8]),
                            "created_at":  datetime.utcnow().isoformat(),
                            "updated_at": datetime.utcnow().isoformat()
                        }
                    ],
                    "created_at": datetime.utcnow().isoformat(),
                    "updated_at": datetime.utcnow().isoformat()
                }
            )
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        raise DatabaseError(f"DynamoDB operation failed: {error_code}", e)
    except Exception as e:
        raise DatabaseError(f"Unexpected error: {str(e)}", e)
#----------------------------------------------------   ----------------------------------- -------------


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        table = dynamodb.Table(check_pointer_table)
        table.load()  # Simple operation to check table accessibility
        return {"status": "healthy"}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": str(e)}
        )