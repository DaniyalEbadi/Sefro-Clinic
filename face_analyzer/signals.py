# This module ensures the face_analyzer app's models are included in audit logging.
# The actual audit logging is handled by logs/signals.py which uses post_save/post_delete
# signals on all models (except those in SKIP_MODELS).
# No additional code is needed here as the logs app automatically picks up all models.
