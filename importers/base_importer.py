from abc import ABC, abstractmethod
from typing import List, Dict, Any
from models.transaction import Transaction
from models.reconciliation_report import ReconciliationReport
from core.transaction_matcher import TransactionMatcher
import time
import logging
import json
from datetime import datetime
from pathlib import Path


class BaseTransactionImporter(ABC):
    """Abstract base class for transaction importers."""
    
    def __init__(self, config: Dict[str, Any], matcher: TransactionMatcher):
        self.config = config
        self.matcher = matcher
        self.platform = self._get_platform_name()
        self.logger = self._setup_logging()
    
    def _setup_logging(self) -> logging.Logger:
        """Setup logging for this importer."""
        logger = logging.getLogger(f"{self.platform}_importer")
        logger.setLevel(logging.INFO)
        
        # Clear existing handlers to avoid duplicates
        logger.handlers.clear()
        
        # Create logs directory if it doesn't exist
        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)
        
        # Create file handler for this run
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = logs_dir / f"{self.platform}_{timestamp}.log"
        
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        
        logger.addHandler(file_handler)
        return logger
    
    @abstractmethod
    def _get_platform_name(self) -> str:
        """Return platform name for this importer."""
        pass
    
    @abstractmethod
    def validate_source(self, source_path: str) -> bool:
        """Validate input source."""
        pass
    
    @abstractmethod
    def extract_transactions(self, source_path: str) -> List[Transaction]:
        """Extract transactions from source."""
        pass
    
    def reconcile_transactions(self, source_path: str) -> ReconciliationReport:
        """Main reconciliation workflow with comprehensive logging."""
        start_time = time.time()
        run_timestamp = datetime.now()
        
        # Generate run ID
        run_id = f"{self.platform}_{run_timestamp.strftime('%Y%m%d_%H%M%S')}"
        
        self.logger.info(f"Starting reconciliation run: {run_id}")
        self.logger.info(f"Source: {source_path}")
        self.logger.info(f"Platform: {self.platform}")
        
        try:
            # Validate source
            self.logger.info("Validating source...")
            if not self.validate_source(source_path):
                error_msg = f"Invalid source: {source_path}"
                self.logger.error(error_msg)
                raise ValueError(error_msg)
            self.logger.info("Source validation successful")
            
            # Extract transactions
            self.logger.info("Extracting transactions...")
            extraction_start = time.time()
            transactions = self.extract_transactions(source_path)
            extraction_time = time.time() - extraction_start
            
            self.logger.info(f"Extracted {len(transactions)} transactions in {extraction_time:.2f}s")
            
            # Match transactions
            self.logger.info("Starting transaction matching...")
            matching_start = time.time()
            match_results = self.matcher.bulk_match_transactions(transactions)
            matching_time = time.time() - matching_start
            
            self.logger.info(f"Completed matching in {matching_time:.2f}s")
            
            # Calculate processing time
            processing_time = time.time() - start_time
            
            # Create report
            report = ReconciliationReport.from_match_results(
                run_id=run_id,
                platform=self.platform,
                source_identifier=source_path,
                match_results=match_results,
                processing_time=processing_time
            )
            
            # Log statistics
            self._log_statistics(report, extraction_time, matching_time)
            
            self.logger.info(f"Reconciliation completed successfully: {run_id}")
            
            return report
            
        except Exception as e:
            self.logger.error(f"Reconciliation failed: {str(e)}", exc_info=True)
            raise
    
    def _log_statistics(self, report: ReconciliationReport, extraction_time: float, matching_time: float):
        """Log detailed statistics about the reconciliation run."""
        stats = {
            "run_id": report.run_id,
            "platform": report.platform,
            "run_date": report.run_date.isoformat(),
            "source_file": report.source_identifier,
            "total_transactions": report.total_transactions,
            "matched_transactions": report.matched_transactions,
            "unmatched_transactions": report.unmatched_transactions,
            "requires_review": report.requires_review,
            "match_rate": report.matched_transactions / report.total_transactions if report.total_transactions > 0 else 0,
            "confidence_distribution": report.confidence_distribution,
            "match_method_breakdown": report.match_method_breakdown,
            "timing": {
                "total_processing_time": report.processing_time,
                "extraction_time": extraction_time,
                "matching_time": matching_time,
                "transactions_per_second": report.total_transactions / report.processing_time if report.processing_time > 0 else 0
            }
        }
        
        self.logger.info("STATISTICS: " + json.dumps(stats, indent=2))