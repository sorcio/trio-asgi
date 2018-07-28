
class App():
    def __init__(self, scope):
        self.scope = scope

    async def __call__(self, receive, send):
        await send({
            'type': 'http.response.start',
            'status': 200,
            'headers': [
                [b'content-type', b'text/plain'],
            ],
        })
        await send({
            'type': 'http.response.body',
            'body': b'Hello, world!',
        })


if __name__ == '__main__':
    import trio
    from trio_web import serve_tcp as serve_http  # todo: why is it called serve_tcp
    trio.run(serve_http, App, 'localhost', 8000)
