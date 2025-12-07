"""
Custom exception classes for chat history API.
"""

from typing import Optional, Dict, Any


class ChatHistoryBaseException(Exception):
    """Base exception for all chat history errors."""
    
    def __init__(
        self, 
        message: str, 
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for API response."""
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "details": self.details
        }


# ============================================================================
# Client Errors (4xx)
# ============================================================================

class InvalidThreadIDError(ChatHistoryBaseException):
    """Raised when thread_id format is invalid."""
    
    def __init__(self, thread_id: str, reason: str):
        super().__init__(
            message=f"Invalid thread_id: {reason}",
            status_code=400,
            details={"thread_id": thread_id, "reason": reason}
        )


# ============================================================================
# Not Found Errors (404)
# ============================================================================

class ThreadNotFoundError(ChatHistoryBaseException):
    """Raised when thread doesn't exist."""
    
    def __init__(self, thread_id: str):
        super().__init__(
            message=f"Thread not found: {thread_id}",
            status_code=404,
            details={"thread_id": thread_id}
        )


# ============================================================================
# Server Errors (5xx)
# ============================================================================

class DeserializationError(ChatHistoryBaseException):
    """Raised when checkpoint deserialization fails."""
    
    def __init__(self, message: str, original_error: Optional[Exception] = None):
        details = {}
        if original_error:
            details["original_error"] = str(original_error)
            details["error_type"] = type(original_error).__name__
        
        super().__init__(
            message=f"Failed to deserialize checkpoint: {message}",
            status_code=500,
            details=details
        )


class DatabaseError(ChatHistoryBaseException):
    """Raised when DynamoDB operation fails."""
    
    def __init__(self, operation: str, original_error: Optional[Exception] = None):
        details = {"operation": operation}
        if original_error:
            details["original_error"] = str(original_error)
            details["error_type"] = type(original_error).__name__
        
        super().__init__(
            message=f"Database operation failed: {operation}",
            status_code=503,
            details=details
        )


class MessageProcessingError(ChatHistoryBaseException):
    """Raised when message processing fails."""
    
    def __init__(self, message_index: int, reason: str):
        super().__init__(
            message=f"Failed to process message at index {message_index}",
            status_code=500,
            details={"message_index": message_index, "reason": reason}
        )

class ChatProcessingError(ChatHistoryBaseException):
    """Raised when chat workflow processing fails."""
    
    def __init__(self, reason: str, original_error: Optional[Exception] = None):
        details = {"reason": reason}
        if original_error:
            details["original_error"] = str(original_error)
            details["error_type"] = type(original_error).__name__
        
        super().__init__(
            message=f"Chat processing failed: {reason}",
            status_code=500,
            details=details
        )