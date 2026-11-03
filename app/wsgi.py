"""Production WSGI entry point. Run one worker: jobs share in-process state."""

from core.hosting import seed_demo
from core.storage import Repository
from app.main import create_app

seed_demo(Repository())
application = create_app(auto_run=False)
server = application.server
