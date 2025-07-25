from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import List

import pandas as pd
from tqdm import tqdm

from importers.base_importer import BaseTransactionImporter
from models.transaction import Transaction


class StripeImporter(BaseTransactionImporter):
    """Stripe CSV transaction importer."""

    def _get_platform_name(self) -> str:
        return "stripe"

    def validate_source(self, source_path: str) -> bool:
        """Validate Stripe CSV file."""
        path = Path(source_path)
        if not path.exists():
            return False

        if not path.suffix.lower() in ['.csv']:
            return False

        try:
            # Check if file has expected Stripe columns
            df = pd.read_csv(source_path, nrows=1)
            required_columns = ['id', 'Customer Email', 'Amount', 'Created date (UTC)', 'Description']

            for col in required_columns:
                if col not in df.columns:
                    return False

            return True
        except Exception:
            return False

    def extract_transactions(self, source_path: str) -> List[Transaction]:
        """Extract transactions from Stripe CSV."""
        df = pd.read_csv(source_path)
        transactions = []

        for _, row in tqdm(df.iterrows(), total=len(df), desc="Processing Stripe transactions", unit="txn"):
            try:
                # Parse date - Stripe format: "26/1/2025 23:18"
                date_str = str(row['Created date (UTC)']).strip()
                if '/' in date_str:
                    # Handle format like "26/1/2025 23:18"
                    date_part = date_str.split(' ')[0]
                    transaction_date = datetime.strptime(date_part, '%d/%m/%Y').date()
                else:
                    # Handle ISO format
                    transaction_date = datetime.fromisoformat(date_str.split('T')[0]).date()

                # Parse amount - Stripe already in dollars based on sample data
                amount = Decimal(str(row['Amount']))

                # Extract email
                email = str(row['Customer Email']).strip() if pd.notna(row['Customer Email']) else None

                # Create transaction
                transaction = Transaction(
                    transaction_id=str(row['id']).strip(),
                    date=transaction_date,
                    amount=amount,
                    description=str(row['Description']).strip(),
                    email=email,
                    platform="stripe",
                    platform_metadata={
                        "customer_id": str(row.get('Customer ID', '')).strip(),
                        "status": str(row.get('Status', '')).strip(),
                        "currency": str(row.get('Currency', 'aud')).strip(),
                        "invoice_id": str(row.get('Invoice ID', '')).strip(),
                    },
                    raw_data=row.to_dict()
                )

                transactions.append(transaction)

            except Exception as e:
                # Log error but continue processing
                print(f"Error processing Stripe row {row.get('id', 'unknown')}: {e}")
                continue

        return transactions
