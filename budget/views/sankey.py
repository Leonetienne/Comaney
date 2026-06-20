import json
from datetime import date

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from ..decorators import feuser_required
from ..sankey_generation import (
    SankeyValidationError,
    generate,
    load_editor_state,
    save_graph,
)
from ._period import _date_range_presets_context
from ._sharing import has_buddy_or_multiuser_project


@feuser_required
def sankey_studio(request):
    feuser = request.feuser
    state = load_editor_state(feuser)
    ctx = {
        "active_nav": "sankey_studio",
        "nav_show_sharing_toggle": has_buddy_or_multiuser_project(feuser),
        "initial_date_from": request.GET.get("date_from", ""),
        "initial_date_to": request.GET.get("date_to", ""),
        "catalog_json": json.dumps(state["catalog"]),
        "nodes_json": json.dumps(state["nodes"]),
        "edges_json": json.dumps(state["edges"]),
    }
    ctx.update(_date_range_presets_context(feuser))
    return render(request, "budget/sankey_studio.html", ctx)


@feuser_required
@require_POST
def sankey_save_api(request):
    feuser = request.feuser
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    try:
        save_graph(feuser, body.get("nodes", {}), body.get("edges", []))
    except SankeyValidationError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"ok": True})


@feuser_required
@require_POST
def sankey_generate_api(request):
    feuser = request.feuser
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    try:
        start = date.fromisoformat(body.get("date_from", ""))
        end = date.fromisoformat(body.get("date_to", ""))
    except (ValueError, TypeError):
        return JsonResponse({"error": "Invalid date range"}, status=400)
    sharing = body.get("sharing", "")
    try:
        result = generate(feuser, start, end, sharing)
    except SankeyValidationError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(result)
