# -*- coding: utf-8 -*-
"""
tdc_ifft_window.py - IFFT 창 프로세스 (IFFT 오디오 모드의 출력을 기존 출력과 견준다)

그래프 둘. 크기, 세로 눈금, 가로 눈금, 색, 그리는 방법이 같다 (조건이 같아야 견줄 수 있다):
  위     기존 DAC 출력     기존 경로가 DAC 로 내는 것 (AGC 출력). IFFT 오디오 모드에서도 계산되므로 늘 받는다
  아래   IFFT 후 DAC 출력   IFFT 오디오 모드가 DAC 로 낸 것. 지연만큼 당겨 위와 같은 시간에 놓는다.
                           모드가 꺼져 있으면 DAC 로 나간 것이 기존 출력이라 위와 같다
가로 눈금은 ms 다. 좁은 구간에서는 세로 줄이 1 ms 마다 있고, 그것이 펌웨어의 16 샘플 묶음의 경계다.
보는 순서: 흐르는 동안에는 3 초 전체만 보인다 (수십 ms 짜리 그림은 계속 바뀌면 사람이 읽을 수 없다).
  멈춤을 누르면 그때의 3 초가 멈춰 서고, 구간을 좁혀 아래 막대로 옮겨 가며 본다. 그래프를 클릭하면 그 자리로 간다.
  흐르는 중에 좁은 구간을 고르면 저절로 멈춘다. 이어서를 누르면 3 초로 돌아가 다시 흐른다.
맨 위 글: IFFT 모드, 지연 (기대, 측정), 크기 비, 오차, 최대 차. 계산은 tdc_ifft_compare.py 가 한다.
main 은 ('ifft', (기준 512, 출력 512, mode_cnt, 놓친 ms)) 를 보낸다 (두 목록은 시간 순서. 기준 = 기존 DAC 출력).
모드는 RTT 터미널의 i 키로 바꾼다. 이 창은 보이기만 한다.
"""

import queue
import time

from .tdc_graph_common import (TDC_DMIC_FULL_SCALE, TDC_DMIC_MAX_BINS, TDC_DMIC_SR, TDC_IDLE_SEC, TDC_IFFT_SPANS,
                               TDC_IFFT_VALUE_SHIFT, TdcFastCanvas, tdc_graph_loop, tdc_graph_setup)
from .tdc_ifft_compare import (TDC_IFFT_MAX_LAG, TDC_IFFT_MODE_MIXED, TDC_IFFT_MODE_OFF, TDC_IFFT_MODE_ON,
                               TdcIfftCompare)

TDC_IFFT_WAITING = "waiting for IFFT ... (capture ifft on)\n"
TDC_IFFT_MODE_TEXT = {None: "-", TDC_IFFT_MODE_OFF: "끔", TDC_IFFT_MODE_ON: "켬", TDC_IFFT_MODE_MIXED: "전환 중"}
TDC_IFFT_ENVELOPE_FROM = 6000    # 그릴 샘플이 이보다 많으면 선 대신 화면 한 칸마다 세로 막대로 그린다
TDC_IFFT_DOTS_UPTO = 200         # 그릴 샘플이 이보다 적으면 샘플마다 점을 찍는다
TDC_IFFT_COLOR = "cyan"          # 두 그래프가 같은 색이다


def tdc_ifft_window(from_main, selftest, to_main=None):     # to_main: main 에 보내는 통로 (IFFT 창은 쓰지 않는다)
    """IFFT 창 프로세스."""
    tk, ttk, np, Figure, FigureCanvasTkAgg = tdc_graph_setup()
    from matplotlib.collections import PolyCollection
    from matplotlib.ticker import MaxNLocator, MultipleLocator, NullLocator

    scale = float(1 << TDC_IFFT_VALUE_SHIFT) / float(TDC_DMIC_FULL_SCALE)     # 칸 값 -> DMIC 창과 같은 눈금 (-1 ~ 1)
    span_max = max(sec for _text, sec in TDC_IFFT_SPANS)
    cmp_ = TdcIfftCompare(np, int(TDC_DMIC_SR * span_max) + 2 * TDC_IFFT_MAX_LAG)

    root = tk.Tk()
    root.title("IFFT")
    root.geometry("900x800+480+20")

    ctl = ttk.Frame(root, padding=4)
    ctl.pack(side="bottom", fill="x")
    stats = tk.StringVar(value=TDC_IFFT_WAITING)
    tk.Label(root, textvariable=stats, font=("Consolas", 10), height=2, anchor="nw", justify="left",
             padx=12).pack(side="top", fill="x")

    fig = Figure(figsize=(8.8, 6.8), dpi=100)
    grid = fig.add_gridspec(2, 1, height_ratios=(1, 1), hspace=0.22, left=0.09, right=0.97, top=0.95, bottom=0.08)
    ax_ref = fig.add_subplot(grid[0, 0])
    ax_out = fig.add_subplot(grid[1, 0], sharex=ax_ref)
    arts = {}
    labels = []
    for name, ax in (("ref", ax_ref), ("out", ax_out)):
        poly = PolyCollection([], facecolors=TDC_IFFT_COLOR, edgecolors="none")
        ax.add_collection(poly)
        line, = ax.plot([], [], color=TDC_IFFT_COLOR, lw=1.2, marker="o", markersize=0)
        arts[name] = (poly, line)
        ax.set_ylim(-1.0, 1.0)                           # 고정. 파형을 지금 눈금 (y_limit) 으로 나눠 그린다. 둘이 같은 눈금이다
        ax.set_yticks([-1.0, -0.5, 0.0, 0.5, 1.0])
        ax.set_yticklabels(["", "", "0", "", ""])
        ax.set_facecolor("black")
        ax.grid(alpha=0.35)
        ax.grid(which="minor", axis="x", alpha=0.35)     # 좁은 구간의 1 ms 줄 (글자 없는 눈금)
        labels.append((ax.text(-0.01, 1.0, "", transform=ax.get_yaxis_transform(), ha="right", va="center", fontsize=8),
                       ax.text(-0.01, -1.0, "", transform=ax.get_yaxis_transform(), ha="right", va="center", fontsize=8)))
    ax_ref.set_title("기존 DAC 출력", fontsize=10, loc="left")
    ax_out.set_title("IFFT 후 DAC 출력", fontsize=10, loc="left")
    ax_ref.tick_params(labelbottom=False)
    ax_out.set_xlabel("ms")
    idle = ax_ref.text(0.5, 0.5, "비활성  (capture ifft on)", transform=ax_ref.transAxes,
                       ha="center", va="center", fontsize=13, color="#bbbbbb")
    canvas = FigureCanvasTkAgg(fig, master=root)
    canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
    moving = [a for name in ("ref", "out") for a in arts[name]] + [t for pair in labels for t in pair] + [idle]
    fast = TdcFastCanvas(root, canvas, fig, moving)

    st = {"last": 0.0, "dirty": False, "y_limit": 1.0, "y_init": False, "y_t": time.time(), "paused": False,
          "xlim": None, "last_stats": 0.0, "seen": {}, "buffers": 0, "back": 0}
    live_span = TDC_IFFT_SPANS[0][0]                    # 흐르는 동안의 구간 (가장 넓은 것)

    # 아래 줄 1: 멈춤, 구간, 지연 맞춤, 측정 지연으로 맞춤. 아래 줄 2: 멈춘 그림에서 보는 자리 (왼쪽 옛것, 오른쪽 최근)
    span = tk.StringVar(value=live_span)
    align = tk.IntVar(value=1)
    use_measured = tk.IntVar(value=0)
    where = tk.DoubleVar(value=1.0)

    def span_sec():
        return dict(TDC_IFFT_SPANS)[span.get()]

    def set_paused(on):
        if on == st["paused"]:
            return
        st["paused"] = on
        pause_btn.configure(text="이어서" if on else "멈춤")
        if not on:
            cmp_.mark_break()                           # 멈춘 동안 받지 않은 구간이 있다
            span.set(live_span)
            where.set(1.0)
        on_view()

    def on_view(_value=None):
        """구간이나 보는 자리가 바뀌었다. 흐르는 중에 좁은 구간을 고르면 멈춘다."""
        if span.get() != live_span and not st["paused"]:
            set_paused(True)
            return
        pos.state(["!disabled"] if st["paused"] and span.get() != live_span else ["disabled"])
        st["dirty"] = True

    pause_btn = ttk.Button(ctl, text="멈춤", width=8, command=lambda: set_paused(not st["paused"]))
    pause_btn.pack(side="left", padx=(3, 10))
    ttk.Label(ctl, text="구간").pack(side="left")
    for text, _sec in TDC_IFFT_SPANS:
        ttk.Radiobutton(ctl, text=text, value=text, variable=span, command=on_view).pack(side="left", padx=3)
    ttk.Separator(ctl, orient="vertical").pack(side="left", fill="y", padx=6)
    for text, var in (("지연 맞춤", align), ("측정 지연으로 맞춤", use_measured)):
        ttk.Checkbutton(ctl, text=text, variable=var, command=on_view).pack(side="left", padx=3)
    pos = ttk.Scale(root, from_=0.0, to=1.0, variable=where, command=on_view)
    pos.pack(side="bottom", fill="x", padx=8, before=canvas.get_tk_widget())
    pos.state(["disabled"])

    def back_samples(n):
        """보는 구간의 오른쪽 끝이 가장 최근에서 몇 샘플 앞인가 (16 의 배수)."""
        room = int(TDC_DMIC_SR * span_max) - n
        return (int(round((1.0 - where.get()) * room)) // 16) * 16 if st["paused"] and room > 0 else 0

    def on_click(event):
        """멈춘 그림을 클릭하면 그 자리가 가운데로 온다. 3 초 전체를 보고 있었으면 한 단계 좁힌다."""
        if not st["paused"] or event.xdata is None:
            return
        if span.get() == live_span:
            span.set(TDC_IFFT_SPANS[1][0])
        n = int(TDC_DMIC_SR * span_sec())
        room = int(TDC_DMIC_SR * span_max) - n
        back = -event.xdata * TDC_DMIC_SR / 1000.0 - n / 2.0
        where.set(1.0 - min(max(back / room, 0.0), 1.0))
        on_view()

    canvas.mpl_connect("button_press_event", on_click)

    def delay_now():
        """그릴 때와 수치를 낼 때 쓰는 지연 (샘플)."""
        if not align.get():
            return 0
        if use_measured.get() and cmp_.measured is not None:
            return cmp_.measured
        return cmp_.expected_delay()

    def envelope(samples, max_bins):
        """칸마다 최소와 최대: (칸 하나의 샘플 수, 최소, 최대)."""
        n = len(samples)
        step = max(1, (n + max_bins - 1) // max_bins)
        full = n // step
        blocks = samples[n - full * step:].reshape(full, step)
        return step, blocks.min(axis=1), blocks.max(axis=1)

    def set_wave(name, ax, samples):
        """samples (세로 눈금으로 나눈 값) 를 선 (샘플이 적으면 점도) 또는 세로 막대로. 가로는 ms."""
        poly, line = arts[name]
        n = len(samples)
        if n <= TDC_IFFT_ENVELOPE_FROM:
            line.set_data((np.arange(n) - (n - 1) - st["back"]) * 1000.0 / TDC_DMIC_SR, samples)
            line.set_markersize(3.5 if n <= TDC_IFFT_DOTS_UPTO else 0)
            line.set_visible(True)
            poly.set_visible(False)
            return
        step, low, high = envelope(samples, min(TDC_DMIC_MAX_BINS, max(int(ax.bbox.width), 100)))
        bottom = np.minimum(low, np.append(high[1:], low[-1]))
        top = np.maximum(high, np.append(low[1:], high[-1]))
        top = np.maximum(top, bottom + 2.0 / max(ax.bbox.height, 1.0))
        edges = (np.arange(len(low) + 1) * step - len(low) * step - st["back"]) * 1000.0 / TDC_DMIC_SR
        x = np.repeat(edges, 2)[1:-1]
        poly.set_verts([np.concatenate((np.column_stack((x, np.repeat(top, 2))),
                                        np.column_stack((x[::-1], np.repeat(bottom, 2)[::-1]))))])
        poly.set_visible(True)
        line.set_visible(False)

    def draw():
        now = time.time()
        d = delay_now()
        n = int(TDC_DMIC_SR * span_sec())
        back = back_samples(n)
        ref, out = cmp_.view(n, d, back)
        ref, out = ref * scale, out * scale
        st["back"] = back
        # 세로 눈금은 둘 가운데 큰 쪽에 맞추고 두 그래프가 같이 쓴다
        peak = float(max(np.max(np.abs(ref)), np.max(np.abs(out)))) if n else 0.0
        desired = max(peak * 1.25, 1e-6)
        if not st["y_init"] or desired >= st["y_limit"] or st["paused"]:
            st["y_limit"] = desired                      # 커질 때는 바로. 멈춘 그림은 보는 구간에 맞춘다
            st["y_init"] = True
        else:                                            # 줄 때는 천천히
            st["y_limit"] = max(desired, st["y_limit"] * 0.9 ** ((now - st["y_t"]) / 0.06))
        st["y_t"] = now
        y = st["y_limit"]
        set_wave("ref", ax_ref, ref / y)
        set_wave("out", ax_out, out / y)
        for top_text, bot_text in labels:
            top_text.set_text("+%.2g" % y)
            bot_text.set_text("-%.2g" % y)
        # 가로축은 배경이라 바뀔 때만 전체를 다시 그린다
        ms = span_sec() * 1000.0
        right = -back * 1000.0 / TDC_DMIC_SR
        xlim = (right - ms, right)
        if xlim != st["xlim"]:
            st["xlim"] = xlim
            ax_ref.set_xlim(*xlim)
            # 좁은 구간은 1 ms 마다 세로 줄 (펌웨어의 16 샘플 묶음 경계)
            ax_ref.xaxis.set_major_locator(MaxNLocator(nbins=10, steps=[1, 2, 5, 10]))
            ax_ref.xaxis.set_minor_locator(MultipleLocator(1.0) if ms <= 30.0 else NullLocator())
            return True
        return False

    def update_stats():
        d = delay_now()
        exp = cmp_.expected_delay()
        line1 = "IFFT 모드: %-7s  지연: 기대 %d (%.1f ms), 측정 %s%s" % (
            TDC_IFFT_MODE_TEXT[cmp_.mode], exp, exp * 1000.0 / TDC_DMIC_SR, cmp_.measure_note,
            "    [멈춤]" if st["paused"] else "")
        s = cmp_.stats(d)
        if s is None:
            line2 = "비교할 샘플 없음"
        elif s["silent"]:
            line2 = "기존 출력 0   최대 차 %d" % s["max_diff"]
        else:
            if s["max_diff"] == 0:
                err = "오차 없음"
            else:
                err = "오차 %.1f dB (크기 맞춤 %.1f dB)   최대 차 %d" % (s["err_db"], s["err_fit_db"], s["max_diff"])
            line2 = "크기 비 %+.2f dB   %s" % (s["gain_db"], err)
            if s["count"] >= 4000 and d == exp:
                st["seen"][cmp_.mode] = s
        stats.set(line1 + "\n" + line2)

    def tick():
        try:
            while True:
                kind, payload = from_main.get_nowait()
                if kind == "ifft":
                    st["last"] = time.time()
                    if not st["paused"]:
                        cmp_.feed(*payload)
                        st["buffers"] += 1
                        st["dirty"] = True
        except queue.Empty:
            pass
        now = time.time()
        on = (now - st["last"]) < TDC_IDLE_SEC
        redraw = full = False
        if idle.get_visible() == on:                     # 상태가 바뀌었을 때만
            idle.set_visible(not on)
            if not on:
                stats.set(TDC_IFFT_WAITING)
            redraw = True
        if (on or st["paused"]) and now - st["last_stats"] >= 0.25:
            st["last_stats"] = now
            update_stats()
        if st["dirty"]:
            st["dirty"] = False
            full = draw()
            redraw = True
        if full:
            fast.redraw()
        elif redraw:
            fast.update()

    close_window = tdc_graph_loop(root, tick, 60)
    if selftest:
        # 터미널의 자동 점검이 이 창이 떠 있는 동안 RTT i 키를 보낸다 (기존 경로 -> IFFT 오디오 모드)
        # 좁은 구간 (저절로 멈춘다) -> 자리 옮김 -> 이어서. 모드가 바뀌기 전에 끝낸다
        root.after(700, lambda: span.set(TDC_IFFT_SPANS[2][0]) or on_view())
        root.after(1000, lambda: where.set(0.4) or on_view())
        root.after(1300, lambda: set_paused(False))

        def check_result():
            seen = st["seen"]
            assert st["buffers"] > 0 and not idle.get_visible(), st["buffers"]
            assert TDC_IFFT_MODE_OFF in seen and seen[TDC_IFFT_MODE_OFF]["max_diff"] == 0, seen.get(TDC_IFFT_MODE_OFF)
            assert TDC_IFFT_MODE_ON in seen and abs(seen[TDC_IFFT_MODE_ON]["gain_db"] + 0.017) < 0.05 \
                and seen[TDC_IFFT_MODE_ON]["err_fit_db"] < -40.0, seen.get(TDC_IFFT_MODE_ON)
            print("selftest ifft: buffers %d, off max diff %d, on gain %+.3f dB err fit %.1f dB, delay %s" % (
                st["buffers"], seen[TDC_IFFT_MODE_OFF]["max_diff"], seen[TDC_IFFT_MODE_ON]["gain_db"],
                seen[TDC_IFFT_MODE_ON]["err_fit_db"], cmp_.measure_note), flush=True)
        root.after(5200, check_result)
        root.after(5400, close_window)
    root.mainloop()
