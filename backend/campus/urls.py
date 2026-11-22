from django.contrib import admin
from django.urls import include, path
from core.health import live, ready

urlpatterns = [path("admin/", admin.site.urls), path("api/", include("core.urls")),
               path("health/", ready), path("health/live/", live)]
