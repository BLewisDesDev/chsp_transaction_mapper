import pandas as pd
from typing import List
from pathlib import Path
from datetime import datetime
from decimal import Decimal

from importers.base_importer import BaseTransactionImporter
from models.transaction import Transaction


class BankStatementImporter(BaseTransactionImporter):
    """Generic bank statement CSV importer."""
    
    def _get_platform_name(self) -> str:
        return "bank_statement"
    
    def validate_source(self, source_path: str) -> bool:
        """Validate bank statement CSV file."""
        path = Path(source_path)
        if not path.exists():
            return False
        
        if not path.suffix.lower() in ['.csv']:
            return False
        
        try:
            # Check if file has expected bank statement columns
            df = pd.read_csv(source_path, nrows=1)
            required_columns = ['Date', 'Amount', 'Transaction Details']
            
            for col in required_columns:
                if col not in df.columns:
                    return False
            
            return True
        except Exception:
            return False
    
    def extract_transactions(self, source_path: str) -> List[Transaction]:
        """Extract transactions from bank statement CSV."""
        df = pd.read_csv(source_path)
        transactions = []
        
        for idx, row in df.iterrows():
            try:
                # Parse date
                date_str = str(row['Date']).strip()
                transaction_date = datetime.strptime(date_str, '%d/%m/%Y').date()
                
                # Parse amount - handle negative values
                amount_str = str(row['Amount']).replace('$', '').replace(',', '').strip()
                if amount_str.startswith('(') and amount_str.endswith(')'):
                    # Handle negative amounts in parentheses
                    amount = -Decimal(amount_str[1:-1])
                else:
                    amount = Decimal(amount_str)
                
                # Get transaction details
                description = str(row['Transaction Details']).strip()
                
                # Create transaction
                transaction = Transaction(
                    transaction_id=f"bank_{idx+1}",
                    date=transaction_date,
                    amount=amount,
                    description=description,
                    platform="bank_statement",
                    platform_metadata={
                        "account_number": str(row.get('Account Number', '')).strip(),
                        "transaction_type": str(row.get('Transaction Type', '')).strip(),
                        "balance": str(row.get('Balance', '')).strip(),
                        "category": str(row.get('Category', '')).strip(),
                        "merchant_name": str(row.get('Merchant Name', '')).strip(),
                    },
                    raw_data=row.to_dict()
                )
                
                transactions.append(transaction)
                
            except Exception as e:
                print(f"Error processing bank statement row {idx+1}: {e}")
                continue
        
        return transactions