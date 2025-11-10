import os
import logging
import functools
from .exceptions import *


import logging

logger = logging.getLogger('cdp')


class GenericAttr:
    def __init__(self, name, session):
        self.__dict__['name'] = name
        self.__dict__['session'] = session

    def __getattr__(self, item):
        method_name = "%s.%s" % (self.name, item)
        event_listener = self.session.get_listener(method_name)

        if event_listener:
            return event_listener

        return functools.partial(self.session.call_method, method_name)

    def __setattr__(self, key, value):
        self.session.set_listener("%s.%s" % (self.name, key), value)


class CDPSession:
    def __init__(self, session_id: str or None, target):
        self.debug = os.getenv("DEBUG", False)
        self.session_id = session_id

        self.target = target

        self.event_handlers = {}
        

    def __getattr__(self, item):
        attr = GenericAttr(item, self)
        setattr(self, item, attr)
        return attr

    def call_method(self, _method, *args, **kwargs):

        if args:
            raise CallMethodException("the params should be key=value format")

        timeout = kwargs.pop("_timeout", None)
        payload = {"method": _method, "params": kwargs}
        if self.session_id:
            payload['sessionId'] = self.session_id

        result = self.target._send(payload, timeout=timeout)
        if 'result' not in result and 'error' in result:
            logging.warn("%s error: %s" %
                         (_method, result['error']['message']))
            raise CallMethodException("calling method: %s error: %s" % (
                _method, result['error']['message']))

        return result['result']

    def set_listener(self, event, callback):
        if not callback:
            return self.event_handlers.pop(event, None)

        if not callable(callback):
            raise RuntimeException("callback should be callable")

        self.event_handlers[event] = callback
        return True

    def get_listener(self, event):
        return self.event_handlers.get(event, None)

    def del_all_listeners(self):
        self.event_handlers = {}
        return True

    def __str__(self):
        return "<CDPSession [%s-%s]>" % (self.target.id, self.session_id)

    __repr__ = __str__
