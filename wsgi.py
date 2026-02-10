"""
PythonAnywhere WSGI Configuration
==================================
This file is used by PythonAnywhere to serve your Flask app.

Instructions:
1. Upload your project to PythonAnywhere (e.g., via git clone or zip upload)
2. In PythonAnywhere's Web tab, set the WSGI config file to point to this file
3. Set your virtualenv path
4. Add a .env file in your project directory with your secrets

The WSGI config file on PythonAnywhere will look like:

    import sys
    path = '/home/YOUR_USERNAME/CS3305-2026-Team-9'
    if path not in sys.path:
        sys.path.insert(0, path)
    from wsgi import application
"""

import os
import sys

# Ensure the project directory is on the Python path
project_dir = os.path.dirname(os.path.abspath(__file__))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

# Change working directory to the project directory
# (ensures relative paths like 'uploads/' and 'sharelink.db' work correctly)
os.chdir(project_dir)

from app import app as application
