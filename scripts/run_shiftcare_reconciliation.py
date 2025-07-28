#!/usr/bin/env python3
"""
ShiftCare Invoice Reconciliation Runner
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
from importers.shiftcare_importer import ShiftCareImporter
from exporters.shiftcare_report import ShiftCareReport


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
    if len(sys.argv) != 2:
        print("Usage: python run_shiftcare_reconciliation.py <account_type>")
        print("Account types: DA (domestic assistance) or HM (home maintenance)")
        sys.exit(1)
    
    account_type = sys.argv[1].upper()
    
    if account_type not in ['DA', 'HM']:
        print("Error: Account type must be 'DA' or 'HM'")
        sys.exit(1)
    
    try:
        # Load configuration
        config = load_config(project_root / 'config' / 'caura_config.yaml')
        
        # Load client map
        client_map_path = config['paths']['client_map']
        client_map = ClientMapLoader(client_map_path)
        client_map.load_client_map()
        
        # Initialize matcher
        matcher = TransactionMatcher(config, client_map)
        
        # Run ShiftCare import
        importer = ShiftCareImporter(config, matcher, account_type)
        
        # Run reconciliation (this calls extract_transactions internally)
        report = importer.reconcile_transactions("shiftcare_api")
        
        # Get detailed data after reconciliation
        invoices_data, shifts_data = importer.get_detailed_data()
        
        # Export results
        export_reconciliation_report(report, config['paths'])
        
        # Export detailed Excel report
        print("Creating detailed Excel report...")
        excel_exporter = ShiftCareReport(client_map)
        output_dir = Path(config['paths']['output_base']) / config['paths']['reports_subdir']
        excel_file = output_dir / f"{report.run_id}_shiftcare_{account_type.lower()}_detailed.xlsx"
        
        excel_path = excel_exporter.export_excel_report(
            invoices_data=invoices_data,
            shifts_data=shifts_data,
            report=report,
            output_path=str(excel_file)
        )
        
        print(f"Detailed Excel report saved to: {excel_path}")
        
        # Print summary
        print(f"\n🎯 ShiftCare {account_type} Reconciliation Complete")
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
        
        # Print detailed data summary
        print(f"\n📋 Detailed Data Summary:")
        print(f"   Total invoices processed: {len(invoices_data)}")
        print(f"   Total shifts extracted: {len(shifts_data)}")
        
        # Calculate unique clients
        unique_clients = set()
        for invoice in invoices_data:
            if invoice.get('client_id'):
                unique_clients.add(invoice['client_id'])
        print(f"   Unique clients: {len(unique_clients)}")
        
        # Calculate date range of services
        if shifts_data:
            service_dates = [shift.get('service_date') for shift in shifts_data if shift.get('service_date')]
            if service_dates:
                service_dates.sort()
                # Format dates to dd/mm/yy format
                def format_date(date_str):
                    if '/' in date_str and len(date_str) == 10:  # dd/mm/yyyy format
                        parts = date_str.split('/')
                        return f"{parts[0]}/{parts[1]}/{parts[2][-2:]}"  # Convert yyyy to yy
                    return date_str
                
                start_date = format_date(service_dates[0])
                end_date = format_date(service_dates[-1])
                print(f"   Service date range: {start_date} - {end_date}")
        
    except Exception as e:
        print(f"❌ Reconciliation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()