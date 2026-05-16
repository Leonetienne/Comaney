"""
Service layer for the Buddies feature.

Import these classes wherever buddy logic is needed; never import model-level
logic directly from views or the API layer.
"""
from ._helpers import _display_name
from .email import BuddyEmailService
from .expense import BuddyExpenseService
from .group import BuddyGroupService
from .lifecycle import BuddyLifecycleService
from .query import BuddyQueryService
from .settlement import BuddySettlementService

__all__ = [
    "BuddyEmailService",
    "BuddyExpenseService",
    "BuddyGroupService",
    "BuddyLifecycleService",
    "BuddyQueryService",
    "BuddySettlementService",
    "_display_name",
]
