"""Information reminder work owned by the existing Worker lifecycle."""
from ...storage.information_automation_schema import ready
from ..notification_targets import NotificationTargetService
from ..notification_email_transport import WorkspaceEmailTransportService
from ..workspace_telegram_transport import WorkspaceTelegramTransportService
from .execution import evaluate_pending
from .delivery import ReminderTransport, dispatch_pending


def run_information_automations(store, *, data_dir):
    if not ready(store.connect()):
        return
    targets = NotificationTargetService(store, data_dir=data_dir,
        email_transport=WorkspaceEmailTransportService(store, data_dir=data_dir),
        telegram_transport=WorkspaceTelegramTransportService(store, data_dir=data_dir))
    from .semantic_claims import maintain_semantic_leases
    maintain_semantic_leases(store)
    evaluate_pending(store, targets)
    dispatch_pending(store, targets, ReminderTransport(store, targets, data_dir), limit=1)
