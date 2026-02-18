import sys
import os


def get_user_data_dir():
    """Return a writable directory for database, uploads, and .env.

    When running as a PyInstaller bundle, use the directory where the
    executable is located (persistent across runs).
    When running in development, use the project directory.
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))
