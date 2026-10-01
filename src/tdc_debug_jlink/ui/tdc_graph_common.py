# -*- coding: utf-8 -*-
"""
tdc_graph_common.py - 그래프 창 공통 (상수, matplotlib 준비, 주기 루프)

설계 화면 견본(docs/tasks/pylink/20260924_1556_rtt-pylink-통합/첨부_설계_화면견본.py)에서 옮겼다.
그래프 창은 J-Link 를 만지지 않는다. main 이 통로로 보낸 것만 그린다.
"""

TDC_BANDS = 32               # vMag 밴드 수
TDC_CAPTURE_MAX = 5          # 그래프에 고정할 수 있는 곡선 수
TDC_QUEUE_MAX = 400          # 통로 길이. 넘으면 main 이 버린다
TDC_DMIC_SR = 16000          # DMIC 샘플 속도 (Hz)
TDC_DMIC_FRAME = 512         # DMIC 버퍼 하나 (32 ms)
TDC_DMIC_FULL_SCALE = 1 << 23
TDC_DMIC_WAVE_SEC = 3.0      # 파형 창 (초). 설계 결정_D73 (이전 5 초). 기존 DMIC 도구는 10 초. features/tdc_inject.py TDC_SILENT_SHOW_MS 와 같게 둔다
TDC_DMIC_STATS_SEC = 3.0     # 수치를 내는 구간 (초). 파형 창의 마지막 부분 (지금은 파형 창 전체)
TDC_DMIC_HIST_SEC = 30.0     # 레벨 기록 창 (초)
TDC_DMIC_MAX_BINS = 1200     # 파형을 그릴 때 줄이는 칸 수 (칸마다 최소, 최대를 남긴다)
TDC_SPL_OFFSET_DB = 120.0    # dB SPL 추정 = dBFS + 120 (기존 DMIC 도구의 값)
TDC_NOISE_GATE_SPL = 29.5    # AGC noise gate (dB SPL)
TDC_ROTATION_SPL = 75.0      # AGC rotation point (dB SPL)
TDC_IDLE_SEC = 0.5           # 이 시간 동안 데이터가 없으면 비활성으로 표시
TDC_INJECT_FREQS = (1000, 2000, 4000, 6000)   # DMIC 창 주입 목록 (Hz). features/tdc_inject.py TDC_SINE_FREQS 와 같게 둔다
TDC_INJECT_CHOICES = tuple("사인 %g kHz" % (f / 1000.0) for f in TDC_INJECT_FREQS)
TDC_INJECT_WAV = "WAV 파일..."


def tdc_graph_setup():
    """그래프 창 프로세스가 처음에 부른다. (tk, ttk, np, Figure, FigureCanvasTkAgg)"""
    import tkinter as tk
    from tkinter import ttk

    import matplotlib
    matplotlib.use("TkAgg")
    matplotlib.rcParams["font.family"] = "Malgun Gothic"
    matplotlib.rcParams["axes.unicode_minus"] = False
    import numpy as np
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    return tk, ttk, np, Figure, FigureCanvasTkAgg


def tdc_graph_loop(root, tick, period_ms):
    """tick 을 주기로 부른다. 닫는 함수를 돌려준다.
    그리기 예약이 남은 채 창을 없애면 Tk 가 오류 글을 내므로, 그리기를 멈춘 뒤 닫는다"""
    closing = {"on": False}

    def close_window():
        closing["on"] = True
        root.after(250, root.destroy)

    def run():
        if closing["on"]:
            return
        tick()
        root.after(period_ms, run)

    root.protocol("WM_DELETE_WINDOW", close_window)
    root.after(period_ms, run)
    return close_window
