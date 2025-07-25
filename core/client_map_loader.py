import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from fuzzywuzzy import fuzz


class ClientMapLoader:
    """Read-only loader for CHSP Client Mapper registry."""

    def __init__(self, registry_path: str):
        self.registry_path = registry_path
        self._client_cache: Optional[Dict[str, Any]] = None
        self._email_index: Optional[Dict[str, str]] = None
        self._name_index: Optional[Dict[str, List[str]]] = None
        self._platform_index: Optional[Dict[str, Dict[str, str]]] = None

    def load_client_map(self) -> Dict[str, Any]:
        """Load and cache client registry."""
        if self._client_cache is None:
            with open(self.registry_path, 'r') as f:
                data = json.load(f)

            # Handle different JSON structures
            if isinstance(data, dict) and 'clients' in data:
                # New format: {"metadata": {...}, "clients": [...]}
                clients_list = data['clients']
                self._client_cache = {client['caura_id']: client for client in clients_list}
            elif isinstance(data, dict):
                # Old format: {"CL00001": {...}, "CL00002": {...}}
                self._client_cache = data
            else:
                raise ValueError("Invalid client registry format")

            self._build_indices()
        return self._client_cache

    def _build_indices(self):
        """Build lookup indices for fast matching."""
        if not self._client_cache:
            return

        self._email_index = {}
        self._name_index = {}
        self._platform_index = {}

        for caura_id, client in self._client_cache.items():
            # Email index
            emails = client.get("personal_info", {}).get("emails", [])
            for email in emails:
                if email:
                    self._email_index[email.lower()] = caura_id

            # Name index
            personal_info = client.get("personal_info", {})
            given_name = personal_info.get("given_name", "")
            family_name = personal_info.get("family_name", "")
            full_name = f"{given_name} {family_name}".strip()
            if full_name:
                name_key = full_name.lower()
                if name_key not in self._name_index:
                    self._name_index[name_key] = []
                self._name_index[name_key].append(caura_id)

            # Platform identifier index
            platform_ids = client.get("platform_identifiers", [])
            for platform_info in platform_ids:
                platform = platform_info.get("platform", "")
                identifiers = platform_info.get("identifiers", {})

                if platform not in self._platform_index:
                    self._platform_index[platform] = {}

                # Index by client_id if available
                client_id = identifiers.get("client_id")
                if client_id:
                    self._platform_index[platform][client_id] = caura_id

                # Index by display_name if available
                display_name = identifiers.get("display_name")
                if display_name:
                    self._platform_index[platform][display_name.lower()] = caura_id

    def find_client_by_email(self, email: str) -> Optional[str]:
        """Find client by email address."""
        self.load_client_map()
        return self._email_index.get(email.lower())

    def find_clients_by_name(self, name: str) -> List[str]:
        """Find clients by name (can return multiple matches)."""
        self.load_client_map()
        return self._name_index.get(name.lower(), [])

    def find_client_by_platform_id(self, platform: str, identifier: str) -> Optional[str]:
        """Find client by platform-specific identifier."""
        self.load_client_map()
        platform_data = self._platform_index.get(platform, {})
        return platform_data.get(identifier) or platform_data.get(identifier.lower())

    def get_client(self, caura_id: str) -> Optional[Dict[str, Any]]:
        """Get full client record by caura_id."""
        self.load_client_map()
        return self._client_cache.get(caura_id)

    def get_client_by_address(self, address: str) -> Optional[Dict[str, Any]]:
        """Get client by address (email or platform identifier)."""
        self.load_client_map()

        # Check email index first
        client_id = self.find_client_by_email(address)
        if client_id:
            return self.get_client(client_id)

        # Check platform identifiers
        for platform, identifiers in self._platform_index.items():
            if address in identifiers:
                return self.get_client(identifiers[address])

        return None
    
    def find_client_by_street_address(self, address_description: str, min_score: float = 0.80) -> Optional[Tuple[str, float, Dict[str, Any]]]:
        """
        Find client by street address from transaction description.
        
        Args:
            address_description: Address string from transaction description
            min_score: Minimum similarity score to consider a match (0.0-1.0)
            
        Returns:
            Tuple of (caura_id, match_score, match_details) or None if no match found
        """
        self.load_client_map()
        
        if not address_description or len(address_description.strip()) < 5:
            return None
            
        # Clean and normalize the input address
        normalized_input = self._normalize_address(address_description)
        
        best_match = None
        best_score = 0.0
        best_details = {}
        
        for caura_id, client in self._client_cache.items():
            location = client.get("location", {})
            if not location:
                continue
                
            # Build full address from client location components
            client_address_parts = []
            
            # Add unit number if present
            if location.get("address_1"):
                client_address_parts.append(str(location["address_1"]).strip())
                
            # Add street address (required)
            if location.get("address_2"):
                client_address_parts.append(str(location["address_2"]).strip())
                
            # Add suburb (required)
            if location.get("suburb"):
                client_address_parts.append(str(location["suburb"]).strip())
                
            # Add postcode if present
            if location.get("postcode"):
                client_address_parts.append(str(location["postcode"]).strip())
            
            if not client_address_parts:
                continue
                
            # Create full client address
            full_client_address = " ".join(client_address_parts)
            normalized_client_address = self._normalize_address(full_client_address)
            
            # Calculate similarity scores using different strategies
            scores = []
            match_strategies = []
            
            # Strategy 1: Full address similarity
            full_score = fuzz.partial_ratio(normalized_input, normalized_client_address) / 100.0
            scores.append(full_score)
            match_strategies.append("full_address")
            
            # Strategy 2: Street address only (address_2)
            if location.get("address_2"):
                street_only = self._normalize_address(location["address_2"])
                street_score = fuzz.partial_ratio(normalized_input, street_only) / 100.0
                scores.append(street_score)
                match_strategies.append("street_only")
            
            # Strategy 3: Suburb matching
            if location.get("suburb"):
                suburb_normalized = self._normalize_address(location["suburb"])
                if suburb_normalized in normalized_input:
                    suburb_score = 0.85  # High score for suburb containment
                    scores.append(suburb_score)
                    match_strategies.append("suburb_match")
            
            # Strategy 4: Postcode exact matching
            if location.get("postcode"):
                postcode = str(location["postcode"]).strip()
                if postcode in address_description:
                    postcode_score = 0.90  # Very high score for postcode match
                    scores.append(postcode_score)
                    match_strategies.append("postcode_match")
            
            # Get the best score for this client
            if scores:
                client_best_score = max(scores)
                best_strategy_idx = scores.index(client_best_score)
                best_strategy = match_strategies[best_strategy_idx]
                
                if client_best_score > best_score and client_best_score >= min_score:
                    best_score = client_best_score
                    best_match = caura_id
                    best_details = {
                        "matched_address": full_client_address,
                        "match_strategy": best_strategy,
                        "client_location": location,
                        "input_address": address_description,
                        "normalized_input": normalized_input,
                        "all_scores": dict(zip(match_strategies, scores))
                    }
        
        if best_match:
            return (best_match, best_score, best_details)
        
        return None
    
    def _normalize_address(self, address: str) -> str:
        """
        Normalize address for matching by removing common variations.
        """
        if not address:
            return ""
            
        # Convert to lowercase
        normalized = address.lower().strip()
        
        # Remove common punctuation
        normalized = re.sub(r'[,.\-_/]', ' ', normalized)
        
        # Normalize street type abbreviations
        street_types = {
            r'\bst\b': 'street',
            r'\brd\b': 'road', 
            r'\bave\b': 'avenue',
            r'\bavenue\b': 'avenue',
            r'\bdr\b': 'drive',
            r'\bpl\b': 'place',
            r'\bcr\b': 'crescent',
            r'\bcrescent\b': 'crescent',
            r'\bct\b': 'court',
            r'\bcourt\b': 'court',
            r'\bln\b': 'lane',
            r'\blane\b': 'lane',
            r'\bwy\b': 'way',
            r'\bway\b': 'way'
        }
        
        for abbrev, full in street_types.items():
            normalized = re.sub(abbrev, full, normalized)
        
        # Normalize unit/apartment indicators
        unit_indicators = {
            r'\bunit\b': 'u',
            r'\bapt\b': 'u', 
            r'\bapartment\b': 'u',
            r'\bflat\b': 'u'
        }
        
        for indicator, replacement in unit_indicators.items():
            normalized = re.sub(indicator, replacement, normalized)
            
        # Remove extra whitespace
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        
        return normalized
