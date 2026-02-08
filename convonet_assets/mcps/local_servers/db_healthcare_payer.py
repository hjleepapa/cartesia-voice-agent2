"""
MCP Server for Healthcare Payer Operations
Provides tools for managing claims, eligibility, benefits, prior authorizations, and provider network
"""

from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
from typing import List, Optional, Dict, Any
from sqlalchemy import create_engine, text, func, and_, or_
from sqlalchemy.orm import Session, sessionmaker
from uuid import UUID, uuid4
from datetime import datetime, timezone, timedelta
import os
import sys
import logging
import json
from decimal import Decimal
import random
import string
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
mcp = FastMCP("Healthcare Payer MCP Server")

# Database setup
DB_URI = os.getenv("DB_URI")
if not DB_URI:
    logger.error("❌ DB_URI environment variable not set")
    sys.exit(1)

engine = create_engine(DB_URI, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

from convonet.models.base import Base

# Lazy import healthcare models
HealthcareMember = None
HealthcarePlan = None
PlanBenefit = None
HealthcareClaim = None
ClaimLineItem = None
PriorAuthorization = None
MemberAccumulation = None
HealthcareProvider = None
CareProgram = None
MemberCareProgram = None
ClaimStatus = None
DenialReason = None
PriorAuthStatus = None
EligibilityStatus = None
ServiceCategory = None
NetworkTier = None


def _lazy_import_healthcare_models():
    """Lazy import healthcare models to avoid circular dependency"""
    global HealthcareMember, HealthcarePlan, PlanBenefit, HealthcareClaim
    global ClaimLineItem, PriorAuthorization, MemberAccumulation
    global HealthcareProvider, CareProgram, MemberCareProgram
    global ClaimStatus, DenialReason, PriorAuthStatus, EligibilityStatus
    global ServiceCategory, NetworkTier
    
    if HealthcareMember is None:
        try:
            from convonet.models.healthcare_payer_models import (
                HealthcareMember as HM,
                HealthcarePlan as HP,
                PlanBenefit as PB,
                HealthcareClaim as HC,
                ClaimLineItem as CLI,
                PriorAuthorization as PA,
                MemberAccumulation as MA,
                HealthcareProvider as HPR,
                CareProgram as CP,
                MemberCareProgram as MCP,
                ClaimStatus as CS,
                DenialReason as DR,
                PriorAuthStatus as PAS,
                EligibilityStatus as ES,
                ServiceCategory as SC,
                NetworkTier as NT
            )
            HealthcareMember = HM
            HealthcarePlan = HP
            PlanBenefit = PB
            HealthcareClaim = HC
            ClaimLineItem = CLI
            PriorAuthorization = PA
            MemberAccumulation = MA
            HealthcareProvider = HPR
            CareProgram = CP
            MemberCareProgram = MCP
            ClaimStatus = CS
            DenialReason = DR
            PriorAuthStatus = PAS
            EligibilityStatus = ES
            ServiceCategory = SC
            NetworkTier = NT
        except ImportError as e:
            logger.error(f"❌ Failed to import healthcare models: {e}")
            raise


def _ensure_tables() -> None:
    try:
        _lazy_import_healthcare_models()
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        logger.error(f"❌ Failed to create healthcare tables: {e}")
        raise


_ensure_tables()


def _generate_claim_number() -> str:
    """Generate a unique claim number"""
    prefix = "CLM"
    timestamp = datetime.now().strftime("%Y%m%d")
    random_part = ''.join(random.choices(string.digits, k=6))
    return f"{prefix}{timestamp}{random_part}"


def _generate_auth_number() -> str:
    """Generate a unique authorization number"""
    prefix = "AUTH"
    timestamp = datetime.now().strftime("%Y%m%d")
    random_part = ''.join(random.choices(string.digits, k=5))
    return f"{prefix}{timestamp}{random_part}"


def _get_member_by_user_id(db: Session, user_id: str):
    """Get healthcare member by user_id"""
    _lazy_import_healthcare_models()
    return db.query(HealthcareMember).filter(
        HealthcareMember.user_id == UUID(user_id)
    ).first()


# ============================================================================
# ELIGIBILITY TOOLS
# ============================================================================

@mcp.tool()
def check_eligibility(member_id: str) -> Dict[str, Any]:
    """Check member eligibility status and coverage details.
    
    Args:
        member_id: UUID of the member (use authenticated_user_id from state)
        
    Returns:
        Dictionary with eligibility status and coverage details
    """
    _lazy_import_healthcare_models()
    db = SessionLocal()
    try:
        member = _get_member_by_user_id(db, member_id)
        
        if not member:
            return {
                "success": False,
                "error": "Member not found. Please verify your information."
            }
        
        plan = member.plan
        is_active = member.eligibility_status == EligibilityStatus.ACTIVE
        
        return {
            "success": True,
            "eligibility_status": member.eligibility_status.value,
            "is_active": is_active,
            "member_number": member.member_number,
            "group_number": member.group_number,
            "plan_name": plan.plan_name if plan else None,
            "plan_type": plan.plan_type if plan else None,
            "coverage_start_date": member.coverage_start_date.isoformat() if member.coverage_start_date else None,
            "coverage_end_date": member.coverage_end_date.isoformat() if member.coverage_end_date else None,
            "relationship_to_subscriber": member.relationship_to_subscriber,
            "message": "Your coverage is active." if is_active else f"Your coverage status is {member.eligibility_status.value}."
        }
    except Exception as e:
        logger.error(f"❌ Error checking eligibility: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def get_coverage_dates(member_id: str) -> Dict[str, Any]:
    """Get member's coverage effective dates.
    
    Args:
        member_id: UUID of the member
        
    Returns:
        Dictionary with coverage dates
    """
    _lazy_import_healthcare_models()
    db = SessionLocal()
    try:
        member = _get_member_by_user_id(db, member_id)
        
        if not member:
            return {"success": False, "error": "Member not found"}
        
        today = datetime.now(timezone.utc)
        days_remaining = None
        if member.coverage_end_date:
            days_remaining = (member.coverage_end_date - today).days
        
        return {
            "success": True,
            "coverage_start_date": member.coverage_start_date.isoformat() if member.coverage_start_date else None,
            "coverage_end_date": member.coverage_end_date.isoformat() if member.coverage_end_date else "No end date (continuous coverage)",
            "days_remaining": days_remaining if days_remaining and days_remaining > 0 else None,
            "is_coverage_active": member.eligibility_status == EligibilityStatus.ACTIVE
        }
    except Exception as e:
        logger.error(f"❌ Error getting coverage dates: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


# ============================================================================
# CLAIMS TOOLS
# ============================================================================

@mcp.tool()
def search_claims(
    member_id: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 10
) -> Dict[str, Any]:
    """Search member's claims with optional filters.
    
    Args:
        member_id: UUID of the member
        date_from: Start date for search (ISO format)
        date_to: End date for search (ISO format)
        status: Filter by claim status (submitted, processing, approved, denied, paid)
        limit: Maximum number of claims to return
        
    Returns:
        Dictionary with list of matching claims
    """
    _lazy_import_healthcare_models()
    db = SessionLocal()
    try:
        logger.info(f"🔍 search_claims called with member_id={member_id}")
        
        member = _get_member_by_user_id(db, member_id)
        
        if not member:
            logger.warning(f"⚠️ Member not found for user_id={member_id}")
            return {"success": False, "error": "Member not found"}
        
        logger.info(f"✅ Found member: id={member.id}, member_number={member.member_number}")
        
        # Debug: Check total claims for this member
        total_claims = db.query(HealthcareClaim).filter(
            HealthcareClaim.member_id == member.id
        ).count()
        logger.info(f"📊 Total claims for member {member.id}: {total_claims}")
        
        query = db.query(HealthcareClaim).filter(
            HealthcareClaim.member_id == member.id
        )
        
        # Apply date filters
        if date_from:
            try:
                from_date = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
                query = query.filter(HealthcareClaim.service_date >= from_date)
            except:
                pass
        
        if date_to:
            try:
                to_date = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
                query = query.filter(HealthcareClaim.service_date <= to_date)
            except:
                pass
        
        # Apply status filter
        if status:
            try:
                status_enum = ClaimStatus(status.lower())
                query = query.filter(HealthcareClaim.status == status_enum)
            except:
                pass
        
        # Order by most recent first
        query = query.order_by(HealthcareClaim.service_date.desc())
        claims = query.limit(limit).all()
        
        if not claims:
            # Debug: Check if there are any claims at all in the database
            all_claims_count = db.query(HealthcareClaim).count()
            logger.info(f"📊 Total claims in database: {all_claims_count}")
            
            # Check claims with different member_ids
            if all_claims_count > 0:
                sample_claim = db.query(HealthcareClaim).first()
                logger.info(f"📋 Sample claim member_id: {sample_claim.member_id}")
            
            return {
                "success": True,
                "claims": [],
                "message": "No claims found matching your criteria."
            }
        
        return {
            "success": True,
            "claims_count": len(claims),
            "claims": [
                {
                    "claim_number": claim.claim_number,
                    "claim_id": str(claim.id),
                    "service_date": claim.service_date.strftime("%Y-%m-%d") if claim.service_date else None,
                    "provider_name": claim.provider_name,
                    "billed_amount": float(claim.billed_amount) if claim.billed_amount else 0,
                    "paid_amount": float(claim.paid_amount) if claim.paid_amount else 0,
                    "member_responsibility": float(claim.member_responsibility) if claim.member_responsibility else 0,
                    "status": claim.status.value,
                    "denial_reason": claim.denial_reason.value if claim.denial_reason else None
                }
                for claim in claims
            ]
        }
    except Exception as e:
        logger.error(f"❌ Error searching claims: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def get_claim_status(member_id: str, claim_id: str) -> Dict[str, Any]:
    """Get detailed status of a specific claim.
    
    Args:
        member_id: UUID of the member
        claim_id: Claim number or UUID
        
    Returns:
        Dictionary with claim status details
    """
    _lazy_import_healthcare_models()
    db = SessionLocal()
    try:
        member = _get_member_by_user_id(db, member_id)
        
        if not member:
            return {"success": False, "error": "Member not found"}
        
        # Search by claim number or ID
        claim = db.query(HealthcareClaim).filter(
            HealthcareClaim.member_id == member.id,
            or_(
                HealthcareClaim.claim_number == claim_id,
                HealthcareClaim.id == UUID(claim_id) if len(claim_id) == 36 else False
            )
        ).first()
        
        if not claim:
            return {
                "success": False,
                "error": f"Claim {claim_id} not found. Please verify the claim number."
            }
        
        # Build status explanation
        status_explanations = {
            ClaimStatus.SUBMITTED: "We received your claim and it's in queue for processing.",
            ClaimStatus.PROCESSING: "Your claim is currently being reviewed by our team.",
            ClaimStatus.PENDING_INFO: "We need additional information to process this claim.",
            ClaimStatus.APPROVED: "Your claim has been approved and payment is being processed.",
            ClaimStatus.PARTIALLY_APPROVED: "Part of your claim was approved.",
            ClaimStatus.DENIED: "This claim was not approved.",
            ClaimStatus.PAID: "This claim has been paid.",
            ClaimStatus.APPEALED: "Your appeal is being reviewed.",
            ClaimStatus.APPEAL_APPROVED: "Your appeal was approved.",
            ClaimStatus.APPEAL_DENIED: "Your appeal was not approved."
        }
        
        return {
            "success": True,
            "claim_number": claim.claim_number,
            "status": claim.status.value,
            "status_explanation": status_explanations.get(claim.status, ""),
            "service_date": claim.service_date.strftime("%Y-%m-%d") if claim.service_date else None,
            "provider_name": claim.provider_name,
            "billed_amount": float(claim.billed_amount) if claim.billed_amount else 0,
            "allowed_amount": float(claim.allowed_amount) if claim.allowed_amount else None,
            "paid_amount": float(claim.paid_amount) if claim.paid_amount else 0,
            "member_responsibility": float(claim.member_responsibility) if claim.member_responsibility else 0,
            "deductible_applied": float(claim.deductible_applied) if claim.deductible_applied else 0,
            "copay_applied": float(claim.copay_applied) if claim.copay_applied else 0,
            "coinsurance_applied": float(claim.coinsurance_applied) if claim.coinsurance_applied else 0,
            "denial_reason": claim.denial_reason.value if claim.denial_reason else None,
            "denial_details": claim.denial_details,
            "received_date": claim.received_date.strftime("%Y-%m-%d") if claim.received_date else None,
            "processed_date": claim.processed_date.strftime("%Y-%m-%d") if claim.processed_date else None,
            "can_appeal": claim.status == ClaimStatus.DENIED and not claim.is_appealed
        }
    except Exception as e:
        logger.error(f"❌ Error getting claim status: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def get_claim_details(member_id: str, claim_id: str) -> Dict[str, Any]:
    """Get full details of a claim including line items.
    
    Args:
        member_id: UUID of the member
        claim_id: Claim number or UUID
        
    Returns:
        Dictionary with complete claim details
    """
    _lazy_import_healthcare_models()
    db = SessionLocal()
    try:
        member = _get_member_by_user_id(db, member_id)
        
        if not member:
            return {"success": False, "error": "Member not found"}
        
        claim = db.query(HealthcareClaim).filter(
            HealthcareClaim.member_id == member.id,
            or_(
                HealthcareClaim.claim_number == claim_id,
                HealthcareClaim.id == UUID(claim_id) if len(claim_id) == 36 else False
            )
        ).first()
        
        if not claim:
            return {"success": False, "error": f"Claim {claim_id} not found"}
        
        # Get line items
        line_items = db.query(ClaimLineItem).filter(
            ClaimLineItem.claim_id == claim.id
        ).order_by(ClaimLineItem.line_number).all()
        
        # Denial reason explanations
        denial_explanations = {
            DenialReason.NOT_COVERED: "This service is not covered under your current plan benefits.",
            DenialReason.OUT_OF_NETWORK: "This provider is not in your plan's network.",
            DenialReason.NO_PRIOR_AUTH: "This service required prior authorization which was not obtained.",
            DenialReason.NOT_MEDICALLY_NECESSARY: "Based on the information provided, this service did not meet medical necessity criteria.",
            DenialReason.DUPLICATE_CLAIM: "This appears to be a duplicate of an existing claim.",
            DenialReason.TIMELY_FILING: "This claim was submitted after the filing deadline.",
            DenialReason.COORDINATION_OF_BENEFITS: "We need information about other insurance coverage.",
            DenialReason.MAX_BENEFIT_REACHED: "You've reached the maximum benefit for this service.",
            DenialReason.INCOMPLETE_INFO: "The claim is missing required information.",
            DenialReason.EXPERIMENTAL: "This treatment is considered experimental or investigational."
        }
        
        return {
            "success": True,
            "claim_number": claim.claim_number,
            "status": claim.status.value,
            "service_date": claim.service_date.strftime("%Y-%m-%d") if claim.service_date else None,
            "provider": {
                "name": claim.provider_name,
                "npi": claim.provider_npi,
                "network_tier": claim.provider_network_tier.value if claim.provider_network_tier else None
            },
            "diagnosis_codes": claim.diagnosis_codes,
            "financials": {
                "billed_amount": float(claim.billed_amount) if claim.billed_amount else 0,
                "allowed_amount": float(claim.allowed_amount) if claim.allowed_amount else 0,
                "paid_amount": float(claim.paid_amount) if claim.paid_amount else 0,
                "member_responsibility": float(claim.member_responsibility) if claim.member_responsibility else 0,
                "breakdown": {
                    "deductible": float(claim.deductible_applied) if claim.deductible_applied else 0,
                    "copay": float(claim.copay_applied) if claim.copay_applied else 0,
                    "coinsurance": float(claim.coinsurance_applied) if claim.coinsurance_applied else 0
                }
            },
            "denial_info": {
                "reason": claim.denial_reason.value if claim.denial_reason else None,
                "explanation": denial_explanations.get(claim.denial_reason, "") if claim.denial_reason else None,
                "details": claim.denial_details
            } if claim.denial_reason else None,
            "line_items": [
                {
                    "line_number": item.line_number,
                    "procedure_code": item.procedure_code,
                    "description": item.procedure_description,
                    "billed": float(item.billed_amount) if item.billed_amount else 0,
                    "allowed": float(item.allowed_amount) if item.allowed_amount else 0,
                    "paid": float(item.paid_amount) if item.paid_amount else 0,
                    "is_covered": item.is_covered
                }
                for item in line_items
            ],
            "dates": {
                "received": claim.received_date.strftime("%Y-%m-%d") if claim.received_date else None,
                "processed": claim.processed_date.strftime("%Y-%m-%d") if claim.processed_date else None,
                "paid": claim.paid_date.strftime("%Y-%m-%d") if claim.paid_date else None
            },
            "appeal_info": {
                "is_appealed": claim.is_appealed,
                "appeal_date": claim.appeal_date.strftime("%Y-%m-%d") if claim.appeal_date else None,
                "appeal_decision": claim.appeal_decision
            } if claim.is_appealed else None
        }
    except Exception as e:
        logger.error(f"❌ Error getting claim details: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def file_claim_appeal(member_id: str, claim_id: str, reason: str) -> Dict[str, Any]:
    """File an appeal for a denied claim.
    
    Args:
        member_id: UUID of the member
        claim_id: Claim number or UUID
        reason: Reason for the appeal
        
    Returns:
        Dictionary with appeal confirmation
    """
    _lazy_import_healthcare_models()
    db = SessionLocal()
    try:
        member = _get_member_by_user_id(db, member_id)
        
        if not member:
            return {"success": False, "error": "Member not found"}
        
        claim = db.query(HealthcareClaim).filter(
            HealthcareClaim.member_id == member.id,
            or_(
                HealthcareClaim.claim_number == claim_id,
                HealthcareClaim.id == UUID(claim_id) if len(claim_id) == 36 else False
            )
        ).first()
        
        if not claim:
            return {"success": False, "error": f"Claim {claim_id} not found"}
        
        if claim.status != ClaimStatus.DENIED:
            return {
                "success": False,
                "error": f"Only denied claims can be appealed. This claim status is {claim.status.value}."
            }
        
        if claim.is_appealed:
            return {
                "success": False,
                "error": "This claim has already been appealed."
            }
        
        # File the appeal
        claim.is_appealed = True
        claim.appeal_date = datetime.now(timezone.utc)
        claim.appeal_reason = reason
        claim.status = ClaimStatus.APPEALED
        
        db.commit()
        
        logger.info(f"✅ Filed appeal for claim {claim.claim_number}")
        
        return {
            "success": True,
            "claim_number": claim.claim_number,
            "appeal_filed_date": claim.appeal_date.strftime("%Y-%m-%d"),
            "appeal_reason": reason,
            "message": "Your appeal has been filed successfully. You should receive a decision within 30-60 days. We'll send you a letter with the outcome.",
            "expected_decision_date": (datetime.now(timezone.utc) + timedelta(days=45)).strftime("%Y-%m-%d")
        }
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error filing appeal: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def get_eob(member_id: str, claim_id: str) -> Dict[str, Any]:
    """Get Explanation of Benefits (EOB) for a claim.
    
    Args:
        member_id: UUID of the member
        claim_id: Claim number or UUID
        
    Returns:
        Dictionary with EOB details formatted for explanation
    """
    _lazy_import_healthcare_models()
    db = SessionLocal()
    try:
        member = _get_member_by_user_id(db, member_id)
        
        if not member:
            return {"success": False, "error": "Member not found"}
        
        claim = db.query(HealthcareClaim).filter(
            HealthcareClaim.member_id == member.id,
            or_(
                HealthcareClaim.claim_number == claim_id,
                HealthcareClaim.id == UUID(claim_id) if len(claim_id) == 36 else False
            )
        ).first()
        
        if not claim:
            return {"success": False, "error": f"Claim {claim_id} not found"}
        
        billed = float(claim.billed_amount) if claim.billed_amount else 0
        allowed = float(claim.allowed_amount) if claim.allowed_amount else 0
        paid = float(claim.paid_amount) if claim.paid_amount else 0
        member_resp = float(claim.member_responsibility) if claim.member_responsibility else 0
        
        return {
            "success": True,
            "eob_summary": {
                "claim_number": claim.claim_number,
                "service_date": claim.service_date.strftime("%B %d, %Y") if claim.service_date else None,
                "provider": claim.provider_name,
                "what_provider_charged": billed,
                "what_plan_allows": allowed,
                "discount_savings": billed - allowed if allowed else 0,
                "what_plan_paid": paid,
                "what_you_owe": member_resp,
                "breakdown": {
                    "deductible_applied": float(claim.deductible_applied) if claim.deductible_applied else 0,
                    "copay": float(claim.copay_applied) if claim.copay_applied else 0,
                    "coinsurance": float(claim.coinsurance_applied) if claim.coinsurance_applied else 0
                }
            },
            "explanation": f"For your visit on {claim.service_date.strftime('%B %d') if claim.service_date else 'this date'} with {claim.provider_name or 'your provider'}: "
                          f"They charged ${billed:.2f}. Based on our agreement with the provider, we allow ${allowed:.2f}. "
                          f"We paid ${paid:.2f} and your share is ${member_resp:.2f}."
        }
    except Exception as e:
        logger.error(f"❌ Error getting EOB: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


# ============================================================================
# BENEFITS TOOLS
# ============================================================================

@mcp.tool()
def get_benefits_summary(member_id: str) -> Dict[str, Any]:
    """Get summary of member's benefits.
    
    Args:
        member_id: UUID of the member
        
    Returns:
        Dictionary with benefits summary
    """
    _lazy_import_healthcare_models()
    db = SessionLocal()
    try:
        member = _get_member_by_user_id(db, member_id)
        
        if not member:
            return {"success": False, "error": "Member not found"}
        
        plan = member.plan
        if not plan:
            return {"success": False, "error": "No plan information found"}
        
        # Get benefits
        benefits = db.query(PlanBenefit).filter(
            PlanBenefit.plan_id == plan.id
        ).all()
        
        return {
            "success": True,
            "plan_info": {
                "plan_name": plan.plan_name,
                "plan_type": plan.plan_type
            },
            "deductibles": {
                "individual_in_network": float(plan.individual_deductible_in_network),
                "individual_out_of_network": float(plan.individual_deductible_out_of_network) if plan.individual_deductible_out_of_network else None,
                "family_in_network": float(plan.family_deductible_in_network) if plan.family_deductible_in_network else None,
                "family_out_of_network": float(plan.family_deductible_out_of_network) if plan.family_deductible_out_of_network else None
            },
            "out_of_pocket_max": {
                "individual_in_network": float(plan.individual_oop_max_in_network),
                "individual_out_of_network": float(plan.individual_oop_max_out_of_network) if plan.individual_oop_max_out_of_network else None,
                "family_in_network": float(plan.family_oop_max_in_network) if plan.family_oop_max_in_network else None,
                "family_out_of_network": float(plan.family_oop_max_out_of_network) if plan.family_oop_max_out_of_network else None
            },
            "covered_services": [
                {
                    "service": benefit.service_category.value.replace("_", " ").title(),
                    "is_covered": benefit.is_covered,
                    "copay_in_network": float(benefit.copay_in_network) if benefit.copay_in_network else None,
                    "coinsurance_in_network": float(benefit.coinsurance_in_network) if benefit.coinsurance_in_network else None,
                    "requires_prior_auth": benefit.requires_prior_auth,
                    "requires_referral": benefit.requires_referral
                }
                for benefit in benefits
            ],
            "plan_features": {
                "requires_referral": plan.requires_referral,
                "has_pharmacy_benefit": plan.has_pharmacy_benefit,
                "has_mental_health_parity": plan.has_mental_health_parity
            }
        }
    except Exception as e:
        logger.error(f"❌ Error getting benefits summary: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def check_benefit_coverage(member_id: str, service_type: str) -> Dict[str, Any]:
    """Check if a specific service is covered and get cost details.
    
    Args:
        member_id: UUID of the member
        service_type: Type of service (e.g., office_visit, surgery, mental_health)
        
    Returns:
        Dictionary with coverage details for the service
    """
    _lazy_import_healthcare_models()
    db = SessionLocal()
    try:
        member = _get_member_by_user_id(db, member_id)
        
        if not member:
            return {"success": False, "error": "Member not found"}
        
        plan = member.plan
        if not plan:
            return {"success": False, "error": "No plan information found"}
        
        # Try to find matching service category
        service_lower = service_type.lower().replace(" ", "_")
        
        # Map common service names to categories
        service_mappings = {
            "doctor": "office_visit",
            "doctor visit": "office_visit",
            "primary care": "office_visit",
            "specialist": "specialist_visit",
            "er": "emergency",
            "emergency room": "emergency",
            "hospital": "hospital_inpatient",
            "lab": "diagnostic_lab",
            "labs": "diagnostic_lab",
            "blood work": "diagnostic_lab",
            "x-ray": "diagnostic_imaging",
            "xray": "diagnostic_imaging",
            "mri": "diagnostic_imaging",
            "ct scan": "diagnostic_imaging",
            "imaging": "diagnostic_imaging",
            "therapy": "mental_health",
            "counseling": "mental_health",
            "psychiatry": "mental_health",
            "physical therapy": "physical_therapy",
            "pt": "physical_therapy",
            "surgery": "surgery",
            "preventive": "preventive",
            "annual physical": "preventive",
            "checkup": "preventive"
        }
        
        mapped_service = service_mappings.get(service_lower, service_lower)
        
        try:
            service_category = ServiceCategory(mapped_service)
        except:
            return {
                "success": False,
                "error": f"Service type '{service_type}' not recognized. Please try a different description."
            }
        
        benefit = db.query(PlanBenefit).filter(
            PlanBenefit.plan_id == plan.id,
            PlanBenefit.service_category == service_category
        ).first()
        
        if not benefit:
            return {
                "success": True,
                "service_type": service_type,
                "is_covered": False,
                "message": f"I couldn't find specific coverage information for {service_type}. Please contact member services for details."
            }
        
        service_name = benefit.service_category.value.replace("_", " ").title()
        
        return {
            "success": True,
            "service_type": service_name,
            "is_covered": benefit.is_covered,
            "in_network": {
                "copay": float(benefit.copay_in_network) if benefit.copay_in_network else None,
                "coinsurance_percentage": float(benefit.coinsurance_in_network) if benefit.coinsurance_in_network else None
            },
            "out_of_network": {
                "copay": float(benefit.copay_out_of_network) if benefit.copay_out_of_network else None,
                "coinsurance_percentage": float(benefit.coinsurance_out_of_network) if benefit.coinsurance_out_of_network else None
            },
            "requirements": {
                "requires_prior_auth": benefit.requires_prior_auth,
                "requires_referral": benefit.requires_referral
            },
            "limits": {
                "annual_limit": benefit.annual_limit,
                "lifetime_limit": float(benefit.lifetime_limit) if benefit.lifetime_limit else None
            },
            "notes": benefit.coverage_notes,
            "message": f"Yes, {service_name} is covered under your plan." if benefit.is_covered else f"{service_name} is not covered under your current plan."
        }
    except Exception as e:
        logger.error(f"❌ Error checking benefit coverage: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def get_deductible_status(member_id: str) -> Dict[str, Any]:
    """Get member's deductible accumulation status.
    
    Args:
        member_id: UUID of the member
        
    Returns:
        Dictionary with deductible status
    """
    _lazy_import_healthcare_models()
    db = SessionLocal()
    try:
        member = _get_member_by_user_id(db, member_id)
        
        if not member:
            return {"success": False, "error": "Member not found"}
        
        plan = member.plan
        if not plan:
            return {"success": False, "error": "No plan information found"}
        
        # Get current year accumulation
        current_year = datetime.now().year
        accumulation = db.query(MemberAccumulation).filter(
            MemberAccumulation.member_id == member.id,
            MemberAccumulation.plan_year == current_year
        ).first()
        
        met_in_network = float(accumulation.individual_deductible_met_in_network) if accumulation else 0
        total_in_network = float(plan.individual_deductible_in_network)
        remaining_in_network = max(0, total_in_network - met_in_network)
        
        met_oon = float(accumulation.individual_deductible_met_out_of_network) if accumulation else 0
        total_oon = float(plan.individual_deductible_out_of_network) if plan.individual_deductible_out_of_network else None
        remaining_oon = max(0, total_oon - met_oon) if total_oon else None
        
        return {
            "success": True,
            "plan_year": current_year,
            "individual_in_network": {
                "deductible": total_in_network,
                "met": met_in_network,
                "remaining": remaining_in_network,
                "is_met": remaining_in_network == 0
            },
            "individual_out_of_network": {
                "deductible": total_oon,
                "met": met_oon,
                "remaining": remaining_oon,
                "is_met": remaining_oon == 0 if remaining_oon is not None else None
            } if total_oon else None,
            "message": f"You've met ${met_in_network:.2f} of your ${total_in_network:.2f} in-network deductible. You have ${remaining_in_network:.2f} remaining."
        }
    except Exception as e:
        logger.error(f"❌ Error getting deductible status: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def get_out_of_pocket_status(member_id: str) -> Dict[str, Any]:
    """Get member's out-of-pocket maximum accumulation status.
    
    Args:
        member_id: UUID of the member
        
    Returns:
        Dictionary with out-of-pocket status
    """
    _lazy_import_healthcare_models()
    db = SessionLocal()
    try:
        member = _get_member_by_user_id(db, member_id)
        
        if not member:
            return {"success": False, "error": "Member not found"}
        
        plan = member.plan
        if not plan:
            return {"success": False, "error": "No plan information found"}
        
        # Get current year accumulation
        current_year = datetime.now().year
        accumulation = db.query(MemberAccumulation).filter(
            MemberAccumulation.member_id == member.id,
            MemberAccumulation.plan_year == current_year
        ).first()
        
        met_in_network = float(accumulation.individual_oop_met_in_network) if accumulation else 0
        total_in_network = float(plan.individual_oop_max_in_network)
        remaining_in_network = max(0, total_in_network - met_in_network)
        
        return {
            "success": True,
            "plan_year": current_year,
            "individual_in_network": {
                "out_of_pocket_max": total_in_network,
                "met": met_in_network,
                "remaining": remaining_in_network,
                "is_met": remaining_in_network == 0
            },
            "message": f"You've spent ${met_in_network:.2f} toward your ${total_in_network:.2f} out-of-pocket maximum. " +
                      (f"Once you reach ${total_in_network:.2f}, we'll pay 100% of covered services for the rest of the year." if remaining_in_network > 0 else "You've reached your maximum - we're now paying 100% of covered services!")
        }
    except Exception as e:
        logger.error(f"❌ Error getting out-of-pocket status: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def get_copay_info(member_id: str, service_type: str) -> Dict[str, Any]:
    """Get copay information for a specific service type.
    
    Args:
        member_id: UUID of the member
        service_type: Type of service
        
    Returns:
        Dictionary with copay information
    """
    # Reuse the benefit coverage check
    return check_benefit_coverage(member_id, service_type)


# ============================================================================
# PRIOR AUTHORIZATION TOOLS
# ============================================================================

@mcp.tool()
def check_prior_auth_required(
    member_id: str,
    procedure_code: Optional[str] = None,
    service_type: Optional[str] = None,
    diagnosis_code: Optional[str] = None
) -> Dict[str, Any]:
    """Check if a procedure requires prior authorization.
    
    Args:
        member_id: UUID of the member
        procedure_code: CPT/HCPCS procedure code
        service_type: Type of service (alternative to procedure code)
        diagnosis_code: ICD-10 diagnosis code
        
    Returns:
        Dictionary indicating if prior auth is required
    """
    _lazy_import_healthcare_models()
    db = SessionLocal()
    try:
        member = _get_member_by_user_id(db, member_id)
        
        if not member:
            return {"success": False, "error": "Member not found"}
        
        plan = member.plan
        if not plan:
            return {"success": False, "error": "No plan information found"}
        
        # Common procedures that typically require prior auth
        prior_auth_procedures = {
            "70553": {"name": "MRI Brain", "requires_auth": True},
            "71250": {"name": "CT Scan Chest", "requires_auth": True},
            "27447": {"name": "Knee Replacement", "requires_auth": True},
            "27130": {"name": "Hip Replacement", "requires_auth": True},
            "97110": {"name": "Physical Therapy", "requires_auth": True},
            "95810": {"name": "Sleep Study", "requires_auth": True},
            "45378": {"name": "Colonoscopy", "requires_auth": False},
            "77067": {"name": "Mammogram", "requires_auth": False},
        }
        
        # Check by procedure code
        if procedure_code and procedure_code in prior_auth_procedures:
            proc_info = prior_auth_procedures[procedure_code]
            return {
                "success": True,
                "procedure_code": procedure_code,
                "procedure_name": proc_info["name"],
                "requires_prior_auth": proc_info["requires_auth"],
                "message": f"{'Yes, prior authorization is required' if proc_info['requires_auth'] else 'No, prior authorization is not required'} for {proc_info['name']}."
            }
        
        # Check by service type
        if service_type:
            service_lower = service_type.lower()
            
            # Map common service names
            auth_required_services = {
                "mri": True,
                "ct scan": True,
                "surgery": True,
                "joint replacement": True,
                "knee replacement": True,
                "hip replacement": True,
                "physical therapy": True,
                "sleep study": True,
                "dme": True,
                "durable medical equipment": True,
                "home health": True,
                "skilled nursing": True,
                "office visit": False,
                "lab": False,
                "blood work": False,
                "preventive": False,
                "annual physical": False,
                "colonoscopy": False,
                "mammogram": False
            }
            
            for service_name, requires_auth in auth_required_services.items():
                if service_name in service_lower:
                    return {
                        "success": True,
                        "service_type": service_type,
                        "requires_prior_auth": requires_auth,
                        "message": f"{'Yes, prior authorization is required' if requires_auth else 'No, prior authorization is not required'} for {service_type}."
                    }
        
        # Default response if not found
        return {
            "success": True,
            "procedure_code": procedure_code,
            "service_type": service_type,
            "requires_prior_auth": None,
            "message": "I couldn't find specific authorization requirements for this procedure. I recommend contacting us to verify before scheduling your procedure."
        }
    except Exception as e:
        logger.error(f"❌ Error checking prior auth requirement: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def submit_prior_auth(
    member_id: str,
    procedure_code: str,
    provider_npi: str,
    diagnosis_code: Optional[str] = None,
    procedure_description: Optional[str] = None,
    clinical_notes: Optional[str] = None,
    is_urgent: bool = False
) -> Dict[str, Any]:
    """Submit a prior authorization request.
    
    Args:
        member_id: UUID of the member
        procedure_code: CPT/HCPCS procedure code
        provider_npi: NPI of the requesting/servicing provider
        diagnosis_code: ICD-10 diagnosis code
        procedure_description: Description of the procedure
        clinical_notes: Supporting clinical information
        is_urgent: Whether this is an urgent request
        
    Returns:
        Dictionary with authorization request details
    """
    _lazy_import_healthcare_models()
    db = SessionLocal()
    try:
        member = _get_member_by_user_id(db, member_id)
        
        if not member:
            return {"success": False, "error": "Member not found"}
        
        # Create authorization request
        auth = PriorAuthorization(
            member_id=member.id,
            auth_number=_generate_auth_number(),
            procedure_code=procedure_code,
            procedure_description=procedure_description,
            diagnosis_codes=[diagnosis_code] if diagnosis_code else None,
            requesting_provider_npi=provider_npi,
            servicing_provider_npi=provider_npi,
            clinical_notes=clinical_notes,
            is_urgent=is_urgent,
            status=PriorAuthStatus.PENDING,
            requested_date=datetime.now(timezone.utc)
        )
        
        db.add(auth)
        db.commit()
        db.refresh(auth)
        
        # Expected turnaround
        turnaround_days = 3 if is_urgent else 15
        expected_decision = datetime.now(timezone.utc) + timedelta(days=turnaround_days)
        
        logger.info(f"✅ Submitted prior auth {auth.auth_number} for member {member.member_number}")
        
        return {
            "success": True,
            "auth_number": auth.auth_number,
            "status": auth.status.value,
            "procedure_code": procedure_code,
            "procedure_description": procedure_description,
            "is_urgent": is_urgent,
            "submitted_date": auth.requested_date.strftime("%Y-%m-%d"),
            "expected_decision_date": expected_decision.strftime("%Y-%m-%d"),
            "message": f"Your prior authorization request has been submitted. Reference number: {auth.auth_number}. " +
                      f"{'For urgent requests, we aim to respond within 72 hours.' if is_urgent else 'You should receive a decision within 15 business days.'}"
        }
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error submitting prior auth: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def get_prior_auth_status(member_id: str, auth_id: str) -> Dict[str, Any]:
    """Check the status of a prior authorization request.
    
    Args:
        member_id: UUID of the member
        auth_id: Authorization number or UUID
        
    Returns:
        Dictionary with authorization status
    """
    _lazy_import_healthcare_models()
    db = SessionLocal()
    try:
        member = _get_member_by_user_id(db, member_id)
        
        if not member:
            return {"success": False, "error": "Member not found"}
        
        auth = db.query(PriorAuthorization).filter(
            PriorAuthorization.member_id == member.id,
            or_(
                PriorAuthorization.auth_number == auth_id,
                PriorAuthorization.id == UUID(auth_id) if len(auth_id) == 36 else False
            )
        ).first()
        
        if not auth:
            return {"success": False, "error": f"Authorization {auth_id} not found"}
        
        status_messages = {
            PriorAuthStatus.PENDING: "Your request is being reviewed.",
            PriorAuthStatus.APPROVED: "Your request has been approved!",
            PriorAuthStatus.DENIED: "Your request was not approved.",
            PriorAuthStatus.EXPIRED: "This authorization has expired.",
            PriorAuthStatus.CANCELLED: "This authorization was cancelled.",
            PriorAuthStatus.ADDITIONAL_INFO_NEEDED: "We need additional information to complete the review."
        }
        
        return {
            "success": True,
            "auth_number": auth.auth_number,
            "status": auth.status.value,
            "status_message": status_messages.get(auth.status, ""),
            "procedure_code": auth.procedure_code,
            "procedure_description": auth.procedure_description,
            "requested_date": auth.requested_date.strftime("%Y-%m-%d") if auth.requested_date else None,
            "decision_date": auth.decision_date.strftime("%Y-%m-%d") if auth.decision_date else None,
            "decision_reason": auth.decision_reason,
            "approved_details": {
                "approved_units": auth.approved_units,
                "valid_from": auth.approved_from_date.strftime("%Y-%m-%d") if auth.approved_from_date else None,
                "valid_to": auth.approved_to_date.strftime("%Y-%m-%d") if auth.approved_to_date else None,
                "expiration_date": auth.expiration_date.strftime("%Y-%m-%d") if auth.expiration_date else None
            } if auth.status == PriorAuthStatus.APPROVED else None
        }
    except Exception as e:
        logger.error(f"❌ Error getting prior auth status: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def list_prior_auths(member_id: str, status: Optional[str] = None) -> Dict[str, Any]:
    """List all prior authorizations for a member.
    
    Args:
        member_id: UUID of the member
        status: Optional filter by status
        
    Returns:
        Dictionary with list of authorizations
    """
    _lazy_import_healthcare_models()
    db = SessionLocal()
    try:
        member = _get_member_by_user_id(db, member_id)
        
        if not member:
            return {"success": False, "error": "Member not found"}
        
        query = db.query(PriorAuthorization).filter(
            PriorAuthorization.member_id == member.id
        )
        
        if status:
            try:
                status_enum = PriorAuthStatus(status.lower())
                query = query.filter(PriorAuthorization.status == status_enum)
            except:
                pass
        
        auths = query.order_by(PriorAuthorization.requested_date.desc()).all()
        
        return {
            "success": True,
            "authorizations_count": len(auths),
            "authorizations": [
                {
                    "auth_number": auth.auth_number,
                    "procedure_code": auth.procedure_code,
                    "procedure_description": auth.procedure_description,
                    "status": auth.status.value,
                    "requested_date": auth.requested_date.strftime("%Y-%m-%d") if auth.requested_date else None,
                    "expiration_date": auth.expiration_date.strftime("%Y-%m-%d") if auth.expiration_date else None
                }
                for auth in auths
            ]
        }
    except Exception as e:
        logger.error(f"❌ Error listing prior auths: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


# ============================================================================
# PROVIDER NETWORK TOOLS
# ============================================================================

@mcp.tool()
def search_providers(
    member_id: str,
    specialty: str,
    zip_code: Optional[str] = None,
    radius_miles: int = 25,
    limit: int = 10
) -> Dict[str, Any]:
    """Search for in-network providers by specialty and location.
    
    Args:
        member_id: UUID of the member
        specialty: Provider specialty (e.g., cardiology, orthopedics)
        zip_code: ZIP code for location-based search
        radius_miles: Search radius in miles
        limit: Maximum number of results
        
    Returns:
        Dictionary with matching providers
    """
    _lazy_import_healthcare_models()
    db = SessionLocal()
    try:
        member = _get_member_by_user_id(db, member_id)
        
        if not member:
            return {"success": False, "error": "Member not found"}
        
        # Build query
        query = db.query(HealthcareProvider).filter(
            HealthcareProvider.is_accepting_patients == True
        )
        
        # Filter by specialty (case-insensitive partial match)
        specialty_lower = specialty.lower()
        
        # Specialty mappings
        specialty_mappings = {
            "primary care": ["family medicine", "internal medicine", "general practice"],
            "heart": ["cardiology", "cardiovascular"],
            "cardiologist": ["cardiology"],
            "orthopedic": ["orthopedic surgery", "sports medicine"],
            "skin": ["dermatology"],
            "dermatologist": ["dermatology"],
            "mental health": ["psychiatry", "psychology", "behavioral health"],
            "therapist": ["psychology", "behavioral health"],
            "psychiatrist": ["psychiatry"],
            "women's health": ["obstetrics", "gynecology", "ob/gyn"],
            "obgyn": ["obstetrics", "gynecology"],
            "children": ["pediatrics"],
            "pediatrician": ["pediatrics"],
        }
        
        search_terms = specialty_mappings.get(specialty_lower, [specialty_lower])
        
        # Create OR conditions for specialty search
        specialty_conditions = []
        for term in search_terms:
            specialty_conditions.append(
                func.lower(HealthcareProvider.primary_specialty).contains(term)
            )
        
        if specialty_conditions:
            query = query.filter(or_(*specialty_conditions))
        
        # Filter by zip code if provided
        if zip_code:
            query = query.filter(HealthcareProvider.zip_code == zip_code)
        
        # Prefer Tier 1 providers, then by rating
        query = query.order_by(
            HealthcareProvider.network_tier,
            HealthcareProvider.quality_rating.desc().nullslast()
        )
        
        providers = query.limit(limit).all()
        
        if not providers:
            return {
                "success": True,
                "providers": [],
                "message": f"No {specialty} providers found in your area. Try expanding your search radius or contact us for assistance."
            }
        
        return {
            "success": True,
            "search_criteria": {
                "specialty": specialty,
                "zip_code": zip_code,
                "radius_miles": radius_miles
            },
            "providers_count": len(providers),
            "providers": [
                {
                    "name": f"Dr. {provider.first_name} {provider.last_name}" if provider.first_name else provider.organization_name,
                    "npi": provider.npi,
                    "specialty": provider.primary_specialty,
                    "network_tier": provider.network_tier.value,
                    "tier_description": "Preferred (lowest cost)" if provider.network_tier == NetworkTier.TIER_1 else "Standard in-network",
                    "address": f"{provider.address_line_1}, {provider.city}, {provider.state} {provider.zip_code}",
                    "phone": provider.phone,
                    "accepting_patients": provider.is_accepting_patients,
                    "quality_rating": float(provider.quality_rating) if provider.quality_rating else None,
                    "languages": provider.languages
                }
                for provider in providers
            ]
        }
    except Exception as e:
        logger.error(f"❌ Error searching providers: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def check_provider_network(member_id: str, provider_npi: str) -> Dict[str, Any]:
    """Check if a specific provider is in-network.
    
    Args:
        member_id: UUID of the member
        provider_npi: NPI of the provider
        
    Returns:
        Dictionary with provider network status
    """
    _lazy_import_healthcare_models()
    db = SessionLocal()
    try:
        member = _get_member_by_user_id(db, member_id)
        
        if not member:
            return {"success": False, "error": "Member not found"}
        
        provider = db.query(HealthcareProvider).filter(
            HealthcareProvider.npi == provider_npi
        ).first()
        
        if not provider:
            return {
                "success": True,
                "provider_npi": provider_npi,
                "is_in_network": False,
                "message": "This provider was not found in our network directory. They may be out-of-network, which could result in higher costs."
            }
        
        tier_descriptions = {
            NetworkTier.TIER_1: "Preferred provider - lowest cost to you",
            NetworkTier.TIER_2: "Standard in-network provider",
            NetworkTier.TIER_3: "Out-of-network - higher costs apply"
        }
        
        is_in_network = provider.network_tier in [NetworkTier.TIER_1, NetworkTier.TIER_2]
        
        return {
            "success": True,
            "provider": {
                "name": f"Dr. {provider.first_name} {provider.last_name}" if provider.first_name else provider.organization_name,
                "npi": provider.npi,
                "specialty": provider.primary_specialty
            },
            "network_status": {
                "is_in_network": is_in_network,
                "network_tier": provider.network_tier.value,
                "tier_description": tier_descriptions.get(provider.network_tier, "")
            },
            "contact": {
                "address": f"{provider.address_line_1}, {provider.city}, {provider.state} {provider.zip_code}",
                "phone": provider.phone
            },
            "accepting_patients": provider.is_accepting_patients,
            "message": f"{'Good news! ' if is_in_network else ''}{provider.organization_name or f'Dr. {provider.last_name}'} is {'in' if is_in_network else 'out of'} network. {tier_descriptions.get(provider.network_tier, '')}"
        }
    except Exception as e:
        logger.error(f"❌ Error checking provider network: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def get_provider_details(provider_npi: str) -> Dict[str, Any]:
    """Get detailed information about a provider.
    
    Args:
        provider_npi: NPI of the provider
        
    Returns:
        Dictionary with provider details
    """
    _lazy_import_healthcare_models()
    db = SessionLocal()
    try:
        provider = db.query(HealthcareProvider).filter(
            HealthcareProvider.npi == provider_npi
        ).first()
        
        if not provider:
            return {"success": False, "error": "Provider not found"}
        
        return {
            "success": True,
            "provider": {
                "name": f"Dr. {provider.first_name} {provider.last_name}" if provider.first_name else provider.organization_name,
                "npi": provider.npi,
                "primary_specialty": provider.primary_specialty,
                "secondary_specialties": provider.secondary_specialties,
                "network_tier": provider.network_tier.value
            },
            "contact": {
                "phone": provider.phone,
                "fax": provider.fax,
                "email": provider.email,
                "website": provider.website
            },
            "location": {
                "address_line_1": provider.address_line_1,
                "address_line_2": provider.address_line_2,
                "city": provider.city,
                "state": provider.state,
                "zip_code": provider.zip_code
            },
            "quality": {
                "rating": float(provider.quality_rating) if provider.quality_rating else None,
                "reviews_count": provider.patient_reviews_count
            },
            "languages": provider.languages,
            "hospital_affiliations": provider.hospital_affiliations,
            "accepting_new_patients": provider.is_accepting_patients
        }
    except Exception as e:
        logger.error(f"❌ Error getting provider details: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


# ============================================================================
# CARE MANAGEMENT TOOLS
# ============================================================================

@mcp.tool()
def get_care_programs(member_id: str) -> Dict[str, Any]:
    """Get available care management programs for a member.
    
    Args:
        member_id: UUID of the member
        
    Returns:
        Dictionary with available programs
    """
    _lazy_import_healthcare_models()
    db = SessionLocal()
    try:
        member = _get_member_by_user_id(db, member_id)
        
        if not member:
            return {"success": False, "error": "Member not found"}
        
        # Get all active programs
        programs = db.query(CareProgram).filter(
            CareProgram.is_active == True
        ).all()
        
        # Get member's enrolled programs
        enrolled = db.query(MemberCareProgram).filter(
            MemberCareProgram.member_id == member.id,
            MemberCareProgram.is_active == True
        ).all()
        enrolled_ids = [e.program_id for e in enrolled]
        
        return {
            "success": True,
            "available_programs": [
                {
                    "program_id": str(program.id),
                    "program_code": program.program_code,
                    "name": program.program_name,
                    "type": program.program_type,
                    "description": program.description,
                    "is_enrolled": program.id in enrolled_ids,
                    "features": {
                        "coaching": program.includes_coaching,
                        "monitoring": program.includes_monitoring,
                        "rewards": program.includes_rewards
                    },
                    "target_conditions": program.target_conditions
                }
                for program in programs
            ],
            "enrolled_count": len(enrolled)
        }
    except Exception as e:
        logger.error(f"❌ Error getting care programs: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def enroll_care_program(member_id: str, program_id: str) -> Dict[str, Any]:
    """Enroll member in a care management program.
    
    Args:
        member_id: UUID of the member
        program_id: UUID or code of the program
        
    Returns:
        Dictionary with enrollment confirmation
    """
    _lazy_import_healthcare_models()
    db = SessionLocal()
    try:
        member = _get_member_by_user_id(db, member_id)
        
        if not member:
            return {"success": False, "error": "Member not found"}
        
        # Find program
        program = db.query(CareProgram).filter(
            or_(
                CareProgram.id == UUID(program_id) if len(program_id) == 36 else False,
                CareProgram.program_code == program_id
            )
        ).first()
        
        if not program:
            return {"success": False, "error": "Program not found"}
        
        # Check if already enrolled
        existing = db.query(MemberCareProgram).filter(
            MemberCareProgram.member_id == member.id,
            MemberCareProgram.program_id == program.id,
            MemberCareProgram.is_active == True
        ).first()
        
        if existing:
            return {
                "success": False,
                "error": f"You're already enrolled in {program.program_name}."
            }
        
        # Create enrollment
        enrollment = MemberCareProgram(
            member_id=member.id,
            program_id=program.id,
            is_active=True,
            enrolled_date=datetime.now(timezone.utc)
        )
        
        db.add(enrollment)
        db.commit()
        
        logger.info(f"✅ Enrolled member {member.member_number} in program {program.program_code}")
        
        return {
            "success": True,
            "program_name": program.program_name,
            "enrolled_date": enrollment.enrolled_date.strftime("%Y-%m-%d"),
            "message": f"You've been enrolled in {program.program_name}! A care coordinator will reach out within 3-5 business days to get you started."
        }
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error enrolling in care program: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def get_preventive_care(member_id: str) -> Dict[str, Any]:
    """Get preventive care recommendations and reminders.
    
    Args:
        member_id: UUID of the member
        
    Returns:
        Dictionary with preventive care information
    """
    _lazy_import_healthcare_models()
    db = SessionLocal()
    try:
        member = _get_member_by_user_id(db, member_id)
        
        if not member:
            return {"success": False, "error": "Member not found"}
        
        # Calculate age if DOB available
        age = None
        if member.date_of_birth:
            today = datetime.now(timezone.utc)
            age = today.year - member.date_of_birth.year
            if today.month < member.date_of_birth.month or (today.month == member.date_of_birth.month and today.day < member.date_of_birth.day):
                age -= 1
        
        # Build recommendations based on age
        recommendations = [
            {
                "service": "Annual Physical Exam",
                "frequency": "Every year",
                "covered_at": "100% - No cost to you",
                "age_range": "All ages"
            },
            {
                "service": "Flu Shot",
                "frequency": "Every year",
                "covered_at": "100% - No cost to you",
                "age_range": "All ages"
            }
        ]
        
        if age and age >= 50:
            recommendations.append({
                "service": "Colonoscopy",
                "frequency": "Every 10 years starting at 45-50",
                "covered_at": "100% - No cost to you",
                "age_range": "45+"
            })
        
        if age and age >= 40:
            recommendations.append({
                "service": "Mammogram",
                "frequency": "Every 1-2 years starting at 40-50",
                "covered_at": "100% - No cost to you",
                "age_range": "40+"
            })
        
        return {
            "success": True,
            "preventive_care": {
                "message": "Preventive care services are covered at 100% when you see an in-network provider. Here are your recommended screenings:",
                "recommendations": recommendations
            },
            "note": "These are general recommendations. Please consult with your doctor about your specific needs."
        }
    except Exception as e:
        logger.error(f"❌ Error getting preventive care: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


if __name__ == "__main__":
    mcp.run()
