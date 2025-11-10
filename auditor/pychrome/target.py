import os
import logging
import threading
import websocket
from .exceptions import *
from .cdp import CDPSession

try:
    import Queue as queue
except ImportError:
    import queue
import json

import logging
logger = logging.getLogger('target')


class Target:
    def __init__(self, **kwargs):
        """
        {
            "description": "",
            "devtoolsFrontendUrl": "/devtools/inspector.html?ws=localhost:9222/devtools/page/DAB7FB6187B554E10B0BD18821265734",
            "id": "DAB7FB6187B554E10B0BD18821265734",
            "title": "Yahoo",
            "type": "page",
            "url": "https://www.yahoo.com/",
            "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/DAB7FB6187B554E10B0BD18821265734"
        } 
        """
        self.id = kwargs.get("id")
        self.type = kwargs.get("type")
        self.debug = os.getenv("DEBUG")
        self._connected = False
        self._websocket_url = kwargs.get("webSocketDebuggerUrl")
        self._kwargs = kwargs
        self._ws = None
        self._cur_id = 1000
        self.sessions = {}
        self.method_results = {}
        self._connect()

        self._recv_th = threading.Thread(target=self._recv_loop)
        self._recv_th.daemon = True
        self._handle_event_th = threading.Thread(
            target=self._handle_event_loop)
        self._handle_event_th.daemon = True

        self._stopped = threading.Event()
        self.event_queue = queue.Queue()

        self._recv_th.start()
        self._handle_event_th.start()

    def _send(self, message, timeout=None):
        if 'id' not in message:
            self._cur_id += 1
            message['id'] = self._cur_id

        message_json = json.dumps(message)

        if self.debug:  # pragma: no cover
            print("SEND > %s to %s\n" % (message_json, self._websocket_url))

        if not isinstance(timeout, (int, float)) or timeout > 1:
            q_timeout = 1
        else:
            q_timeout = timeout / 2.0
        message_key = message['id']
        try:
            self.method_results[message_key] = queue.Queue()

            # just raise the exception to user
            self._ws.send(message_json)

            while not self._stopped.is_set():
                try:
                    if isinstance(timeout, (int, float)):
                        if timeout < q_timeout:
                            q_timeout = timeout

                        timeout -= q_timeout

                    return self.method_results[message_key].get(timeout=q_timeout)
                except queue.Empty:
                    if isinstance(timeout, (int, float)) and timeout <= 0:
                        raise TimeoutException(
                            "Calling %s timeout" % message['method'])

                    continue

            raise UserAbortException(
                "User abort, call stop() when calling %s" % message['method'])
        finally:
            self.method_results.pop(message_key, None)

    def _recv_loop(self):
        while not self._stopped.is_set():
            try:
                self._ws.settimeout(1)
                message_json = self._ws.recv()
                message = json.loads(message_json)
            except websocket.WebSocketTimeoutException:
                continue
            except (websocket.WebSocketException, OSError):
                if not self._stopped.is_set():
                    logger.error("websocket exception", exc_info=True)
                    self._stopped.set()
                return

            if self.debug:  # pragma: no cover
                print('< RECV %s from %s\n' % (message_json, self._websocket_url))

            if "method" in message:
                self.event_queue.put(message)

            elif "id" in message:
                message_key = message["id"]
                if message_key in self.method_results:
                    self.method_results[message_key].put(message)
            else:  # pragma: no cover
                logging.warn("unknown message: %s" % message)

    def _handle_event_loop(self):
        while not self._stopped.is_set():
            try:
                event = self.event_queue.get(timeout=1)
            except queue.Empty:
                continue
            params = event['params']
            session_id = event.get('sessionId')
            session = self.sessions[session_id] # we should have all event listeners for this session

            if event['method'] in session.event_handlers:
                try:
                    session.event_handlers[event['method']](**params)
                except Exception as e:
                    logger.error("callback %s exception" %
                                 event['method'], exc_info=True)

            self.event_queue.task_done()

    def get_or_create_session(self, session_id: str or None) -> CDPSession:
        if session_id not in self.sessions:
            self.sessions[session_id] = CDPSession(session_id, self)
        return self.sessions[session_id]

    def _connect(self):
        if self._connected:
            return False
        if not self._websocket_url:
            raise RuntimeException(
                "Already has another client connect to this target")
        self._connected = True
        self._ws = websocket.create_connection(
            self._websocket_url, enable_multithread=True, suppress_origin=True)
        self.session = CDPSession(None, self)
        self.sessions[None] = self.session
        return True

    def stop(self):
        if not self._connected:
            raise RuntimeException("Target is not running")
        if self._ws:
            self._ws.close()
        self._stopped.set()
        self._recv_th.join()
        self._handle_event_th.join()
        return True

    def __str__(self):
        return "<Target [%s]>" % self.id

    __repr__ = __str__
