from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import date
from decimal import Decimal


class Transaction(BaseModel):
    """Base transaction model for all platforms."""
    
    transaction_id: str
    date: date
    amount: Decimal
    description: str
    reference: Optional[str] = None
    email: Optional[str] = None
    client_identifier: Optional[str] = None
    platform: str
    platform_metadata: Dict[str, Any] = {}
    raw_data: Dict[str, Any] = {}
    
    class Config:
        json_encoders = {
            Decimal: str,
            date: lambda v: v.isoformat()
        }