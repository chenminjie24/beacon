from sqlalchemy.orm import Session

from app.id_utils import prefixed_id
from app.models import Alert, AlertLevel, AlertStatus, AuditLog


def write_audit(db: Session, *, actor: str, action: str, resource_type: str, resource_id: str, detail: dict) -> None:
    log = AuditLog(
        id=prefixed_id('aud'),
        actor=actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail,
    )
    db.add(log)


def create_alert(db: Session, *, level: AlertLevel, category: str, message: str, payload: dict) -> Alert:
    alert = Alert(
        id=prefixed_id('alr'),
        level=level,
        category=category,
        message=message,
        payload=payload,
        status=AlertStatus.OPEN,
    )
    db.add(alert)
    return alert
