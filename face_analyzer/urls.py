from django.urls import path

from .views import (
    FaceAnalysisDetailView,
    FaceAnalysisHistoryView,
    FaceAnalysisTipsView,
    FaceAnalyzeView,
)

app_name = 'face_analyzer'

urlpatterns = [
    path('face/analyze/', FaceAnalyzeView.as_view(), name='analyze'),
    path('face/<int:pk>/tips/', FaceAnalysisTipsView.as_view(), name='tips'),
    path('face/history/', FaceAnalysisHistoryView.as_view(), name='history'),
    path('face/history/<int:pk>/', FaceAnalysisDetailView.as_view(), name='history-detail'),
]
