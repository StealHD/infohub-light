"""Information reminder work owned by the existing Worker lifecycle."""
from ...storage.information_unified_schema import ready
from ..notification_targets import NotificationTargetService
from ..notification_email_transport import WorkspaceEmailTransportService
from ..workspace_telegram_transport import WorkspaceTelegramTransportService
from .execution import evaluate_pending
from .delivery import ReminderTransport, dispatch_pending
from .preview_delivery import dispatch_preview_notifications


def run_information_automations(store, *, data_dir):
    if not ready(store.connect()):
        return
    targets = NotificationTargetService(store, data_dir=data_dir,
        email_transport=WorkspaceEmailTransportService(store, data_dir=data_dir),
        telegram_transport=WorkspaceTelegramTransportService(store, data_dir=data_dir))
    from .semantic_claims import maintain_semantic_leases
    maintain_semantic_leases(store)
    evaluate_pending(store, targets)
    sender = ReminderTransport(store, targets, data_dir)
    dispatch_pending(store, targets, sender, limit=1)
    dispatch_preview_notifications(store, targets, sender, limit=1)
