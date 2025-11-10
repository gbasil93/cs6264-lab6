from graph import *
import logging
from collections import defaultdict

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

LOGGING_TO_TERMINAL = True


def log_event_handler(func):
    def wrapper(*args, **kwargs):
        logger.info(f"\n##### Running handler {func.__name__} #####\n")
        func(*args, **kwargs)

    return wrapper


class Handler:
    # need to maintain a static frame objects
    frame_id_map: {str: Frame} = {}  # frame_id -> frame_node
    resource_map: {str: Resource} = {}  # md5(url) -> resource_node
    attached_frame_map: {
        str: {"parent_frame": str, "actor": dict}
    } = {}  # child_frame_id -> parent_frame_id, stack_trace
    script_map: {str: Script} = {}  # script_node.id -> script_node
    frame_map: {str: Frame} = {}  # frame_node.id -> frame_node
    request_map: {str: Node} = {}  # request.id -> request initiator
    opened_window_map: {str: Window} = {}  # md5(url) -> window_node

    def __init__(self) -> None:
        self.current_frame = None
        self.neo4j_msgs = defaultdict(list)

    def _get_current_frame(self, frame_id: str, loader_id: str = "") -> Frame:
        frame = Frame(frame_id, loader_id)
        if loader_id:
            return Handler.frame_map.get(frame.id, frame)
        return Handler.frame_id_map.get(frame_id, frame)

    def _add_neo4j_msg(self, filename, msg):
        self.neo4j_msgs[filename].append(msg)

    def log_node(self, node):
        if LOGGING_TO_TERMINAL:
            print(node)

    def log_edge(self, edge):
        if LOGGING_TO_TERMINAL:
            print(edge)

    @log_event_handler
    def handle_frame_navigated(self, **kwargs):
        # {
        #     "frame": {
        #         "id": "CC32444DB8AB53750805953982BE6089",
        #         "loaderId": "6AD7F9CF4BB291D2F3B4196D8AB19374",
        #         "url": "chrome://new-tab-page/",
        #         "domainAndRegistry": "",
        #         "securityOrigin": "chrome://new-tab-page",
        #         "mimeType": "text/html",
        #         "adFrameStatus": {"adFrameType": "none"},
        #         "secureContextType": "Secure",
        #         "crossOriginIsolatedContextType": "NotIsolated",
        #         "gatedAPIFeatures": [],
        #     },
        #     "type": "Navigation",
        # }

        msg = kwargs["frame"]
        frame_node = Frame.parse(msg)
        Handler.frame_id_map[msg["id"]] = frame_node
        Handler.frame_map[frame_node.id] = frame_node

        self._add_neo4j_msg(LoggerFile.FrameNode, frame_node.to_json())
        if parent_frame_id := msg.get("parentId"):
            parent_frame = Handler.frame_id_map[parent_frame_id]
            if msg["id"] in Handler.attached_frame_map:
                attach_info = Handler.attached_frame_map[msg["id"]]
                actor = attach_info["actor"]
                attach_edge = parent_frame.add_edge(frame_node, EdgeType.attach)
                self.log_edge(attach_edge)
                self._add_neo4j_msg(LoggerFile.FrameEdge, attach_edge)
                self._add_neo4j_msg(
                    LoggerFile.FrameEdge,
                    parent_frame.add_edge(frame_node, EdgeType.navigate),
                )
                if actor:
                    script_id = actor["scriptId"]
                    script = Script(script_id, parent_frame.id)
                    create_edge = script.add_edge(frame_node, EdgeType.create)
                    self.log_edge(create_edge)
                    self._add_neo4j_msg(LoggerFile.FrameEdge, create_edge)

        # If the frame is a page (the blank page upon starting a new tab).
        if not self.current_frame:
            self.log_node(self.current_frame)
            if (window_key := md5(msg["url"])) in Handler.opened_window_map:
                window_node = Handler.opened_window_map[window_key]
                window_edge = window_node.add_edge(frame_node, EdgeType.load)
                self._add_neo4j_msg(LoggerFile.WindowEdge, window_edge)

        elif (
            self.current_frame.property["frame_id"] == frame_node.property["frame_id"]
        ):  # same-tab navigation
            nav_edge = self.current_frame.add_edge(
                frame_node, EdgeType.navigate, {"type": kwargs["type"]}
            )
            self.log_node(frame_node)
            self.log_edge(nav_edge)
            self._add_neo4j_msg(LoggerFile.FrameEdge, nav_edge)
        self.current_frame = frame_node

    @log_event_handler
    def handle_request_will_be_sent(self, **kwargs):
        """
            {
                "requestId": "28086.125",
                "loaderId": "A52232418E9F8926EF9293BFD91FCCE2",
                "documentURL": "chrome://new-tab-page/",
                "request": {
                        "url": "chrome://resources/mojo/mojo/public/mojom/base/big_buffer.mojom-webui.js",
                        "method": "GET",
                        "headers": {
                                "Referer": "",
                                "Origin": "chrome://new-tab-page",
                                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
                        },
                        "mixedContentType": "none",
                        "initialPriority": "High",
                        "referrerPolicy": "strict-origin-when-cross-origin",
                        "isSameSite": false
                },
                "timestamp": 241295.479136,
                "wallTime": 1691606823.169876,
                "initiator": {
                        "type": "script",
                        "url": "chrome://resources/mojo/mojo/public/mojom/base/string16.mojom-webui.js",
                        "lineNumber": 3,
                        "columnNumber": 157
                },
                "redirectHasExtraInfo": false,
                "type": "Script",
                "frameId": "489EDEAA21AA2C03D9BEBC6CB82C13B7",
                "hasUserGesture": false
        }
        """

        """
        Initiator Types:
            Parser - Chrome's HTML parser initiated the request.
            Script - A script initiated the request.
            Other - Some other process or action initiated the request, such as the user navigating to a page via a link, or by entering a URL in the address bar.
        """
        initiator = kwargs["initiator"]
        current_frame = self.current_frame
        if "frameId" in kwargs:
            current_frame = self._get_current_frame(
                kwargs["frameId"], kwargs["loaderId"]
            )

        logger_file = LoggerFile.FrameEdge
        src_node = None
        if initiator["type"] == "script":
            # Initiator JavaScript stack trace, set for Script only
            if stack := initiator["stack"]:
                call_frames = stack["callFrames"]
                if len(call_frames):
                    latest_frame = call_frames[0]
                    script_id = latest_frame["scriptId"]
                    frame_id = current_frame.id
                    src_node = Script(script_id, frame_id)
                    logger_file = LoggerFile.ScriptRequestEdge
                else:
                    logger.warning("Stack call frames is empty.")
            else:
                logger.warning("Stack attribute not found.")
        elif initiator["type"] in {"parser", "other"}:
            src_node = current_frame
        else:  # We don't need to consider other initiator types
            return

        msg = kwargs["request"]
        resource_type = kwargs.get("type")
        resource_node = Resource.parse(msg, resource_type)
        self.resource_map[md5(resource_node.get("url"))] = resource_node

        request_edge = src_node.add_edge(
            resource_node,
            EdgeType.request,
            {
                "wallTime": kwargs["wallTime"],
                "hasUserGesture": kwargs["hasUserGesture"],
                "method": kwargs["request"]["method"],
                "referrerPolicy": kwargs["request"]["referrerPolicy"],
            },
        )
        Handler.request_map[kwargs["requestId"]] = src_node
        self.log_edge(request_edge)
        self._add_neo4j_msg(logger_file, request_edge)

    @log_event_handler
    def handle_response_received(self, **kwargs):
        # {
        #     "requestId": "26660.208",
        #     "loaderId": "050A203556530800A634F3B2E5989E97",
        #     "timestamp": 260364.251126,
        #     "type": "Script",
        #     "response": {
        #         "url": "https://github.githubassets.com/assets/app_assets_modules_github_ref-selector_ts-0e2b12902d39.js",
        #         "status": 200,
        #         "statusText": "",
        #         "headers": {
        #             "x-fastly-request-id": "e81a17d4363241da2018969dc88b74c5021dd318",
        #             "date": "Wed, 09 Aug 2023 16:43:39 GMT",
        #             "content-encoding": "gzip",
        #             "via": "1.1 varnish",
        #             "age": "4850760",
        #             "x-cache": "HIT",
        #             "content-length": "3430",
        #             "x-served-by": "cache-iad-kiad7000158-IAD",
        #             "last-modified": "Wed, 14 Jun 2023 00:00:21 GMT",
        #             "server": "AmazonS3",
        #             "etag": '"36131d994b708536be50b640fb64c7b5"',
        #             "vary": "Accept-Encoding",
        #             "content-type": "application/javascript",
        #             "access-control-allow-origin": "*",
        #             "cache-control": "public, max-age=31536000",
        #             "accept-ranges": "bytes",
        #             "x-cache-hits": "8864",
        #         },
        #         "mimeType": "application/javascript",
        #         "connectionReused": False,
        #         "connectionId": 0,
        #         "remoteIPAddress": "185.199.109.154",
        #         "remotePort": 443,
        #         "fromDiskCache": True,
        #         "fromServiceWorker": False,
        #         "fromPrefetchCache": False,
        #         "encodedDataLength": 0,
        #         "timing": {
        #             "requestTime": 258641.579434,
        #             "proxyStart": -1,
        #             "proxyEnd": -1,
        #             "dnsStart": -1,
        #             "dnsEnd": -1,
        #             "connectStart": -1,
        #             "connectEnd": -1,
        #             "sslStart": -1,
        #             "sslEnd": -1,
        #             "workerStart": -1,
        #             "workerReady": -1,
        #             "workerFetchStart": -1,
        #             "workerRespondWithSettled": -1,
        #             "sendStart": 0.03,
        #             "sendEnd": 0.03,
        #             "pushStart": 0,
        #             "pushEnd": 0,
        #             "receiveHeadersEnd": 0.25,
        #         },
        #         "responseTime": 1691599419387.4,
        #         "protocol": "h2",
        #         "alternateProtocolUsage": "unspecifiedReason",
        #         "securityState": "unknown",
        #     },
        #     "hasExtraInfo": False,
        #     "frameId": "29E979082EAADCADD9CE4B4447F9972B",
        # }

        response = kwargs["response"]
        url = response["url"]

        if md5(url) not in self.resource_map:
            logger.warning(
                f"md5 of url {url} in the response was not found in logs.\n"  # Response message:\n{kwargs}\n"
            )
            return

        resource_node = self.resource_map[md5(url)]

        if resource_node.get("type") == "Unknown":
            logger.warning(f"Fill <type> property of resource {url}")
            resource_node.add_property(type=kwargs["type"])

        if (request_id := kwargs["requestId"]) not in Handler.request_map:
            logger.warning(
                f"requestID {request_id} in the response was not found in logs.\n"  # Response message:\n{kwargs}\n"
            )
            return

        initiator = Handler.request_map[request_id]
        response_edge = resource_node.add_edge(
            initiator,
            EdgeType.respond,
            {
                "status": response["status"],
                "mimeType": response["mimeType"],
                "remoteIpAddress": response.get("remoteIpAddress", "Unknown"),
                "fromServiceWorker": response["fromServiceWorker"],
            },
        )
        self.log_edge(response_edge)
        self._add_neo4j_msg(LoggerFile.ResourceNode, resource_node.to_json())
        self._add_neo4j_msg(LoggerFile.ResourceEdge, response_edge)

    @log_event_handler
    def handle_script_parsed(self, **kwargs):
        # {
        #     "scriptId": "224",
        #     "url": "https://github.githubassets.com/assets/chunk-ui_packages_webauthn-get-element_webauthn-get-element_ts-e119439d7139.js",
        #     "startLine": 0,
        #     "startColumn": 0,
        #     "endLine": 1,
        #     "endColumn": 97,
        #     "executionContextId": 4,
        #     "hash": "8dbc481204ca4b25260d92bd830af6182a6e313e5fa3764bed4f9a16d0973340",
        #     "executionContextAuxData": {
        #         "isDefault": True,
        #         "type": "default",
        #         "frameId": "4C87B86E67C745DF21A837C2A7482BDC",
        #     },
        #     "isLiveEdit": False,
        #     "sourceMapURL": "ui_packages_webauthn-get-element_webauthn-get-element_ts-eb4a61befd05.js.map",
        #     "hasSourceURL": False,
        #     "isModule": False,
        #     "length": 7551,
        #     "scriptLanguage": "JavaScript",
        #     "embedderName": "https://github.githubassets.com/assets/chunk-ui_packages_webauthn-get-element_webauthn-get-element_ts-e119439d7139.js",
        # }
        script_node = Script.parse(kwargs, self.current_frame)
        self.log_node(script_node)
        self._add_neo4j_msg(LoggerFile.ScriptNode, script_node.to_json())
        self.script_map[script_node.id] = script_node

        compile_edge = self.current_frame.add_edge(script_node, EdgeType.compile, {})
        self.log_edge(compile_edge)
        self._add_neo4j_msg(LoggerFile.FrameEdge, compile_edge)

    @log_event_handler
    def handle_download_begin(self, **kwargs):
        # {
        #     "frameId": "4C87B86E67C745DF21A837C2A7482BDC",
        #     "guid": "21a5cc80-bddc-43d6-a4fd-04bdc7049a7f",
        #     "url": "https://codeload.github.com/fate0/pychrome/zip/refs/heads/master",
        #     "suggestedFilename": "pychrome-master.zip",
        # }

        """
        Task 2.1.1
        - Based on frame_id, find the corresponding frame_node from frame_id_map.
        - Create a download edge (type: EdgeType.download) between the frame node and the file node.
          No extra properites need to be added to the edge, i.e., the last parameter of add_edge() is {}.
        - Add the file node to LoggerFile.FileNode and the the download edge to LoggerFile.FrameEdge through _add_neo4j_msg().
        - You can use self.log_node() and self.log_edge() (or print()) to check if they are successfully created.
        """

        file_node = File.parse(kwargs)
        frame_id = kwargs["frameId"]
        # TODO

    @log_event_handler
    def handle_window_open(self, **kwargs):
        window_node = Window.parse(kwargs)
        self.log_node(window_node)
        self._add_neo4j_msg(LoggerFile.WindowNode, window_node.to_json())

        open_edge = self.current_frame.add_edge(
            window_node,
            EdgeType.open,
            {"windowName": kwargs["windowName"]},
        )
        self.log_edge(open_edge)
        self._add_neo4j_msg(LoggerFile.FrameEdge, open_edge)

        Handler.opened_window_map[md5(kwargs["url"])] = window_node

    @log_event_handler
    def handle_frame_attached(self, **kwargs):
        # {
        #     "frameId": "8C7D47E7EA7BC30FF1B9834844009648",
        #     "parentFrameId": "CC32444DB8AB53750805953982BE6089",
        #     "stack": {
        #         "callFrames": [
        #             {
        #                 "functionName": "__createAndInsertInstance",
        #                 "scriptId": "148",
        #                 "url": "chrome://resources/polymer/v3_0/polymer/polymer_bundled.min.js",
        #                 "lineNumber": 0,
        #                 "columnNumber": 63549,
        #             },
        #             {
        #                 "functionName": "__ensureInstance",
        #                 "scriptId": "148",
        #                 "url": "chrome://resources/polymer/v3_0/polymer/polymer_bundled.min.js",
        #                 "lineNumber": 0,
        #                 "columnNumber": 62600,
        #             },
        #             {
        #                 "functionName": "__render",
        #                 "scriptId": "148",
        #                 "url": "chrome://resources/polymer/v3_0/polymer/polymer_bundled.min.js",
        #                 "lineNumber": 0,
        #                 "columnNumber": 62684,
        #             },
        #             {
        #                 "functionName": "",
        #                 "scriptId": "148",
        #                 "url": "chrome://resources/polymer/v3_0/polymer/polymer_bundled.min.js",
        #                 "lineNumber": 0,
        #                 "columnNumber": 61664,
        #             },
        #         ]
        #     },
        # }

        parent_frame_id = kwargs["parentFrameId"]
        child_frame_id = kwargs["frameId"]

        actor = None
        if stack := kwargs.get("stack"):
            actor = stack["callFrames"][0]

        Handler.attached_frame_map[child_frame_id] = {
            "parent": parent_frame_id,
            "actor": actor,
        }
