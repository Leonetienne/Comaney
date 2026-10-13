from django.urls import path

from . import views
from .endpoint import mcp_endpoint

urlpatterns = [
    path("mcp", mcp_endpoint, name="mcp_endpoint"),
    path("mcp/", mcp_endpoint),
    path("agent-keys/", views.agent_key_create, name="agent_key_create"),
    path("agent-keys/<int:uid>/permissions/", views.agent_key_permissions, name="agent_key_permissions"),
    path("agent-keys/<int:uid>/revoke/", views.agent_key_revoke, name="agent_key_revoke"),
]
