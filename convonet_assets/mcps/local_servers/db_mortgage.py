"""
MCP Server for Mortgage Application Operations
Provides tools for managing mortgage applications, financial data, documents, and debts
"""

from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
from typing import List, Optional, Dict, Any
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from uuid import UUID, uuid4
from datetime import datetime, timezone
import os
import sys
import logging
import json
from decimal import Decimal
from pathlib import Path

# Ensure project root is on sys.path so convonet imports work
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize FastMCP server
mcp = FastMCP("Mortgage Application MCP Server")

# Database setup
DB_URI = os.getenv("DB_URI")
if not DB_URI:
    logger.error("❌ DB_URI environment variable not set")
    sys.exit(1)

engine = create_engine(DB_URI, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

from convonet.models.base import Base

# Lazy import mortgage models
MortgageApplication = None
MortgageDocument = None
MortgageDebt = None
ApplicationStatus = None
DocumentType = None
DocumentStatus = None

def _lazy_import_mortgage_models():
    """Lazy import mortgage models to avoid circular dependency"""
    global MortgageApplication, MortgageDocument, MortgageDebt
    global ApplicationStatus, DocumentType, DocumentStatus
    if MortgageApplication is None:
        try:
            from convonet.models.mortgage_models import (
                MortgageApplication as MA,
                MortgageDocument as MD,
                MortgageDebt as MDEBT,
                ApplicationStatus as AS,
                DocumentType as DT,
                DocumentStatus as DS
            )
            MortgageApplication, MortgageDocument, MortgageDebt = MA, MD, MDEBT
            ApplicationStatus, DocumentType, DocumentStatus = AS, DT, DS
        except ImportError as e:
            logger.error(f"❌ Failed to import mortgage models: {e}")
            raise


def _ensure_tables() -> None:
    try:
        _lazy_import_mortgage_models()
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        logger.error(f"❌ Failed to create mortgage tables: {e}")
        raise


_ensure_tables()


@mcp.tool()
def create_mortgage_application(user_id: str) -> Dict[str, Any]:
    """Create a new mortgage application for a user.

    IMPORTANT: Use authenticated_user_id from the agent state for the user_id parameter.
    Do NOT ask the user for their user_id - it's already available in the state.

    Args:
        user_id: UUID of the user creating the application (use authenticated_user_id from state)

    Returns:
        Dictionary with application_id and status
    """
    _lazy_import_mortgage_models()
    db = SessionLocal()
    try:
        # Use enum instance - EnumValueType will convert to value automatically
        application = MortgageApplication(
            user_id=UUID(user_id),
            status=ApplicationStatus.DRAFT  # EnumValueType will convert to "draft" value
        )
        db.add(application)
        db.commit()
        db.refresh(application)

        logger.info(f"✅ Created mortgage application {application.id} for user {user_id}")
        return {
            "success": True,
            "application_id": str(application.id),
            "status": application.status.value,
            "message": "Mortgage application created successfully"
        }
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error creating mortgage application: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def get_mortgage_application_status(user_id: str, application_id: Optional[str] = None) -> Dict[str, Any]:
    """Get the status and details of a mortgage application.

    Args:
        user_id: UUID of the user
        application_id: Optional UUID of specific application (if None, gets most recent)

    Returns:
        Dictionary with application status and details
    """
    _lazy_import_mortgage_models()
    db = SessionLocal()
    try:
        query = db.query(MortgageApplication).filter(
            MortgageApplication.user_id == UUID(user_id)
        )

        if application_id:
            query = query.filter(MortgageApplication.id == UUID(application_id))
        else:
            query = query.order_by(MortgageApplication.created_at.desc())

        application = query.first()

        if not application:
            return {
                "success": False,
                "error": "No mortgage application found"
            }

        # Get documents count
        documents_count = db.query(MortgageDocument).filter(
            MortgageDocument.application_id == application.id
        ).count()

        # Get debts
        debts = db.query(MortgageDebt).filter(
            MortgageDebt.application_id == application.id
        ).all()

        total_monthly_debt = sum([float(debt.monthly_payment) for debt in debts])

        return {
            "success": True,
            "application_id": str(application.id),
            "status": application.status.value,
            "credit_score": application.credit_score,
            "dti_ratio": float(application.dti_ratio) if application.dti_ratio else None,
            "monthly_income": float(application.monthly_income) if application.monthly_income else None,
            "monthly_debt": float(application.monthly_debt) if application.monthly_debt else None,
            "down_payment_amount": float(application.down_payment_amount) if application.down_payment_amount else None,
            "total_savings": float(application.total_savings) if application.total_savings else None,
            "completion_percentage": application.get_completion_percentage(),
            "documents_count": documents_count,
            "debts_count": len(debts),
            "total_monthly_debt": total_monthly_debt,
            "financial_review_completed": application.financial_review_completed,
            "document_collection_completed": application.document_collection_completed,
            "created_at": application.created_at.isoformat() if application.created_at else None
        }
    except Exception as e:
        logger.error(f"❌ Error getting mortgage application status: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def update_mortgage_financial_info(
    user_id: str,
    application_id: Optional[str] = None,
    credit_score: Optional[int] = None,
    monthly_income: Optional[float] = None,
    monthly_debt: Optional[float] = None,
    down_payment_amount: Optional[float] = None,
    closing_costs_estimate: Optional[float] = None,
    total_savings: Optional[float] = None,
    loan_amount: Optional[float] = None,
    property_value: Optional[float] = None
) -> Dict[str, Any]:
    """Update financial information for a mortgage application.

    Args:
        user_id: UUID of the user
        application_id: Optional UUID of application (if None, gets most recent)
        credit_score: Credit score (minimum 620 for conventional)
        monthly_income: Monthly gross income
        monthly_debt: Total monthly debt payments
        down_payment_amount: Amount saved for down payment
        closing_costs_estimate: Estimated closing costs
        total_savings: Total savings available
        loan_amount: Desired loan amount
        property_value: Estimated property value

    Returns:
        Dictionary with success status and updated information
    """
    _lazy_import_mortgage_models()
    db = SessionLocal()
    try:
        query = db.query(MortgageApplication).filter(
            MortgageApplication.user_id == UUID(user_id)
        )

        if application_id:
            query = query.filter(MortgageApplication.id == UUID(application_id))
        else:
            query = query.order_by(MortgageApplication.created_at.desc())

        application = query.first()

        if not application:
            return {"success": False, "error": "No mortgage application found"}

        # Update fields
        if credit_score is not None:
            application.credit_score = credit_score
        if monthly_income is not None:
            application.monthly_income = Decimal(str(monthly_income))
        if monthly_debt is not None:
            application.monthly_debt = Decimal(str(monthly_debt))
        if down_payment_amount is not None:
            application.down_payment_amount = Decimal(str(down_payment_amount))
        if closing_costs_estimate is not None:
            application.closing_costs_estimate = Decimal(str(closing_costs_estimate))
        if total_savings is not None:
            application.total_savings = Decimal(str(total_savings))
        if loan_amount is not None:
            application.loan_amount = Decimal(str(loan_amount))
        if property_value is not None:
            application.property_value = Decimal(str(property_value))

        # Calculate DTI ratio if income and debt are available
        if application.monthly_income and application.monthly_debt:
            dti = (float(application.monthly_debt) / float(application.monthly_income)) * 100
            application.dti_ratio = Decimal(str(round(dti, 2)))

        # Mark financial review as completed if key fields are present
        if application.credit_score and application.monthly_income and application.monthly_debt:
            application.financial_review_completed = True
            if application.status == ApplicationStatus.DRAFT:
                application.status = ApplicationStatus.FINANCIAL_REVIEW

        db.commit()
        db.refresh(application)

        logger.info(f"✅ Updated financial info for application {application.id}")
        return {
            "success": True,
            "application_id": str(application.id),
            "credit_score": application.credit_score,
            "dti_ratio": float(application.dti_ratio) if application.dti_ratio else None,
            "monthly_income": float(application.monthly_income) if application.monthly_income else None,
            "monthly_debt": float(application.monthly_debt) if application.monthly_debt else None,
            "financial_review_completed": application.financial_review_completed
        }
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error updating financial info: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def calculate_dti_ratio(user_id: str, application_id: Optional[str] = None) -> Dict[str, Any]:
    """Calculate debt-to-income (DTI) ratio for a mortgage application.

    Args:
        user_id: UUID of the user
        application_id: Optional UUID of application (if None, gets most recent)

    Returns:
        Dictionary with DTI ratio and interpretation
    """
    _lazy_import_mortgage_models()
    db = SessionLocal()
    try:
        query = db.query(MortgageApplication).filter(
            MortgageApplication.user_id == UUID(user_id)
        )

        if application_id:
            query = query.filter(MortgageApplication.id == UUID(application_id))
        else:
            query = query.order_by(MortgageApplication.created_at.desc())

        application = query.first()

        if not application:
            return {"success": False, "error": "No mortgage application found"}

        if not application.monthly_income or not application.monthly_debt:
            return {
                "success": False,
                "error": "Monthly income and debt are required to calculate DTI ratio"
            }

        dti = (float(application.monthly_debt) / float(application.monthly_income)) * 100
        application.dti_ratio = Decimal(str(round(dti, 2)))

        # Interpretation
        if dti < 36:
            interpretation = "Excellent - Very low DTI ratio"
        elif dti < 43:
            interpretation = "Good - Within preferred range"
        elif dti < 50:
            interpretation = "Acceptable - May require additional review"
        else:
            interpretation = "High - May face challenges in approval"

        db.commit()

        return {
            "success": True,
            "dti_ratio": round(dti, 2),
            "monthly_income": float(application.monthly_income),
            "monthly_debt": float(application.monthly_debt),
            "interpretation": interpretation
        }
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error calculating DTI ratio: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def add_mortgage_debt(
    user_id: str,
    debt_type: str,
    monthly_payment: float,
    application_id: Optional[str] = None,
    creditor_name: Optional[str] = None,
    outstanding_balance: Optional[float] = None,
    interest_rate: Optional[float] = None,
    description: Optional[str] = None
) -> Dict[str, Any]:
    """Add a debt to a mortgage application.

    Args:
        user_id: UUID of the user
        debt_type: Type of debt (credit_card, student_loan, auto_loan, mortgage, other)
        monthly_payment: Monthly payment amount
        application_id: Optional UUID of application (if None, gets most recent)
        creditor_name: Name of creditor
        outstanding_balance: Outstanding balance
        interest_rate: Annual interest rate
        description: Additional description

    Returns:
        Dictionary with success status and debt information
    """
    _lazy_import_mortgage_models()
    db = SessionLocal()
    try:
        query = db.query(MortgageApplication).filter(
            MortgageApplication.user_id == UUID(user_id)
        )

        if application_id:
            query = query.filter(MortgageApplication.id == UUID(application_id))
        else:
            query = query.order_by(MortgageApplication.created_at.desc())

        application = query.first()

        if not application:
            return {"success": False, "error": "No mortgage application found"}

        debt = MortgageDebt(
            application_id=application.id,
            debt_type=debt_type,
            monthly_payment=Decimal(str(monthly_payment)),
            creditor_name=creditor_name,
            outstanding_balance=Decimal(str(outstanding_balance)) if outstanding_balance else None,
            interest_rate=Decimal(str(interest_rate)) if interest_rate else None,
            description=description
        )

        db.add(debt)

        # Recalculate total monthly debt
        total_debt = db.query(MortgageDebt).filter(
            MortgageDebt.application_id == application.id
        ).all()
        total_monthly = sum([float(d.monthly_payment) for d in total_debt])
        application.monthly_debt = Decimal(str(total_monthly))

        # Recalculate DTI if income is available
        if application.monthly_income:
            dti = (total_monthly / float(application.monthly_income)) * 100
            application.dti_ratio = Decimal(str(round(dti, 2)))

        db.commit()
        db.refresh(debt)

        logger.info(f"✅ Added debt {debt.id} to application {application.id}")
        return {
            "success": True,
            "debt_id": str(debt.id),
            "debt_type": debt.debt_type,
            "monthly_payment": float(debt.monthly_payment),
            "total_monthly_debt": total_monthly,
            "dti_ratio": float(application.dti_ratio) if application.dti_ratio else None
        }
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error adding debt: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def get_mortgage_debts(user_id: str, application_id: Optional[str] = None) -> Dict[str, Any]:
    """Get all debts for a mortgage application.

    Args:
        user_id: UUID of the user
        application_id: Optional UUID of application (if None, gets most recent)

    Returns:
        Dictionary with list of debts
    """
    _lazy_import_mortgage_models()
    db = SessionLocal()
    try:
        query = db.query(MortgageApplication).filter(
            MortgageApplication.user_id == UUID(user_id)
        )

        if application_id:
            query = query.filter(MortgageApplication.id == UUID(application_id))
        else:
            query = query.order_by(MortgageApplication.created_at.desc())

        application = query.first()

        if not application:
            return {"success": False, "error": "No mortgage application found"}

        debts = db.query(MortgageDebt).filter(
            MortgageDebt.application_id == application.id
        ).all()

        return {
            "success": True,
            "debts": [
                {
                    "debt_id": str(debt.id),
                    "debt_type": debt.debt_type,
                    "creditor_name": debt.creditor_name,
                    "monthly_payment": float(debt.monthly_payment),
                    "outstanding_balance": float(debt.outstanding_balance) if debt.outstanding_balance else None,
                    "interest_rate": float(debt.interest_rate) if debt.interest_rate else None
                }
                for debt in debts
            ],
            "total_monthly_debt": sum([float(d.monthly_payment) for d in debts])
        }
    except Exception as e:
        logger.error(f"❌ Error getting debts: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def upload_mortgage_document(
    user_id: str,
    document_type: str,
    document_name: str,
    application_id: Optional[str] = None,
    file_path: Optional[str] = None,
    file_url: Optional[str] = None
) -> Dict[str, Any]:
    """Upload a document for a mortgage application.

    Args:
        user_id: UUID of the user
        document_type: Type of document (identification, income_paystub, income_w2, income_tax_return, etc.)
        document_name: Name of the document
        application_id: Optional UUID of application (if None, gets most recent)
        file_path: Path to the file (if stored locally)
        file_url: URL to the file (if stored externally)

    Returns:
        Dictionary with success status and document information
    """
    _lazy_import_mortgage_models()
    db = SessionLocal()
    try:
        query = db.query(MortgageApplication).filter(
            MortgageApplication.user_id == UUID(user_id)
        )

        if application_id:
            query = query.filter(MortgageApplication.id == UUID(application_id))
        else:
            query = query.order_by(MortgageApplication.created_at.desc())

        application = query.first()

        if not application:
            return {"success": False, "error": "No mortgage application found"}

        # Map document type string to enum
        try:
            doc_type_enum = DocumentType[document_type.upper()] if hasattr(DocumentType, document_type.upper()) else DocumentType(document_type)
        except:
            return {"success": False, "error": f"Invalid document type: {document_type}"}

        document = MortgageDocument(
            application_id=application.id,
            document_type=doc_type_enum,
            document_name=document_name,
            file_path=file_path,
            file_url=file_url,
            status=DocumentStatus.UPLOADED,
            uploaded_at=datetime.now(timezone.utc)
        )

        db.add(document)

        # Update application status if needed
        if application.status == ApplicationStatus.FINANCIAL_REVIEW:
            application.status = ApplicationStatus.DOCUMENT_COLLECTION

        # Check if all required documents are uploaded
        required_docs = _get_required_documents()
        uploaded_docs = db.query(MortgageDocument).filter(
            MortgageDocument.application_id == application.id,
            MortgageDocument.status.in_([DocumentStatus.UPLOADED, DocumentStatus.VERIFIED])
        ).all()
        uploaded_types = [doc.document_type for doc in uploaded_docs]

        # Simple check: if we have at least one document from each category
        has_id = any(dt.value.startswith('identification') for dt in uploaded_types)
        has_income = any(dt.value.startswith('income') for dt in uploaded_types)
        has_asset = any(dt.value.startswith('asset') for dt in uploaded_types)
        has_debt = any(dt.value.startswith('debt') for dt in uploaded_types)

        if has_id and has_income and has_asset:
            application.document_collection_completed = True

        db.commit()
        db.refresh(document)

        logger.info(f"✅ Uploaded document {document.id} for application {application.id}")
        return {
            "success": True,
            "document_id": str(document.id),
            "document_type": document.document_type.value,
            "document_name": document.document_name,
            "status": document.status.value,
            "document_collection_completed": application.document_collection_completed
        }
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error uploading document: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def get_mortgage_documents(user_id: str, application_id: Optional[str] = None) -> Dict[str, Any]:
    """Get all documents for a mortgage application.

    Args:
        user_id: UUID of the user
        application_id: Optional UUID of application (if None, gets most recent)

    Returns:
        Dictionary with list of documents
    """
    _lazy_import_mortgage_models()
    db = SessionLocal()
    try:
        query = db.query(MortgageApplication).filter(
            MortgageApplication.user_id == UUID(user_id)
        )

        if application_id:
            query = query.filter(MortgageApplication.id == UUID(application_id))
        else:
            query = query.order_by(MortgageApplication.created_at.desc())

        application = query.first()

        if not application:
            return {"success": False, "error": "No mortgage application found"}

        documents = db.query(MortgageDocument).filter(
            MortgageDocument.application_id == application.id
        ).all()

        return {
            "success": True,
            "documents": [
                {
                    "document_id": str(doc.id),
                    "document_type": doc.document_type.value,
                    "document_name": doc.document_name,
                    "status": doc.status.value,
                    "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None
                }
                for doc in documents
            ]
        }
    except Exception as e:
        logger.error(f"❌ Error getting documents: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def get_required_documents() -> Dict[str, Any]:
    """Get list of required documents for mortgage application.

    Returns:
        Dictionary with categorized list of required documents
    """
    return {
        "success": True,
        "required_documents": {
            "identification": [
                "Government-issued ID (driver's license or passport)",
                "Social Security number"
            ],
            "income_employment": [
                "Pay stubs from the last 30 days",
                "W-2 forms from the last two years",
                "Federal tax returns from the last two years"
            ],
            "income_self_employed": [
                "Profit & loss statements",
                "1099 forms"
            ],
            "assets": [
                "Bank statements from the last 2-3 months",
                "Investment account statements",
                "Retirement account statements (401k, IRA)"
            ],
            "debts": [
                "List of all outstanding debts (credit cards, student loans, auto loans)"
            ],
            "down_payment": [
                "Documentation showing source of down payment",
                "Gift letters if applicable"
            ]
        }
    }


@mcp.tool()
def get_missing_documents(user_id: str, application_id: Optional[str] = None) -> Dict[str, Any]:
    """Get list of missing documents for a mortgage application.

    Args:
        user_id: UUID of the user
        application_id: Optional UUID of application (if None, gets most recent)

    Returns:
        Dictionary with list of missing documents
    """
    _lazy_import_mortgage_models()
    db = SessionLocal()
    try:
        query = db.query(MortgageApplication).filter(
            MortgageApplication.user_id == UUID(user_id)
        )

        if application_id:
            query = query.filter(MortgageApplication.id == UUID(application_id))
        else:
            query = query.order_by(MortgageApplication.created_at.desc())

        application = query.first()

        if not application:
            return {"success": False, "error": "No mortgage application found"}

        uploaded_docs = db.query(MortgageDocument).filter(
            MortgageDocument.application_id == application.id,
            MortgageDocument.status.in_([DocumentStatus.UPLOADED, DocumentStatus.VERIFIED])
        ).all()
        uploaded_types = [doc.document_type.value for doc in uploaded_docs]

        required = _get_required_documents()["required_documents"]
        missing = []

        # Check identification
        if not any("identification" in dt for dt in uploaded_types):
            missing.extend(required["identification"])

        # Check income
        if not any("income" in dt for dt in uploaded_types):
            missing.extend(required["income_employment"])

        # Check assets
        if not any("asset" in dt for dt in uploaded_types):
            missing.extend(required["assets"])

        # Check down payment
        if not any("down_payment" in dt for dt in uploaded_types):
            missing.extend(required["down_payment"])

        return {
            "success": True,
            "missing_documents": missing,
            "uploaded_count": len(uploaded_docs),
            "required_count": len(missing) + len(uploaded_docs)
        }
    except Exception as e:
        logger.error(f"❌ Error getting missing documents: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def _get_required_documents():
    """Helper function to get required documents list"""
    return {
        "required_documents": {
            "identification": ["ID", "SSN"],
            "income": ["Pay stubs", "W-2", "Tax returns"],
            "assets": ["Bank statements", "Investment statements"],
            "down_payment": ["Down payment source"]
        }
    }


if __name__ == "__main__":
    mcp.run()
