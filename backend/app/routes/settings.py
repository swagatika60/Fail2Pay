"""Recovery settings API — merchant-configurable recovery behaviour.

Serves GET (current settings) and PUT (validated update) for recovery settings.
Safety protections (hard-stop rules, opt-out, min reminder spacing) are not
configurable here and are always reported as enabled.
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.settings import RecoverySettingsResponse, RecoverySettingsUpdate
from app.services import recovery_settings as settings_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/recovery", response_model=RecoverySettingsResponse)
def get_recovery_settings(db: Session = Depends(get_db)):
    """Return the merchant's recovery settings (with safety toggles fixed on)."""
    row = settings_service.get_or_create(db)
    return settings_service.to_response(row)


@router.put("/recovery", response_model=RecoverySettingsResponse)
def update_recovery_settings(
    payload: RecoverySettingsUpdate,
    db: Session = Depends(get_db),
):
    """Validate and persist recovery settings; returns the new settings."""
    row = settings_service.save_settings(db, payload.model_dump())
    logger.info("recovery settings updated for merchant=%s", row.merchant_id)
    return settings_service.to_response(row)