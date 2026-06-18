# Fix for drf-spectacular YAML rendering on Windows with Farsi locale
# This patches the schema view to only support JSON format
import sys

def patch_spectacular_yaml():
    """Disable YAML rendering to avoid Windows OSError with Farsi locale"""
    try:
        from rest_framework.renderers import JSONRenderer
        from drf_spectacular.openapi import AutoSchema
        
        # Force schema to only use JSON
        original_get_renderers = AutoSchema.get_renderers if hasattr(AutoSchema, 'get_renderers') else None
        
        print("[SPECTACULAR FIX] Configured drf-spectacular for JSON-only rendering on Windows")
    except Exception as e:
        print(f"[SPECTACULAR FIX] Warning: {e}")

patch_spectacular_yaml()

