from django.apps import AppConfig


class FaceAnalyzerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'face_analyzer'
    verbose_name = 'Face AI Analyzer'

    def ready(self):
        import face_analyzer.signals  # noqa: F401
