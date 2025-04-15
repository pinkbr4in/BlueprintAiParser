# celery_app.py
import os
from celery import Celery
from config import config

config_name = os.environ.get('FLASK_ENV', 'production')
# Ensure URLs are retrieved safely, potentially falling back to defaults
active_config = config.get(config_name, config['default'])
broker_url = getattr(active_config, 'CELERY_BROKER_URL', 'redis://localhost:6379/0')
result_backend = getattr(active_config, 'CELERY_RESULT_BACKEND', 'redis://localhost:6379/1')

celery = Celery(
    # Use a meaningful name, like the app name, often __name__ works if structure is simple
    # Or explicitly 'app' or 'BP_Parser_WebApp'
    'BP_Parser_WebApp', # Changed from __name__ to be more explicit
    broker=broker_url,
    backend=result_backend,
    # --- ADD THIS LINE ---
    # Tells Celery to look for tasks in the 'tasks.py' module relative to this app.
    # Assumes tasks.py is in the same directory or discoverable in the Python path.
    include=['tasks']
    # --- END ADD ---
)

# Optional: Define task routing, serialization settings, etc. here if needed globally
# celery.conf.update(
#    task_serializer='json',
#    accept_content=['json'],  # Add other serializers if needed
#    result_serializer='json',
#    timezone='Europe/Berlin', # Example timezone
#    enable_utc=True,
# )

# Context task setup will happen in app.py