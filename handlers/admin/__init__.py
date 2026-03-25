"""
handlers/admin — Admin panel handlers (DM only).

Register all admin callbacks and commands on the PTB Application.
"""

from handlers.admin.menu import register_menu_handler
from handlers.admin.group_view import register_group_view_handlers
from handlers.admin.muted import register_muted_handlers
from handlers.admin.spam_log import register_spam_log_handlers
from handlers.admin.patterns import register_patterns_handlers
from handlers.admin.admins import register_admins_handlers


def register_admin_handlers(app) -> None:
    """Mount every admin-panel handler onto the PTB Application."""
    register_menu_handler(app)
    register_group_view_handlers(app)
    register_muted_handlers(app)
    register_spam_log_handlers(app)
    register_patterns_handlers(app)
    register_admins_handlers(app)
