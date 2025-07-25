#!/usr/bin/env python3
"""
Stripe Transaction Reconciliation Runner

Processes Stripe transactions using the file path configured in caura_config.yaml
under data.stripe_csv_file_path. No command line arguments required.
"""

import sys
import json
import yaml
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
load_dotenv(project_root / "config" / ".env")

from core.client_map_loader import ClientMapLoader
from core.transaction_matcher import TransactionMatcher
from importers.stripe_importer import StripeImporter


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
    # Load configuration first to get the file path
    config = load_config(project_root / 'config' / 'caura_config.yaml')
    
    # Get stripe CSV file path from config
    csv_file = config.get('data', {}).get('stripe_csv_file_path')
    if not csv_file:
        print("Error: stripe_csv_file_path not found in config")
        sys.exit(1)
    
    # Validate file exists
    if not Path(csv_file).exists():
        print(f"Error: Stripe CSV file not found: {csv_file}")
        sys.exit(1)
    
    print(f"Processing Stripe transactions from: {csv_file}")
    
    try:
        
        # Load client map
        client_map_path = config['paths']['client_map']
        client_map = ClientMapLoader(client_map_path)
        client_map.load_client_map()
        
        # Initialize matcher
        matcher = TransactionMatcher(config, client_map)
        
        # Run Stripe import
        importer = StripeImporter(config, matcher)
        report = importer.reconcile_transactions(csv_file)
        
        # Export results
        export_reconciliation_report(report, config['paths'])
        
        # Print summary
        print(f"\n🎯 Stripe Reconciliation Complete")
        print(f"   Total transactions: {report.total_transactions}")
        print(f"   Matched: {report.matched_transactions}")
        print(f"   Unmatched: {report.unmatched_transactions}")
        print(f"   Requires review: {report.requires_review}")
        print(f"   Processing time: {report.processing_time:.2f}s")
        
        # Print confidence breakdown
        print(f"\n📊 Confidence Distribution:")
        for level, count in report.confidence_distribution.items():
            print(f"   {level.capitalize()}: {count}")
        
        # Print method breakdown
        print(f"\n🔍 Match Methods:")
        for method, count in report.match_method_breakdown.items():
            print(f"   {method.replace('_', ' ').title()}: {count}")
        
    except Exception as e:
        print(f"❌ Reconciliation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()