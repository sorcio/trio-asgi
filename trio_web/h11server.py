# HTTP/1.1 implementation based on h11
# Derived from work by Nathaniel J. Smith <njs@pobox.com> and other contributors
# https://github.com/python-hyper/h11/blob/33c5282340b61ddea0dc00a16b6582170d822d81/examples/trio-server.py

from itertools import count
import logging
from wsgiref.handlers import format_date_time

import trio
import h11

MAX_RECV = 2 ** 16
TIMEOUT = 10

################################################################
# I/O adapter: h11 <-> trio
################################################################

# The core of this could be factored out to be usable for trio-based clients
# too, as well as servers. But as a simplified pedagogical example we don't
# attempt this here.
class TrioHTTPWrapper:
    _next_id = count()

    def __init__(self, stream):
        self.stream = stream
        self.conn = h11.Connection(h11.SERVER)
        # Our Server: header
        self.ident = " ".join([
            "trio-asgi/0.0.1",
            h11.PRODUCT_ID,
        ]).encode("ascii")
        # A unique id for this connection, to include in debugging output
        # (useful for understanding what's going on if there are multiple
        # simultaneous clients).
        self._obj_id = next(TrioHTTPWrapper._next_id)

    async def send(self, event):
        # The code below doesn't send ConnectionClosed, so we don't bother
        # handling it here either -- it would require that we do something
        # appropriate when 'data' is None.
        assert type(event) is not h11.ConnectionClosed
        data = self.conn.send(event)
        await self.stream.send_all(data)

    async def _read_from_peer(self):
        if self.conn.they_are_waiting_for_100_continue:
            self.info("Sending 100 Continue")
            go_ahead = h11.InformationalResponse(
                status_code=100,
                headers=self.basic_headers())
            await self.send(go_ahead)
        try:
            data = await self.stream.receive_some(MAX_RECV)
        except ConnectionError:
            # They've stopped listening. Not much we can do about it here.
            data = b""
        self.conn.receive_data(data)

    async def next_event(self):
        while True:
            event = self.conn.next_event()
            if event is h11.NEED_DATA:
                await self._read_from_peer()
                continue
            return event

    async def shutdown_and_clean_up(self):
        # When this method is called, it's because we definitely want to kill
        # this connection, either as a clean shutdown or because of some kind
        # of error or loss-of-sync bug, and we no longer care if that violates
        # the protocol or not. So we ignore the state of self.conn, and just
        # go ahead and do the shutdown on the socket directly. (If you're
        # implementing a client you might prefer to send ConnectionClosed()
        # and let it raise an exception if that violates the protocol.)
        #
        try:
            # self.sock.shutdown(SHUT_WR)
            await self.stream.send_eof()
        except (trio.ClosedStreamError, trio.BrokenStreamError):
            # They're already gone, nothing to do
            return
        # Wait and read for a bit to give them a chance to see that we closed
        # things, but eventually give up and just close the socket.
        # XX FIXME: possibly we should set SO_LINGER to 0 here, so
        # that in the case where the client has ignored our shutdown and
        # declined to initiate the close themselves, we do a violent shutdown
        # (RST) and avoid the TIME_WAIT?
        # it looks like nginx never does this for keepalive timeouts, and only
        # does it for regular timeouts (slow clients I guess?) if explicitly
        # enabled ("Default: reset_timedout_connection off")
        with trio.move_on_after(TIMEOUT):
            try:
                while True:
                    # Attempt to read until EOF
                    got = await self.stream.receive_some(MAX_RECV)
                    if not got:
                        break
            finally:
                await self.stream.aclose()

    def basic_headers(self):
        # HTTP requires these headers in all responses (client would do
        # something different here)
        return [
            ("Date", format_date_time(None).encode("ascii")),
            ("Server", self.ident),
        ]

    def info(self, *args):
        # Little debugging method
        logging.debug("{}: {}".format(self._obj_id,
            ' '.join('%s' for i in range(len(args)))), *args)


################################################################
# Server main loop
################################################################

# General theory:
#
# If everything goes well:
# - we'll get a Request
# - our response handler will read the request body and send a full response
# - that will either leave us in MUST_CLOSE (if the client doesn't
#   support keepalive) or DONE/DONE (if the client does).
#
# But then there are many, many different ways that things can go wrong
# here. For example:
# - we don't actually get a Request, but rather a ConnectionClosed
# - exception is raised from somewhere (naughty client, broken
#   response handler, whatever)
#   - depending on what went wrong and where, we might or might not be
#     able to send an error response, and the connection might or
#     might not be salvagable after that
# - response handler doesn't fully read the request or doesn't send a
#   full response
#
# But these all have one thing in common: they involve us leaving the
# nice easy path up above. So we can just proceed on the assumption
# that the nice easy thing is what's happening, and whenever something
# goes wrong do our best to get back onto that path, and h11 will keep
# track of how successful we were and raise new errors if things don't work
# out.
async def http_serve(request_handler, sock):
    wrapper = TrioHTTPWrapper(sock)
    while True:
        assert wrapper.conn.states == {
            h11.CLIENT: h11.IDLE, h11.SERVER: h11.IDLE}

        try:
            with trio.move_on_after(TIMEOUT):
                wrapper.info("Server main loop waiting for request")
                event = await wrapper.next_event()
                wrapper.info("Server main loop got event:", event)
                if type(event) is h11.Request:
                    await request_handler(wrapper, event)
        except Exception as exc:
            wrapper.info("Error during response handler:", exc)
            await maybe_send_error_response(wrapper, exc)

        if wrapper.conn.our_state is h11.MUST_CLOSE:
            wrapper.info("connection is not reusable, so shutting down")
            await wrapper.shutdown_and_clean_up()
            return
        else:
            try:
                wrapper.info("trying to re-use connection")
                wrapper.conn.start_next_cycle()
            except h11.LocalProtocolError:
                wrapper.info("not in a reusable state")
                return
            except h11.ProtocolError:
                states = wrapper.conn.states
                wrapper.info("unexpected state", states, "-- bailing out")
                await maybe_send_error_response(
                    wrapper,
                    RuntimeError("unexpected state {}".format(states)))
                await wrapper.shutdown_and_clean_up()
                return


################################################################
# Attempt at an ASGI-compatible interface
################################################################

async def h11_serve_asgi(application, sock):
    async def request_adapter(wrapper, event):
        scope = {
            'type': 'http',
            'http_version': '1.1',
            'method': event.method.decode('ascii').upper(),
            'scheme': 'http',
            'path': event.target.decode('utf-8'),
            'query_string': b'',
            'root_path': '',
            'headers': event.headers,
            # 'client': None,
            # 'server': None,
        }
        application_instance = application(scope)
        request_received = False
        send_headers = wrapper.basic_headers()
        send_status = None
        headers_sent = False
        chunked = False

        async def receive():
            nonlocal request_received
            if request_received:
                raise ValueError('request was already received')
            event = await wrapper.next_event()
            if type(event) is h11.EndOfMessage:
                request_received = True
                return {
                    'type': 'http.request',
                    'body': b'',
                    'more_body': False,
                }
            elif type(event) is h11.Data:
                return {
                    'type': 'http.request',
                    'body': event.data,
                    'more_body': True,
                }
            else:
                raise RuntimeError('unexpected event')

        async def send(evt):
            if evt['type'] == 'http.response.start':
                nonlocal send_status
                send_status = evt['status']
                send_headers.extend(evt['headers'])
            elif evt['type'] == 'http.response.body':
                nonlocal headers_sent, chunked
                body = evt.get('body', b'')
                more_body = evt.get('more_body', False)
                chunked |= more_body
                if not headers_sent:
                    content_length = len(body)
                    if not chunked:
                        send_headers.append(('content-length', str(content_length)))
                    res = h11.Response(status_code=send_status, headers=send_headers)
                    await wrapper.send(res)
                    headers_sent = True
                await wrapper.send(h11.Data(data=body))
            elif evt['type'] == 'http.disconnect':
                pass
            else:
                return ValueError(evt['type'])

        await application_instance(receive, send)

    await http_serve(request_adapter, sock)


################################################################
# Helpers
################################################################

# Helper function
async def send_simple_response(wrapper, status_code, content_type, body):
    wrapper.info("Sending", status_code,
                 "response with", len(body), "bytes")
    headers = wrapper.basic_headers()
    headers.append(("Content-Type", content_type))
    headers.append(("Content-Length", str(len(body))))
    res = h11.Response(status_code=status_code, headers=headers)
    await wrapper.send(res)
    await wrapper.send(h11.Data(data=body))
    await wrapper.send(h11.EndOfMessage())


async def maybe_send_error_response(wrapper, exc):
    # If we can't send an error, oh well, nothing to be done
    wrapper.info("trying to send error response...")
    if wrapper.conn.our_state not in {h11.IDLE, h11.SEND_RESPONSE}:
        wrapper.info("...but I can't, because our state is",
                     wrapper.conn.our_state)
        return
    try:
        if isinstance(exc, h11.RemoteProtocolError):
            status_code = exc.error_status_hint
        else:
            status_code = 500
        body = str(exc).encode("utf-8")
        await send_simple_response(wrapper,
                                   status_code,
                                   "text/plain; charset=utf-8",
                                   body)
    except Exception as exc:
        wrapper.info("error while sending error response:", exc)
