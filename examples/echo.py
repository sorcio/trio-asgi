import json

import trio
from trio_web import serve_tcp


class TrioAsgiApplication:
    def __init__(self, scope):
        self.scope = scope

    async def __call__(self, receive, send):
        body = bytearray()
        while True:
            request = await receive()
            body += request.get('body', b'')
            print('body chunk:', body)
            if not request.get('more_body', False):
                break
        await send({
            'type': 'http.response.start',
            'status': 200,
            'headers': [
                [b'content-type', b'text/plain'],
            ],
        })
        document = {
            "method": self.scope['method'],
            "target": self.scope['path'],
            "headers": [(name.decode("latin1"), value.decode("latin1"))
                        for (name, value) in self.scope['headers']],
            "body": body.decode('latin1'),
        }
        data = json.dumps(document, ensure_ascii=True, indent=4).encode('ascii')
        await send({
            'type': 'http.response.body',
            'body': data,
        })


if __name__ == '__main__':
    trio.run(serve_tcp, TrioAsgiApplication, 'localhost', 18888)
