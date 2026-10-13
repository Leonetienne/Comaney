from budget import catalog_service
from budget.catalog_service import CatalogError
from budget.models import Category, Tag

from .common import ID, ref_json
from ..registry import READ, WRITE, NotFound, OpError, operation

_TITLE = {"type": "string", "description": "Up to 128 characters."}
_SYNC = " Catalog partners get the same change."


def _get(model, feuser, uid):
    item = model.objects.filter(uid=uid, owning_feuser=feuser).first()
    if item is None:
        raise NotFound(f"{model.__name__} not found.")
    return item


def _run(fn):
    try:
        return ref_json(fn())
    except CatalogError as exc:
        raise OpError(str(exc))


def _register(kind, model, plural, create, rename, delete):
    @operation(
        f"{plural}_list", concern="catalog", access=READ, method="GET", path=f"{plural}/",
        description=f"All of the feuser's {plural}.",
    )
    def list_(ctx, args):
        return {plural: [ref_json(i) for i in model.objects.filter(owning_feuser=ctx.feuser).order_by("title")]}

    @operation(
        f"{plural}_get", concern="catalog", access=READ, method="GET", path=f"{plural}/<int:id>/",
        description=f"One {kind}.", params={"id": ID}, required=["id"],
    )
    def get(ctx, args):
        return ref_json(_get(model, ctx.feuser, args["id"]))

    @operation(
        f"{plural}_create", concern="catalog", access=WRITE, method="POST", path=f"{plural}/",
        description=f"Create a {kind}.{_SYNC}", params={"title": _TITLE}, required=["title"], status=201,
    )
    def create_(ctx, args):
        return _run(lambda: create(ctx.feuser, args["title"]))

    @operation(
        f"{plural}_update", concern="catalog", access=WRITE, method="PATCH", path=f"{plural}/<int:id>/",
        description=f"Rename a {kind}.{_SYNC}", params={"id": ID, "title": _TITLE}, required=["id", "title"],
    )
    def update(ctx, args):
        item = _get(model, ctx.feuser, args["id"])
        return _run(lambda: rename(item, ctx.feuser, args["title"]))

    @operation(
        f"{plural}_delete", concern="catalog", access=WRITE, method="DELETE", path=f"{plural}/<int:id>/",
        description=f"Delete a {kind}; expenses lose it.{_SYNC}",
        params={"id": ID}, required=["id"], destructive=True, status=204,
    )
    def delete_(ctx, args):
        delete(_get(model, ctx.feuser, args["id"]), ctx.feuser)
        return None


_register("category", Category, "categories",
          catalog_service.create_category, catalog_service.rename_category, catalog_service.delete_category)
_register("tag", Tag, "tags",
          catalog_service.create_tag, catalog_service.rename_tag, catalog_service.delete_tag)
