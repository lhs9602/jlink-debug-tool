# -*- coding: utf-8 -*-
"""
tdc_dmic_window.py - DMIC 창 프로세스 (설계 결정_D63, D65)

기존 DMIC 도구(dmic_realtime_visualizer_optimized.py)의 화면을 따른다: 파형(최근 3 초, 결정_D73), 레벨 기록, 수치 글, Reset hold.
아래 줄에서 주입을 켜고 끈다 (원천 목록, 버튼, 상태 글, 결정_D76). 창은 요청만 main 에 보내고 버튼은 main 의 답을 보고 바꾼다.
main 은 ('dmic', (시간 순서 샘플, 놓친 ms)) 를 보낸다. 주입 중에는 주입한 샘플과 무음 ms 다 (무음만큼 0 이 앞에 붙는다, 결정_D71).
파형 창보다 긴 덩어리 (주입 무음이 길었을 때) 는 끝의 파형 창 길이만 그린다. 놓친 ms 는 이 창에서 쓰지 않는다 (터미널의 종합 로그가 낸다).
주입 상태는 ('dmic_state', {'inject': 이름 또는 None, 'error': 글, 'data_dir': WAV 폴더}) 로 온다. 설계 화면 견본에서 옮겼다.
"""

import collections
import math
import queue
import time

from .tdc_graph_common import (TDC_BANDS, TDC_CAPTURE_MAX, TDC_DMIC_FRAME, TDC_DMIC_FULL_SCALE, TDC_DMIC_HIST_SEC,
                               TDC_DMIC_MAX_BINS, TDC_DMIC_SR, TDC_DMIC_STATS_SEC, TDC_DMIC_WAVE_SEC, TDC_IDLE_SEC,
                               TDC_INJECT_CHOICES, TDC_INJECT_FREQS, TDC_INJECT_WAV, TDC_NOISE_GATE_SPL, TDC_ROTATION_SPL,
                               TDC_SPL_OFFSET_DB, TdcFastCanvas, tdc_graph_loop, tdc_graph_setup)


TDC_DMIC_WAITING = "waiting for DMIC ... (capture dmic on)"
TDC_DMIC_STATS_LINES = 3        # 수치 글의 줄 수 (peak, rms, AGC region)


def tdc_dmic_window(from_main, selftest, to_main=None):
    """DMIC 창 프로세스. 기존 DMIC 도구 (dmic_realtime_visualizer_optimized.py) 의 화면을 따른다:
      파형 (검은 바탕, 점선은 AGC 경계), 레벨 기록 (영역 색 3 개, peak / rms), 수치 글.
      DNN 보정용인 fmax, crest, scenario 기록 (Record, Stop, Summary) 은 뺐다."""
    tk, ttk, np, Figure, FigureCanvasTkAgg = tdc_graph_setup()
    from matplotlib.collections import PolyCollection

    gate_fs = 10.0 ** ((TDC_NOISE_GATE_SPL - TDC_SPL_OFFSET_DB) / 20.0)
    rot_fs = 10.0 ** ((TDC_ROTATION_SPL - TDC_SPL_OFFSET_DB) / 20.0)
    agc_block = 16                                   # AGC 가 보는 블록 (1 ms)
    wave_n = int(TDC_DMIC_SR * TDC_DMIC_WAVE_SEC)
    stats_n = int(TDC_DMIC_SR * TDC_DMIC_STATS_SEC)
    hist_n = int(TDC_DMIC_HIST_SEC * TDC_DMIC_SR / TDC_DMIC_FRAME)

    def wave_title(inject_name):
        head = ("주입: %s" % inject_name) if inject_name else "Live DMIC"
        return "%s (%g s), 점선: AGC gate %g / rotation %g dB SPL" % (
            head, TDC_DMIC_WAVE_SEC, TDC_NOISE_GATE_SPL, TDC_ROTATION_SPL)

    root = tk.Tk()
    root.title("DMIC")
    root.geometry("860x780+40+40")
    dctl = ttk.Frame(root, padding=4)
    dctl.pack(side="bottom", fill="x")
    # 수치 글은 matplotlib 그림이 아니라 Tk 글로 낸다 (그림 안의 글은 그릴 때마다 느리다). 줄 수를 고정해 글이 바뀌어도 그림 크기가 그대로다
    stats = tk.StringVar(value=TDC_DMIC_WAITING)
    tk.Label(root, textvariable=stats, font=("Consolas", 9), height=TDC_DMIC_STATS_LINES, anchor="nw", justify="left",
             padx=12).pack(side="bottom", fill="x")

    dfig = Figure(figsize=(8.4, 6.4), dpi=100)
    dgrid = dfig.add_gridspec(2, 1, hspace=0.36, left=0.10, right=0.97, top=0.95, bottom=0.08)
    ax_wav = dfig.add_subplot(dgrid[0, 0])
    guides = [(ax_wav.axhline(s * lv, color="0.5", ls="--", lw=0.7), s * lv)
              for lv in (gate_fs, rot_fs) for s in (1, -1)]
    # 파형은 화면 한 칸마다 세로 막대 (그 칸의 최소 ~ 최대) 를 세운 면 하나로 그린다.
    # 선으로 이으면 소리가 촘촘할 때 느리다 (잰 값: 선 34 ~ 61 ms, 면 1 ~ 10 ms)
    wave = PolyCollection([], facecolors="cyan", edgecolors="none")
    ax_wav.add_collection(wave)
    ax_wav.set_xlim(-TDC_DMIC_WAVE_SEC, 0)
    ax_wav.set_ylim(-1.0, 1.0)                       # 고정. 파형을 지금 눈금 (y_limit) 으로 나눠 그린다
    ax_wav.set_yticks([-1.0, -0.5, 0.0, 0.5, 1.0])
    ax_wav.set_yticklabels(["", "", "0", "", ""])
    y_top = ax_wav.text(-0.01, 1.0, "+1", transform=ax_wav.get_yaxis_transform(), ha="right", va="center", fontsize=8)
    y_bot = ax_wav.text(-0.01, -1.0, "-1", transform=ax_wav.get_yaxis_transform(), ha="right", va="center", fontsize=8)
    ax_wav.set_title(wave_title(None), fontsize=10)
    ax_wav.set_ylabel("amplitude")
    ax_wav.set_facecolor("black")
    ax_wav.grid(alpha=0.3)
    wav_idle = ax_wav.text(0.5, 0.5, "비활성  (capture dmic on)", transform=ax_wav.transAxes,
                           ha="center", va="center", fontsize=13, color="#bbbbbb")

    ax_spl = dfig.add_subplot(dgrid[1, 0])
    ax_spl.axhspan(0, TDC_NOISE_GATE_SPL, color="0.85", alpha=0.5)
    ax_spl.axhspan(TDC_NOISE_GATE_SPL, TDC_ROTATION_SPL, color="#c8e6c9", alpha=0.5)
    ax_spl.axhspan(TDC_ROTATION_SPL, 130, color="#ffe0b2", alpha=0.5)
    line_pk, = ax_spl.plot([], [], color="#c1121f", lw=1.3, label="peak SPL")
    line_rms, = ax_spl.plot([], [], color="#1d3557", lw=1.3, label="rms SPL")
    ax_spl.set_xlim(-TDC_DMIC_HIST_SEC, 0)
    ax_spl.set_ylim(10, 120)
    ax_spl.set_ylabel("dB SPL (est.)")
    ax_spl.set_xlabel("time (s)")
    ax_spl.set_title("Level history, 회색: gated  초록: amplify  주황: attenuation", fontsize=10)
    ax_spl.legend(loc="upper left", fontsize=8)
    ax_spl.grid(alpha=0.3)

    dcanvas = FigureCanvasTkAgg(dfig, master=root)
    dcanvas.get_tk_widget().pack(side="top", fill="both", expand=True)
    # 바뀌는 것만 다시 그린다. 적은 순서로 그린다: 점선, 파형, 세로 눈금 글, 비활성 글, 레벨 곡선
    fast = TdcFastCanvas(root, dcanvas, dfig,
                         [g for g, _v in guides] + [wave, y_top, y_bot, wav_idle, line_pk, line_rms])

    dm = {"buf": np.zeros(wave_n, dtype=np.float32), "filled": 0, "frames": 0, "dirty": False, "last": 0.0,
          "hist_t": collections.deque(maxlen=hist_n), "hist_pk": collections.deque(maxlen=hist_n),
          "hist_rms": collections.deque(maxlen=hist_n), "y_limit": 1.0, "y_init": False, "y_t": time.time(),
          "reset": False, "last_stats": 0.0, "window": None}

    def to_dbfs(amp):
        return 20.0 * math.log10(amp) if amp > 0 else float("-inf")

    def frame_metrics(buf):
        """기존 DMIC 도구의 frame_metrics 에서 쓰는 것만 옮겼다 (buf 는 -1 ~ 1 로 맞춘 값)"""
        if buf.size == 0:
            return None
        ac = buf - float(np.mean(buf))
        peak = float(np.max(np.abs(ac)))
        rms = float(np.sqrt(np.mean(ac * ac)))
        n512 = ac.size // TDC_DMIC_FRAME
        if n512:
            b = ac[ac.size - n512 * TDC_DMIC_FRAME:].reshape(n512, TDC_DMIC_FRAME)
            frame_max = float(np.sqrt(np.mean(b * b, axis=1)).max()) * math.sqrt(2.0)
        else:
            frame_max = 0.0
        n16 = ac.size // agc_block
        if n16:
            bp = np.max(np.abs(ac[ac.size - n16 * agc_block:].reshape(n16, agc_block)), axis=1)
            spl = 20.0 * np.log10(np.maximum(bp, 1e-12)) + TDC_SPL_OFFSET_DB
            gate = 100.0 * float(np.mean(spl < TDC_NOISE_GATE_SPL))
            atten = 100.0 * float(np.mean(spl > TDC_ROTATION_SPL))
            amp = 100.0 - gate - atten
        else:
            gate = amp = atten = 0.0
        return {"peak": peak, "rms": rms,
                "peak_dbfs": to_dbfs(peak), "rms_dbfs": to_dbfs(rms),
                "peak_spl": to_dbfs(peak) + TDC_SPL_OFFSET_DB, "rms_spl": to_dbfs(rms) + TDC_SPL_OFFSET_DB,
                "fmax_spl": to_dbfs(frame_max) + TDC_SPL_OFFSET_DB,     # AGC 영역 판정에만 쓴다
                "blk_gate": gate, "blk_amp": amp, "blk_atten": atten}

    def envelope(samples, max_bins):
        """칸마다 최소와 최대를 남긴다: (칸 하나의 샘플 수, 최소, 최대). 그리는 점만 줄이고 원본은 그대로다"""
        n = len(samples)
        step = max(1, (n + max_bins - 1) // max_bins)
        full = n // step
        blocks = samples[:full * step].reshape(full, step)
        return step, blocks.min(axis=1), blocks.max(axis=1)

    def feed_dmic(payload):
        codes, _missed_ms = payload                     # 놓친 ms 는 이 창에서 쓰지 않는다 (터미널의 종합 로그가 낸다)
        s = np.asarray(codes, dtype=np.float32) / float(TDC_DMIC_FULL_SCALE)
        tail = s[-wave_n:]                               # 파형 창보다 긴 덩어리 (주입 무음이 길었을 때) 는 끝의 창 길이만
        dm["buf"][:-len(tail)] = dm["buf"][len(tail):]
        dm["buf"][-len(tail):] = tail
        dm["filled"] = min(dm["filled"] + len(s), wave_n)
        now = time.time()
        m = frame_metrics(s)
        if m:
            dm["hist_pk"].append(m["peak_spl"])
            dm["hist_rms"].append(m["rms_spl"])
            dm["hist_t"].append(now)
        dm["frames"] += 1
        dm["dirty"] = True
        dm["last"] = now

    def update_stats():
        n = min(dm["filled"], stats_n)
        w = frame_metrics(dm["buf"][wave_n - n:]) if n else None
        dm["window"] = w
        if w is None:
            stats.set(TDC_DMIC_WAITING)
            return
        if dm["hist_t"]:
            tt = np.array(dm["hist_t"]) - dm["hist_t"][-1]
            line_pk.set_data(tt, np.array(dm["hist_pk"]))
            line_rms.set_data(tt, np.array(dm["hist_rms"]))
        region = ("GATED" if w["fmax_spl"] < TDC_NOISE_GATE_SPL else
                  "AMPLIFY" if w["fmax_spl"] < TDC_ROTATION_SPL else "ATTENUATION")
        stats.set(
            "peak   %.6f   %6.1f dBFS   %5.1f dB SPL\n"
            "rms    %.6f   %6.1f dBFS   %5.1f dB SPL\n"
            "AGC region: %-12s blocks gate/amp/atten = %.0f/%.0f/%.0f %%" % (
                w["peak"], w["peak_dbfs"], w["peak_spl"], w["rms"], w["rms_dbfs"], w["rms_spl"],
                region, w["blk_gate"], w["blk_amp"], w["blk_atten"]))

    def draw_dmic():
        now = time.time()
        # 칸 수는 화면의 가로 칸 수에 맞춘다 (더 잘게 나눠도 보이지 않는다)
        step, low, high = envelope(dm["buf"], min(TDC_DMIC_MAX_BINS, max(int(ax_wav.bbox.width), 100)))
        visible_peak = float(max(-low.min(), high.max()))
        desired = max(visible_peak * 1.25, 1e-6)
        if dm["filled"]:
            if not dm["y_init"] or dm["reset"] or desired >= dm["y_limit"]:
                dm["y_limit"] = desired                  # 커질 때는 바로 (Reset hold 도)
                dm["y_init"] = True
            else:                                        # 줄 때는 천천히
                dm["y_limit"] = max(desired, dm["y_limit"] * 0.9 ** ((now - dm["y_t"]) / 0.06))
        dm["y_t"] = now
        dm["reset"] = False
        # 칸마다 세로 막대 (최소 ~ 최대). 옆 칸과 끊어져 보이지 않게 다음 칸에 닿도록 늘리고, 화면의 한 칸 두께는 남긴다
        low, high = low / dm["y_limit"], high / dm["y_limit"]
        bottom = np.minimum(low, np.append(high[1:], low[-1]))
        top = np.maximum(high, np.append(low[1:], high[-1]))
        top = np.maximum(top, bottom + 2.0 / max(ax_wav.bbox.height, 1.0))
        edges = (np.arange(len(low) + 1) * step - (wave_n - 1)) / float(TDC_DMIC_SR)
        x = np.repeat(edges, 2)[1:-1]                    # 칸의 왼쪽 끝, 오른쪽 끝
        wave.set_verts([np.concatenate((np.column_stack((x, np.repeat(top, 2))),
                                        np.column_stack((x[::-1], np.repeat(bottom, 2)[::-1]))))])
        for g, v in guides:
            g.set_ydata([v / dm["y_limit"], v / dm["y_limit"]])
        y_top.set_text("+%.2g" % dm["y_limit"])
        y_bot.set_text("-%.2g" % dm["y_limit"])

    def reset_hold():
        dm["reset"] = True
        dm["dirty"] = True

    ttk.Button(dctl, text="Reset hold", command=reset_hold).pack(side="left", padx=3)

    # 주입 (DMIC 의 옵션, 결정_D76). 창은 요청만 보내고 J-Link 일은 main 이 한다. 버튼은 main 의 답을 보고 바꾼다
    ij = {"on": None, "wav": None, "data_dir": "", "last": TDC_INJECT_CHOICES[0], "wait": 0.0}
    ttk.Separator(dctl, orient="vertical").pack(side="left", fill="y", padx=6)
    ttk.Label(dctl, text="주입").pack(side="left")
    src = tk.StringVar(value=TDC_INJECT_CHOICES[0])
    src_box = ttk.Combobox(dctl, textvariable=src, values=TDC_INJECT_CHOICES + (TDC_INJECT_WAV,),
                           state="readonly", width=18)
    src_box.pack(side="left", padx=3)
    inj_btn = ttk.Button(dctl, text="주입 켜기")
    inj_btn.pack(side="left", padx=3)
    inj_msg = tk.StringVar(value="마이크")
    ttk.Label(dctl, textvariable=inj_msg).pack(side="left", padx=6)

    def send(req):
        if to_main is None:
            inj_msg.set("main 통로 없음")
            return
        try:
            to_main.put_nowait(("dmic_inject", req))
        except queue.Full:
            inj_msg.set("요청을 보내지 못했다")
            return
        inj_btn.state(["disabled"])
        ij["wait"] = time.time()

    def request():
        """지금 고른 원천으로 켜기 요청. 고른 것이 없으면 None."""
        v = src.get()
        if v in TDC_INJECT_CHOICES:
            return ("sine", TDC_INJECT_FREQS[TDC_INJECT_CHOICES.index(v)])
        if ij["wav"]:
            return ("wav", ij["wav"])
        return None

    def on_source(_event=None):
        if src.get() == TDC_INJECT_WAV:
            from tkinter import filedialog
            path = filedialog.askopenfilename(parent=root, title="주입 WAV (16 kHz 모노)",
                                              initialdir=ij["data_dir"], filetypes=[("WAV", "*.wav")])
            if not path:
                src.set(ij["last"])                 # 취소: 전에 고른 것으로
                return
            ij["wav"] = path
            src.set(path.replace("\\", "/").split("/")[-1])
        ij["last"] = src.get()
        if ij["on"]:
            send(request())                         # 주입 중이면 새 원천으로 바로 바꾼다

    def on_button():
        if ij["on"]:
            send(None)
            return
        req = request()
        if req is not None:
            send(req)

    src_box.bind("<<ComboboxSelected>>", on_source)
    inj_btn.configure(command=on_button)

    def on_state(st):
        """main 의 주입 상태: 버튼, 상태 글, 파형 제목과 색"""
        name = st.get("inject")
        if st.get("data_dir"):
            ij["data_dir"] = st["data_dir"]
        ij["on"] = name
        ij["wait"] = 0.0
        inj_btn.configure(text="주입 끄기" if name else "주입 켜기")
        inj_btn.state(["!disabled"])
        inj_msg.set(st.get("error") or (("주입: %s" % name) if name else "마이크"))
        wave.set_facecolor("orange" if name else "cyan")
        ax_wav.set_title(wave_title(name), fontsize=10)
        fast.redraw()                               # 제목은 배경이라 전체를 다시 그린다

    def tick():
        try:
            while True:
                kind, payload = from_main.get_nowait()
                if kind == "dmic":
                    feed_dmic(payload)
                elif kind == "dmic_state":
                    on_state(payload)
        except queue.Empty:
            pass
        now = time.time()
        if ij["wait"] and now - ij["wait"] > 2.0:          # main 이 답하지 않으면 버튼을 다시 쓸 수 있게
            ij["wait"] = 0.0
            inj_btn.state(["!disabled"])
        dmic_on = (now - dm["last"]) < TDC_IDLE_SEC
        redraw = False
        if wav_idle.get_visible() == dmic_on:            # 상태가 바뀌었을 때만
            wav_idle.set_visible(not dmic_on)
            if not dmic_on:
                stats.set(TDC_DMIC_WAITING)
            redraw = True
        if dmic_on and (now - dm["last_stats"] >= 0.25 or dm["reset"]):
            dm["last_stats"] = now
            update_stats()
            redraw = True
        if dm["dirty"]:
            dm["dirty"] = False
            draw_dmic()
            redraw = True
        if redraw:
            fast.update()

    close_window = tdc_graph_loop(root, tick, 60)
    if selftest:
        root.after(1000, on_button)                         # 사인 1 kHz 주입 켜기
        root.after(1800, lambda: src.set(TDC_INJECT_CHOICES[1]) or on_source())   # 주입 중 2 kHz 로 바꾸기
        root.after(2550, reset_hold)

        def check_result():
            assert dm["frames"] > 0 and not wav_idle.get_visible(), dm["frames"]
            assert dm["window"] is not None and stats.get().count("\n") == TDC_DMIC_STATS_LINES - 1, repr(stats.get())
            assert ij["on"] == TDC_INJECT_CHOICES[1], ij["on"]
            print("selftest dmic: buffers %d, rms %.1f dB SPL, text lines %d, 주입 %s" % (
                dm["frames"], dm["window"]["rms_spl"], stats.get().count("\n") + 1, ij["on"]), flush=True)
        root.after(2800, check_result)
        root.after(3000, close_window)
    root.mainloop()
