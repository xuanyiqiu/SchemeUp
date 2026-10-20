import os

# Run Qt headless unless a platform is set explicitly, so tests never flash windows.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
