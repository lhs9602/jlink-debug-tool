# -*- coding: utf-8 -*-
"""
tdc_vmag_window.py - vMag 창 프로세스 (설계 결정_D57, D58, D65)

보기 3 가지(실시간, 구간 평균, 최근 평균), 곡선 5 개 캡처, 체크된 캡처만 삭제.
main 은 ('frames', [32 밴드 x 8 프레임]) 을 보낸다. 설계 화면 견본에서 옮겼다.
"""

import collections
import math
import queue
import time

from .tdc_graph_common import (TDC_BANDS, TDC_CAPTURE_MAX, TDC_DMIC_FRAME, TDC_DMIC_FULL_SCALE, TDC_DMIC_HIST_SEC,
                               TDC_DMIC_MAX_BINS, TDC_DMIC_SR, TDC_DMIC_STATS_SEC, TDC_DMIC_WAVE_SEC, TDC_IDLE_SEC,
                               TDC_NOISE_GATE_SPL, TDC_ROTATION_SPL, TDC_SPL_OFFSET_DB, tdc_graph_loop, tdc_graph_setup)

TDC_VMAG_MAX = (1 << 23) - 1    # vMag 최대. CFX 24 비트 int, sqrt(Re^2 + Im^2) 라 0 이상 (1.5 FrequencyAnalysis.c:79-81)
TDC_VMAG_TICKS = ((1, "1"), (10, "10"), (100, "100"), (1000, "1k"), (10000, "10k"), (100000, "100k"),
                  (1000000, "1M"), (TDC_VMAG_MAX, "8.4M"))  # 세로축 눈금 (값, 글자)


def tdc_vmag_window(from_main, selftest, to_main=None):     # to_main: main 에 보내는 통로 (vMag 창은 쓰지 않는다)
    """vMag 창 프로세스. 보기 방식 3 가지, 곡선 5 개 캡처와 체크박스"""
    tk, ttk, np, Figure, FigureCanvasTkAgg = tdc_graph_setup()

    colors = ["#d62728", "#2ca02c", "#ff7f0e", "#9467bd", "#8c564b"]
    root = tk.Tk()
    root.title("vMag")
    root.geometry("980x600+920+40")

    top = ttk.Frame(root, padding=6)
    top.pack(side="top", fill="x")
    mode = tk.StringVar(value="live")
    ttk.Label(top, text="보기").pack(side="left")
    for text, value in (("실시간", "live"), ("구간 평균", "block"), ("최근 평균", "moving")):
        ttk.Radiobutton(top, text=text, value=value, variable=mode).pack(side="left", padx=4)
    ttk.Label(top, text="   프레임 수 N").pack(side="left")
    n_var = tk.StringVar(value="500")
    ttk.Spinbox(top, from_=1, to=10000, increment=50, width=7, textvariable=n_var).pack(side="left", padx=4)
    info = tk.StringVar(value="받은 프레임 0")
    ttk.Label(top, textvariable=info).pack(side="right")

    side = ttk.Frame(root, padding=6)
    side.pack(side="right", fill="y")
    ttk.Label(side, text="캡처 (5 개까지)").pack(anchor="w")

    fig = Figure(figsize=(7.6, 5.0), dpi=100)
    ax = fig.add_subplot(111)
    x = np.arange(1, TDC_BANDS + 1)
    live_line, = ax.plot(x, np.zeros(TDC_BANDS), color="#1f77b4", linewidth=2.0, marker="o", markersize=3, label="현재")
    ax.set_xlim(0.5, TDC_BANDS + 0.5)
    # 세로축은 로그 눈금, 1 ~ vMag 최대로 고정한다 (작은 값과 큰 값이 함께 보인다. DNN 도 vMag 를 log2 로 바꿔 본다).
    # 값을 log10 으로 바꿔 보통 축에 그리고 눈금 글자만 붙인다 (vmag_plot)
    ax.set_ylim(0, math.log10(TDC_VMAG_MAX))
    ax.set_yticks([math.log10(v) for v, _ in TDC_VMAG_TICKS])
    ax.set_yticklabels([s for _, s in TDC_VMAG_TICKS])
    ax.set_xlabel("밴드")
    ax.set_ylabel("vMag 대표값 (로그 눈금)")
    ax.grid(True, alpha=0.3)
    vmag_idle = ax.text(0.5, 0.5, "비활성  (capture vmag on)", transform=ax.transAxes,
                        ha="center", va="center", fontsize=13, color="#888888")
    canvas = FigureCanvasTkAgg(fig, master=root)
    canvas.get_tk_widget().pack(side="left", fill="both", expand=True)

    st = {"count": 0, "sum": np.zeros(TDC_BANDS), "n": 0, "win": collections.deque(),
          "shown": np.zeros(TDC_BANDS), "last_mode": "live", "last_n": 500, "dirty": False, "last": 0.0}
    caps = []       # {"slot", "line", "var", "check"}

    def vmag_plot(values):
        """그릴 값: log10. 1 보다 작은 값 (0) 은 1 (아래 끝) 로 올린다. 새 배열이라 캡처는 복사본이 된다"""
        return np.log10(np.maximum(values, 1.0))

    def get_n():
        try:
            return max(1, min(10000, int(n_var.get())))
        except ValueError:
            return st["last_n"]

    def reset_avg():
        st["sum"] = np.zeros(TDC_BANDS)
        st["n"] = 0
        st["win"].clear()

    def feed(frame, m, n):
        if m == "live":
            st["shown"] = frame
            st["dirty"] = True
        elif m == "block":
            st["sum"] += frame
            st["n"] += 1
            if st["n"] >= n:
                st["shown"] = st["sum"] / st["n"]
                st["dirty"] = True
                st["sum"] = np.zeros(TDC_BANDS)
                st["n"] = 0
        else:
            st["win"].append(frame)
            st["sum"] += frame
            while len(st["win"]) > n:
                st["sum"] -= st["win"].popleft()
            st["shown"] = st["sum"] / len(st["win"])
            st["dirty"] = True

    def refresh_legend():
        handles = [live_line] + [c["line"] for c in caps if c["var"].get()]
        ax.legend(handles=handles, loc="upper right", fontsize=8)
        canvas.draw_idle()

    def on_check():
        for c in caps:
            c["line"].set_visible(bool(c["var"].get()))
        refresh_legend()

    def on_capture():
        if len(caps) >= TDC_CAPTURE_MAX:
            info.set("캡처 5 개가 찼습니다. 삭제한 뒤 캡처하세요")
            return
        used = [c["slot"] for c in caps]
        k = [s for s in range(TDC_CAPTURE_MAX) if s not in used][0]     # 비어 있는 가장 앞 번호 (색도 이 번호를 따른다)
        names = {"live": "실시간", "block": "구간 평균", "moving": "최근 평균"}
        label = "캡처 %d (%s, %s)" % (k + 1, names[mode.get()], time.strftime("%H:%M:%S"))
        line, = ax.plot(x, vmag_plot(st["shown"]), color=colors[k], linewidth=1.4, linestyle="--", label=label)
        var = tk.IntVar(value=1)
        check = tk.Checkbutton(side, text=label, variable=var, command=on_check, fg=colors[k], anchor="w")
        check.pack(anchor="w")
        caps.append({"slot": k, "line": line, "var": var, "check": check})
        refresh_legend()

    def on_clear():
        """체크된 캡처만 지운다. 체크를 끈 캡처는 남는다"""
        keep = []
        for c in caps:
            if c["var"].get():
                c["line"].remove()
                c["check"].destroy()
            else:
                keep.append(c)
        if len(keep) == len(caps):
            info.set("삭제할 캡처를 체크하세요")
            return
        caps[:] = keep
        if info.get().startswith("캡처 5"):
            info.set("받은 프레임 %d" % st["count"])
        refresh_legend()

    ttk.Button(top, text="캡처", command=on_capture).pack(side="left", padx=(16, 4))
    ttk.Button(top, text="캡처 삭제", command=on_clear).pack(side="left")
    refresh_legend()

    def tick():
        m, n = mode.get(), get_n()
        if m != st["last_mode"] or n != st["last_n"]:
            reset_avg()
            st["last_mode"], st["last_n"] = m, n
        try:
            while True:
                kind, payload = from_main.get_nowait()
                if kind == "frames":
                    for f in payload:
                        feed(np.asarray(f, dtype=float), m, n)
                        st["count"] += 1
                    st["last"] = time.time()
        except queue.Empty:
            pass
        vmag_on = (time.time() - st["last"]) < TDC_IDLE_SEC
        redraw = False
        if vmag_idle.get_visible() == vmag_on:           # 상태가 바뀌었을 때만
            vmag_idle.set_visible(not vmag_on)
            redraw = True
        if st["dirty"]:
            st["dirty"] = False
            live_line.set_ydata(vmag_plot(st["shown"]))
            redraw = True
        if redraw:
            canvas.draw_idle()
        if not info.get().startswith(("캡처 5", "삭제할 캡처")):
            info.set("받은 프레임 %d" % st["count"])

    close_window = tdc_graph_loop(root, tick, 40)
    if selftest:
        root.after(900, on_capture)
        root.after(1200, lambda: mode.set("moving"))
        root.after(1800, on_capture)
        root.after(2000, lambda: caps[0]["var"].set(0) or on_check())
        root.after(2200, on_clear)          # 체크된 캡처 2 만 지워지고 캡처 1 은 남는다
        root.after(2400, on_capture)        # 비어 있는 번호 2 로 다시 들어간다

        def check_result():
            slots = sorted(c["slot"] for c in caps)
            assert slots == [0, 1], slots
            assert st["count"] > 0 and not vmag_idle.get_visible(), st["count"]
            print("selftest vmag: capture slots %s, frames %d" % ([s + 1 for s in slots], st["count"]), flush=True)
        root.after(2800, check_result)
        root.after(3000, close_window)
    root.mainloop()
