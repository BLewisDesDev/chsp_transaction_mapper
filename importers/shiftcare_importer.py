import aiohttp
import asyncio
import base64
import json
from typing import List, Dict, Any, Tuple
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import os
from tqdm import tqdm

from importers.base_importer import BaseTransactionImporter
from models.transaction import Transaction


class ShiftCareImporter(BaseTransactionImporter):
    """ShiftCare API invoice importer."""
    
    def __init__(self, config: Dict[str, Any], matcher, account_type: str = "DA"):
        self.account_type = account_type  # Set this before super().__init__
        super().__init__(config, matcher)
        self.base_url = "https://api.shiftcare.com/api/v3"
        self.timeout = 30
        self.rate_limit_delay = 2
        
        # Get API credentials from environment
        api_key_env = f"SHIFTCARE_{account_type}_API_KEY"
        account_id_env = f"SHIFTCARE_{account_type}_ACCOUNT_ID"
        
        self.api_key = os.getenv(api_key_env)
        self.account_id = os.getenv(account_id_env)
        
        if not self.api_key or not self.account_id:
            raise ValueError(f"Missing ShiftCare {account_type} credentials")
        
        # Progress tracking
        self.progress_file = Path(f"logs/shiftcare_{account_type.lower()}_progress.json")
        self.progress_file.parent.mkdir(exist_ok=True)
        
        # Data storage for detailed reporting
        self.invoices_data = []
        self.shifts_data = []
    
    def _get_platform_name(self) -> str:
        return f"shiftcare_{self.account_type.lower()}"
        
    
    def validate_source(self, source_path: str = None) -> bool:
        """Validate API connection."""
        try:
            return asyncio.run(self._test_api_connection())
        except Exception as e:
            print(f"API validation error: {e}")
            return False
    
    async def _test_api_connection(self) -> bool:
        """Test API connection."""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/invoices"
                auth_string = base64.b64encode(f"{self.account_id}:{self.api_key}".encode()).decode()
                headers = {
                    'Authorization': f'Basic {auth_string}',
                    'Accept': '*/*'
                }
                params = {'page': 1, 'per_page': 1}
                
                async with session.get(url, headers=headers, params=params, timeout=self.timeout) as response:
                    return response.status == 200
        except Exception:
            return False
    
    def extract_transactions(self, source_path: str = None) -> List[Transaction]:
        """Extract invoice transactions from ShiftCare API."""
        return asyncio.run(self._async_extract_transactions())
    
    def get_detailed_data(self) -> Tuple[List[Dict], List[Dict]]:
        """Get detailed invoices and shifts data for reporting."""
        return self.invoices_data, self.shifts_data
    
    def _load_progress(self) -> Dict:
        """Load progress from JSON file."""
        if self.progress_file.exists():
            try:
                with open(self.progress_file, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return {'last_completed_page': 0, 'completed_invoice_ids': []}
    
    def _save_progress(self, page: int, completed_invoice_ids: List[str]):
        """Save progress to JSON file."""
        progress = {
            'last_completed_page': page,
            'completed_invoice_ids': completed_invoice_ids,
            'last_updated': datetime.now().isoformat()
        }
        with open(self.progress_file, 'w') as f:
            json.dump(progress, f, indent=2)
    
    async def _async_extract_transactions(self) -> List[Transaction]:
        """Async extraction of ALL invoice transactions in one run."""
        transactions = []
        
        # Load progress for resume capability  
        progress = self._load_progress()
        start_page = max(1, progress['last_completed_page'] + 1) if progress['last_completed_page'] > 0 else 1
        completed_ids = set(progress['completed_invoice_ids'])
        
        print(f"Starting from page {start_page} (found {len(completed_ids)} previously completed invoices)")
        
        # First, get total count for progress bar (but don't rely on it)
        print("Fetching invoice count...")
        total_invoices = await self._get_total_invoice_count()
        print(f"Total invoices from API: {total_invoices}")
        
        # Initialize data storage (preserve existing data if resuming)
        if start_page == 1:
            self.invoices_data = []
            self.shifts_data = []
        
        page = start_page
        processed_count = len(completed_ids)
        
        # Use dynamic progress bar that updates as we find more invoices
        async with aiohttp.ClientSession() as session:
            pbar = tqdm(initial=processed_count, desc="Processing invoices", unit="invoice")
            
            try:
                # Process ALL pages until we've got everything - simple loop like the working client importer
                while True:
                    success = await self._process_single_invoice_page(session, page, completed_ids, transactions, pbar)
                    
                    if not success:
                        print(f"No more invoices found on page {page}, stopping")
                        break
                    
                    print(f"Completed page {page}")
                    page += 1
                    await asyncio.sleep(self.rate_limit_delay)
                    
            finally:
                pbar.close()
        
        print(f"✅ Processing complete!")
        print(f"   Total invoices processed: {len(self.invoices_data)}")
        print(f"   Total shifts extracted: {len(self.shifts_data)}")
        print(f"   Total transactions created: {len(transactions)}")
        
        # Clear progress file after successful completion
        if self.progress_file.exists():
            self.progress_file.unlink()
            print("   Progress file cleared")
        
        return transactions
    
    async def _process_single_invoice_page(self, session, page: int, completed_ids: set, transactions: list, pbar) -> bool:
        """Process a single page of invoices - returns False when no more data found."""
        try:
            invoices, meta = await self._fetch_invoices_page(session, page)
            
            if not invoices:
                return False  # No invoices = no more pages
            
            page_processed = 0
            # Convert invoices to transactions and extract detailed data
            for invoice in invoices:
                invoice_id = str(invoice.get('id', ''))
                
                # Skip if already processed
                if invoice_id in completed_ids:
                    continue
                
                try:
                    transaction = await self._invoice_to_transaction(session, invoice)
                    if transaction:
                        transactions.append(transaction)
                    
                    # Store detailed invoice data
                    self.invoices_data.append(invoice)
                    
                    # Extract shift data from invoice items
                    await self._extract_shift_data(session, invoice)
                    
                    completed_ids.add(invoice_id)
                    page_processed += 1
                    pbar.update(1)
                    
                except Exception as e:
                    print(f"Error processing invoice {invoice_id}: {e}")
                    continue
            
            # Save progress after each page
            self._save_progress(page, list(completed_ids))
            
            print(f"Page {page}: processed {page_processed} new invoices")
            return len(invoices) > 0  # Continue if we got invoices
            
        except Exception as e:
            print(f"Failed to process page {page}: {e}")
            return False
    
    async def _get_total_invoice_count(self) -> int:
        """Get total count of invoices for progress bar."""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/invoices"
                auth_string = base64.b64encode(f"{self.account_id}:{self.api_key}".encode()).decode()
                
                headers = {
                    'Authorization': f'Basic {auth_string}',
                    'Accept': '*/*'
                }
                params = {
                    'page': 1,
                    'per_page': 1,
                    'payment_status': 'paid',
                    'start_date': '2025-01-01',
                    'end_date': '2025-06-30'
                }
                
                async with session.get(url, headers=headers, params=params, timeout=self.timeout) as response:
                    if response.status != 200:
                        return 0
                    
                    data = await response.json()
                    
                    # Debug: print the response structure
                    print(f"API response keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
                    
                    if isinstance(data, dict):
                        # Try different possible locations for total count
                        meta = data.get('meta', {})
                        total = meta.get('total', 0)
                        
                        if total == 0:
                            # Alternative: try pagination info
                            total = meta.get('total_count', 0)
                            
                        if total == 0:
                            # Alternative: calculate from pagination
                            per_page = meta.get('per_page', 20)
                            last_page = meta.get('last_page', 1)
                            total = per_page * last_page
                            
                        print(f"Total count from API: {total}")
                        return total
                    
                    return 0
        except Exception as e:
            print(f"Failed to get invoice count: {e}")
            return 0
    
    async def _fetch_invoices_page(self, session: aiohttp.ClientSession, page: int) -> tuple[List[Dict], Dict]:
        """Fetch single page of invoices - simplified like the working client importer."""
        url = f"{self.base_url}/invoices"
        auth_string = base64.b64encode(f"{self.account_id}:{self.api_key}".encode()).decode()
        
        headers = {
            'Authorization': f'Basic {auth_string}',
            'Accept': '*/*'
        }
        params = {
            'page': page,
            'per_page': 20,
            'payment_status': 'paid',
            'start_date': '2025-01-01',
            'end_date': '2025-06-30'
        }
        
        try:
            async with session.get(url, headers=headers, params=params, timeout=self.timeout) as response:
                if response.status != 200:
                    print(f"API returned status {response.status} for page {page}")
                    return [], {}
                
                data = await response.json()
                
                if isinstance(data, dict):
                    invoices = data.get('invoices', [])
                    meta = data.get('meta', {})
                else:
                    invoices = data if isinstance(data, list) else []
                    meta = {}
                
                print(f"Fetched {len(invoices)} invoices from page {page}")
                return invoices, meta
                
        except Exception as e:
            print(f"API request failed for invoices page {page}: {e}")
            return [], {}
    
    async def _invoice_to_transaction(self, session: aiohttp.ClientSession, invoice: Dict) -> Transaction:
        """Convert ShiftCare invoice to Transaction object."""
        try:
            # Get client details for the invoice
            client_data = await self._fetch_client_for_invoice(session, invoice)
            
            # Parse invoice date
            invoice_date_str = invoice.get('invoice_date') or invoice.get('created_at')
            if invoice_date_str:
                invoice_date = datetime.fromisoformat(invoice_date_str.split('T')[0]).date()
            else:
                invoice_date = datetime.now().date()
            
            # Parse amount
            amount = Decimal(str(invoice.get('total_amount', 0)))
            
            # Get client identifier and email
            client_id = None
            client_email = None
            client_display_name = None
            
            if client_data:
                client_id = str(client_data.get('id', ''))
                client_email = client_data.get('email')
                client_display_name = client_data.get('display_name')
            
            # Create description
            description = f"ShiftCare Invoice #{invoice.get('invoice_number', invoice.get('id'))}"
            if client_display_name:
                description += f" - {client_display_name}"
            
            return Transaction(
                transaction_id=f"invoice_{invoice.get('id')}",
                date=invoice_date,
                amount=amount,
                description=description,
                email=client_email,
                client_identifier=client_id,
                platform=self.platform,
                platform_metadata={
                    "invoice_id": str(invoice.get('id', '')),
                    "invoice_number": str(invoice.get('invoice_number', '')),
                    "client_id": client_id,
                    "client_display_name": client_display_name,
                    "payment_status": invoice.get('payment_status'),
                    "due_date": invoice.get('due_date')
                },
                raw_data=invoice
            )
            
        except Exception as e:
            print(f"Error converting invoice to transaction: {e}")
            return None
    
    async def _fetch_client_for_invoice(self, session: aiohttp.ClientSession, invoice: Dict) -> Dict:
        """Fetch client details for an invoice."""
        client_id = invoice.get('client_id')
        if not client_id:
            return None
        
        url = f"{self.base_url}/clients"
        auth_string = base64.b64encode(f"{self.account_id}:{self.api_key}".encode()).decode()
        
        headers = {
            'Authorization': f'Basic {auth_string}',
            'Accept': '*/*'
        }
        params = {
            'filter_by_id': client_id,
            'per_page': 1
        }
        
        try:
            async with session.get(url, headers=headers, params=params, timeout=self.timeout) as response:
                if response.status != 200:
                    return None
                
                data = await response.json()
                
                if isinstance(data, dict):
                    clients = data.get('clients', [])
                    return clients[0] if clients else None
                elif isinstance(data, list) and data:
                    return data[0]
                
                return None
                
        except Exception as e:
            print(f"Failed to fetch client {client_id}: {e}")
            return None
    
    async def _extract_shift_data(self, session: aiohttp.ClientSession, invoice: Dict):
        """Extract individual shift data from invoice items."""
        invoice_items = invoice.get('invoice_items', [])
        
        for item in invoice_items:
            # Create shift record with client info
            shift_data = {
                'shift_id': item.get('shift_id', ''),
                'invoice_id': invoice.get('id', ''),
                'client_id': invoice.get('client_id', ''),
                'amount': item.get('amount', 0),
                'quantity': item.get('quantity', 0),
                'rate': item.get('rate', 0),
                'description': item.get('description', ''),
                'pricebook_name': item.get('pricebook_name', ''),
                'rate_name': item.get('rate_name', ''),
                'service_date': self._extract_service_date_from_item(item),
                'created_at': item.get('created_at', ''),
                'category': item.get('category', ''),
                'reference_no': item.get('reference_no', '')
            }
            
            self.shifts_data.append(shift_data)
    
    def _extract_service_date_from_item(self, item: Dict) -> str:
        """Extract service date from item description."""
        import re
        description = item.get('description', '')
        
        # Look for date pattern like "03/02/2025" in the description
        date_pattern = r'(\d{2}/\d{2}/\d{4})'
        match = re.search(date_pattern, description)
        
        if match:
            return match.group(1)
        
        return ''