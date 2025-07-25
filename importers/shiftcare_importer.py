import aiohttp
import asyncio
import base64
from typing import List, Dict, Any
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
    
    async def _async_extract_transactions(self) -> List[Transaction]:
        """Async extraction of invoice transactions."""
        transactions = []
        page = 1
        
        # First, get total count for progress bar
        print("Fetching invoice count...")
        total_invoices = await self._get_total_invoice_count()
        
        async with aiohttp.ClientSession() as session:
            with tqdm(total=total_invoices, desc="Processing invoices", unit="invoice") as pbar:
                while True:
                    invoices, has_more = await self._fetch_invoices_page(session, page)
                    
                    if not invoices:
                        break
                    
                    # Convert invoices to transactions
                    for invoice in invoices:
                        try:
                            transaction = await self._invoice_to_transaction(session, invoice)
                            if transaction:
                                transactions.append(transaction)
                            pbar.update(1)
                        except Exception as e:
                            print(f"Error processing invoice {invoice.get('id', 'unknown')}: {e}")
                            pbar.update(1)
                            continue
                    
                    if not has_more:
                        break
                    
                    page += 1
                    await asyncio.sleep(self.rate_limit_delay)
        
        return transactions
    
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
                    'payment_status': 'paid'
                }
                
                async with session.get(url, headers=headers, params=params, timeout=self.timeout) as response:
                    if response.status != 200:
                        return 0
                    
                    data = await response.json()
                    
                    if isinstance(data, dict):
                        meta = data.get('meta', {})
                        return meta.get('total', 0)
                    
                    return 0
        except Exception as e:
            print(f"Failed to get invoice count: {e}")
            return 0
    
    async def _fetch_invoices_page(self, session: aiohttp.ClientSession, page: int) -> tuple[List[Dict], bool]:
        """Fetch single page of invoices."""
        url = f"{self.base_url}/invoices"
        auth_string = base64.b64encode(f"{self.account_id}:{self.api_key}".encode()).decode()
        
        headers = {
            'Authorization': f'Basic {auth_string}',
            'Accept': '*/*'
        }
        params = {
            'page': page,
            'per_page': 20,
            'payment_status': 'paid'  # Focus on paid invoices for transaction matching
        }
        
        try:
            async with session.get(url, headers=headers, params=params, timeout=self.timeout) as response:
                if response.status != 200:
                    return [], False
                
                data = await response.json()
                
                if isinstance(data, dict):
                    invoices = data.get('invoices', [])
                    meta = data.get('meta', {})
                    has_more = page < meta.get('last_page', 1)
                else:
                    invoices = data if isinstance(data, list) else []
                    has_more = len(invoices) == 20  # Assume more if we got full page
                
                return invoices, has_more
                
        except Exception as e:
            print(f"API request failed for invoices page {page}: {e}")
            return [], False
    
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