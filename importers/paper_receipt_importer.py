import pandas as pd
from typing import List
from pathlib import Path
from datetime import datetime
from decimal import Decimal

from importers.base_importer import BaseTransactionImporter
from models.transaction import Transaction


class PaperReceiptImporter(BaseTransactionImporter):
    """Paper receipt CSV importer."""
    
    def _get_platform_name(self) -> str:
        return "paper_receipt"
    
    def validate_source(self, source_path: str) -> bool:
        """Validate paper receipt CSV file."""
        path = Path(source_path)
        if not path.exists():
            return False
        
        if not path.suffix.lower() in ['.csv']:
            return False
        
        try:
            # Check if file has expected paper receipt columns
            df = pd.read_csv(source_path, nrows=1)
            required_columns = ['Name', 'Suburb', 'DATE', 'AMOUNT', 'Service', 'Email']
            
            for col in required_columns:
                if col not in df.columns:
                    return False
            
            return True
        except Exception:
            return False
    
    def extract_transactions(self, source_path: str) -> List[Transaction]:
        """Extract transactions from paper receipt CSV."""
        df = pd.read_csv(source_path)
        transactions = []
        
        for idx, row in df.iterrows():
            try:
                # Parse date
                date_str = str(row['DATE']).strip()
                
                # Skip rows with empty or invalid dates
                if not date_str or date_str.lower() in ['nan', 'none', '']:
                    continue
                
                # Try multiple date formats
                try:
                    transaction_date = datetime.strptime(date_str, '%d/%m/%Y').date()
                except ValueError:
                    try:
                        transaction_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                    except ValueError:
                        try:
                            transaction_date = datetime.strptime(date_str, '%m/%d/%Y').date()
                        except ValueError:
                            print(f"Warning: Could not parse date '{date_str}' in row {idx+1}, skipping")
                            continue
                
                # Parse amount
                amount_str = str(row['AMOUNT']).replace('$', '').replace(',', '').strip()
                amount = Decimal(amount_str)
                
                # Get client details
                client_name = str(row['Name']).strip()
                client_suburb = str(row['Suburb']).strip() if pd.notna(row['Suburb']) else None
                client_email = str(row['Email']).strip() if pd.notna(row['Email']) else None
                service = str(row.get('Service', '')).strip()
                comment = str(row.get('Comment', '')).strip()
                
                # Create description
                description = f"Paper Receipt - {client_name}"
                if client_suburb:
                    description += f" ({client_suburb})"
                if service:
                    description += f" - {service}"
                if comment:
                    description += f" - {comment}"
                
                # Create transaction
                transaction = Transaction(
                    transaction_id=f"receipt_{idx+1}",
                    date=transaction_date,
                    amount=amount,
                    description=description,
                    email=client_email,
                    platform="paper_receipt",
                    platform_metadata={
                        "client_name": client_name,
                        "client_suburb": client_suburb,
                        "service": service,
                        "comment": comment,
                    },
                    raw_data=row.to_dict()
                )
                
                transactions.append(transaction)
                
            except Exception as e:
                print(f"Error processing paper receipt row {idx+1}: {e}")
                continue
        
        return transactions