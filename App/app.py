"""
FastAPI application with proper exception handling.
"""
import boto3
import os
from dotenv import load_dotenv
from datetime import datetime
from fastapi import FastAPI, Request, Depends, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from pydantic import BaseModel
from langchain_core.messages import HumanMessage

# Import your custom exceptions and utilities
from .core.exceptions import (
    ChatHistoryBaseException,
    InvalidThreadIDError,
    ThreadNotFoundError,
    DeserializationError,
    DatabaseError,
    NoAccessToThread
)
from .utils.validators import ThreadIDValidator
from .utils.serializers import CheckpointSerializer, extract_messages
from ChatBot.LangGraph_workflow import app as langgraph_app
from App.api.routes.google_oauth import router as google_oauth_router
from App.core.config import settings
from App.core.exceptions import ChatHistoryBaseException, InvalidThreadIDError, ThreadNotFoundError, DeserializationError, DatabaseError
from App.models.requests import UserRegister, UserLogin, ChatRequest
from App.models.responses import Token, UserResponse, ChatResponse
from App.services.auth_service import AuthService
from App.api.dependencies import get_current_user

load_dotenv()

app = FastAPI(title=settings.app_name, version=settings.app_version)
app.include_router(google_oauth_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://texascollegeguides.com", "https://www.texascollegeguides.com", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Your existing DynamoDB setup
dynamodb = boto3.resource('dynamodb', region_name=os.getenv("AWS_REGION", "us-east-1"))
check_pointer_table = os.getenv("CHECKPOINTER_TABLE", "langgraph-checkpoints")
user_personal_history_table = os.getenv("USER_PERSONAL_HISTORY", "user-personal-history")


auth_service = AuthService()

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

# ============================================================================
# Authentication Endpoints
# ============================================================================

@app.post("/auth/register", response_model=Token)
async def register(user_data: UserRegister):
    """Register a new user."""
    result = auth_service.register_user(
        email=user_data.email,
        password=user_data.password,
        full_name=user_data.full_name
    )
    return Token(access_token=result["access_token"])

@app.post("/auth/login", response_model=Token)
async def login(login_data: UserLogin):
    """Login with email and password."""
    result = auth_service.login_user(
        email=login_data.email,
        password=login_data.password
    )
    return Token(access_token=result["access_token"])

@app.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    """Get current user info."""
    user = auth_service.get_user_by_id(current_user["user_id"])
    return UserResponse(
        user_id=user["user_id"],
        email=user["email"],
        full_name=user.get("full_name"),
        created_at=user["created_at"]
    )

@app.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie(
        key=settings.access_cookie_name,
        path="/",
        domain=settings.cookie_domain or None,
    )
    return {"message": "Logged out"}
# ---------------------------------------------------------------------------------------------------------------------




# ---------------------------------------------------------------------------------------------------------------------
# GET Chat History
# ---------------------------------------------------------------------------------------------------------------------
@app.get("/chats/specific/{thread_id}")
async def get_chat_history(thread_id: str, max_messages: int = 100, current_user: dict = Depends(get_current_user)):
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
        current_user_id = current_user["email"]
        
        #first check if thread_id is in checpointer table if not then it is new and dont care about ownership else get along rest of the code
        checkpointer_table = dynamodb.Table(check_pointer_table)  # or settings.checkpointer_table
        response = checkpointer_table.query(
            KeyConditionExpression=Key("PK").eq(thread_id),
            ScanIndexForward=False,
            Limit=1,
            ConsistentRead=True,
        )

        items = response.get("Items", [])

        # If there is no checkpoint at all for this thread_id,
        # treat it as "no history yet" (new or invalid thread).
        if not items:
            return {
                "thread_id": thread_id,
                "message_count": 0,
                "messages": [],
            }

        # check for thread_id belongs to current user in personal history
        history_table = dynamodb.Table(user_personal_history_table)
        history_resp = history_table.get_item(Key={"user_id": current_user_id})
        history_item = history_resp.get("Item")

        # If user has no history at all
        if not history_item:
            # You can choose 404 or 403. 403 is more explicit:
            raise NoAccessToThread("You do not have access to this thread")

        personal_history = history_item.get("personal_history", [])

        # Check if this thread_id is in their personal_history list
        owns_thread = any(
            h.get("thread_id") == thread_id for h in personal_history
        )

        if not owns_thread:
            raise NoAccessToThread("You do not have access to this thread")

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

@app.get("/chats/personal-history", response_model=PersonalChatHistoryResponse)
async def get_personal_chat_history(current_user: dict = Depends(get_current_user)):
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
        user_id = current_user["email"]
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

class ChatResponse(BaseModel):
    thread_id: str
    user_message: str
    model_response: str

@app.post("/chats/{thread_id}", response_model=ChatResponse)
async def chat_with_model(thread_id: str, item: ChatRequest, current_user: dict = Depends(get_current_user)):
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
        user= current_user["email"]
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


# -----------------------------------------------------------------------------------------------------
# Health Check Endpoints
# -----------------------------------------------------------------------------------------------------
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

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Texas College ChatBot API",
        "version": settings.app_version,
        "status": "online"
    }
# -----------------------------------------------------------------------------------------------------