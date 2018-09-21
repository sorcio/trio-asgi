from functools import partial

import trio

from .h11server import h11_serve_asgi


async def serve_tcp(application, host, port):
    serve_func = partial(h11_serve_asgi, application)
    await trio.serve_tcp(serve_func, host=host, port=port)


def run(application, host=None, port=None):
    """ Run the given ASGI application.
    """
    
    host = str(host) if host else 'localhost'
    port = int(port) if port else 8080
    
    if host == 'localhost':
        host = '127.0.0.1'
    
    print("Running {} on http://{}:{} (CTRL + C to quit)".format(__name__, host, port))
    try:
        trio.run(serve_tcp, application, host, port)
    except KeyboardInterrupt:
        pass
