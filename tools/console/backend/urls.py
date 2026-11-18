"""
backend.urls — what Django answers inside the three prefixes the dispatcher
gives it (../dispatch.py): /admin/, /accounts/ and /api/v1/.

Phase B1 (ADR 0006) ports no route: the admin and the health endpoints only.
/accounts/ is reserved for B3's sign-in and answers 404 until then; anything
else under /api/v1/ is a 404 as well.
"""
from django.contrib import admin
from django.urls import path

from . import views

admin.site.site_header = "Harness Console administration"
admin.site.site_title = "Harness Console admin"
admin.site.index_title = "Operational records"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/healthz", views.healthz, name="healthz"),
    path("api/v1/readyz", views.readyz, name="readyz"),
    path("api/v1/version", views.version, name="version"),
]
