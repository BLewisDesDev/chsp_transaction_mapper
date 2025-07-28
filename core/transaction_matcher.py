from typing import Any, Dict, List, Optional

from core.client_map_loader import ClientMapLoader
from fuzzywuzzy import fuzz
from models.match_result import MatchResult
from models.transaction import Transaction


class TransactionMatcher:
    """Core matching engine for transactions."""

    def __init__(self, config: Dict[str, Any], client_map: ClientMapLoader):
        self.config = config
        self.client_map = client_map
        self.matching_config = config.get("matching", {})
        self.thresholds = self.matching_config.get("confidence_thresholds", {
            "high": 0.85,
            "medium": 0.60,
            "low": 0.40
        })

    def match_transaction(self, transaction: Transaction) -> MatchResult:
        """Match a single transaction using available strategies."""

        # Strategy 1: Exact platform identifier match (prioritized for ShiftCare)
        if transaction.client_identifier:
            client_id = self.client_map.find_client_by_platform_id(
                transaction.platform,
                transaction.client_identifier
            )
            if client_id:
                return MatchResult(
                    transaction_id=transaction.transaction_id,
                    client_caura_id=client_id,
                    confidence_score=1.0,
                    match_method="exact_client_id",
                    match_details={"matched_identifier": transaction.client_identifier},
                    is_matched=True,
                    requires_review=False
                )

        # Strategy 2: Exact email match (fallback)
        if transaction.email:
            client_id = self.client_map.find_client_by_email(transaction.email)
            if client_id:
                return MatchResult(
                    transaction_id=transaction.transaction_id,
                    client_caura_id=client_id,
                    confidence_score=1.0,
                    match_method="exact_email",
                    match_details={"matched_email": transaction.email},
                    is_matched=True,
                    requires_review=False
                )

        # Strategy 3: Paper receipt specific matching (name + suburb verification)
        if transaction.platform == "paper_receipt":
            result = self._paper_receipt_match(transaction)
            if result:
                return result

        # Strategy 4: Fuzzy name match (for all platforms)
        result = self._fuzzy_name_match(transaction)
        if result:
            return result

        # Strategy 5: Address match
        result = self._address_match(transaction)
        if result:
            return result

        # No match found
        return MatchResult(
            transaction_id=transaction.transaction_id,
            client_caura_id=None,
            confidence_score=0.0,
            match_method="no_match",
            match_details={},
            is_matched=False,
            requires_review=True
        )

    def _fuzzy_name_match(self, transaction: Transaction) -> Optional[MatchResult]:
        """Attempt fuzzy matching on names extracted from description."""
        description = transaction.description.lower()
        name_threshold = self.matching_config.get("fuzzy_matching", {}).get("name_threshold", 0.85)

        # Get all client names for comparison
        self.client_map.load_client_map()

        best_match = None
        best_score = 0.0
        best_client_id = None

        for caura_id, client in self.client_map._client_cache.items():
            personal_info = client.get("personal_info", {})
            given_name = personal_info.get("given_name", "")
            family_name = personal_info.get("family_name", "")
            full_name = f"{given_name} {family_name}".strip().lower()

            if not full_name:
                continue

            # Check if name appears in description
            if full_name in description:
                score = 1.0
            else:
                # Fuzzy match against description
                score = fuzz.partial_ratio(full_name, description) / 100.0

            if score > best_score and score >= (name_threshold / 100.0):
                best_score = score
                best_client_id = caura_id
                best_match = full_name

        if best_match and best_score >= (name_threshold / 100.0):
            requires_review = best_score < self.thresholds["high"]

            return MatchResult(
                transaction_id=transaction.transaction_id,
                client_caura_id=best_client_id,
                confidence_score=best_score,
                match_method="fuzzy_name",
                match_details={
                    "matched_name": best_match,
                    "fuzzy_score": best_score
                },
                is_matched=True,
                requires_review=requires_review
            )

        return None

    def _paper_receipt_match(self, transaction: Transaction) -> Optional[MatchResult]:
        """Enhanced matching for paper receipts using name and suburb verification."""
        client_name = transaction.platform_metadata.get("client_name")
        client_suburb = transaction.platform_metadata.get("client_suburb")
        
        if not client_name:
            return None
            
        name_threshold = self.matching_config.get("fuzzy_matching", {}).get("name_threshold", 0.85) / 100.0
        
        self.client_map.load_client_map()
        
        best_match = None
        best_score = 0.0
        best_client_id = None
        best_details = {}
        
        for caura_id, client in self.client_map._client_cache.items():
            personal_info = client.get("personal_info", {})
            given_name = personal_info.get("given_name", "")
            family_name = personal_info.get("family_name", "")
            full_name = f"{given_name} {family_name}".strip()
            
            if not full_name:
                continue
            
            # Calculate name similarity
            name_score = fuzz.ratio(client_name.lower(), full_name.lower()) / 100.0
            
            # If we have suburb info, use it for verification
            suburb_boost = 0.0
            if client_suburb and name_score >= 0.60:  # Only check suburb for reasonable name matches
                client_location = client.get("location", {})
                client_location_suburb = client_location.get("suburb", "")
                
                if client_location_suburb:
                    suburb_score = fuzz.ratio(client_suburb.lower(), client_location_suburb.lower()) / 100.0
                    if suburb_score >= 0.80:  # Suburb matches well
                        suburb_boost = 0.15  # Boost overall confidence
            
            total_score = min(1.0, name_score + suburb_boost)
            
            if total_score > best_score and total_score >= name_threshold:
                best_score = total_score
                best_client_id = caura_id
                best_match = full_name
                best_details = {
                    "matched_name": full_name,
                    "input_name": client_name,
                    "name_score": name_score,
                    "suburb_boost": suburb_boost,
                    "suburb_verified": suburb_boost > 0,
                    "input_suburb": client_suburb
                }
        
        if best_match and best_score >= name_threshold:
            requires_review = best_score < self.thresholds["high"]
            
            return MatchResult(
                transaction_id=transaction.transaction_id,
                client_caura_id=best_client_id,
                confidence_score=best_score,
                match_method="paper_receipt_name_fuzzy",
                match_details=best_details,
                is_matched=True,
                requires_review=requires_review
            )
        
        return None

    def _address_match(self, transaction: Transaction) -> Optional[MatchResult]:
        """Attempt address matching from transaction description."""
        description = transaction.description
        address_threshold = self.matching_config.get("address_matching", {}).get("min_score", 0.80)

        # Use the new address search method
        address_result = self.client_map.find_client_by_street_address(description, address_threshold)

        if address_result:
            client_id, match_score, match_details = address_result
            requires_review = match_score < self.thresholds["high"]

            return MatchResult(
                transaction_id=transaction.transaction_id,
                client_caura_id=client_id,
                confidence_score=match_score,
                match_method="address_match",
                match_details=match_details,
                is_matched=True,
                requires_review=requires_review
            )

        return None

    def bulk_match_transactions(self, transactions: List[Transaction]) -> List[MatchResult]:
        """Match multiple transactions efficiently."""
        return [self.match_transaction(tx) for tx in transactions]
