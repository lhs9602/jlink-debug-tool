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
TDC_DMIC_MAX_BINS = 1200     # 파형을 그릴 때 줄이는 칸 수의 상한 (칸마다 최소, 최대를 남긴다. 칸 수는 화면의 가로 칸 수에 맞춘다)
TDC_SPL_OFFSET_DB = 120.0    # dB SPL 추정 = dBFS + 120 (기존 DMIC 도구의 값)
TDC_NOISE_GATE_SPL = 29.5    # AGC noise gate (dB SPL)
TDC_ROTATION_SPL = 75.0      # AGC rotation point (dB SPL)
TDC_IDLE_SEC = 0.5           # 이 시간 동안 데이터가 없으면 비활성으로 표시
TDC_INJECT_FREQS = (1000, 2000, 4000, 6000)   # DMIC 창 주입 목록 (Hz). features/tdc_inject.py TDC_SINE_FREQS 와 같게 둔다
TDC_INJECT_CHOICES = tuple("사인 %g kHz" % (f / 1000.0) for f in TDC_INJECT_FREQS)
TDC_INJECT_WAV = "WAV 파일..."
TDC_SETTLE_MS = 150          # 창을 옮기거나 크기를 바꾸다 멈춘 뒤 이 시간이 지나면 다시 그린다


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


class TdcFastCanvas:
    """그래프를 빨리 그린다 (matplotlib 그림 하나).

    전체 그리기 (canvas.draw) 는 글자 때문에 느리다 (잰 값: DMIC 창 약 180 ms, vMag 창 약 40 ms). 그동안 창이 멈춘다.
      - 바뀌지 않는 것 (축, 눈금, 제목, 범례, 고정한 곡선) 은 한 번 그려 배경으로 간직하고, 바뀌는 것만 그 위에 다시 그린다
      - 창을 옮기거나 크기를 바꾸는 동안에는 그리지 않는다. 멈추고 TDC_SETTLE_MS 뒤에 한 번 그린다
    쓰는 법
      fast = TdcFastCanvas(root, canvas, fig, [바뀌는 artist. 적은 순서로 그린다])
      fast.update()    바뀌는 artist 의 값을 바꾼 뒤
      fast.redraw()    바뀌지 않는 것 (제목, 범례, 고정한 곡선) 을 바꾼 뒤
    바뀌는 artist 는 배경 위에 그리므로 범례와 겹치면 범례 위에 보인다"""

    def __init__(self, root, canvas, fig, artists):
        self.root = root
        self.canvas = canvas
        self.fig = fig
        self.artists = list(artists)
        self.background = None
        self.full = True            # 다음에는 전체 그리기를 한다
        self.waiting = False        # 그릴 것이 있는데 미뤘다
        self.resize_event = None    # 미뤄 둔 크기 바꾸기 (그림 영역의 마지막 Configure)
        self.settle_id = None       # 멈춤을 기다리는 예약. None 이 아니면 창을 옮기거나 크기를 바꾸는 중이다
        for a in self.artists:
            a.set_animated(True)    # 전체 그리기에서 빠진다. 배경 위에 따로 그린다
        canvas.mpl_connect("draw_event", self._on_full_draw)
        canvas.mpl_connect("resize_event", self._on_resized)
        # 그림 영역의 Configure 는 matplotlib 이 받아 크기가 바뀔 때마다 전체 그리기를 한다. 그것을 대신 받아 멈춘 뒤에 한 번만 넘긴다
        canvas.get_tk_widget().bind("<Configure>", self._on_canvas_configure)
        root.bind("<Configure>", self._on_root_configure, add="+")

    def _hold(self):
        if self.settle_id is not None:
            self.root.after_cancel(self.settle_id)
        self.settle_id = self.root.after(TDC_SETTLE_MS, self._settle)

    def _on_root_configure(self, event):
        if event.widget is self.root:       # 창 안의 다른 것 (버튼, 글) 의 Configure 도 여기로 온다
            self._hold()

    def _on_canvas_configure(self, event):
        self.resize_event = event
        self._hold()

    def _settle(self):
        """창이 멈췄다: 미뤄 둔 크기 바꾸기와 그리기를 한다"""
        self.settle_id = None
        if self.resize_event is not None:
            event, self.resize_event = self.resize_event, None
            self.waiting = False
            self.canvas.resize(event)       # matplotlib: 그림 크기를 맞추고 전체 그리기를 예약한다
        elif self.waiting:
            self.waiting = False
            self.update()

    def _on_resized(self, event):
        self.full = True                    # 간직한 배경은 옛 크기다

    def _on_full_draw(self, event):
        """전체 그리기가 끝났다 (바뀌는 것은 빠져 있다): 배경으로 간직하고 바뀌는 것을 그 위에 그린다"""
        self.background = self.canvas.copy_from_bbox(self.fig.bbox)
        self.full = False
        for a in self.artists:
            self.fig.draw_artist(a)

    def update(self):
        """바뀌는 artist 를 다시 그린다. 창을 옮기거나 크기를 바꾸는 중이면 미뤘다가 멈춘 뒤에 그린다"""
        if self.settle_id is not None:
            self.waiting = True
            return
        if self.full or self.background is None:
            self.canvas.draw()              # 전체 그리기 (끝에 _on_full_draw)
            return
        self.canvas.restore_region(self.background)
        for a in self.artists:
            self.fig.draw_artist(a)
        self.canvas.blit(self.fig.bbox)

    def redraw(self):
        """바뀌지 않는 것을 바꿨을 때: 배경부터 다시 그린다"""
        self.full = True
        self.update()


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
