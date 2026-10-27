from django.urls import path
from . import views

app_name = 'data_ingestion'

urlpatterns = [
    path('upload/', views.upload_view, name='upload'),
]
