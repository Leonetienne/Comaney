"""
Service layer for the Buddies feature.

Import these classes wherever buddy logic is needed; never import model-level
logic directly from views or the API layer.
"""
from ._helpers import _display_name
from .archive import BuddyArchiveService
from .email import BuddyEmailService
from .expense import BuddyExpenseService
from .export import BuddyExportService, ProjectExportService
from .group import BuddyGroupService, ProjectService
from .lifecycle import BuddyLifecycleService
from .query import BuddyQueryService
from .settlement import BuddySettlementService

__all__ = [
    "BuddyArchiveService",
    "BuddyEmailService",
    "BuddyExpenseService",
    "BuddyExportService",
    "BuddyGroupService",
    "ProjectExportService",
    "ProjectService",
    "BuddyLifecycleService",
    "BuddyQueryService",
    "BuddySettlementService",
    "_display_name",
]
