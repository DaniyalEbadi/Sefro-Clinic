from rest_framework import status
from rest_framework.exceptions import APIException

PERSIAN_ANALYZE_FAILURE = 'تحلیل چهره ناموفق بود. لطفاً تصویر واضحتری ارسال کنید.'


class AnalyzerError(APIException):
    """Analysis backend failed (misconfiguration, provider error, unreadable image)."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_detail = 'Face analysis failed. Please try again later.'
    default_code = 'analysis_failed'


class FaceAnalyzerError(APIException):
    """Client-facing analysis failure: no/multiple face, MediaPipe/OpenCV errors."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = PERSIAN_ANALYZE_FAILURE
    default_code = 'face_analysis_failed'
