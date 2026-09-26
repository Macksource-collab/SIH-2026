from .models import AuditLog


def audit(db, action, user_id=None, resource_type="system", resource_id=None, details=None):
    """Explicit metadata only: never pass request bodies, passwords, or tokens."""
    db.add(AuditLog(user_id=user_id, action=action, resource_type=resource_type,
                    resource_id=str(resource_id) if resource_id else None, details=details or {}))
