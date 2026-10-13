"""Category and tag writes shared by the web views, the REST API and the MCP server."""
from django.utils import timezone

from .models import Category, Tag

TITLE_MAX_LENGTH = 128


class CatalogError(Exception):
    """Invalid category or tag input; the message names the problem."""


def _clean_title(title) -> str:
    title = str(title or "").strip()
    if not title:
        raise CatalogError("Title required.")
    if len(title) > TITLE_MAX_LENGTH:
        raise CatalogError(f"Title must be {TITLE_MAX_LENGTH} characters or fewer.")
    return title


def _sync(model):
    from buddies.services import partnership
    if model is Category:
        return partnership.sync_category_create, partnership.sync_category_rename, partnership.sync_category_delete
    return partnership.sync_tag_create, partnership.sync_tag_rename, partnership.sync_tag_delete


def _create(model, feuser, title):
    title = _clean_title(title)
    item = model.objects.create(owning_feuser=feuser, title=title)
    _sync(model)[0](title, feuser)
    return item


def _rename(item, feuser, title):
    title = _clean_title(title)
    old_title = item.title
    item.title = title
    item.last_mod = timezone.now()
    item.save(update_fields=["title", "last_mod"])
    _sync(type(item))[1](old_title, title, feuser)
    return item


def _delete(item, feuser):
    title = item.title
    item.delete()
    _sync(type(item))[2](title, feuser)


def create_category(feuser, title) -> Category:
    """Create a category and mirror it to every onboarded catalog partner."""
    return _create(Category, feuser, title)


def rename_category(category, feuser, title) -> Category:
    return _rename(category, feuser, title)


def delete_category(category, feuser) -> None:
    _delete(category, feuser)


def create_tag(feuser, title) -> Tag:
    """Create a tag and mirror it to every onboarded catalog partner."""
    return _create(Tag, feuser, title)


def rename_tag(tag, feuser, title) -> Tag:
    return _rename(tag, feuser, title)


def delete_tag(tag, feuser) -> None:
    _delete(tag, feuser)
