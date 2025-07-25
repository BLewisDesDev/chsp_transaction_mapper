# CHSP Transaction Mapper

## Project Overview

A transaction reconciliation system that uses the CHSP Client Mapper registry to identify clients from bank statements and transaction records. Built with flexible matching strategies, comprehensive audit trails, and extensible platform architecture.

**Version 1.0** - Clean implementation with proven patterns from CHSP Client Mapper.

## Architecture Principles

### Learned from CHSP Client Mapper

- **Extensible Platform Architecture**: Each transaction source gets its own importer
- **External-Only Data Storage**: No local transaction storage, only logs and statistics
- **Bulk Processing**: Memory-efficient operations with atomic saves
- **Configuration-Driven**: YAML config for matching rules, thresholds, patterns
- **Statistics Tracking**: JSON statistics files for each import run
- **Clean Separation**: Models, importers, core logic, and scripts clearly separated

### Core Design Decisions

- **Client Map Dependency**: Loads existing client registry as read-only reference
- **Match Confidence Scoring**: All matches tracked with confidence levels (0.0-1.0)
- **Audit-First Approach**: Every match/non-match logged with reasoning
- **No Transaction Storage**: Process and export only, no local transaction database
- **Flexible Matching**: Multiple strategies (exact, fuzzy, pattern-based) per platform

## Project Structure

```
chsp_transaction_mapper/
├── config/
│   ├── caura_config.yaml          # Matching rules, thresholds, patterns
│   ├── .env.example              # Environment variables template
│   └── .env                      # Secrets (not committed)
├── core/
│   ├── client_map_loader.py      # Loads CHSP client registry (read-only)
│   ├── transaction_matcher.py    # Core matching engine with strategies
│   └── reconciliation_engine.py  # Main reconciliation orchestrator
├── models/
│   ├── transaction.py            # Transaction data model
│   ├── match_result.py           # Match result with confidence scoring
│   └── reconciliation_report.py  # Report aggregation model
├── matchers/
│   ├── base_matcher.py           # Abstract base for matching strategies
│   ├── exact_matcher.py          # Exact name/reference matching
│   ├── fuzzy_matcher.py          # Fuzzy string matching
│   └── pattern_matcher.py        # Regex pattern matching
├── importers/
│   ├── base_importer.py          # Base transaction importer
│   ├── bank_statement_importer.py # Generic bank statement processor
│   └── [platform]_importer.py   # Platform-specific importers
├── scripts/
│   ├── run_[platform]_reconciliation.py # Individual platform scripts
│   └── run_full_reconciliation.py       # Process all platforms
├── logs/                         # Rotation logs (debug only)
├── output/                       # External export location
│   ├── reconciliation_reports/   # Match results by run
│   ├── statistics/               # JSON stats by platform/date
│   └── audit_trails/             # Detailed match reasoning
└── requirements.txt
```

## Data Models

### Transaction Model

```python
class Transaction(BaseModel):
    transaction_id: str
    date: date
    amount: Decimal
    description: str
    reference: Optional[str] = None
    account_info: Dict[str, Any] = {}
    platform_metadata: Dict[str, Any] = {}
    raw_data: Dict[str, Any] = {}  # Original platform data
```

### Match Result Model

```python
class MatchResult(BaseModel):
    transaction_id: str
    client_caura_id: Optional[str] = None
    confidence_score: float  # 0.0 - 1.0
    match_method: str  # "exact", "fuzzy", "pattern", "manual"
    match_details: Dict[str, Any] = {}
    audit_trail: List[str] = []
    is_matched: bool
    requires_review: bool = False
```

### Reconciliation Report Model

```python
class ReconciliationReport(BaseModel):
    run_id: str
    platform: str
    run_date: datetime
    source_file: str
    total_transactions: int
    matched_transactions: int
    unmatched_transactions: int
    requires_review: int
    confidence_distribution: Dict[str, int]  # High/Medium/Low counts
    match_method_breakdown: Dict[str, int]
    processing_time: float
    match_results: List[MatchResult]
```

## Core Components

### 1. Client Map Loader (`core/client_map_loader.py`)

```python
class ClientMapLoader:
    """Read-only loader for CHSP Client Mapper registry."""

    def __init__(self, client_registry_path: str):
        self.registry_path = client_registry_path
        self._client_cache = None
        self._lookup_indices = None

    def load_client_map(self) -> Dict[str, Client]:
        """Load and cache client registry."""

    def build_lookup_indices(self) -> Dict[str, Any]:
        """Build fast lookup indices for matching."""
        # Name variations, phone numbers, ACNs, etc.

    def find_clients_by_name(self, name: str) -> List[Client]:
        """Find clients by name variations."""

    def find_client_by_acn(self, acn: str) -> Optional[Client]:
        """Find client by ACN (exact match)."""
```

### 2. Transaction Matcher (`core/transaction_matcher.py`)

```python
class TransactionMatcher:
    """Core matching engine with pluggable strategies."""

    def __init__(self, config: Dict[str, Any], client_map: ClientMapLoader):
        self.config = config
        self.client_map = client_map
        self.matchers = self._load_matchers()

    def match_transaction(self, transaction: Transaction) -> MatchResult:
        """Match single transaction using all strategies."""

    def bulk_match_transactions(self, transactions: List[Transaction]) -> List[MatchResult]:
        """Efficiently match multiple transactions."""
```

### 3. Matching Strategies (`matchers/`)

#### Exact Matcher

- ACN exact match
- Reference number exact match
- Phone number exact match
- Confidence: 1.0

#### Fuzzy Matcher

- Name similarity (Levenshtein distance)
- Address similarity
- Configurable thresholds
- Confidence: 0.6-0.95

#### Pattern Matcher

- Regex patterns for transaction descriptions
- Client name extraction patterns
- Reference format patterns
- Confidence: 0.4-0.8

## Configuration System

### Master Config (`config/caura_config.yaml`)

```yaml
matching:
  confidence_thresholds:
    high: 0.85 # Auto-accept
    medium: 0.60 # Requires review
    low: 0.40 # Flag for manual review

  fuzzy_matching:
    name_threshold: 0.85
    address_threshold: 0.80

  exact_matching:
    acn_weight: 1.0
    phone_weight: 0.95
    reference_weight: 0.90

  pattern_matching:
    enabled_patterns:
      - client_name_in_description
      - acn_in_reference
      - phone_in_memo

platforms:
  bank_statements:
    date_formats: ["%d/%m/%Y", "%Y-%m-%d"]
    amount_patterns: ["$", "AUD"]

  platform_specific:
    commbank:
      reference_column: "Reference"
      description_column: "Description"
    anz:
      reference_column: "Memo"
      description_column: "Transaction Details"

export:
  output_base_path: "/Users/byron/repos/DATABASE/chsp_transaction_mapper"
  reports_subdir: "reconciliation_reports"
  statistics_subdir: "statistics"
  audit_subdir: "audit_trails"
```

### Environment Variables (`.env`)

```env
# Client Registry Path
CLIENT_REGISTRY_PATH=/Users/byron/repos/DATABASE/chsp_client_mapper/chsp_client_map.json

# Output Location
OUTPUT_BASE_PATH=/Users/byron/repos/DATABASE/chsp_transaction_mapper

# API Keys (if needed)
BANK_API_KEY=your_api_key_here
```

## Import Pipeline Architecture

### Base Importer (`importers/base_importer.py`)

```python
class BaseTransactionImporter(ABC):
    """Abstract base for transaction importers."""

    def __init__(self, config: Dict[str, Any], matcher: TransactionMatcher):
        self.config = config
        self.matcher = matcher

    @abstractmethod
    def validate_source(self, source_path: str) -> bool:
        """Validate input file/data source."""

    @abstractmethod
    def extract_transactions(self, source_path: str) -> List[Transaction]:
        """Extract transactions from source."""

    def reconcile_transactions(self, source_path: str) -> ReconciliationReport:
        """Main reconciliation workflow."""
        # 1. Validate source
        # 2. Extract transactions
        # 3. Bulk match against client map
        # 4. Generate report with statistics
        # 5. Export results
```

### Platform-Specific Importers

Each platform gets its own importer inheriting from base:

- `bank_statement_importer.py` - Generic CSV/Excel bank statements
- `commbank_importer.py` - Commonwealth Bank specific formats
- `anz_importer.py` - ANZ specific formats
- `manual_transactions_importer.py` - Manual entry format

## Execution Scripts

### Individual Platform Script (`scripts/run_commbank_reconciliation.py`)

```python
#!/usr/bin/env python3
"""
CommBank Transaction Reconciliation Runner
"""

def main():
    config = load_config('config/caura_config.yaml')

    # Load client map
    client_map = ClientMapLoader(config['client_registry_path'])
    client_map.load_client_map()

    # Initialize matcher
    matcher = TransactionMatcher(config, client_map)

    # Run CommBank import
    importer = CommBankImporter(config, matcher)
    report = importer.reconcile_transactions(sys.argv[1])  # File path

    # Export results
    export_reconciliation_report(report, config['export'])

    print(f"Reconciliation complete: {report.matched_transactions}/{report.total_transactions} matched")

if __name__ == "__main__":
    main()
```

## Output Structure

### Reconciliation Report (`output/reconciliation_reports/`)

```json
{
	"run_id": "commbank_20250725_143022",
	"platform": "commbank",
	"run_date": "2025-07-25T14:30:22",
	"source_file": "/path/to/statement.csv",
	"total_transactions": 1250,
	"matched_transactions": 892,
	"unmatched_transactions": 358,
	"requires_review": 45,
	"confidence_distribution": {
		"high": 847, // >= 0.85
		"medium": 45, // 0.60-0.84
		"low": 0 // 0.40-0.59
	},
	"match_method_breakdown": {
		"exact": 750,
		"fuzzy": 97,
		"pattern": 45,
		"manual": 0
	},
	"processing_time": 12.34,
	"match_results": [
		{
			"transaction_id": "TXN001",
			"client_caura_id": "CL00001234",
			"confidence_score": 0.95,
			"match_method": "exact",
			"match_details": {
				"matched_field": "acn",
				"matched_value": "AC12345678"
			},
			"audit_trail": [
				"Extracted ACN 'AC12345678' from transaction reference",
				"Found exact ACN match in client registry",
				"Match confidence: 0.95 (exact ACN match)"
			],
			"is_matched": true,
			"requires_review": false
		}
	]
}
```

### Statistics File (`output/statistics/`)

```json
{
	"platform": "commbank",
	"run_date": "2025-07-25T14:30:22",
	"performance_metrics": {
		"transactions_per_second": 102.4,
		"total_processing_time": 12.34,
		"memory_usage_mb": 45.2
	},
	"matching_effectiveness": {
		"overall_match_rate": 0.714, // 892/1250
		"high_confidence_rate": 0.678, // 847/1250
		"review_required_rate": 0.036 // 45/1250
	},
	"platform_specific_metrics": {
		"unique_references_found": 234,
		"acn_extractions_successful": 456,
		"name_fuzzy_matches": 97
	}
}
```

## Development Phases

### Phase 1: Foundation (Week 1-2)

- [ ] Project structure setup
- [ ] Core models (Transaction, MatchResult, Report)
- [ ] Client map loader with caching
- [ ] Base importer abstract class
- [ ] Configuration system
- [ ] Basic exact matcher

### Phase 2: Matching Engine (Week 3-4)

- [ ] Transaction matcher orchestrator
- [ ] Fuzzy matching strategy
- [ ] Pattern matching strategy
- [ ] Confidence scoring algorithm
- [ ] Bulk processing optimizations

### Phase 3: Platform Importers (Week 5-6)

- [ ] Generic bank statement importer
- [ ] CommBank specific importer
- [ ] ANZ specific importer
- [ ] Execution scripts
- [ ] Error handling and validation

### Phase 4: Reporting & Export (Week 7-8)

- [ ] Reconciliation report generation
- [ ] Statistics calculation and export
- [ ] Audit trail logging
- [ ] Performance metrics tracking
- [ ] Output file management

## Success Metrics

- **Match Rate**: >70% automatic matches with high confidence
- **Processing Speed**: >100 transactions/second
- **False Positive Rate**: <2% incorrect matches
- **Review Queue**: <10% of transactions requiring manual review
- **Performance**: Handle 10,000+ transactions efficiently

## Key Differences from CHSP Client Mapper

1. **Read-Only Client Data**: Never modifies client registry
2. **Confidence-Based Matching**: Every match scored 0.0-1.0
3. **Audit-Heavy**: Extensive reasoning logs for compliance
4. **Review Workflow**: Built-in flagging for uncertain matches
5. **Multiple Matching Strategies**: Pluggable matcher architecture
6. **Transaction-Focused**: Purpose-built for financial reconciliation

This architecture leverages proven patterns from CHSP Client Mapper while adding transaction-specific capabilities for robust financial reconciliation.
