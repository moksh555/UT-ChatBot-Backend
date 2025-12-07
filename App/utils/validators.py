"""
Input validation utilities.
"""

import re
from ..core.exceptions import InvalidThreadIDError


class ThreadIDValidator:
    """Validator for thread IDs."""
    
    # Only alphanumeric, hyphens, and underscores
    VALID_PATTERN = re.compile(r'^[a-zA-Z0-9_][a-zA-Z0-9_@-]*$')
    MAX_LENGTH = 256
    
    @classmethod
    def validate(cls, thread_id: str) -> str:
        """
        Validate thread_id format.
        
        Args:
            thread_id: Thread ID to validate
            
        Returns:
            Validated thread_id
            
        Raises:
            InvalidThreadIDError: If validation fails
        """
        # Check if empty
        if not thread_id or not thread_id.strip():
            raise InvalidThreadIDError(thread_id, "thread_id cannot be empty")
        
        thread_id = thread_id.strip()
        
        # Check length
        if len(thread_id) > cls.MAX_LENGTH:
            raise InvalidThreadIDError(
                thread_id,
                f"thread_id exceeds maximum length of {cls.MAX_LENGTH}"
            )
        
        # Check pattern
        if not cls.VALID_PATTERN.match(thread_id):
            raise InvalidThreadIDError(
                thread_id,
                "thread_id can only contain alphanumeric characters, hyphens, and underscores"
            )
        
        return thread_id