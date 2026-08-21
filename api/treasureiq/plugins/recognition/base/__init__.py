"""BASE recognition plugins: one primary platform identity per municipality."""
from treasureiq.plugins.recognition.base.wordpress_agid import (
    PLUGIN,
    WordPressAgidRecognitionPlugin,
)

WORDPRESS_AGID_RECOGNITION_PLUGIN = PLUGIN

__all__ = ["PLUGIN", "WORDPRESS_AGID_RECOGNITION_PLUGIN", "WordPressAgidRecognitionPlugin"]
