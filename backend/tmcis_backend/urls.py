from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("api/admin/", admin.site.urls),
    # The shared API service is mounted at /api and preserves that prefix.
    path("api/", include("tmcis.urls")),
]
