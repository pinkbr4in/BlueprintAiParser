# wsgi.py
from app import create_app

# This is the entry point for the WSGI server
application = create_app('production')

#if __name__ == "__main__":
#     application.run()