# -*- coding: utf-8 -*-
"""
tdc_terminal.py - 터미널 창 (설계 결정_D61, D62, D65, D66)

창 1 개를 좌우로 나눈다. 왼쪽 RTT 터미널 (화면을 클릭하고 키를 누르면 한 글자씩 바로 타깃으로),
오른쪽 pylink 터미널 (입력 칸에 명령, Enter). 이 창을 닫으면 전부 끝난다 (main 과 그래프 창도).
그래프 창은 main 이 ('open', 기능) 을 보내면 연다 (capture ... on 이 받아들여졌을 때). 창을 닫으면 capture ... off 를 보낸다.
그래프 창에는 main 에 보내는 통로(명령 통로)도 넘긴다. DMIC 창은 주입 조작을 이 통로로 보낸다 (결정_D76).
새 글이 붙을 때 스크롤이 맨 아래에 있으면 따라 내려가고, 위로 올려 보고 있으면 그 자리에 둔다 (RTT, pylink 모두. 결정_D85).
친 명령은 맨 아래로 내린다.
설계 화면 견본에서 옮겼다. J-Link 를 만지지 않는다.
"""

import multiprocessing as mp
import queue
import re

from .tdc_dmic_window import tdc_dmic_window
from .tdc_vmag_window import tdc_vmag_window

# RTT 글의 ANSI 색 코드 (1.5 SEGGER_RTT.h RTT_CTRL_*: ESC[0m 초기화, ESC[2;3xm 보통, ESC[1;3xm 밝게).
# 화면에는 찍지 않고 글자색으로 바꾼다. 다른 제어 코드(화면 지우기 등)는 버린다.
TDC_ANSI_RE = re.compile(r"\x1b\[([0-9;]*)([A-Za-z])")
TDC_ANSI_NORMAL = {30: "#8a939b", 31: "#e06c75", 32: "#98c379", 33: "#e5c07b",
                   34: "#61afef", 35: "#c678dd", 36: "#56b6c2", 37: "#d8dee9"}
TDC_ANSI_BRIGHT = {30: "#aab3bb", 31: "#ff7b86", 32: "#b5e890", 33: "#ffd580",
                   34: "#82c4ff", 35: "#e39cff", 36: "#7fe0ea", 37: "#ffffff"}
TDC_NOTE_COLOR = "#f0c674"      # [연결] 알림, 창 열기와 닫기 알림
# 터미널 창 색. RTT 는 어두운 바탕 (TDC_UI), pylink 는 흰 바탕 (TDC_UI_LIGHT) 으로 두 터미널을 구분한다
TDC_UI = {"bg": "#1e2227", "panel": "#16191d", "head": "#252a31", "sash": "#2c313a", "fg": "#d8dee9",
          "dim": "#8a939b", "accent": "#61afef", "sel": "#3e4451", "ok": "#98c379", "bad": "#e06c75",
          "thumb": "#252a31", "thumb_on": "#3e4451", "scroll": "Vertical.TScrollbar"}
TDC_UI_LIGHT = {"panel": "#ffffff", "head": "#e9ebee", "fg": "#202020", "dim": "#6b7280", "accent": "#1f6feb",
                "sel": "#cfe3ff", "note": "#b26a00", "thumb": "#d5d9de", "thumb_on": "#b8bec6",
                "scroll": "Light.Vertical.TScrollbar"}
TDC_UI_FONT = ("Malgun Gothic", 9)
TDC_TEXT_FONT = ("Consolas", 10)

TDC_SELFTEST_COMMANDS = (
    # (ms, 명령). --selftest 에서 차례로 친다. 그래프 창은 스스로 3 초 뒤에 닫히고, 그때 capture off 가 나가야 한다
    (800, "status"),
    (1000, "read 0x21010000 6"),
    (1200, "write 0x21010000 1"),
    (1400, "capture dmic on"),
    (1600, "capture vmag on"),
    (2000, "save on"),
    (2200, "log 2"),
    (6500, "save off"),
    (9000, "status"),
)


def tdc_terminal_run(to_term, from_term, to_dmic, to_vmag, main_proc, stop_evt, selftest=False, title_note=""):
    import tkinter as tk
    from tkinter import ttk

    # 기능마다 창 (프로세스) 하나. 새 기능의 창은 여기에 한 줄 더한다
    windows = {"dmic": {"target": tdc_dmic_window, "queue": to_dmic, "proc": None, "name": "DMIC"},
               "vmag": {"target": tdc_vmag_window, "queue": to_vmag, "proc": None, "name": "vMag"}}

    root = tk.Tk()
    root.title("RTT + pylink 터미널" + title_note)
    root.geometry("1460x600")
    root.configure(bg=TDC_UI["bg"])
    style = ttk.Style(root)
    style.theme_use("clam")                              # 스크롤바 색을 바꿀 수 있는 테마 (이 창에만)
    for pal in (TDC_UI, TDC_UI_LIGHT):
        style.configure(pal["scroll"], background=pal["thumb"], troughcolor=pal["panel"], bordercolor=pal["panel"],
                        lightcolor=pal["thumb"], darkcolor=pal["thumb"], arrowcolor=pal["dim"])
        style.map(pal["scroll"], background=[("active", pal["thumb_on"])])

    # 아래 상태 줄. 왼쪽 네모의 색으로 연결 상태를 보인다 (초록 연결됨, 빨강 끊김, 회색 그 밖)
    bar = tk.Frame(root, bg=TDC_UI["head"])
    bar.pack(side="bottom", fill="x")
    dot = tk.Frame(bar, width=8, height=8, bg=TDC_UI["dim"])
    dot.pack(side="left", padx=(8, 6))
    status = tk.Label(bar, text="연결 중", anchor="w", bg=TDC_UI["head"], fg=TDC_UI["dim"], font=TDC_UI_FONT, pady=3)
    status.pack(side="left", fill="x", expand=True)

    def set_status(s):
        if s.startswith("연결됨"):
            color = TDC_UI["ok"]
        elif "끊김" in s or s.startswith("연결 안 됨"):
            color = TDC_UI["bad"]
        else:
            color = TDC_UI["dim"]
        dot.configure(bg=color)
        status.configure(text=s)

    pane = tk.PanedWindow(root, orient="horizontal", sashwidth=4, sashrelief="flat", bd=0, bg=TDC_UI["sash"])
    pane.pack(fill="both", expand=True)

    def make_side(title, ui, on_enter, hint, key_mode):
        """key_mode 가 참이면 입력 칸 없이 누른 키를 한 글자씩 바로 넘긴다 (RTT). 거짓이면 입력 칸 + Enter (pylink)
        위에 제목 줄 (제목, 안내), 가운데 글, 아래 입력 줄 (pylink 만). ui 는 색 (TDC_UI, TDC_UI_LIGHT)"""
        frame = tk.Frame(pane, bg=ui["panel"])
        head = tk.Frame(frame, bg=ui["head"])
        head.pack(side="top", fill="x")
        tk.Label(head, text=title, bg=ui["head"], fg=ui["fg"], font=("Malgun Gothic", 10, "bold"),
                 padx=8, pady=4).pack(side="left")
        tk.Label(head, text=hint, bg=ui["head"], fg=ui["dim"], font=TDC_UI_FONT).pack(side="left")
        entry = None
        if not key_mode:
            line = tk.Frame(frame, bg=ui["head"])
            line.pack(side="bottom", fill="x")
            tk.Label(line, text=">", bg=ui["head"], fg=ui["accent"], font=TDC_TEXT_FONT, padx=8).pack(side="left")
            entry = tk.Entry(line, bg=ui["head"], fg=ui["fg"], insertbackground=ui["fg"], relief="flat",
                             highlightthickness=0, font=TDC_TEXT_FONT)
            entry.pack(side="left", fill="x", expand=True, pady=5, padx=(0, 8))
        text = tk.Text(frame, bg=ui["panel"], fg=ui["fg"], insertbackground=ui["fg"], font=TDC_TEXT_FONT, wrap="none",
                       state="disabled", bd=0, highlightthickness=0, padx=8, pady=6,
                       selectbackground=ui["sel"], selectforeground=ui["fg"])
        scroll = ttk.Scrollbar(frame, command=text.yview, style=ui["scroll"])
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)

        text.bind("<Button-1>", lambda _e: text.focus_set())
        if key_mode:
            def key(event):
                if event.state & 0x4:                     # Ctrl 조합은 타깃에 보내지 않는다
                    k = event.keysym.lower()
                    if k == "c":
                        copy_sel(text)
                    elif k == "a":
                        text.tag_add("sel", "1.0", "end")
                    return "break"
                if event.char:
                    on_enter(event.char)
                return "break"
            text.bind("<Key>", key)
        else:
            text.bind("<Control-c>", lambda _e: copy_sel(text) or "break")
            text.bind("<Control-C>", lambda _e: copy_sel(text) or "break")
            def enter(_event=None):
                line = entry.get().strip()
                entry.delete(0, "end")
                if line:
                    on_enter(line)
            entry.bind("<Return>", enter)
        return frame, text, entry

    def copy_sel(text_widget):
        """선택한 글을 클립보드로. 선택이 없으면 아무 일도 하지 않는다"""
        try:
            sel = text_widget.get("sel.first", "sel.last")
        except tk.TclError:
            return
        root.clipboard_clear()
        root.clipboard_append(sel)

    follow = set()      # 글이 붙은 글 상자 가운데 맨 아래로 내릴 것. scroll_down 이 한 번에 내린다

    def at_bottom(text_widget):
        """스크롤이 맨 아래에 있는가 (글의 끝이 보이는가)"""
        return text_widget.yview()[1] >= 1.0

    def put(text_widget, s, tag=None, force=False):
        """글을 끝에 붙인다. 붙이기 전에 스크롤이 맨 아래에 있었으면 따라 내려가고, 위로 올려 보고 있었으면 보던 자리가
        그대로 남는다. force 가 참이면 스크롤 위치와 관계없이 내린다 (친 명령). 내리는 것은 scroll_down 이 한다"""
        if force or at_bottom(text_widget):
            follow.add(text_widget)
        text_widget.configure(state="normal")
        text_widget.insert("end", s, tag) if tag else text_widget.insert("end", s)
        text_widget.configure(state="disabled")

    def scroll_down():
        """표시해 둔 글 상자를 맨 아래로 내린다. 글을 붙인 뒤의 see 는 화면 배치를 다시 계산해 느리다 (한 번에 약 2 ms).
        글마다 부르면 RTT 글이 많을 때 창이 밀리므로, 한 번의 처리 끝에 글 상자마다 한 번만 부른다"""
        for text_widget in follow:
            text_widget.see("end")
        follow.clear()

    ansi = {"fg": None, "bright": False, "pending": ""}

    def ansi_tag(color):
        name = "fg" + color
        if name not in rtt_text.tag_names():
            rtt_text.tag_configure(name, foreground=color)
        return name

    def apply_sgr(params):
        for p in [int(x) if x else 0 for x in params.split(";")]:
            if p == 0:
                ansi["fg"], ansi["bright"] = None, False
            elif p == 1:
                ansi["bright"] = True
            elif p in (2, 22):
                ansi["bright"] = False
            elif p == 39:
                ansi["fg"] = None
            elif 30 <= p <= 37:
                ansi["fg"] = p

    def put_rtt(s):
        """RTT 글. ANSI 색 코드를 글자색으로 바꾼다. 조각 끝에서 잘린 코드는 다음 조각과 합친다.
        스크롤은 put 과 같다"""
        s = ansi["pending"] + s.replace("\r\n", "\n").replace("\r", "")
        ansi["pending"] = ""
        cut = s.rfind("\x1b")
        if cut != -1 and not TDC_ANSI_RE.match(s, cut) and len(s) - cut < 16:
            ansi["pending"], s = s[cut:], s[:cut]
        if at_bottom(rtt_text):
            follow.add(rtt_text)
        rtt_text.configure(state="normal")
        pos = 0
        for m in TDC_ANSI_RE.finditer(s):
            chunk = s[pos:m.start()].replace("\x1b", "")
            if chunk:
                table = TDC_ANSI_BRIGHT if ansi["bright"] else TDC_ANSI_NORMAL
                tag = ansi_tag(table[ansi["fg"]]) if ansi["fg"] else None
                rtt_text.insert("end", chunk, tag) if tag else rtt_text.insert("end", chunk)
            if m.group(2) == "m":
                apply_sgr(m.group(1))
            pos = m.end()
        chunk = s[pos:].replace("\x1b", "")
        if chunk:
            table = TDC_ANSI_BRIGHT if ansi["bright"] else TDC_ANSI_NORMAL
            tag = ansi_tag(table[ansi["fg"]]) if ansi["fg"] else None
            rtt_text.insert("end", chunk, tag) if tag else rtt_text.insert("end", chunk)
        rtt_text.configure(state="disabled")

    def send(item):
        try:
            from_term.put_nowait(item)
        except queue.Full:
            pass

    def open_window(key):
        """그 기능의 창이 없으면 연다. 이미 열려 있으면 그대로 둔다"""
        w = windows[key]
        if w["proc"] is not None and w["proc"].is_alive():
            return
        w["proc"] = mp.Process(target=w["target"], args=(w["queue"], selftest, from_term), daemon=True)
        w["proc"].start()
        put(cmd_text, "%s 창을 엽니다\n" % w["name"], tag="note")

    def on_rtt(ch):
        send(("rtt_in", ch))

    def on_cmd(line):
        put(cmd_text, "> %s\n" % line, tag="echo", force=True)     # 친 명령은 맨 아래로 내린다 (답이 보이게)
        scroll_down()
        send(("cmd", line))

    left, rtt_text, _unused = make_side("RTT 터미널", TDC_UI, on_rtt,
                                        "화면을 클릭하고 키를 누르면 한 글자씩 바로 타깃으로 보낸다", True)
    right, cmd_text, cmd_entry = make_side("pylink 터미널", TDC_UI_LIGHT, on_cmd, "명령 (Enter). help 로 목록", False)
    cmd_text.tag_configure("echo", foreground=TDC_UI_LIGHT["accent"])     # 친 명령
    cmd_text.tag_configure("log", foreground=TDC_UI_LIGHT["dim"])         # 종합 로그
    cmd_text.tag_configure("note", foreground=TDC_UI_LIGHT["note"])       # 창 열기, 닫기
    pane.add(left, minsize=300)
    pane.add(right, minsize=300)
    root.update_idletasks()
    pane.sash_place(0, 728, 0)
    cmd_entry.focus_set()

    auto_off = []       # 창이 닫혀 끈 기능 (점검용)

    def tick():
        rtt_parts = []      # 이어서 온 RTT 글. 모아서 한 번에 붙인다

        def put_rtt_parts():
            if rtt_parts:
                put_rtt("".join(rtt_parts))
                rtt_parts.clear()

        try:
            while True:
                kind, s = to_term.get_nowait()
                if kind == "rtt":
                    rtt_parts.append(s)
                elif kind == "rtt_note":
                    put_rtt_parts()
                    put(rtt_text, "[연결] %s\n" % s, tag=ansi_tag(TDC_NOTE_COLOR))   # 연결, 끊김, RTT 시작
                elif kind == "cmd":
                    put(cmd_text, s)                    # 명령에 대한 답, 자동 알림
                elif kind == "log":
                    put(cmd_text, s, tag="log")         # 종합 로그
                elif kind == "status":
                    set_status(s)
                elif kind == "open":
                    open_window(s)
        except queue.Empty:
            pass
        put_rtt_parts()
        for key, w in windows.items():
            if w["proc"] is not None and not w["proc"].is_alive():
                # 그래프 창이 닫혔다: 그 기능의 가져오기도 끈다
                w["proc"] = None
                send(("cmd", "capture %s off" % key))
                put(cmd_text, "%s 창이 닫혀 capture %s off\n" % (w["name"], key), tag="note")
                auto_off.append(key)
        scroll_down()
        if not main_proc.is_alive():
            set_status("main 프로세스 끊김")
        root.after(20, tick)

    def on_close():
        # 터미널 창을 닫으면 전부 끝난다: main 에 알리고, 그래프 창도 닫는다
        send(("quit", ""))
        main_proc.join(3.0)
        stop_evt.set()
        for w in windows.values():
            if w["proc"] is not None and w["proc"].is_alive():
                w["proc"].terminate()
        if main_proc.is_alive():
            main_proc.terminate()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.after(20, tick)
    if selftest:
        root.after(600, lambda: on_rtt("v"))
        for ms, line in TDC_SELFTEST_COMMANDS:
            root.after(ms, lambda s=line: on_cmd(s))
        root.after(9800, lambda: print("selftest terminal: auto off %s, main alive %s" % (
            sorted(auto_off), main_proc.is_alive()), flush=True))
        root.after(10000, on_close)
    root.mainloop()
