
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django_asgi_app = get_asgi_application()

# from channels.routing import ProtocolTypeRouter, URLRouter
# # routing WebSocket ditambahkan nanti kalau udah ada consumer

# application = ProtocolTypeRouter({
#     "http": django_asgi_app,
#     # "websocket": ... (isi nanti kalau udah ada fitur real-time)
# })