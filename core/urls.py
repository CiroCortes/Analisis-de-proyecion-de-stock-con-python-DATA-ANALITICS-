import os
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.dashboard.urls')),
    path('auth/', include('apps.authentication.urls')),
    path('inventory/', include('apps.inventory.urls')),
    path('ingest/', include('apps.data_ingestion.urls')),
    path('purchasing/', include('apps.purchasing.urls')),
    path('ai/', include('apps.ai_assistant.urls')),
    path('reports/', include('apps.reports.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static('/reports/figures/', document_root=os.path.join(settings.BASE_DIR, 'reports', 'figures'))
