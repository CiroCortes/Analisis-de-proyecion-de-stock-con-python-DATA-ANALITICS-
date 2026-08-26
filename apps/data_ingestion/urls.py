from django.urls import path
from . import views

app_name = 'data_ingestion'

urlpatterns = [
    path('upload/', views.upload_excel_view, name='upload'),
    path('api/progress/', views.progress_api_view, name='progress_api'),
]
