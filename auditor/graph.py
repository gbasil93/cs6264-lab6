import hashlib
import pathlib

AUDITOR_DIR = pathlib.Path(__file__).parent

LOG_DIR = AUDITOR_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)


class NodeType:
    default = "default"
    Frame = "Frame"
    Script = "Script"
    Host = "Host"
    Resource = "Resource"
    File = "File"
    Parser = "HTMLParser"
    Window = "Window"


class EdgeType:
    create = "create"
    navigate = "navigate"
    attach = "attach"
    call = "call"
    load = "load"
    add = "add"
    remove = "remove"
    redirect = "redirect"
    open = "open"
    download = "download"
    request = "request"
    respond = "respond"
    compile = "compile"
    initiate = "initiate"
    append = "append"
    modify = "modify"
    trigger = "trigger"
    listen = "listen"
    register = "register"
    unregister = "unregister"
    hangoff = "hangoff"
    update = "update"


def md5(string):
    return hashlib.md5(string.encode("utf-8")).hexdigest()


class Node:
    def __init__(self, node_id: str, node_type: str):
        self.id = node_id
        self.type = node_type
        self.dummy = False
        self.property = {"id": self.id}

    def add_edge(self, target, rel: str, props=None):
        if props is None:
            props = {}
        return {
            "srcNodeId": self.id,
            "srcNodeType": self.type,
            "dstNodeId": target.id,
            "dstNodeType": target.type,
            "rel": rel,
            **props,
        }

    def add_property(self, **kwargs):
        for k, v in kwargs.items():
            self.property[k] = v

    def get(self, name):
        return self.property.get(name)

    def to_json(self):
        return self.property

    def __str__(self):
        return f"Node<{self.type}>, ID<{self.id}>"


# Parser parses HTML
class Parser(Node):
    def __init__(self, node_id):
        super().__init__(f"parser_{node_id}", NodeType.Parser)


# TODO: add description for students
class Frame(Node):
    def __init__(self, frame_id: str, loader_id: str):
        super().__init__(f"{frame_id}_{loader_id}", NodeType.Frame)
        self.parser = Parser(self.id)
        self.initiator = None

    @staticmethod
    def parse(msg):
        # msg = Page.Frame
        # TODO: convert to Frame class -> get typing
        frame = Frame(msg.get("id"), msg.get("loaderId"))
        frame.add_property(
            url=msg.get("url"),
            is_page=not bool(
                msg.get("parentId")
            ),  # A frame is a page if parent_id is null
            security_origin=msg.get("securityOrigin"),
            mime_type=msg.get("mimeType"),
            frame_id=msg.get("id"),
            loader_id=msg.get("loaderId"),
        )
        return frame


class Script(Node):
    def __init__(self, script_id, frame_node_id):
        super().__init__(f"{script_id}_{frame_node_id}", NodeType.Script)
        self.behavior = {}
        self.frame_node_id = frame_node_id

    @staticmethod
    def parse(msg, current_frame):
        # msg = Debugger.scriptParsed
        script = Script(msg.get("scriptId"), current_frame.id)
        script.add_property(
            script_url=msg.get("url"),
            line=msg.get("startLine"),
            column=msg.get("startColumn"),
            script_id=msg.get("scriptId"),
            hash=msg.get("hash"),
        )
        return script


# Network.Request -> resource
class Resource(Node):
    def __init__(self, url):
        super().__init__(md5(url), NodeType.Resource)

    @staticmethod
    def parse(msg, resource_type):  # resource_type = Network.requestWillBeSent.type
        # msg = Network.Request
        resource = Resource(msg.get("url"))
        resource.add_property(
            type=resource_type
            or "Uknown",  # TODO: To be updated upon response being received
            url=msg.get("url"),
        )
        return resource


class File(Node):
    def __init__(self, url):
        super().__init__(md5(url), NodeType.File)

    @staticmethod
    def parse(msg):
        # msg = Page.downloadWillBegin
        file = File(msg.get("url"))
        file.add_property(filename=msg.get("suggestedFilename"))

        return file


class Window(Node):
    def __init__(self, url):
        super().__init__(md5(url), NodeType.Window)

    @staticmethod
    def parse(msg):
        # msg =Page.windowOpen
        window = Window(msg.get("url"))
        window.add_property(
            url=msg.get("url"), window_features=msg.get("windowFeatures", [])
        )
        return window


class LoggerFile:
    FrameNode = LOG_DIR / "FrameNode.tsv"
    FrameEdge = LOG_DIR / "FrameEdge.tsv"

    ResourceNode = LOG_DIR / "ResourceNode.tsv"
    ResourceEdge = LOG_DIR / "ResourceEdge.tsv"

    ScriptNode = LOG_DIR / "ScriptNode.tsv"
    ScriptRequestEdge = LOG_DIR / "ScriptRequestEdge.tsv"
    ScriptCreateEdge = LOG_DIR / "ScriptCreateEdge.tsv"

    WindowNode = LOG_DIR / "WindowNode.tsv"
    WindowEdge = LOG_DIR / "WindowEdge.tsv"

    FileNode = LOG_DIR / "FileNode.tsv"
    FileEdge = LOG_DIR / "FileEdge.tsv"
