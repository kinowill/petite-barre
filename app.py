"""Discreet local Ollama widget for Windows."""
import base64
import http.client
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import winreg
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox
from tkinter import font as tkfont

import mistune
from PIL import Image, ImageGrab, ImageOps, ImageTk
from tkinterdnd2 import DND_FILES, TkinterDnD

HISTORY = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "HauhauMini" / "history.json"
SETTINGS = HISTORY.with_name("settings.json")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
BG, PANEL, FG, ACCENT = "#1b2027", "#29313b", "#f4f1e9", "#86d9c6"
TRANSPARENT = "#ff00ff"
IDLE_OPACITY, HOVER_OPACITY = 0.65, 0.95
MAX_IMAGES = 4
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MARKDOWN = mistune.create_markdown(renderer="ast", plugins=["strikethrough", "table"])


def markdown_runs(source):
    """Convert Markdown to text and Tk styles, preserving literal code."""
    runs = []
    trailing_newlines = 0

    def emit(value, tags=()):
        nonlocal trailing_newlines
        if not value:
            return
        styles = set(tags)
        if "md_bold" in styles and "md_italic" in styles:
            styles.difference_update(("md_bold", "md_italic"))
            styles.add("md_bolditalic")
        styles = tuple(sorted(styles))
        if runs and runs[-1][1] == styles:
            runs[-1] = (runs[-1][0] + value, styles)
        else:
            runs.append((value, styles))
        if value.strip("\n"):
            trailing_newlines = len(value) - len(value.rstrip("\n"))
        else:
            trailing_newlines += len(value)

    def line_break(count=1):
        if runs and trailing_newlines < count:
            emit("\n" * (count - trailing_newlines))

    def inline(tokens, tags=()):
        for token in tokens:
            kind = token["type"]
            children = token.get("children", [])
            if kind in ("strong", "emphasis", "strikethrough"):
                style = {"strong": "md_bold", "emphasis": "md_italic", "strikethrough": "md_strike"}[kind]
                inline(children, tags + (style,))
            elif kind == "codespan":
                emit(token["raw"], tags + ("md_code",))
            elif kind == "softbreak":
                emit(" ", tags)
            elif kind == "linebreak":
                emit("\n", tags)
            elif kind in ("link", "image"):
                inline(children, tags + ("md_link",))
                url = token.get("attrs", {}).get("url", "")
                label = "".join(child.get("raw", "") for child in children)
                if url and label != url:
                    emit(f" ({url})", tags + ("md_link",))
            elif children:
                inline(children, tags)
            else:
                emit(token.get("raw", ""), tags)

    def blocks(tokens, tags=(), depth=0):
        for token in tokens:
            kind = token["type"]
            children = token.get("children", [])
            if kind == "blank_line":
                line_break(2)
            elif kind in ("paragraph", "block_text", "heading"):
                line_break()
                styles = tags + ("md_bold", "md_heading") if kind == "heading" else tags
                inline(children, styles)
                line_break()
            elif kind == "list":
                attrs = token.get("attrs", {})
                start = attrs.get("start", 1)
                for index, item in enumerate(children):
                    line_break()
                    prefix = f"{start + index}. " if attrs.get("ordered") else "• "
                    list_tags = tags + ("md_list",)
                    emit("  " * depth + prefix, list_tags)
                    for child_index, child in enumerate(item.get("children", [])):
                        if child["type"] in ("paragraph", "block_text"):
                            if child_index:
                                line_break()
                                emit("  " * (depth + 1), list_tags)
                            inline(child.get("children", []), list_tags)
                            line_break()
                        else:
                            blocks([child], tags, depth + 1)
                line_break()
            elif kind == "block_quote":
                line_break()
                blocks(children, tags + ("md_quote",), depth)
            elif kind == "block_code":
                line_break()
                emit(token.get("raw", "").rstrip("\n"), tags + ("md_code",))
                line_break()
            elif kind == "thematic_break":
                line_break()
                emit("────────────────", tags + ("md_quote",))
                line_break()
            elif kind == "table":
                line_break()
                for section in children:
                    rows = [section] if section["type"] == "table_head" else section.get("children", [])
                    for row in rows:
                        for index, cell in enumerate(row.get("children", [])):
                            if index:
                                emit("  |  ", tags)
                            styles = tags + ("md_bold",) if cell.get("attrs", {}).get("head") else tags
                            inline(cell.get("children", []), styles)
                        line_break()
            elif children:
                blocks(children, tags, depth)
            else:
                emit(token.get("raw", ""), tags)
                line_break()

    blocks(MARKDOWN(source))
    while runs and runs[-1][0].endswith("\n"):
        value, tags = runs.pop()
        value = value.rstrip("\n")
        if value:
            runs.append((value, tags))
            break
    return runs


def markdown_plain(source):
    return "".join(value for value, _tags in markdown_runs(source))


def configure_markdown(text):
    fonts = {}
    for tag, options in (("md_bold", {"weight": "bold"}), ("md_italic", {"slant": "italic"}),
                         ("md_bolditalic", {"weight": "bold", "slant": "italic"}),
                         ("md_code", {"family": "Consolas"})):
        font = tkfont.Font(root=text.winfo_toplevel(), font=text["font"])
        font.configure(**options)
        fonts[tag] = font
        text.tag_configure(tag, font=font)
    text.markdown_fonts = fonts
    text.tag_configure("md_code", background="#222831", foreground=ACCENT)
    text.tag_configure("md_heading", foreground=ACCENT)
    text.tag_configure("md_quote", foreground="#bdc7d0", lmargin1=8, lmargin2=8)
    text.tag_configure("md_list", lmargin2=12)
    text.tag_configure("md_link", underline=True)
    text.tag_configure("md_strike", overstrike=True)


def insert_markdown(text, source):
    for value, tags in markdown_runs(source):
        text.insert("end-1c", value, tags)


def make_attachment(image, name):
    if image.width * image.height > 40_000_000:
        raise ValueError("Image trop grande : maximum 40 millions de pixels.")
    normalized = ImageOps.exif_transpose(image)
    normalized.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    mode = "RGBA" if normalized.mode in ("RGBA", "LA") or "transparency" in normalized.info else "RGB"
    normalized = normalized.convert(mode)
    buffer = io.BytesIO()
    normalized.save(buffer, format="PNG")
    preview = normalized.copy()
    preview.thumbnail((28, 28), Image.Resampling.LANCZOS)
    return {"name": name, "data": base64.b64encode(buffer.getvalue()).decode("ascii"), "preview": preview}


def read_attachment(path):
    path = Path(path)
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError("Image trop lourde : maximum 20 Mo par fichier.")
    with Image.open(path) as image:
        return make_attachment(image, path.name)


class GenerationCancelled(Exception):
    """The user stopped this generation."""


class GenerationRequest:
    def __init__(self):
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.transport = None

    def attach(self, transport):
        with self.lock:
            if not self.cancelled.is_set():
                self.transport = transport
                return
        self.close_transport(transport)
        raise GenerationCancelled()

    def detach(self):
        with self.lock:
            self.transport = None

    def cancel(self):
        self.cancelled.set()
        with self.lock:
            transport = self.transport
        if transport is not None:
            self.close_transport(transport)

    @staticmethod
    def close_transport(transport):
        # Shutdown interrupts a blocked read, including hidden thinking chunks.
        try:
            transport.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        transport.close()


def list_ollama_models():
    connection = http.client.HTTPConnection("127.0.0.1", 11434, timeout=5)
    try:
        connection.request("GET", "/api/tags")
        with connection.getresponse() as response:
            body = response.read()
            if response.status >= 400:
                raise ValueError(f"Ollama a répondu HTTP {response.status}.")
        data = json.loads(body)
        if not isinstance(data, dict):
            raise TypeError("Réponse Ollama invalide.")
        models = data.get("models", [])
        if not isinstance(models, list):
            raise TypeError("Liste de modèles Ollama invalide.")
        return sorted({item["name"] for item in models
                       if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"]})
    finally:
        connection.close()


def stream_ollama(messages, model, thinking=False, generation=None):
    generation = generation if generation is not None else GenerationRequest()
    payload = json.dumps({"model": model, "messages": messages, "stream": True, "think": thinking}).encode("utf-8")
    connection = http.client.HTTPConnection("127.0.0.1", 11434, timeout=300)
    received_content = False
    try:
        if generation.cancelled.is_set():
            raise GenerationCancelled()
        connection.connect()
        generation.attach(connection.sock)
        connection.request("POST", "/api/chat", payload, {"Content-Type": "application/json"})
        with connection.getresponse() as response:
            if response.status >= 400:
                raise ValueError(f"HTTP {response.status} : {response.read(4096).decode('utf-8', errors='replace')}")
            for line in response:
                if generation.cancelled.is_set():
                    raise GenerationCancelled()
                if not line.strip():
                    continue
                data = json.loads(line)
                if data.get("error"):
                    raise ValueError(data["error"])
                chunk = data.get("message", {}).get("content", "")
                if chunk:
                    received_content = True
                    yield chunk
                if data.get("done"):
                    break
    except (OSError, http.client.HTTPException):
        if generation.cancelled.is_set():
            raise GenerationCancelled() from None
        raise
    finally:
        generation.detach()
        connection.close()
    if generation.cancelled.is_set():
        raise GenerationCancelled()
    if not received_content:
        raise ValueError("Le modèle a renvoyé une réponse vide.")


def read_history():
    try:
        value = json.loads(HISTORY.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, ValueError):
        return []


def write_history(items):
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    temporary = HISTORY.with_suffix(".tmp")
    temporary.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(HISTORY)


def read_settings():
    try:
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        return settings if isinstance(settings, dict) else {}
    except (OSError, ValueError):
        return {}


def write_settings(**updates):
    settings = read_settings()
    settings.update(updates)
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    temporary = SETTINGS.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(SETTINGS)


def read_thinking():
    return read_settings().get("thinking") is True


def write_thinking(enabled):
    write_settings(thinking=enabled)


def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, "Hauhau Mini")
        return True
    except FileNotFoundError:
        return False


def set_startup(enabled):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            executable = pythonw if pythonw.exists() else Path(sys.executable)
            winreg.SetValueEx(key, "Hauhau Mini", 0, winreg.REG_SZ, f'"{executable}" "{Path(__file__).resolve()}"')
        else:
            try:
                winreg.DeleteValue(key, "Hauhau Mini")
            except FileNotFoundError:
                pass


def speak(text):
    script = ("[Console]::InputEncoding=[Text.Encoding]::UTF8; "
              "$t=[Console]::In.ReadToEnd(); Add-Type -AssemblyName System.Speech; "
              "$v=New-Object System.Speech.Synthesis.SpeechSynthesizer; $v.Speak($t)")
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", script], input=text,
                   encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW, check=True)


class Widget:
    def __init__(self):
        self.root = TkinterDnD.Tk()
        self.root.title("Hauhau Mini")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", IDLE_OPACITY)
        self.root.attributes("-transparentcolor", TRANSPARENT)
        self.root.configure(bg=TRANSPARENT)
        self.width, self.height = 392, 50
        self.busy = False
        self.loading = False
        self.loading_frame = 0
        self.answer_source = ""
        self.request_id = 0
        self.active_request = None
        self.context = []
        self.history = read_history()
        self.history_window = None
        self.prompt_window = None
        self.attachments = []
        self.attachment_photos = []
        settings = read_settings()
        system_prompt = settings.get("system_prompt", "")
        self.system_prompt = system_prompt if isinstance(system_prompt, str) else ""
        stored_model = settings.get("model", "")
        self.model = stored_model.strip() if isinstance(stored_model, str) else ""
        self.model_window = None
        self.voice = tk.BooleanVar(value=False)
        self.thinking = tk.BooleanVar(value=read_thinking())
        self.autostart = tk.BooleanVar(value=startup_enabled())
        self.drag = None
        self.opacity_target = IDLE_OPACITY
        self.opacity_job = None

        self.background = tk.Canvas(self.root, bg=TRANSPARENT, highlightthickness=0, bd=0)
        self.background.place(relwidth=1, relheight=1)
        self.background.bind("<Configure>", self.paint_background)
        self.outer = tk.Frame(self.root, bg=PANEL)
        self.outer.place(x=12, y=6, relwidth=1, relheight=1, width=-44, height=-12)
        self.main = tk.Frame(self.outer, bg=PANEL)
        self.main.pack(fill="both", expand=True)
        self.attachment_frame = tk.Frame(self.main, bg=PANEL)
        self.input_surface = tk.Canvas(self.main, bg=PANEL, highlightthickness=0, bd=0)
        self.entry = tk.Text(self.input_surface, height=1, wrap="word", bg=PANEL, fg=FG,
                             insertbackground=ACCENT, relief="flat", bd=0, padx=0, pady=0,
                             font=("Segoe UI", 10), undo=True)
        self.entry_window = self.input_surface.create_window(3, 4, anchor="nw", window=self.entry)
        self.input_surface.bind("<Configure>", self.paint_input)
        self.entry.bind("<Return>", self.on_return)
        self.entry.bind("<Control-v>", self.paste_image)
        self.input_surface.pack(side="left", fill="both", expand=True)
        self.answer_surface = tk.Canvas(self.main, bg=PANEL, highlightthickness=0, bd=0)
        self.answer = tk.Text(self.answer_surface, wrap="word", bg=PANEL, fg=FG, relief="flat",
                              bd=0, padx=0, pady=0, font=("Segoe UI", 10), cursor="hand2")
        self.answer_font = tkfont.Font(font=self.answer["font"])
        configure_markdown(self.answer)
        for tag, color in (("fade_top", "#4b535c"), ("fade_middle", "#8f9396"), ("fade_bottom", "#d1d0ce")):
            self.answer.tag_configure(tag, foreground=color)
        self.answer.tag_configure("loading", foreground=ACCENT)
        self.answer_window = self.answer_surface.create_window(3, 4, anchor="nw", window=self.answer)
        self.answer_surface.bind("<Configure>", self.paint_answer)
        self.answer.bind("<Button-1>", lambda _event: self.new_question())
        self.answer.bind("<MouseWheel>", lambda _event: self.root.after_idle(self.update_fade), add="+")
        self.grip = tk.Canvas(self.root, width=18, height=24, bg=PANEL,
                              highlightthickness=0, bd=0, cursor="fleur")
        self.grip.place(relx=1, rely=1, x=-20, y=-25, anchor="center")
        for grip_x in (5, 11):
            for grip_y in (6, 12, 18):
                self.grip.create_oval(grip_x-1, grip_y-1, grip_x+1, grip_y+1,
                                      fill="#75818d", outline="", tags="dots")
        self.grip.bind("<ButtonPress-1>", self.drag_start)
        self.grip.bind("<B1-Motion>", self.drag_move)
        self.grip.bind("<ButtonRelease-1>", self.drag_end)
        self.grip.bind("<Enter>", lambda _event: self.grip.itemconfigure("dots", fill="#bdc8d1"))
        self.grip.bind("<Leave>", lambda _event: self.grip.itemconfigure("dots", fill="#75818d"))
        self.stop_button = tk.Canvas(self.root, width=20, height=24, bg=PANEL,
                                      highlightthickness=0, bd=0, cursor="hand2")
        self.stop_button.create_line(6, 8, 14, 16, fill="#a2abb5", width=1.5, tags="cross")
        self.stop_button.create_line(6, 16, 14, 8, fill="#a2abb5", width=1.5, tags="cross")
        self.stop_button.bind("<Button-1>", lambda _event: self.stop_generation())
        self.stop_button.bind("<Enter>", lambda _event: self.stop_button.itemconfigure("cross", fill="#ffaaa3"))
        self.stop_button.bind("<Leave>", lambda _event: self.stop_button.itemconfigure("cross", fill="#a2abb5"))
        self.root.bind("<Button-3>", self.show_menu)
        self.root.bind("<Alt-ButtonPress-1>", self.drag_start)
        self.root.bind("<Alt-B1-Motion>", self.drag_move)
        self.root.bind("<Alt-ButtonRelease-1>", self.drag_end)
        self.root.bind("<Escape>", lambda _event: self.stop_generation() if self.busy else self.new_question())
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Enter>", self.check_hover, add="+")
        self.root.bind("<Leave>", self.check_hover, add="+")
        for target in (self.root, self.background, self.outer, self.main, self.input_surface,
                       self.entry, self.answer_surface, self.answer, self.grip, self.attachment_frame):
            target.drop_target_register(DND_FILES)
            target.dnd_bind("<<Drop>>", self.drop_images)
        x = (self.root.winfo_screenwidth() - self.width) // 2
        y = (self.root.winfo_screenheight() - self.height) // 2
        self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")
        self.root.after_idle(self.update_hover)

    def check_hover(self, _event=None):
        self.root.after_idle(self.update_hover)

    def update_hover(self):
        x, y = self.root.winfo_pointerxy()
        hovered = self.root.winfo_containing(x, y)
        over_bar = self.drag is not None or (hovered is not None and hovered.winfo_toplevel() is self.root)
        target = HOVER_OPACITY if over_bar else IDLE_OPACITY
        if target == self.opacity_target:
            return
        self.opacity_target = target
        if self.opacity_job is None:
            self.animate_opacity()

    def animate_opacity(self):
        current = float(self.root.attributes("-alpha"))
        difference = self.opacity_target - current
        if abs(difference) <= 0.04:
            self.root.attributes("-alpha", self.opacity_target)
            self.opacity_job = None
            return
        self.root.attributes("-alpha", current + (0.04 if difference > 0 else -0.04))
        self.opacity_job = self.root.after(16, self.animate_opacity)

    def paint_background(self, event):
        self.paint_rounded(self.background, event.width, event.height, 24, PANEL)

    @staticmethod
    def paint_rounded(canvas, width, height, radius, color):
        canvas.delete("shape")
        canvas.create_rectangle(radius, 0, width-radius, height, fill=color, outline=color, tags="shape")
        canvas.create_rectangle(0, radius, width, height-radius, fill=color, outline=color, tags="shape")
        for x in (0, width-2*radius):
            for y in (0, height-2*radius):
                canvas.create_oval(x, y, x+2*radius, y+2*radius, fill=color, outline=color, tags="shape")
        canvas.tag_lower("shape")

    def paint_input(self, event):
        self.input_surface.coords(self.entry_window, 3, event.height / 2)
        self.input_surface.itemconfigure(self.entry_window, anchor="w", width=max(1, event.width-6),
                                         height=min(max(1, event.height), self.entry.winfo_reqheight()))

    def paint_answer(self, event):
        if self.height == 50:
            line_height = self.answer_font.metrics("linespace") + 2 * (
                int(self.answer["borderwidth"]) + int(self.answer["highlightthickness"]) + int(self.answer["pady"]))
            self.answer_surface.coords(self.answer_window, 3, event.height / 2)
            self.answer_surface.itemconfigure(self.answer_window, anchor="w", width=max(1, event.width-6),
                                              height=min(max(1, event.height), line_height))
        else:
            self.answer_surface.coords(self.answer_window, 3, 4)
            self.answer_surface.itemconfigure(self.answer_window, anchor="nw", width=max(1, event.width-6),
                                              height=max(1, event.height-8))

    def resize(self, height):
        y = self.root.winfo_y() - (height - self.root.winfo_height())
        self.height = height
        self.root.geometry(f"{self.width}x{height}+{self.root.winfo_x()}+{y}")

    def drag_start(self, event):
        self.drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())
        self.check_hover()

    def drag_move(self, event):
        if self.drag:
            self.root.geometry(f"+{event.x_root-self.drag[0]}+{event.y_root-self.drag[1]}")

    def drag_end(self, _event=None):
        self.drag = None
        self.check_hover()

    def on_return(self, event):
        if event.state & 0x1:
            return None
        self.submit()
        return "break"

    def prepare_answer(self):
        self.answer_source = ""
        self.show_stop_button(True)
        self.attachment_frame.pack_forget()
        self.input_surface.pack_forget()
        self.answer.configure(state="normal")
        self.answer.delete("1.0", "end")
        self.answer.configure(state="disabled")
        self.answer_surface.pack(fill="both", expand=True)
        self.resize(50)
        self.loading = True
        self.loading_frame = 0
        self.animate_loading(self.request_id)

    def animate_loading(self, request_id):
        if request_id != self.request_id or not self.busy or not self.loading:
            return
        frames = ("·", "··", "···")
        self.answer.configure(state="normal")
        self.answer.delete("1.0", "end")
        self.answer.insert("1.0", frames[self.loading_frame % len(frames)])
        self.answer.tag_add("loading", "1.0", "end")
        self.answer.configure(state="disabled")
        self.loading_frame += 1
        self.root.after(320, lambda: self.animate_loading(request_id))

    def append_answer(self, request_id, chunk):
        if request_id != self.request_id:
            return
        self.answer_source += chunk
        self.loading = False
        self.answer.configure(state="normal")
        self.answer.delete("1.0", "end")
        insert_markdown(self.answer, self.answer_source)
        self.answer.configure(state="disabled")
        self.fit_answer()

    def fit_answer(self):
        self.root.update_idletasks()
        count = self.answer.count("1.0", "end", "displaylines")
        lines = max(1, count[0] if count else 1)
        line_height = self.answer_font.metrics("linespace")
        self.resize(min(260, max(50, 20 + lines * line_height)))
        self.root.update_idletasks()
        self.answer.see("end-1c")
        self.root.after_idle(self.update_fade)

    def update_fade(self):
        if not self.answer.winfo_ismapped():
            return
        for tag in ("fade_top", "fade_middle", "fade_bottom"):
            self.answer.tag_remove(tag, "1.0", "end")
        if self.answer.yview()[0] <= 0:
            return
        line_height = self.answer_font.metrics("linespace")
        for index, tag in enumerate(("fade_top", "fade_middle", "fade_bottom")):
            start = self.answer.index(f"@0,{index * line_height}")
            end = self.answer.index(f"@0,{(index + 1) * line_height}")
            if self.answer.compare(start, "<", end):
                self.answer.tag_add(tag, start, end)

    def submit(self):
        if self.busy:
            return
        question = self.entry.get("1.0", "end-1c").strip()
        if not question and self.attachments:
            question = "Décris cette image." if len(self.attachments) == 1 else "Décris ces images."
        if not question:
            return
        if not self.model:
            self.choose_model()
            return
        self.busy = True
        self.request_id += 1
        request_id = self.request_id
        generation = GenerationRequest()
        self.active_request = generation
        user_message = {"role": "user", "content": question}
        image_names = [item["name"] for item in self.attachments]
        if self.attachments:
            user_message["images"] = [item["data"] for item in self.attachments]
        messages = self.context + [user_message]
        if self.system_prompt.strip():
            messages = [{"role": "system", "content": self.system_prompt}] + messages
        thinking = self.thinking.get()
        model = self.model
        self.prepare_answer()

        def work():
            try:
                parts = []
                pending = ""
                last_update = time.monotonic()
                for chunk in stream_ollama(messages, model, thinking=thinking, generation=generation):
                    if request_id != self.request_id:
                        return
                    parts.append(chunk)
                    pending += chunk
                    now = time.monotonic()
                    if len(parts) == 1 or now - last_update >= 0.05:
                        batch, pending = pending, ""
                        self.root.after(0, lambda value=batch: self.append_answer(request_id, value))
                        last_update = now
                if pending:
                    self.root.after(0, lambda value=pending: self.append_answer(request_id, value))
                result = "".join(parts)
                if not result.strip():
                    raise ValueError("Le modèle a renvoyé une réponse vide.")
            except GenerationCancelled:
                return
            except Exception as error:  # noqa: BLE001 - report worker failures in the UI
                try:
                    self.root.after(0, lambda detail=str(error): self.finish_error(request_id, detail))
                except (RuntimeError, tk.TclError):
                    pass
            else:
                try:
                    self.root.after(0, lambda: self.finish(request_id, question, result, user_message, image_names))
                except (RuntimeError, tk.TclError):
                    pass

        threading.Thread(target=work, daemon=True).start()

    def finish(self, request_id, question, result, user_message=None, image_names=None):
        if request_id != self.request_id:
            return
        self.busy = False
        self.loading = False
        self.active_request = None
        self.show_stop_button(False)
        self.fit_answer()
        self.context.extend([user_message if user_message is not None else {"role": "user", "content": question},
                             {"role": "assistant", "content": result}])
        self.history.append({"at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                             "question": question, "answer": result, "images": image_names or []})
        self.attachments.clear()
        self.attachment_photos.clear()
        try:
            write_history(self.history)
        except OSError as error:
            messagebox.showwarning("Hauhau", f"Historique non enregistré : {error}", parent=self.root)
        if self.voice.get():
            threading.Thread(target=self.safe_speak, args=(markdown_plain(result),), daemon=True).start()

    def finish_error(self, request_id, error):
        if request_id == self.request_id:
            self.busy = False
            self.loading = False
            self.active_request = None
            self.show_stop_button(False)
            self.answer.configure(state="normal")
            self.answer.delete("1.0", "end")
            self.answer.insert("1.0", f"Ollama indisponible : {error}\nClique pour réessayer.")
            self.answer.configure(state="disabled")
            self.fit_answer()

    def safe_speak(self, text):
        try:
            speak(text)
        except (OSError, subprocess.CalledProcessError):
            self.root.after(0, lambda: messagebox.showwarning("Hauhau", "La voix Windows n'est pas disponible.", parent=self.root))

    def show_stop_button(self, visible):
        self.outer.place_configure(width=-68 if visible else -44)
        if visible:
            self.stop_button.place(relx=1, rely=1, x=-44, y=-25, anchor="center")
        else:
            self.stop_button.place_forget()

    def stop_generation(self):
        if not self.busy:
            return
        generation = self.active_request
        self.active_request = None
        self.request_id += 1
        self.busy = False
        was_loading = self.loading
        self.loading = False
        if generation is not None:
            generation.cancel()
        self.show_stop_button(False)
        if was_loading:
            self.new_question(clear=False)
        else:
            self.fit_answer()

    def close(self):
        self.stop_generation()
        self.root.destroy()

    def new_question(self, clear=True):
        if self.busy:
            return
        self.answer_surface.pack_forget()
        if clear:
            self.entry.delete("1.0", "end")
            self.attachments.clear()
        self.input_surface.pack(side="left", fill="both", expand=True)
        self.refresh_attachments()
        self.resize(50)
        self.entry.focus_set()

    def reset_context(self):
        self.stop_generation()
        self.request_id += 1
        self.busy = False
        self.loading = False
        self.context.clear()
        self.new_question()

    def toggle_startup(self):
        try:
            set_startup(self.autostart.get())
        except OSError as error:
            self.autostart.set(startup_enabled())
            messagebox.showerror("Hauhau", f"Démarrage Windows : {error}", parent=self.root)

    def toggle_thinking(self):
        try:
            write_thinking(self.thinking.get())
        except OSError as error:
            self.thinking.set(not self.thinking.get())
            messagebox.showerror("Hauhau", f"Réglage non enregistré : {error}", parent=self.root)

    def edit_system_prompt(self):
        if self.prompt_window is not None and self.prompt_window.winfo_exists():
            self.prompt_window.lift()
            return
        window = tk.Toplevel(self.root)
        self.prompt_window = window
        window.title("Modifier le contexte général")
        window.configure(bg=BG)
        window.geometry("560x380")
        window.minsize(420, 300)
        window.attributes("-topmost", True)
        tk.Label(window, text="Consignes générales · prompt système", bg=BG, fg=FG,
                 font=("Segoe UI", 12)).pack(anchor="w", padx=18, pady=(18, 8))
        tk.Label(window, text="Ton, rôle, langue, préférences… Ces consignes seront utilisées à chaque question.\n"
                              "Laisse vide pour le comportement par défaut. La conversation est conservée.",
                 bg=BG, fg="#a2abb5", justify="left", font=("Segoe UI", 9), wraplength=520,
                 ).pack(anchor="w", padx=18, pady=(0, 12))
        footer = tk.Frame(window, bg=BG)
        footer.pack(side="bottom", fill="x", padx=18, pady=14)
        editor = tk.Text(window, wrap="word", bg=PANEL, fg=FG, insertbackground=ACCENT,
                         relief="flat", padx=10, pady=10, font=("Segoe UI", 10), undo=True)
        editor.pack(fill="both", expand=True, padx=18)
        editor.insert("1.0", self.system_prompt)
        tk.Button(footer, text="Enregistrer", command=lambda: self.save_system_prompt(editor, window),
                  bg=ACCENT, fg=BG, relief="flat", cursor="hand2", padx=14, pady=6,
                  ).pack(side="right")
        tk.Button(footer, text="Annuler", command=window.destroy, bg=PANEL, fg=FG,
                  relief="flat", cursor="hand2", padx=14, pady=6).pack(side="right", padx=8)
        tk.Button(footer, text="Effacer", command=lambda: editor.delete("1.0", "end"), bg=BG,
                  fg="#a2abb5", relief="flat", cursor="hand2", pady=6).pack(side="left")
        editor.focus_set()

    def save_system_prompt(self, editor, window):
        value = editor.get("1.0", "end-1c").strip()
        try:
            write_settings(system_prompt=value)
        except OSError:
            messagebox.showerror("Consignes générales", "Les consignes n'ont pas pu être enregistrées.", parent=window)
            return
        self.system_prompt = value
        window.destroy()

    def choose_model(self):
        if self.model_window is not None and self.model_window.winfo_exists():
            self.model_window.lift()
            return
        window = tk.Toplevel(self.root)
        self.model_window = window
        window.title("Choisir un modèle Ollama")
        window.configure(bg=BG)
        window.geometry("460x360")
        window.minsize(360, 280)
        window.attributes("-topmost", True)
        tk.Label(window, text="Modèles installés dans Ollama", bg=BG, fg=FG,
                 font=("Segoe UI", 12)).pack(anchor="w", padx=18, pady=(18, 6))
        status = tk.Label(window, text="Chargement…", bg=BG, fg="#a2abb5",
                          wraplength=420, justify="left")
        status.pack(anchor="w", padx=18, pady=(0, 8))
        model_list = tk.Listbox(window, bg=PANEL, fg=FG, selectbackground=ACCENT,
                                selectforeground=BG, relief="flat", font=("Segoe UI", 10))
        model_list.pack(fill="both", expand=True, padx=18)

        def select_model(_event=None):
            selected = model_list.curselection()
            if not selected or self.busy:
                return
            model = model_list.get(selected[0])
            try:
                write_settings(model=model)
            except OSError as error:
                messagebox.showerror("Modèle Ollama", f"Choix non enregistré : {error}", parent=window)
                return
            if model != self.model:
                self.context.clear()
            self.model = model
            window.destroy()

        model_list.bind("<Double-Button-1>", select_model)
        footer = tk.Frame(window, bg=BG)
        footer.pack(fill="x", padx=18, pady=14)
        tk.Button(footer, text="Actualiser", command=lambda: refresh(), bg=PANEL, fg=FG,
                  relief="flat", cursor="hand2", padx=12, pady=6).pack(side="left")
        tk.Button(footer, text="Utiliser ce modèle", command=select_model, bg=ACCENT, fg=BG,
                  relief="flat", cursor="hand2", padx=12, pady=6).pack(side="right")

        refresh_id = 0

        def refresh():
            nonlocal refresh_id
            refresh_id += 1
            current_id = refresh_id
            status.configure(text="Chargement…")
            model_list.delete(0, "end")

            def work():
                try:
                    models = list_ollama_models()
                    error = None
                except (OSError, http.client.HTTPException, ValueError, TypeError) as exc:
                    models, error = [], str(exc)

                def display():
                    if not window.winfo_exists() or current_id != refresh_id:
                        return
                    if error:
                        status.configure(text=f"Ollama indisponible : {error}")
                    elif not models:
                        status.configure(text="Aucun modèle installé. Lance « ollama pull <modèle> », puis actualise.")
                    else:
                        status.configure(text="Choisis un modèle. Le contexte en mémoire sera effacé si tu changes de modèle.")
                        for model in models:
                            model_list.insert("end", model)
                        if self.model in models:
                            model_list.selection_set(models.index(self.model))
                            model_list.see(models.index(self.model))
                try:
                    self.root.after(0, display)
                except (RuntimeError, tk.TclError):
                    pass

            threading.Thread(target=work, daemon=True).start()

        refresh()

    def refresh_attachments(self):
        for child in self.attachment_frame.winfo_children():
            child.destroy()
        self.attachment_photos.clear()
        self.attachment_frame.pack_forget()
        if not self.attachments or not self.input_surface.winfo_manager():
            return
        self.attachment_frame.pack(side="left", before=self.input_surface, fill="y", padx=(0, 4))
        for index, item in enumerate(self.attachments):
            photo = ImageTk.PhotoImage(item["preview"], master=self.root)
            self.attachment_photos.append(photo)
            frame = tk.Frame(self.attachment_frame, width=32, height=38, bg=PANEL)
            frame.pack(side="left")
            frame.pack_propagate(False)
            thumbnail = tk.Label(frame, image=photo, bg=PANEL, cursor="hand2", bd=0)
            thumbnail.place(x=1, y=5, width=28, height=28)
            remove = tk.Label(frame, text="×", font=("Segoe UI", 8), bg=PANEL,
                              fg=FG, cursor="hand2", bd=0)
            remove.place(x=22, y=0, width=10, height=12)
            for target in (frame, thumbnail, remove):
                target.bind("<Button-1>", lambda _event, value=index: self.remove_attachment(value))
                target.drop_target_register(DND_FILES)
                target.dnd_bind("<<Drop>>", self.drop_images)

    def remove_attachment(self, index):
        if not self.busy and index < len(self.attachments):
            self.attachments.pop(index)
            self.refresh_attachments()

    def clear_attachments(self):
        if not self.busy:
            self.attachments.clear()
            self.refresh_attachments()

    def add_images(self, paths):
        if self.busy:
            return False
        if not self.input_surface.winfo_manager():
            self.new_question()
        added = False
        errors = []
        for path in paths:
            if len(self.attachments) >= MAX_IMAGES:
                errors.append("Maximum 4 images par question.")
                break
            try:
                self.attachments.append(read_attachment(path))
                added = True
            except (OSError, ValueError, Image.DecompressionBombError) as error:
                detail = str(error) if isinstance(error, ValueError) else "Fichier inaccessible ou format non reconnu."
                errors.append(f"{Path(path).name} : {detail}")
        self.refresh_attachments()
        self.entry.focus_set()
        if errors:
            messagebox.showwarning("Ajouter des images", "\n".join(errors), parent=self.root)
        return added

    def choose_images(self):
        if self.busy:
            return
        paths = filedialog.askopenfilenames(parent=self.root, title="Ajouter des images",
                                           filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff"),
                                                      ("Tous les fichiers", "*.*")])
        if paths:
            self.add_images(paths)

    def drop_images(self, event):
        if self.busy:
            return "refuse_drop"
        return "copy" if self.add_images(self.root.tk.splitlist(event.data)) else "refuse_drop"

    def paste_image(self, _event=None):
        if self.busy:
            return "break"
        try:
            value = ImageGrab.grabclipboard()
            if isinstance(value, list):
                self.add_images(value)
                return "break"
            if not isinstance(value, Image.Image):
                return None
            if len(self.attachments) >= MAX_IMAGES:
                messagebox.showwarning("Ajouter des images", "Maximum 4 images par question.", parent=self.root)
                return "break"
            self.attachments.append(make_attachment(value, "Image collée"))
            self.refresh_attachments()
        except (OSError, ValueError, Image.DecompressionBombError):
            messagebox.showwarning("Ajouter des images", "Impossible de lire cette image du presse-papiers.", parent=self.root)
        return "break"

    def show_capabilities(self):
        messagebox.showinfo(
            "Ce que l'assistant peut faire",
            "Texte : écrire, résumer, traduire, expliquer, aider à coder.\n\n"
            "Images : décrire, comparer, analyser une capture ou lire du texte visible si le modèle choisi les accepte.\n"
            "Dépose jusqu'à 4 images sur la barre, ou colle une image avec Ctrl+V.\n"
            "Clique sur une vignette pour retirer l'image avant l'envoi.\n\n"
            "Consignes générales et modèle Ollama : réglables au clic droit.\n\n"
            "Internet : aucun accès dans cette version. Il ne consulte pas les sites et ne connaît pas les nouvelles en direct.\n\n"
            "Tout est traité sur ce PC. Les images restent dans la conversation en mémoire ;\n"
            "l'historique garde uniquement les échanges et les noms des images.",
            parent=self.root,
        )

    def show_menu(self, event):
        menu = tk.Menu(self.root, tearoff=False, bg=PANEL, fg=FG, activebackground=ACCENT)
        menu.add_command(label="Nouvelle question", command=self.new_question)
        menu.add_command(label=f"Modèle Ollama : {self.model or 'choisir…'}", command=self.choose_model)
        menu.add_command(label="Modifier le contexte général…", command=self.edit_system_prompt)
        menu.add_command(label="Ajouter des images…", command=self.choose_images,
                         state="disabled" if self.busy else "normal")
        if self.attachments:
            menu.add_command(label="Retirer les images", command=self.clear_attachments,
                             state="disabled" if self.busy else "normal")
        menu.add_command(label="Historique", command=self.show_history)
        menu.add_command(label="Réinitialiser le contexte", command=self.reset_context)
        menu.add_separator()
        menu.add_checkbutton(label="Mode réflexion du modèle", variable=self.thinking, command=self.toggle_thinking)
        menu.add_checkbutton(label="Lire les réponses à voix haute", variable=self.voice)
        menu.add_checkbutton(label="Démarrer avec Windows", variable=self.autostart, command=self.toggle_startup)
        menu.add_command(label="Ce que l'assistant peut faire…", command=self.show_capabilities)
        menu.add_separator()
        menu.add_command(label="Quitter", command=self.close)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def show_history(self):
        if self.history_window is not None and self.history_window.winfo_exists():
            self.history_window.lift()
            return
        window = tk.Toplevel(self.root)
        self.history_window = window
        window.title("Hauhau · historique local")
        window.configure(bg=BG)
        window.geometry("580x460")
        window.attributes("-topmost", True)
        delete_button = tk.Button(
            window, text="Effacer l'historique", command=lambda: self.clear_history(text),
            bg=PANEL, fg=FG, activebackground=BG, activeforeground=FG,
            relief="flat", cursor="hand2", font=("Segoe UI", 10), pady=6,
        )
        delete_button.pack(side="bottom", fill="x", padx=18, pady=(0, 14))
        text = tk.Text(window, wrap="word", bg=BG, fg=FG, relief="flat",
                       padx=18, pady=18, font=("Segoe UI", 10))
        configure_markdown(text)
        text.pack(fill="both", expand=True)
        if not self.history:
            text.insert("end", "Aucun échange enregistré.")
        for item in reversed(self.history):
            image_note = f"Images : {', '.join(item.get('images', []))}\n" if item.get("images") else ""
            text.insert("end", f"{item.get('at', '')}\nVous : {item.get('question', '')}\n{image_note}\n"
                               "Hauhau : ")
            insert_markdown(text, item.get("answer", ""))
            text.insert("end", f"\n\n{'─'*54}\n\n", ())
        text.configure(state="disabled")

    def clear_history(self, text):
        try:
            HISTORY.unlink(missing_ok=True)
        except OSError as error:
            messagebox.showerror("Hauhau", f"Historique non effacé : {error}", parent=self.history_window)
            return
        self.history.clear()
        text.configure(state="normal")
        text.delete("1.0", "end")
        text.insert("end", "Aucun échange enregistré.")
        text.configure(state="disabled")


if __name__ == "__main__":
    Widget().root.mainloop()
