#!/usr/bin/env python3
"""
Full Transaction Reconciliation Runner
Process all available data sources
"""

import sys
import json
import yaml
import os
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
from importers.shiftcare_importer import ShiftCareImporter
from importers.bank_statement_importer import BankStatementImporter
from importers.paper_receipt_importer import PaperReceiptImporter


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
    
    return report_file


def print_report_summary(platform: str, report):
    """Print summary for a single platform report."""
    print(f"\n🎯 {platform.title()} Reconciliation:")
    print(f"   Total transactions: {report.total_transactions}")
    print(f"   Matched: {report.matched_transactions}")
    print(f"   Unmatched: {report.unmatched_transactions}")
    print(f"   Requires review: {report.requires_review}")
    print(f"   Processing time: {report.processing_time:.2f}s")


def main():
    """Process all available transaction sources."""
    try:
        # Load configuration
        config = load_config(project_root / 'config' / 'caura_config.yaml')
        
        # Load client map
        client_map_path = config['paths']['client_map']
        client_map = ClientMapLoader(client_map_path)
        client_map.load_client_map()
        
        # Initialize matcher
        matcher = TransactionMatcher(config, client_map)
        
        reports = []
        
        print("🚀 Starting Full Transaction Reconciliation")
        print("=" * 50)
        
        # 1. Process Stripe data
        stripe_file = config.get('data', {}).get('stripe_csv_file_path')
        if stripe_file and Path(stripe_file).exists():
            print("\n📊 Processing Stripe transactions...")
            importer = StripeImporter(config, matcher)
            report = importer.reconcile_transactions(stripe_file)
            report_file = export_reconciliation_report(report, config['paths'])
            reports.append(('Stripe', report, report_file))
            print_report_summary('Stripe', report)
        
        # 2. Process ShiftCare DA invoices
        if os.getenv('SHIFTCARE_DA_API_KEY'):
            print("\n📊 Processing ShiftCare DA invoices...")
            try:
                importer = ShiftCareImporter(config, matcher, 'DA')
                report = importer.reconcile_transactions()
                report_file = export_reconciliation_report(report, config['paths'])
                reports.append(('ShiftCare DA', report, report_file))
                print_report_summary('ShiftCare DA', report)
            except Exception as e:
                print(f"❌ ShiftCare DA failed: {e}")
        
        # 3. Process ShiftCare HM invoices
        if os.getenv('SHIFTCARE_HM_API_KEY'):
            print("\n📊 Processing ShiftCare HM invoices...")
            try:
                importer = ShiftCareImporter(config, matcher, 'HM')
                report = importer.reconcile_transactions()
                report_file = export_reconciliation_report(report, config['paths'])
                reports.append(('ShiftCare HM', report, report_file))
                print_report_summary('ShiftCare HM', report)
            except Exception as e:
                print(f"❌ ShiftCare HM failed: {e}")
        
        # 4. Process Bank Statements
        bank_file = config.get('data', {}).get('bank_transactions_file_path')
        if bank_file and Path(bank_file).exists():
            print("\n📊 Processing Bank Statement...")
            importer = BankStatementImporter(config, matcher)
            report = importer.reconcile_transactions(bank_file)
            report_file = export_reconciliation_report(report, config['paths'])
            reports.append(('Bank Statement', report, report_file))
            print_report_summary('Bank Statement', report)
        
        # 5. Process Paper Receipts
        receipt_file = config.get('data', {}).get('paper_reciepts_file_path')
        if receipt_file and Path(receipt_file).exists():
            print("\n📊 Processing Paper Receipts...")
            importer = PaperReceiptImporter(config, matcher)
            report = importer.reconcile_transactions(receipt_file)
            report_file = export_reconciliation_report(report, config['paths'])
            reports.append(('Paper Receipts', report, report_file))
            print_report_summary('Paper Receipts', report)
        
        # Print overall summary
        print("\n" + "=" * 50)
        print("📈 OVERALL RECONCILIATION SUMMARY")
        print("=" * 50)
        
        total_transactions = 0
        total_matched = 0
        total_unmatched = 0
        total_review = 0
        
        for platform, report, report_file in reports:
            total_transactions += report.total_transactions
            total_matched += report.matched_transactions
            total_unmatched += report.unmatched_transactions
            total_review += report.requires_review
            print(f"{platform:15} | {report.total_transactions:4d} | {report.matched_transactions:4d} | {report.unmatched_transactions:4d} | {report.requires_review:4d} | {report_file}")
        
        print("-" * 50)
        print(f"{'TOTAL':15} | {total_transactions:4d} | {total_matched:4d} | {total_unmatched:4d} | {total_review:4d} |")
        
        match_rate = (total_matched / total_transactions * 100) if total_transactions > 0 else 0
        print(f"\n🎯 Overall Match Rate: {match_rate:.1f}%")
        
        if total_review > 0:
            print(f"⚠️  {total_review} transactions require manual review")
        
    except KeyboardInterrupt:
        print("\n\n❌ Reconciliation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Reconciliation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()