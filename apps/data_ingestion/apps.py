from django.apps import AppConfig

class DataIngestionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.data_ingestion'
    verbose_name = 'Ingesta de Datos Datalake (TXT)'
