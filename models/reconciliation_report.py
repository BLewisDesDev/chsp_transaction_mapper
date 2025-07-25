from pydantic import BaseModel
from typing import List, Dict
from datetime import datetime
from models.match_result import MatchResult


class ReconciliationReport(BaseModel):
    """Report containing reconciliation results."""
    
    run_id: str
    platform: str
    run_date: datetime
    source_identifier: str  # file path or API endpoint
    total_transactions: int
    matched_transactions: int
    unmatched_transactions: int
    requires_review: int
    confidence_distribution: Dict[str, int]  # high/medium/low counts
    match_method_breakdown: Dict[str, int]
    processing_time: float
    match_results: List[MatchResult]
    
    @classmethod
    def from_match_results(cls, 
                          run_id: str,
                          platform: str,
                          source_identifier: str,
                          match_results: List[MatchResult],
                          processing_time: float) -> "ReconciliationReport":
        """Create report from match results."""
        
        total = len(match_results)
        matched = sum(1 for r in match_results if r.is_matched)
        unmatched = total - matched
        review_needed = sum(1 for r in match_results if r.requires_review)
        
        # Calculate confidence distribution
        confidence_dist = {"high": 0, "medium": 0, "low": 0}
        for result in match_results:
            confidence_dist[result.confidence_level] += 1
        
        # Calculate method breakdown
        method_breakdown = {}
        for result in match_results:
            method = result.match_method
            method_breakdown[method] = method_breakdown.get(method, 0) + 1
        
        return cls(
            run_id=run_id,
            platform=platform,
            run_date=datetime.now(),
            source_identifier=source_identifier,
            total_transactions=total,
            matched_transactions=matched,
            unmatched_transactions=unmatched,
            requires_review=review_needed,
            confidence_distribution=confidence_dist,
            match_method_breakdown=method_breakdown,
            processing_time=processing_time,
            match_results=match_results
        )