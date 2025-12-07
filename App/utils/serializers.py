"""
Serialization utilities for msgpack data.
"""

import base64
import msgpack
from typing import Dict, Any, Union

from ..core.exceptions import DeserializationError


class CheckpointSerializer:
    """Handles deserialization of checkpoint data."""
    
    @classmethod
    def deserialize(cls, checkpoint_blob: Union[bytes, str, Any]) -> Dict[str, Any]:
        """
        Deserialize checkpoint data from DynamoDB.
        
        Args:
            checkpoint_blob: Raw checkpoint data
            
        Returns:
            Deserialized checkpoint dictionary
            
        Raises:
            DeserializationError: If deserialization fails
        """
        try:
            # Convert to bytes
            raw_bytes = cls._to_bytes(checkpoint_blob)
            
            # Validate not empty
            if len(raw_bytes) == 0:
                raise DeserializationError("Checkpoint data is empty")
            
            # Unpack msgpack
            return msgpack.unpackb(
                raw_bytes,
                raw=False,
                ext_hook=cls._decode_exttype,
                strict_map_key=False
            )
            
        except DeserializationError:
            raise
        except msgpack.exceptions.ExtraData as e:
            raise DeserializationError("Extra data in msgpack", e)
        except msgpack.exceptions.UnpackException as e:
            raise DeserializationError("Invalid msgpack format", e)
        except Exception as e:
            raise DeserializationError(f"Unexpected error: {str(e)}", e)
    
    @staticmethod
    def _to_bytes(checkpoint_blob: Union[bytes, str, Any]) -> bytes:
        """Convert checkpoint blob to bytes."""
        # Handle boto3 Binary type
        if hasattr(checkpoint_blob, '__class__') and 'Binary' in checkpoint_blob.__class__.__name__:
            return bytes(checkpoint_blob)
        
        # Handle bytes/bytearray
        if isinstance(checkpoint_blob, (bytes, bytearray)):
            return bytes(checkpoint_blob)
        
        # Handle base64 string
        if isinstance(checkpoint_blob, str):
            try:
                return base64.b64decode(checkpoint_blob)
            except Exception as e:
                raise DeserializationError(f"Invalid base64 string: {str(e)}", e)
        
        raise DeserializationError(f"Unsupported checkpoint type: {type(checkpoint_blob)}")
    
    @classmethod
    def _decode_exttype(cls, code: int, data: bytes):
        """
        Decode msgpack ExtType objects.
        Code 5 is used by LangChain for serialized messages.
        """
        if code == 5:
            try:
                unpacked = msgpack.unpackb(
                    data,
                    raw=False,
                    strict_map_key=False,
                    ext_hook=cls._decode_exttype
                )
                
                # LangChain format: [module, class, properties_dict]
                if isinstance(unpacked, (list, tuple)) and len(unpacked) >= 3:
                    properties = unpacked[2]
                    return properties if isinstance(properties, dict) else unpacked
                
                return unpacked
                
            except Exception:
                # If nested unpacking fails, return raw data
                return data
        
        # Unknown ExtType code
        return msgpack.ExtType(code, data)


def extract_messages(checkpoint_data: Dict[str, Any]) -> list:
    """
    Extract messages from checkpoint data.
    
    Args:
        checkpoint_data: Deserialized checkpoint
        
    Returns:
        List of message dictionaries
    """
    # Try different possible locations for messages
    messages_raw = (
        checkpoint_data.get("channel_values", {}).get("messages") or
        checkpoint_data.get("values", {}).get("messages") or
        checkpoint_data.get("messages") or
        []
    )
    
    if not isinstance(messages_raw, list):
        return []
    
    # Parse each message
    parsed_messages = []
    for idx, msg in enumerate(messages_raw):
        try:
            parsed = _parse_message(msg)
            if parsed:
                parsed_messages.append(parsed)
        except Exception as e:
            # Skip messages that can't be parsed
            print(f"Warning: Failed to parse message at index {idx}: {e}")
            continue
    
    return parsed_messages


def _parse_message(msg: Any) -> dict:
    """Parse a single message."""
    if not isinstance(msg, dict):
        return None
    
    content = msg.get("content", "")
    
    # Handle structured content (AI messages with tool calls, etc.)
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
        content = " ".join(text_parts) if text_parts else ""
    
    # Ensure content is a string
    if not isinstance(content, str):
        content = str(content)
    
    return {
        "role": msg.get("type", "unknown"),
        "content": content,
        "id": msg.get("id"),
        "name": msg.get("name")
    }