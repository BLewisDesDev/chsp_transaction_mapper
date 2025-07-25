from pydantic import BaseModel
from typing import Optional, Dict, Any, List


class MatchResult(BaseModel):
    """Result of matching a transaction to a client."""
    
    transaction_id: str
    client_caura_id: Optional[str] = None
    confidence_score: float  # 0.0 - 1.0
    match_method: str  # "exact_email", "exact_client_id", "fuzzy_name", "no_match"
    match_details: Dict[str, Any] = {}
    is_matched: bool
    requires_review: bool = False
    
    @property
    def confidence_level(self) -> str:
        """Get confidence level based on score."""
        if self.confidence_score >= 0.85:
            return "high"
        elif self.confidence_score >= 0.60:
            return "medium"
        else:
            return "low"