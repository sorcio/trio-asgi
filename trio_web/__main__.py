import sys
import importlib
from functools import partial

import trio

from trio_web import h11_serve_asgi


appliction_description = sys.argv[1]
modulename, _, name = appliction_description.partition(':')

host, port = 'localhost', 8000
for arg in sys.argv[2:]:
    if arg.startswith('--host='):
        host = arg.split('=')[-1]
    elif arg.startswith('--port='):
        port = int(arg.split('=')[-1])

# moduleparts = modulename.split('.')
# m = importlib.import_module(moduleparts[-1], '.'.join(moduleparts[:-1]))
m = importlib.import_module(modulename)
a = getattr(m, name or 'Application')


async def serve_http(application, host, port):
    serve_func = partial(h11_serve_asgi, application)
    await trio.serve_tcp(serve_func, host=host, port=port)


# from trioweb import 
trio.run(serve_http, a, host, port)
