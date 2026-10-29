# -*- coding: utf-8 -*-
# AI Bridge · Blender ↔ AI Agent 常驻联调桥
#
# 作用：把「文本块 + 每次手动 Run Script」的桥改成插件——安装一次、启用后，
#       每次启动 Blender 自动监听，AI 客户端随时可连。
#
# 安装：偏好设置 → 插件 → 从磁盘安装 → 勾选启用 → 3D 视图按 N，侧栏「AI 联调」
#
# 协议：请求 = UTF-8 Python 源码 + b"<END>"
#       响应 = "OK\n<stdout>" 或 "ERR\n<traceback>" + b"<END>"
#       执行经 bpy.app.timers 调度到 Blender 主线程，单条硬超时 120 秒
#       与 blender-tips 仓库 scripts/blender-remote-control/send.py 兼容
#
# 设计约束：只在 GUI 模式自启；端口占用明确报错、不自动换端口；
#           停桥不卸载插件；禁用插件会关监听并注销定时器。

import bpy
import io
import queue
import re
import socket
import threading
import time
import traceback
import contextlib
from collections import deque

from bpy.app.handlers import persistent

bl_info = {
    "name": "AI Bridge · Blender 联调桥",
    "author": "Simiely",
    "version": (1, 1, 0),
    "blender": (4, 2, 0),
    "location": "3D 视图 > 侧边栏(N) > AI 联调",
    "description": "常驻 socket 桥：AI agent 直接连接 Blender 执行 Python",
    "category": "System",
}

HOST = "127.0.0.1"
DEFAULT_PORT = 9877
EXEC_TIMEOUT = 120.0      # 单条请求硬超时（秒），与旧桥一致
POLL_INTERVAL = 0.05      # 主线程轮询间隔

LOG_TEXT_NAME = "AI_BRIDGE_LOG.md"   # 日志文本块（随 .blend 保存）
MAX_LOG_LINES = 3000                 # 文本块最多保留行数
TAIL_LINES = 20                      # 每条任务记录 stdout 末尾几行

_META_RE = re.compile(r"^#\s*@(name|summary)\s*[:：]\s*(.+)$", re.IGNORECASE)
VERSION_TEXT = ".".join(str(part) for part in bl_info["version"])

# ---------------------------------------------------------------- 运行时状态

_jobs = queue.Queue()
_pending_job = None

_state = {
    "server": None,
    "running": False,
    "port": DEFAULT_PORT,
    "last_error": "",
    "exec_count": 0,
    "last_duration": 0.0,
    "user_stopped": False,   # 用户手动停止后，打开新文件不再自动拉起
    "clients": 0,            # 当前打开的客户端连接数
    "peer": "",              # 最近一次客户端地址
    "last_activity": 0.0,    # 最近一次收包/执行完成的时间戳
    "busy": False,           # 是否正在主线程执行代码
    "job_started_at": 0.0,   # 当前任务的开始时间
    "log": deque(maxlen=30), # 最近 30 次操作（只在内存里，不写 .blend）
}

_registered = False
_state_lock = threading.Lock()


class _Job:
    __slots__ = ("code", "result", "done", "peer")

    def __init__(self, code, peer=""):
        self.code = code
        self.result = "ERR\nno result"
        self.done = threading.Event()
        self.peer = peer


# ---------------------------------------------------------------- socket 服务


class _BridgeServer:
    """只负责监听与收包；真正的执行交给主线程的 _drain。"""

    def __init__(self, port):
        self.port = port
        self._sock = None
        self._thread = None
        self._running = False

    def start(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Windows 上 SO_REUSEADDR 允许两个进程绑同一端口（会静默抢监听），
        # 多开 Blender 必须用 SO_EXCLUSIVEADDRUSE 才能真实报"端口被占用"
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((HOST, self.port))          # 端口占用时这里抛 OSError
        sock.listen(8)
        sock.settimeout(0.5)                  # 便于 stop() 时及时退出 accept
        self._sock = sock
        self._running = True
        self._thread = threading.Thread(
            target=self._serve, name="ai_bridge_accept", daemon=True
        )
        self._thread.start()

    def _serve(self):
        while self._running:
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(
                target=self._handle, args=(conn,), daemon=True
            ).start()

    def _handle(self, conn):
        try:
            try:
                peer = "%s:%d" % conn.getpeername()[:2]
            except Exception:
                peer = "unknown"

            with _state_lock:
                _state["clients"] += 1
                _state["peer"] = peer

            conn.settimeout(EXEC_TIMEOUT)
            raw = b""
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                raw += chunk
                if raw.endswith(b"<END>"):
                    break

            code = raw[:-5].decode("utf-8", errors="replace")
            job = _Job(code, peer)
            _jobs.put(job)

            if not job.done.wait(EXEC_TIMEOUT):
                out = "ERR\ntimeout after %ds" % int(EXEC_TIMEOUT)
            else:
                out = job.result
            conn.sendall(out.encode("utf-8") + b"<END>")
        except Exception:
            pass
        finally:
            with _state_lock:
                _state["clients"] = max(0, _state["clients"] - 1)
                _state["last_activity"] = time.time()
            try:
                conn.close()
            except Exception:
                pass

    def stop(self):
        self._running = False
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._sock = None
        self._thread = None


# ---------------------------------------------------------------- 主线程执行


def _exec_env():
    return {
        "bpy": bpy,
        "C": bpy.context,
        "D": bpy.data,
        "scene": bpy.context.scene,
        "mathutils": __import__("mathutils"),
        "__builtins__": __builtins__,
    }


def _drain():
    """每 0.05s 调度一次：先置 busy 并重绘，下一拍再执行。

    这样"执行中"能在真正开跑前画到面板上——执行期间主线程被占，
    界面不会再有刷新机会。
    """
    global _pending_job

    if _state["busy"] or _pending_job is not None:
        return POLL_INTERVAL

    try:
        job = _jobs.get_nowait()
    except queue.Empty:
        return POLL_INTERVAL

    _pending_job = job
    _state["busy"] = True
    _state["job_started_at"] = time.time()
    _tag_redraw()
    try:
        bpy.app.timers.register(
            _execute_pending, first_interval=0.05, persistent=False
        )
    except Exception as exc:
        # 定时器注册失败时必须把状态复位，否则队列会被永久卡住
        _pending_job = None
        _state["busy"] = False
        _state["job_started_at"] = 0.0
        job.result = "ERR\ntimer register failed: %r" % (exc,)
        job.done.set()
    return POLL_INTERVAL


def _execute_pending():
    """真正执行队列里那一条任务（一次性定时器，执行期间阻塞主线程）。"""
    global _pending_job
    job = _pending_job
    _pending_job = None
    if job is None:
        _state["busy"] = False
        return None

    buf = io.StringIO()
    try:
        before_counts = _counts()
    except Exception:
        before_counts = (0, 0, 0)
    t0 = time.time()
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(job.code, "<ai_bridge>", "exec"), _exec_env())
        job.result = "OK\n" + buf.getvalue()
    except BaseException:
        # 必须接住 BaseException：脚本里 sys.exit() 抛的是 SystemExit，
        # 用 except Exception 会让它一路穿透，直接退出整个 Blender。
        prints = buf.getvalue()
        job.result = "ERR\n" + traceback.format_exc()
        if prints.strip():
            job.result += "\n--- stdout ---\n" + prints
    finally:
        job.done.set()
        dur = time.time() - t0
        ok = job.result.startswith("OK")
        _state["busy"] = False
        _state["job_started_at"] = 0.0
        _state["exec_count"] += 1
        _state["last_duration"] = dur
        _state["last_activity"] = time.time()
        entry = {
            "t": time.time(),
            "ok": ok,
            "dur": dur,
            "peer": job.peer,
            "preview": _preview(job.code),
            "err": "" if ok else _err_tail(job.result),
            "tail": _tail_lines(buf.getvalue()),
            "delta": _delta_text(before_counts, _counts()),
        }
        name, summary = _meta(job.code)
        entry["name"] = name
        entry["summary"] = summary
        _state["log"].append(entry)
        _append_text_log(entry)
        _tag_redraw()

    return None


def _preview(code, limit=60):
    """取第一行有效代码做摘要（跳过空行、注释与 import）。"""
    for line in code.splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text.startswith("import ") or text.startswith("from "):
            continue
        return text[:limit]
    return "<空脚本>"


def _meta(code):
    """从脚本注释里读 @name / @summary（可写在任意位置）。"""
    name = ""
    summary = ""
    for line in code.splitlines():
        match = _META_RE.match(line.strip())
        if not match:
            continue
        key = match.group(1).lower()
        value = match.group(2).strip()
        if key == "name":
            name = value
        else:
            summary = value
    return name, summary


def _entry_label(entry):
    """日志条目的一句话标题：优先 @summary，其次 @name，最后代码首行。"""
    return (entry.get("summary") or entry.get("name") or entry.get("preview") or "")[:60]


def _counts():
    """场景规模三元组，用于算“这次做了什么”。"""
    return (len(bpy.data.objects), len(bpy.data.materials), len(bpy.data.collections))


def _delta_text(before, after):
    labels = ("objects", "materials", "collections")
    parts = []
    for label, old, new in zip(labels, before, after):
        if new != old:
            parts.append("%s %d→%d (%+d)" % (label, old, new, new - old))
    return " · ".join(parts) if parts else "无变化"


def _err_tail(result, limit=160):
    """取 traceback 的最后一行（排除后面附加的 stdout 段）。"""
    main = result.split("\n--- stdout ---\n", 1)[0]
    lines = [line for line in main.splitlines() if line.strip()]
    return lines[-1][:limit] if lines else ""


def _tail_lines(stdout, limit=TAIL_LINES):
    lines = [line.rstrip() for line in stdout.splitlines() if line.strip()]
    return lines[-limit:]


def _append_text_log(entry):
    """把一条操作记录写进随 .blend 保存的文本块。"""
    try:
        block = bpy.data.texts.get(LOG_TEXT_NAME)
        if block is None:
            block = bpy.data.texts.new(LOG_TEXT_NAME)
            body = "# AI Bridge 操作日志\n\n"
        else:
            body = block.as_string()

        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entry["t"]))
        label = _entry_label(entry)
        name = entry.get("name") or ""

        lines = [
            "[%s] %s %.2fs  %s"
            % (stamp, "OK " if entry["ok"] else "ERR", entry["dur"], entry["peer"])
        ]
        if label and name and name != label:
            lines.append("    ▶ %s · %s" % (label, name))
        elif label or name:
            lines.append("    ▶ %s" % (label or name))
        lines.append("    变化: " + entry["delta"])

        if entry["err"]:
            lines.append("    ! " + entry["err"])
        if entry["tail"]:
            lines.append("    输出 %d 行:" % len(entry["tail"]))
            for line in entry["tail"]:
                lines.append("      " + line[:200])

        body += "\n".join(lines) + "\n"
        rows = body.splitlines()
        if len(rows) > MAX_LOG_LINES:
            body = (
                "# AI Bridge 操作日志（已截断）\n"
                + "\n".join(rows[-MAX_LOG_LINES:])
                + "\n"
            )

        block.clear()
        block.write(body)
    except Exception:
        pass


def _tag_redraw():
    """让侧栏面板跟随桥的状态刷新。"""
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:
        pass


_ui_snapshot = None


def _ui_tick():
    """仅当状态变化时重绘；不把"空闲秒数"算进快照，避免 1Hz 无谓重绘。"""
    global _ui_snapshot
    snap = (
        _state["running"],
        _state["clients"],
        _state["busy"],
        bool(_state["last_activity"]),
    )
    if snap != _ui_snapshot:
        _ui_snapshot = snap
        _tag_redraw()
    return 0.5


def _ensure_timers():
    if not bpy.app.timers.is_registered(_drain):
        bpy.app.timers.register(_drain, persistent=True)
    if not bpy.app.timers.is_registered(_ui_tick):
        bpy.app.timers.register(_ui_tick, persistent=True)


def _drop_timers():
    for fn in (_drain, _ui_tick, _execute_pending):
        if bpy.app.timers.is_registered(fn):
            bpy.app.timers.unregister(fn)


# ---------------------------------------------------------------- 启动 / 停止


def _addon_key():
    """legacy 单文件插件用 __name__，扩展插件用 __package__。"""
    return __package__ or __name__


def _prefs():
    try:
        addons = bpy.context.preferences.addons
        key = _addon_key()
        entry = addons.get(key)
        if entry is None:
            # 扩展命名空间（bl_ext.<repo>.<name>）或安装方式差异时按尾名兜底
            base = key.rsplit(".", 1)[-1]
            for name in addons.keys():
                if name == base or name.endswith("." + base):
                    entry = addons[name]
                    break
        return entry.preferences if entry else None
    except Exception:
        return None


def _default_port():
    prefs = _prefs()
    return int(prefs.port) if prefs else DEFAULT_PORT


def start_bridge(port=None):
    """启动监听。返回 True/False，失败原因写入 _state['last_error']。"""
    port = int(port or _default_port())

    if _state["running"]:
        stop_bridge()

    server = _BridgeServer(port)
    try:
        server.start()
    except OSError as exc:
        msg = "端口 %d 无法监听：%s" % (port, exc)
        _state["last_error"] = msg
        print("[AI Bridge] " + msg)
        return False

    _state["server"] = server
    _state["running"] = True
    _state["port"] = port
    _state["last_error"] = ""
    _state["busy"] = False

    _ensure_timers()
    print("[AI Bridge] READY  %s:%d" % (HOST, port))
    return True


def stop_bridge():
    global _pending_job
    was_running = _state["running"] or _state["server"] is not None
    server = _state.get("server")
    if server:
        server.stop()

    _state["server"] = None
    _state["running"] = False
    _state["busy"] = False
    _state["job_started_at"] = 0.0

    if _pending_job is not None:
        _pending_job.result = "ERR\nbridge stopped before execution"
        _pending_job.done.set()
        _pending_job = None

    # 队列里还没轮到的任务也要立刻放行，否则客户端会一直等到超时
    while True:
        try:
            job = _jobs.get_nowait()
        except queue.Empty:
            break
        job.result = "ERR\nbridge stopped before execution"
        job.done.set()

    _drop_timers()
    if was_running:
        print("[AI Bridge] stopped")


# ---------------------------------------------------------------- 自启动


def _autostart_timer():
    if bpy.app.background:          # 无头模式不占端口
        return None

    if _state["user_stopped"]:      # 用户手动停过，不再自动拉起
        return None

    prefs = _prefs()
    if prefs and not prefs.auto_start:
        return None

    if _state["running"]:
        return None

    start_bridge(_default_port())
    return None


def _schedule_autostart(delay=1.0):
    if not bpy.app.timers.is_registered(_autostart_timer):
        bpy.app.timers.register(
            _autostart_timer, first_interval=delay, persistent=True
        )


@persistent
def _on_load_post(_dummy):
    """打开/切换 .blend 后补一次自启尝试（端口可能被别的实例占了）。"""
    _schedule_autostart(0.5)


# ---------------------------------------------------------------- 提示词


PROMPT_TEMPLATE = """# Blender AI 联调 · 连接说明

## 连接信息
- 地址：127.0.0.1:<PORT>
- 协议：TCP，UTF-8
- 请求：Python 源码 + 字符串 "<END>"
- 响应：以 "<END>" 结尾；成功 "OK\\n<输出>"，失败 "ERR\\n<traceback>"
- 执行：Blender 主线程，单条硬超时 120 秒
- 桥端预置名字：bpy / C / D / scene / mathutils

## 客户端（保存为 bl.py 后，python bl.py 脚本.py）
```python
import socket, sys, pathlib

HOST, PORT = "127.0.0.1", <PORT>
code = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")

s = socket.create_connection((HOST, PORT), timeout=300)
s.sendall(code.encode("utf-8") + b"<END>")

buf = b""
while not buf.endswith(b"<END>"):
    chunk = s.recv(65536)
    if not chunk:
        break
    buf += chunk

print(buf[:-5].decode("utf-8", "replace"))
```

## 第一条自检
```python
import bpy
print(bpy.app.version_string, bpy.data.filepath)
print("objects:", len(bpy.data.objects),
      "drivers:", sum(len(o.animation_data.drivers)
                      for o in bpy.data.objects if o.animation_data))
```

## 硬约束
1. 脚本必须是 UTF-8 无 BOM（带 BOM 会 SyntaxError: U+FEFF）
2. 不要写 `if __name__ == "__main__"`：桥端 exec 环境没有 __name__，守卫不成立且会 NameError
3. 禁止文件级 operator：read_factory_settings / read_homefile / wm.open_mainfile
   （会卸载当前文件，实测崩溃、未存盘改动全丢）
4. 超过 60 秒的任务改走 `blender -b`；桥 120 秒硬超时后只是断包，脚本仍在主线程跑
5. 桥只改内存、不存盘；改动前先备份 .blend，改后用新引用独立核验
6. 长任务分段，每阶段把状态写 JSON，超时后读盘回捞

## 排障
- 连不上：先看 3D 视图 N 侧栏「AI 联调」是否显示"运行中"，或 netstat -ano | findstr <PORT>
- 端口被占用：在面板改端口 → 点「应用端口并重启」
"""


def build_prompt(port=None):
    port = int(port or _state["port"])
    return PROMPT_TEMPLATE.replace("<PORT>", str(port))


def build_log_text():
    """优先返回文本块内容（持久化日志），否则退回内存记录。"""
    block = bpy.data.texts.get(LOG_TEXT_NAME)
    if block is not None:
        content = block.as_string()
        if content.strip():
            return content

    if not _state["log"]:
        return "（暂无操作日志）"

    lines = []
    for entry in reversed(_state["log"]):
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entry["t"]))
        lines.append(
            "[%s] %s %.2fs  %s"
            % (stamp, "OK " if entry["ok"] else "ERR", entry["dur"], entry["peer"])
        )
        lines.append("  " + entry["preview"])
        if entry["err"]:
            lines.append("  " + entry["err"])
    return "\n".join(lines)


# ---------------------------------------------------------------- 插件属性


class AIBridgePreferences(bpy.types.AddonPreferences):
    bl_idname = _addon_key()

    port: bpy.props.IntProperty(
        name="端口",
        description="桥监听端口；修改后需点「应用端口并重启」生效",
        default=DEFAULT_PORT,
        min=1024,
        max=65535,
    )
    auto_start: bpy.props.BoolProperty(
        name="随 Blender 启动",
        description="启动 Blender 后自动开始监听（无头模式始终跳过）",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "port")
        layout.prop(self, "auto_start")
        layout.label(text="多开 Blender 时，各实例请使用不同端口", icon='INFO')


# ---------------------------------------------------------------- 操作符


class AIBRIDGE_OT_start(bpy.types.Operator):
    bl_idname = "aib.start"
    bl_label = "启动桥"
    bl_description = "开始监听，接受 AI agent 连接"

    def execute(self, context):
        _state["user_stopped"] = False
        port = _default_port()
        if start_bridge(port):
            self.report({'INFO'}, "AI Bridge 已启动：%s:%d" % (HOST, port))
            return {'FINISHED'}
        self.report({'ERROR'}, _state["last_error"])
        return {'CANCELLED'}


class AIBRIDGE_OT_stop(bpy.types.Operator):
    bl_idname = "aib.stop"
    bl_label = "停止桥"
    bl_description = "关闭监听，已连接的请求不再处理"

    def execute(self, context):
        stop_bridge()
        _state["user_stopped"] = True
        self.report({'INFO'}, "AI Bridge 已停止")
        return {'FINISHED'}


class AIBRIDGE_OT_apply_port(bpy.types.Operator):
    bl_idname = "aib.apply_port"
    bl_label = "应用端口并重启"
    bl_description = "用面板里的端口重新启动监听"

    def execute(self, context):
        prefs = _prefs()
        if prefs is None:
            self.report({'ERROR'}, "未作为插件安装，无法保存端口")
            return {'CANCELLED'}

        port = int(prefs.port)
        if _state["running"] and _state["port"] == port:
            self.report({'INFO'}, "端口未变化：%d" % port)
            return {'FINISHED'}

        _state["user_stopped"] = False
        if start_bridge(port):
            self.report({'INFO'}, "已切换到 %s:%d" % (HOST, port))
            return {'FINISHED'}

        self.report({'ERROR'}, _state["last_error"])
        return {'CANCELLED'}


class AIBRIDGE_OT_open_log(bpy.types.Operator):
    bl_idname = "aib.open_log"
    bl_label = "打开日志"
    bl_description = "在文本编辑器中打开持久化日志文本块"

    def execute(self, context):
        block = bpy.data.texts.get(LOG_TEXT_NAME)
        if block is None:
            self.report({'WARNING'}, "还没有日志，先让 AI 执行一次")
            return {'CANCELLED'}

        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type != 'TEXT_EDITOR':
                    continue
                for space in area.spaces:
                    if space.type == 'TEXT_EDITOR':
                        space.text = block
                area.tag_redraw()
                self.report({'INFO'}, "已在文本编辑器中打开 %s" % LOG_TEXT_NAME)
                return {'FINISHED'}

        self.report({'INFO'}, "切到 Scripting 工作区即可看到文本块 %s" % LOG_TEXT_NAME)
        return {'FINISHED'}


class AIBRIDGE_OT_copy_log(bpy.types.Operator):
    bl_idname = "aib.copy_log"
    bl_label = "复制日志"
    bl_description = "把这几次操作记录复制到剪贴板"

    def execute(self, context):
        try:
            context.window_manager.clipboard = build_log_text()
        except Exception:
            self.report({'ERROR'}, "复制失败：当前环境不支持剪贴板")
            return {'CANCELLED'}
        self.report({'INFO'}, "已复制 %d 条操作记录" % len(_state["log"]))
        return {'FINISHED'}


class AIBRIDGE_OT_clear_log(bpy.types.Operator):
    bl_idname = "aib.clear_log"
    bl_label = "清空日志"
    bl_description = "清掉内存里的操作记录（不影响场景）"

    def execute(self, context):
        _state["log"].clear()
        block = bpy.data.texts.get(LOG_TEXT_NAME)
        if block is not None:
            block.clear()
        self.report({'INFO'}, "操作日志已清空")
        return {'FINISHED'}


class AIBRIDGE_OT_copy_prompt(bpy.types.Operator):
    bl_idname = "aib.copy_prompt"
    bl_label = "复制 AI 连接提示词"
    bl_description = "把当前端口的连接说明复制到剪贴板，可直接发给 AI agent"

    def execute(self, context):
        prompt = build_prompt(_state["port"])
        try:
            context.window_manager.clipboard = prompt
        except Exception:
            self.report({'ERROR'}, "复制失败：当前环境不支持剪贴板")
            return {'CANCELLED'}
        self.report({'INFO'}, "已复制连接提示词（端口 %d）" % _state["port"])
        return {'FINISHED'}


# ---------------------------------------------------------------- 侧栏面板


def _client_status():
    """返回 (文案, 图标)：等待连接 / 已连接 / 执行中。"""
    if not _state["running"]:
        return "已停止", 'PAUSE'
    if _state["busy"]:
        return "执行中", 'PLAY'
    if _state["clients"] > 0:
        return "已连接（%d）" % _state["clients"], 'LINKED'
    return "等待连接", 'TIME'


class AIBRIDGE_PT_main(bpy.types.Panel):
    bl_label = "AI 联调桥"
    bl_idname = "AIBRIDGE_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "AI 联调"

    def draw(self, context):
        layout = self.layout
        prefs = _prefs()
        running = _state["running"]

        box = layout.box()
        row = box.row()
        row.label(
            text="运行中" if running else "已停止",
            icon='PLAY' if running else 'PAUSE',
        )
        if running:
            row.label(text="%s:%d" % (HOST, _state["port"]))

        box.label(text="AI Bridge v%s" % VERSION_TEXT, icon='INFO')

        col = layout.column(align=True)
        if prefs:
            col.prop(prefs, "port")
            col.prop(prefs, "auto_start")
        else:
            col.label(text="未作为插件安装（无法保存端口）", icon='ERROR')

        row = layout.row(align=True)
        sub = row.row(align=True)
        sub.enabled = not running
        sub.operator("aib.start", text="启动", icon='PLAY')
        sub = row.row(align=True)
        sub.enabled = running
        sub.operator("aib.stop", text="停止", icon='PAUSE')

        layout.operator("aib.apply_port", text="应用端口并重启", icon='FILE_REFRESH')
        layout.operator("aib.copy_prompt", text="复制 AI 连接提示词", icon='COPYDOWN')

        if _state["last_error"]:
            box = layout.box()
            box.alert = True
            box.label(text=_state["last_error"], icon='ERROR')

        status, icon = _client_status()
        box = layout.box()
        row = box.row()
        row.label(text=status, icon=icon)
        if _state["clients"] > 0 and _state["peer"]:
            row.label(text=_state["peer"])

        queued = _jobs.qsize()
        if queued:
            box.label(text="排队 %d 个任务" % queued, icon='TIME')

        last = _state["last_activity"]
        if last:
            box.label(
                text="最近活动 %.0f 秒前" % max(0.0, time.time() - last),
                icon='TIME',
            )
        else:
            box.label(text="尚无客户端连接", icon='INFO')

        box.label(
            text="AI 连接：%s:%d" % (HOST, _state["port"]),
            icon='LINKED',
        )
        box.label(
            text="执行 %d 次 · 上次 %.2fs"
            % (_state["exec_count"], _state["last_duration"])
        )
        if bpy.data.filepath:
            box.label(text=bpy.path.basename(bpy.data.filepath), icon='FILE_BLEND')

        box = layout.box()
        box.label(text="最近操作（%d）" % len(_state["log"]), icon='TEXT')
        entries = list(_state["log"])[-6:]
        if not entries:
            box.label(text="暂无记录", icon='INFO')
        else:
            col = box.column(align=True)
            for entry in reversed(entries):
                stamp = time.strftime("%H:%M:%S", time.localtime(entry["t"]))
                col.label(
                    text="%s  %s  %.2fs  %s"
                    % (
                        stamp,
                        "OK " if entry["ok"] else "ERR",
                        entry["dur"],
                        _entry_label(entry)[:32],
                    ),
                    icon='CHECKMARK' if entry["ok"] else 'ERROR',
                )
        block = bpy.data.texts.get(LOG_TEXT_NAME)
        if block is not None:
            box.label(
                text="%s · %d 行（随工程保存）"
                % (LOG_TEXT_NAME, len(block.as_string().splitlines())),
                icon='TEXT',
            )
        else:
            box.label(text="%s（执行一次后生成）" % LOG_TEXT_NAME, icon='INFO')

        row = box.row(align=True)
        row.operator("aib.open_log", text="打开日志", icon='TEXT')
        row.operator("aib.copy_log", text="复制", icon='COPYDOWN')
        row.operator("aib.clear_log", text="清空", icon='TRASH')


# ---------------------------------------------------------------- 注册


_CLASSES = (
    AIBridgePreferences,
    AIBRIDGE_OT_start,
    AIBRIDGE_OT_stop,
    AIBRIDGE_OT_apply_port,
    AIBRIDGE_OT_open_log,
    AIBRIDGE_OT_copy_log,
    AIBRIDGE_OT_clear_log,
    AIBRIDGE_OT_copy_prompt,
    AIBRIDGE_PT_main,
)


def register():
    global _registered
    if _registered:
        return

    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)

    _registered = True
    _state["user_stopped"] = False
    _schedule_autostart(1.0)


def unregister():
    global _registered
    if not _registered:
        return

    stop_bridge()

    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)

    if bpy.app.timers.is_registered(_autostart_timer):
        bpy.app.timers.unregister(_autostart_timer)

    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except (RuntimeError, ValueError):
            pass

    _registered = False


# 兼容旧用法：在 Scripting 工作区直接 Run Script 也能起桥（无 UI、用默认端口）
if __name__ == "__main__":
    start_bridge(DEFAULT_PORT)
