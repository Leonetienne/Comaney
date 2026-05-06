import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from ..decorators import feuser_required
from ..models import Category, Tag


@feuser_required
def categories_tags(request):
    feuser = request.feuser
    categories = Category.objects.filter(owning_feuser=feuser)
    tags = Tag.objects.filter(owning_feuser=feuser)
    return render(request, "budget/categories_tags.html", {
        "active_nav": "categories_tags",
        "categories": categories,
        "tags": tags,
    })


@feuser_required
@require_POST
def category_create(request):
    data = json.loads(request.body)
    title = data.get("title", "").strip()
    if not title:
        return JsonResponse({"error": "Title required."}, status=400)
    if len(title) > 128:
        return JsonResponse({"error": "Title must be 128 characters or fewer."}, status=400)
    category = Category.objects.create(owning_feuser=request.feuser, title=title)
    return JsonResponse({"uid": category.uid, "title": category.title})


@feuser_required
@require_POST
def category_delete(request, uid):
    category = get_object_or_404(Category, uid=uid, owning_feuser=request.feuser)
    category.delete()
    return JsonResponse({"ok": True})


@feuser_required
@require_POST
def category_rename(request, uid):
    category = get_object_or_404(Category, uid=uid, owning_feuser=request.feuser)
    data = json.loads(request.body)
    title = data.get("title", "").strip()
    if not title:
        return JsonResponse({"error": "Title required."}, status=400)
    if len(title) > 128:
        return JsonResponse({"error": "Title must be 128 characters or fewer."}, status=400)
    category.title = title
    category.save(update_fields=["title"])
    return JsonResponse({"uid": category.uid, "title": category.title})


@feuser_required
@require_POST
def tag_create(request):
    data = json.loads(request.body)
    title = data.get("title", "").strip()
    if not title:
        return JsonResponse({"error": "Title required."}, status=400)
    if len(title) > 128:
        return JsonResponse({"error": "Title must be 128 characters or fewer."}, status=400)
    tag = Tag.objects.create(owning_feuser=request.feuser, title=title)
    return JsonResponse({"uid": tag.uid, "title": tag.title})


@feuser_required
@require_POST
def tag_delete(request, uid):
    tag = get_object_or_404(Tag, uid=uid, owning_feuser=request.feuser)
    tag.delete()
    return JsonResponse({"ok": True})


@feuser_required
@require_POST
def tag_rename(request, uid):
    tag = get_object_or_404(Tag, uid=uid, owning_feuser=request.feuser)
    data = json.loads(request.body)
    title = data.get("title", "").strip()
    if not title:
        return JsonResponse({"error": "Title required."}, status=400)
    if len(title) > 128:
        return JsonResponse({"error": "Title must be 128 characters or fewer."}, status=400)
    tag.title = title
    tag.save(update_fields=["title"])
    return JsonResponse({"uid": tag.uid, "title": tag.title})
