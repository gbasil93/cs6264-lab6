#! /usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import unicode_literals

import requests

from .exceptions import *


from .target import Target
from .cdp import CDPSession
import time


class Browser:
    _all_targets = {}

    def __init__(self, url="http://127.0.0.1:9222"):
        self.dev_url = url
        if self.dev_url not in self._all_targets:
            self._targets = self._all_targets[self.dev_url] = {}
        else:
            self._targets = self._all_targets[self.dev_url]
        self.target = None
        self.session = None

        self._create_browser_target()


    def _create_browser_target(self):
        connected = False
        timer = 0
        while not connected:
            try:
                kwargs = self.version()
                self.target = Target(**kwargs, type="browser", id="0")
                self.session = self.target.session
                connected = True
            except requests.exceptions.ConnectionError:
                time.sleep(1)
                timer += 10

    def new_target(self, url=None, timeout=None):
        url = url or ""
        rp = requests.put(
            "%s/json/new?%s" % (self.dev_url, url), json=True, timeout=timeout
        )
        target = Target(**rp.json())
        self._targets[target.id] = target
        return target

    def list_target(self, timeout=None):
        rp = requests.get("%s/json" % self.dev_url, json=True, timeout=timeout)
        targets_map = {}
        for target_json in rp.json():
            if target_json["type"] != "page":  # pragma: no cover
                continue

            if (
                target_json["id"] in self._targets
                and self._targets[target_json["id"]].active == True
            ):
                targets_map[target_json["id"]] = self._targets[target_json["id"]]
            else:
                targets_map[target_json["id"]] = Target(**target_json)

        self._targets = targets_map
        return list(self._targets.values())

    def activate_target(self, target_id, timeout=None):
        if isinstance(target_id, Target):
            target_id = target_id.id

        rp = requests.get(
            "%s/json/activate/%s" % (self.dev_url, target_id), timeout=timeout
        )
        return rp.text

    def close_target(self, target_id, timeout=None):
        if isinstance(target_id, Target):
            target_id = target_id.id

        target = self._targets.pop(target_id, None)
        if target and target.active == True:  # pragma: no cover
            target.stop()

        rp = requests.get("%s/json/close/%s" % (self.dev_url, target_id), timeout=timeout)
        return rp.text

    def version(self, timeout=None):
        rp = requests.get("%s/json/version" % self.dev_url, json=True, timeout=timeout)
        return rp.json()
