from functools import partial

import trio

from .h11server import h11_serve_asgi


async def serve_tcp(application, host, port):
    serve_func = partial(h11_serve_asgi, application)
    await trio.serve_tcp(serve_func, host=host, port=port)
