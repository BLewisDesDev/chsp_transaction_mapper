#!/usr/bin/env python3
"""
Stripe Post-Review Reconciliation Runner

Processes an Excel file where manual PII extraction has been performed on unmatched transactions.
Applies additional matching strategies using extracted Name, Address, ACN, Phone, Email columns.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
load_dotenv(project_root / "config" / ".env")

from core.client_map_loader import ClientMapLoader
from core.transaction_matcher import TransactionMatcher
from models.transaction import Transaction
from models.match_result import MatchResult
from models.reconciliation_report import ReconciliationReport
from exporters.stripe_inter_report import StripeInterReport


class PostReviewMatcher:
    """Enhanced matcher for post-review manual PII extraction."""
    
    def __init__(self, config: dict, client_map: ClientMapLoader):
        self.config = config
        self.client_map = client_map
        self.thresholds = config.get("matching", {}).get("confidence_thresholds", {
            "high": 0.85,
            "medium": 0.60,
            "low": 0.40
        })
    
    def match_by_extracted_pii(self, transaction: Transaction, pii_data: dict):
        """
        Match transaction using manually extracted PII data.
        
        Args:
            transaction: Original transaction object
            pii_data: Dict with keys: Name, Address, ACN, Invoice, Phone, Email
        """
        
        # Strategy 1: Email exact match (highest confidence)
        if pii_data.get('Email'):
            client_id = self.client_map.find_client_by_email(pii_data['Email'])
            if client_id:
                return MatchResult(
                    transaction_id=transaction.transaction_id,
                    client_caura_id=client_id,
                    confidence_score=1.0,
                    match_method="extracted_email",
                    match_details={"matched_email": pii_data['Email']},
                    is_matched=True,
                    requires_review=False
                )
        
        # Strategy 2: ACN exact match 
        if pii_data.get('ACN'):
            client_id = self._find_client_by_acn(pii_data['ACN'])
            if client_id:
                return MatchResult(
                    transaction_id=transaction.transaction_id,
                    client_caura_id=client_id,
                    confidence_score=1.0,
                    match_method="extracted_acn",
                    match_details={"matched_acn": pii_data['ACN']},
                    is_matched=True,
                    requires_review=False
                )
        
        # Strategy 3: Phone exact match
        if pii_data.get('Phone'):
            client_id = self._find_client_by_phone(pii_data['Phone'])
            if client_id:
                return MatchResult(
                    transaction_id=transaction.transaction_id,
                    client_caura_id=client_id,
                    confidence_score=0.95,
                    match_method="extracted_phone",
                    match_details={"matched_phone": pii_data['Phone']},
                    is_matched=True,
                    requires_review=False
                )
        
        # Strategy 4: Address fuzzy match
        if pii_data.get('Address'):
            result = self._fuzzy_address_match(transaction, pii_data['Address'])
            if result:
                return result
        
        # Strategy 5: Name fuzzy match  
        if pii_data.get('Name'):
            result = self._fuzzy_name_match(transaction, pii_data['Name'])
            if result:
                return result
        
        # No match found
        return MatchResult(
            transaction_id=transaction.transaction_id,
            client_caura_id=None,
            confidence_score=0.0,
            match_method="no_match_post_review",
            match_details={},
            is_matched=False,
            requires_review=True
        )
    
    def _find_client_by_acn(self, acn: str):
        """Find client by ACN in platform identifiers."""
        self.client_map.load_client_map()
        
        for caura_id, client in self.client_map._client_cache.items():
            for platform_id in client.get("platform_identifiers", []):
                if platform_id.get("platform") == "aged_care":
                    if platform_id.get("identifiers", {}).get("acn") == acn:
                        return caura_id
        return None
    
    def _find_client_by_phone(self, phone: str):
        """Find client by phone number."""
        self.client_map.load_client_map()
        
        # Clean phone number for comparison
        clean_phone = ''.join(filter(str.isdigit, phone))
        
        for caura_id, client in self.client_map._client_cache.items():
            contact_numbers = client.get("personal_info", {}).get("contact_numbers", [])
            for contact in contact_numbers:
                clean_contact = ''.join(filter(str.isdigit, str(contact)))
                if clean_contact == clean_phone:
                    return caura_id
        return None
    
    def _fuzzy_address_match(self, transaction: Transaction, address: str):
        """Fuzzy match extracted address (comma-separated format)."""
        from fuzzywuzzy import fuzz
        
        if not address or len(address.strip()) < 5:
            return None
            
        # Use existing address matching with extracted address
        result = self.client_map.find_client_by_street_address(address, min_score=0.70)
        
        if result:
            client_id, match_score, match_details = result
            requires_review = match_score < self.thresholds["high"]
            
            return MatchResult(
                transaction_id=transaction.transaction_id,
                client_caura_id=client_id,
                confidence_score=match_score,
                match_method="extracted_address_fuzzy",
                match_details={**match_details, "extracted_address": address},
                is_matched=True,
                requires_review=requires_review
            )
        
        return None
    
    def _fuzzy_name_match(self, transaction: Transaction, name: str):
        """Fuzzy match extracted name."""
        from fuzzywuzzy import fuzz
        
        if not name or len(name.strip()) < 2:
            return None
            
        self.client_map.load_client_map()
        
        best_match = None
        best_score = 0.0
        best_client_id = None
        
        name_threshold = 0.75  # Lower threshold for extracted names
        
        for caura_id, client in self.client_map._client_cache.items():
            personal_info = client.get("personal_info", {})
            given_name = personal_info.get("given_name", "")
            family_name = personal_info.get("family_name", "")
            full_name = f"{given_name} {family_name}".strip()
            
            if not full_name:
                continue
            
            # Fuzzy match extracted name against client name
            score = fuzz.ratio(name.lower(), full_name.lower()) / 100.0
            
            if score > best_score and score >= name_threshold:
                best_score = score
                best_client_id = caura_id
                best_match = full_name
        
        if best_match and best_score >= name_threshold:
            requires_review = best_score < self.thresholds["high"]
            
            return MatchResult(
                transaction_id=transaction.transaction_id,
                client_caura_id=best_client_id,
                confidence_score=best_score,
                match_method="extracted_name_fuzzy",
                match_details={
                    "matched_name": best_match,
                    "extracted_name": name,
                    "fuzzy_score": best_score
                },
                is_matched=True,
                requires_review=requires_review
            )
        
        return None


def load_config(config_path: str) -> dict:
    """Load configuration from YAML file."""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def export_reconciliation_report(report, output_config: dict):
    """Export reconciliation report to JSON."""
    output_base = Path(output_config.get('output_base', 'output'))
    reports_dir = output_base / output_config.get('reports_subdir', 'reconciliation_reports')
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Save report
    report_file = reports_dir / f"{report.run_id}.json"
    with open(report_file, 'w') as f:
        json.dump(report.model_dump(mode='json'), f, indent=2, default=str)

    print(f"Report saved to: {report_file}")


def main():
    excel_file = "/Users/byron/repos/DATABASE/chsp_transaction_mapper/reconciliation_reports/stripe_20250728_123013_stripe_reconciliation.xlsx"
    
    # Validate file exists
    if not Path(excel_file).exists():
        print(f"Error: Excel file not found: {excel_file}")
        sys.exit(1)

    print(f"Processing post-review Excel file: {excel_file}")

    try:
        # Load configuration
        config = load_config(project_root / 'config' / 'caura_config.yaml')
        
        # Load client map
        client_map_path = config['paths']['client_map']
        client_map = ClientMapLoader(client_map_path)
        client_map.load_client_map()

        # Read Excel file
        print("Reading Excel file...")
        df = pd.read_excel(excel_file, sheet_name='Transactions')
        
        # Create Transaction objects from DataFrame
        transactions = []
        for _, row in df.iterrows():
            # Parse date with day first format
            date_str = str(row['Created date (UTC)'])
            try:
                transaction_date = pd.to_datetime(date_str, dayfirst=True).date()
            except:
                # Fallback parsing
                transaction_date = pd.to_datetime(date_str, format='%d/%m/%Y %H:%M').date()
            
            # Parse amount - remove commas
            amount_str = str(row['Amount']).replace(',', '')
            amount = float(amount_str)
            
            transaction = Transaction(
                transaction_id=str(row['id']),
                date=transaction_date,
                amount=amount,
                description=str(row['Description']),
                email=str(row['Customer Email']) if pd.notna(row['Customer Email']) else None,
                platform="stripe",
                platform_metadata={},
                raw_data=row.to_dict()
            )
            transactions.append(transaction)
        
        # Initialize post-review matcher
        matcher = PostReviewMatcher(config, client_map)
        
        # Process matches
        print("Running post-review matching...")
        match_results = []
        email_to_client_map = {}  # Track email -> client_id mappings found through PII
        
        # First pass: Find matches using PII data and build email mapping
        for _, row in df.iterrows():
            transaction_id = str(row['id'])
            transaction = next(tx for tx in transactions if tx.transaction_id == transaction_id)
            
            # Extract PII data
            pii_data = {
                'Name': str(row.get('Name', '')) if pd.notna(row.get('Name')) else None,
                'Address': str(row.get('Address', '')) if pd.notna(row.get('Address')) else None,
                'ACN': str(row.get('ACN', '')) if pd.notna(row.get('ACN')) else None,
                'Invoice': str(row.get('Invoice', '')) if pd.notna(row.get('Invoice')) else None,
                'Phone': str(row.get('Phone', '')) if pd.notna(row.get('Phone')) else None,
                'Email': str(row.get('Email', '')) if pd.notna(row.get('Email')) else None,
            }
            
            # Skip if already matched in original run
            if row.get('Matched') == 'Matched':
                match_result = MatchResult(
                    transaction_id=transaction_id,
                    client_caura_id="PREVIOUSLY_MATCHED",
                    confidence_score=1.0,
                    match_method="previously_matched",
                    match_details={},
                    is_matched=True,
                    requires_review=False
                )
            else:
                # Apply post-review matching
                match_result = matcher.match_by_extracted_pii(transaction, pii_data)
                
                # If we found a match and have an email, map it for other transactions
                if (match_result.is_matched and 
                    match_result.client_caura_id != "PREVIOUSLY_MATCHED" and
                    transaction.email):
                    email_to_client_map[transaction.email] = {
                        'client_id': match_result.client_caura_id,
                        'method': match_result.match_method,
                        'details': match_result.match_details
                    }
            
            match_results.append(match_result)
        
        # Second pass: Apply email-based matches to other transactions with same email
        print(f"Found {len(email_to_client_map)} email mappings, applying to other transactions...")
        
        for i, (_, row) in enumerate(df.iterrows()):
            transaction_id = str(row['id'])
            transaction = next(tx for tx in transactions if tx.transaction_id == transaction_id)
            current_match = match_results[i]
            
            # Skip if already matched or if no email
            if current_match.is_matched or not transaction.email:
                continue
                
            # Check if this email was mapped to a client
            if transaction.email in email_to_client_map:
                mapping = email_to_client_map[transaction.email]
                
                # Create new match result based on email mapping
                match_results[i] = MatchResult(
                    transaction_id=transaction_id,
                    client_caura_id=mapping['client_id'],
                    confidence_score=0.90,  # High confidence for email propagation
                    match_method=f"email_propagated_from_{mapping['method']}",
                    match_details={
                        'propagated_from_email': transaction.email,
                        'original_match_method': mapping['method'],
                        'original_details': mapping['details']
                    },
                    is_matched=True,
                    requires_review=False
                )
        
        # Create report
        run_timestamp = datetime.now()
        run_id = f"stripe_post_review_{run_timestamp.strftime('%Y%m%d_%H%M%S')}"
        
        report = ReconciliationReport.from_match_results(
            run_id=run_id,
            platform="stripe_post_review",
            source_identifier=excel_file,
            match_results=match_results,
            processing_time=0.0  # Not tracking time for post-review
        )

        # Export results
        export_reconciliation_report(report, config['paths'])
        
        # Export updated Excel report
        print("Creating updated Excel report...")
        excel_exporter = StripeInterReport(client_map)
        output_dir = Path(config['paths']['output_base']) / config['paths']['reports_subdir']
        excel_output = output_dir / f"{report.run_id}_stripe_post_review.xlsx"
        
        excel_path = excel_exporter.export_excel_report(
            transactions_df=df,
            transactions=transactions,
            report=report,
            output_path=str(excel_output)
        )
        
        print(f"Updated Excel report saved to: {excel_path}")

        # Print summary
        print(f"\n🎯 Post-Review Reconciliation Complete")
        print(f"   Total transactions: {report.total_transactions}")
        print(f"   Matched: {report.matched_transactions}")
        print(f"   Unmatched: {report.unmatched_transactions}")
        print(f"   Requires review: {report.requires_review}")

        # Print confidence breakdown
        print(f"\n📊 Confidence Distribution:")
        for level, count in report.confidence_distribution.items():
            print(f"   {level.capitalize()}: {count}")

        # Print method breakdown
        print(f"\n🔍 Match Methods:")
        for method, count in report.match_method_breakdown.items():
            print(f"   {method.replace('_', ' ').title()}: {count}")

    except Exception as e:
        print(f"❌ Post-review reconciliation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()