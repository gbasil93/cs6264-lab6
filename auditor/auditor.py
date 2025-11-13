import logging
import logging.config
import subprocess
import threading
from collections import defaultdict

import pandas as pd
import typer

import pychrome
from event_handler import Handler
from graph import LOG_DIR
from post_process import extract_edges

app = typer.Typer()

logging_level = logging.INFO
logger = logging.getLogger("auditor")
logger.setLevel(logging_level)

DEFAULT_CHROME_OPTIONS = {
    "--remote-debugging-port=9222",
    "--user-data-dir=remote-debug-profile",
    "--enable-devtools-experiments",
}


class Auditor:
    def __init__(
        self,
        url="http://127.0.0.1:9222",
        headless=False,
        chrome="google-chrome",
        opts: set = None,
        init_page: str = None,
    ):
        # clean logs
        [log.unlink() for log in LOG_DIR.iterdir()]

        self.url = url
        self.init_page = init_page
        opts = opts or DEFAULT_CHROME_OPTIONS
        if headless:
            opts.add("--headless")
        self.browser_process = subprocess.Popen([chrome, *opts, "about:blank"])
        self.browser: pychrome.Browser = pychrome.Browser(url=self.url)

        self.target_map = {}
        self.event_handlers = []
        self._start_daemon(self._target_monitor)
        self._running_loop()

    def _running_loop(self):
        try:
            print("Auditor is running. Press Ctrl-C to exit.\n")
            while True:
                ...
        except KeyboardInterrupt:
            print("Received Ctrl-C. Exiting Auditor...")
            self.browser_process.kill()
            neo4j_msgs = defaultdict(list)
            for event_handler in self.event_handlers:
                for filename in event_handler.neo4j_msgs:
                    neo4j_msgs[filename] += event_handler.neo4j_msgs[filename]
            for filename in neo4j_msgs:
                df = pd.DataFrame(neo4j_msgs[filename]).drop_duplicates()
                df.to_csv(filename, sep="\t", index=False, encoding="utf-8")
            extract_edges(LOG_DIR)

    def _start_daemon(self, worker):
        worker_th = threading.Thread(target=worker)
        worker_th.daemon = True
        worker_th.start()

    def _target_monitor(self):
        self.browser.session.Target.attachedToTarget = self._handle_new_target
        self.browser.session.Target.setAutoAttach(
            autoAttach=True, waitForDebuggerOnStart=True, flatten=True
        )

        if self.init_page:
            logger.info("open a new tab")
            target = self.browser.new_target()
            logger.info("navigate to a page")
            target.session.Page.navigate(url=self.init_page)

    def _handle_new_target(self, sessionId: str, targetInfo, waitingForDebugger: bool):
        logger.info(
            'a new target was attached. URL: "%s". SESSION: "%s"',
            targetInfo["url"],
            sessionId,
        )
        cdp = self.browser.target.get_or_create_session(sessionId)
        if targetInfo["type"] not in ["page", "tab", "iframe"]:
            logger.warning("Bad type!!", targetInfo["type"])
            if waitingForDebugger:
                cdp.Runtime.runIfWaitingForDebugger()
            return

        # self.session_map[sessionId] = tab
        logger.info("add hooks to this new target")
        cdp.Target.attachedToTarget = self._handle_new_target
        self.add_event_handler(cdp)
        logger.info("#Added event handler")
        cdp.Target.setAutoAttach(
            autoAttach=True, waitForDebuggerOnStart=True, flatten=True
        )
        logger.info("#Set autoattach to true")
        cdp.Debugger.enable()
        logger.info("#Debugger enabled")
        cdp.Page.enable()
        logger.info("#Page enabled")
        cdp.Network.enable()
        logger.info("#Network enabled")

        # Continue to run
        logger.info("continue this target")
        if waitingForDebugger:
            cdp.Runtime.runIfWaitingForDebugger()

    def add_event_handler(self, cdp: pychrome.CDPSession):
        event_handler = Handler()
        self.event_handlers.append(event_handler)
        cdp.Network.requestWillBeSent = event_handler.handle_request_will_be_sent
        cdp.Network.responseReceived = event_handler.handle_response_received
        cdp.Page.frameAttached = event_handler.handle_frame_attached
        cdp.Page.frameNavigated = event_handler.handle_frame_navigated
        cdp.Page.downloadWillBegin = event_handler.handle_download_begin
        cdp.Page.windowOpen = event_handler.handle_window_open
        cdp.Debugger.scriptParsed = event_handler.handle_script_parsed


@app.command()
def run(headless: bool = False, init_page: str = None):
    auditor = Auditor(headless=headless, init_page=init_page)


if __name__ == "__main__":
    app()
