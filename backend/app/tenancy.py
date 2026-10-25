from sqlalchemy.orm import Session

from backend.app.models import TenantRecord

DEFAULT_TENANT_ID = "00000000-0000-4000-8000-000000000001"
DEFAULT_TENANT_NAME = "Northstar Payments"


def ensure_default_tenant(db: Session) -> TenantRecord:
    tenant = db.get(TenantRecord, DEFAULT_TENANT_ID)
    if tenant is None:
        tenant = TenantRecord(id=DEFAULT_TENANT_ID, name=DEFAULT_TENANT_NAME)
        db.add(tenant)
        db.flush()
    return tenant
