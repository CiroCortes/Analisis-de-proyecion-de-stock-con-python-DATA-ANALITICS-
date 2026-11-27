from django.urls import path
from . import views

app_name = 'data_ingestion'

urlpatterns = [
    path('upload/', views.upload_view, name='upload'),
    path('athena/iniciar/', views.sync_athena_start, name='sync_athena_start'),
    path('athena/estado/', views.sync_athena_status, name='sync_athena_status'),
]
