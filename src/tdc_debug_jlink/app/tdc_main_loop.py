# -*- coding: utf-8 -*-
"""
tdc_main_loop.py - main 프로세스 (J-Link 를 쓰는 일 전부, 창 없음. 설계 결정_D60, D61)

J-Link 는 이 프로세스의 한 스레드만 부른다. 루프 한 바퀴:
  명령 처리 -> (켠 블록이 있으면) DCRDR 확인, 바뀌었으면 켠 블록의 flag 와 버퍼 처리
  -> RTT (poll_ms 마다) -> 연결 감시 (watch_ms 마다) -> 종합 로그 (log_s 마다)
창 통로에는 넣기만 하고 기다리지 않는다. 통로가 차면 화면용 데이터는 버린다 (저장 파일은 여기서 써서 빠지지 않는다).
연결이 끊기면 reconnect_s 마다 다시 연결하고 header 를 다시 읽는다 (결정_D26).
터미널의 연결 해제 버튼을 누르면 J-Link 를 닫고, 연결 버튼을 누를 때까지 다시 연결하지 않는다 (hold).
header magic 이 사라졌다가 돌아오면 (펌웨어 재초기화) header 를 다시 읽고 켜 둔 기능을 다시 시작한다.
"""

import os
import queue
import time

from ..blocks.tdc_header import TDC_MAGIC, tdc_bind, tdc_read_magic
from ..features.tdc_capture import TdcDoubleBuffer, tdc_dmic_time_order, tdc_vmag_frames
from ..features.tdc_inject import TDC_SINE_FREQS, TdcInject, TdcInjectError, TdcSine, TdcWavSource
from ..features.tdc_save import TdcSaver
from ..link.tdc_memory import TDC_DCRDR, TDC_STATS, tdc_read_word, tdc_stats_reset
from ..link.tdc_rtt import TdcRtt, TdcRttError
from .tdc_commands import TDC_CAP_ID, TDC_CAPS, TDC_HELP, TDC_ID_DMIC, TDC_ID_IFFT, TDC_ID_VMAG, tdc_command


class TdcStop(Exception):
    pass


class TdcPerf:
    """명령 perf 의 측정값. 항목마다 횟수, 합, 최대 (초)."""

    KEYS = ("loop", "service", "inject", "dmic", "vmag", "ifft", "rtt")

    def __init__(self):
        self.reset()

    def reset(self):
        self.t0 = time.perf_counter()
        self.v = {k: [0, 0.0, 0.0] for k in self.KEYS}
        tdc_stats_reset()

    def add(self, key, dt):
        e = self.v[key]
        e[0] += 1
        e[1] += dt
        e[2] = max(e[2], dt)

    def report(self):
        span = max(time.perf_counter() - self.t0, 1e-6)

        def rate(k):
            return self.v[k][0] / span

        def avg(k):
            n, s, _m = self.v[k]
            return 1000.0 * s / n if n else 0.0

        s = TDC_STATS
        lines = [
            "측정 %.1f s (다음 perf 는 지금부터)" % span,
            "루프 한 바퀴      평균 %.2f ms, 최대 %.1f ms, 1 초에 %.0f 바퀴" % (avg("loop"), 1000.0 * self.v["loop"][2], rate("loop")),
            "알림 처리         1 초에 %.0f 번, 평균 %.2f ms, 최대 %.1f ms" % (rate("service"), avg("service"), 1000.0 * self.v["service"][2]),
            "  주입 채움       1 초에 %.0f 번, 평균 %.2f ms" % (rate("inject"), avg("inject")),
            "  DMIC 가져오기   1 초에 %.0f 번, 평균 %.2f ms" % (rate("dmic"), avg("dmic")),
            "  vMag 가져오기   1 초에 %.0f 번, 평균 %.2f ms" % (rate("vmag"), avg("vmag")),
            "  IFFT 가져오기   1 초에 %.0f 번, 평균 %.2f ms" % (rate("ifft"), avg("ifft")),
            "RTT               평균 %.2f ms" % avg("rtt"),
            "J-Link 읽기       1 초에 %.0f 번, 한 번 평균 %.3f ms (평균 %.0f 워드)" % (
                s["read_n"] / span, 1000.0 * s["read_s"] / s["read_n"] if s["read_n"] else 0.0,
                s["read_words"] / s["read_n"] if s["read_n"] else 0.0),
            "J-Link 쓰기       1 초에 %.0f 번, 한 번 평균 %.3f ms" % (
                s["write_n"] / span, 1000.0 * s["write_s"] / s["write_n"] if s["write_n"] else 0.0),
        ]
        self.reset()
        return "\n".join(lines)


class TdcMain:
    def __init__(self, cfg, link, to_term, from_term, to_win, stop_evt, selftest=False):
        self.cfg = cfg
        self.link = link
        self.to_term = to_term
        self.from_term = from_term
        self.to_win = to_win
        self.stop_evt = stop_evt
        self.selftest = selftest
        self.jl = None
        self.bound = {}
        self.bind_lines = []
        self.magic = None
        self.rtt = TdcRtt(cfg["rtt_cb"], cfg["rtt_up"], cfg["rtt_down"])
        self.cap = {"dmic": TdcDoubleBuffer("dmic", "cur_buf", "pos"), "vmag": TdcDoubleBuffer("vmag", "write_buf", "write_pos"),
                    "ifft": TdcDoubleBuffer("ifft", "cur_buf", "pos", bufs=("ref_buf", "out_buf"), per_buf=("mode_cnt",))}
        self.inj = TdcInject()
        self.saver = TdcSaver(cfg["out_dir"])
        self.log_s = cfg["log_s"]
        self.sent = 0
        self.dropped = 0
        self.user_write_calls = 0
        self.last_dcrdr = None
        self.loop_max_gap = 0.0
        self.perf = TdcPerf()
        self.hold = False           # 사용자가 연결을 해제했다. 참인 동안 J-Link 를 열지 않는다
        self.retry_now = False      # 연결 버튼: 다시 연결을 기다리는 중이면 바로 시도한다

    # ------------------------------------------------------------------ 통로
    def _put(self, q, item):
        try:
            q.put_nowait(item)
            return True
        except queue.Full:
            self.dropped += 1
            return False

    def term(self, kind, text):
        self._put(self.to_term, (kind, text))

    def reply(self, text):
        self.term("cmd", text + "\n")

    def to_window(self, key, item):
        if self._put(self.to_win[key], item):
            self.sent += 1

    # ------------------------------------------------------------------ 상태
    def any_on(self):
        return self.cap["dmic"].on or self.cap["vmag"].on or self.cap["ifft"].on or self.inj.on

    def status_text(self):
        link = ("연결됨 %s" % self.link.describe()) if self.jl is not None else "연결 안 됨"
        blocks = self.bind_lines[-1] if self.bind_lines else "디버그 블록 정보 없음"
        dmic = "off"
        if self.cap["dmic"].on:
            dmic = ("on (주입 %s)" % self.inj.source.name) if self.inj.on else "on"
        return "%s / %s / dmic %s, vmag %s, ifft %s / 저장 %s / 창으로 보낸 것 %d, 버린 것 %d" % (
            link, blocks, dmic, "on" if self.cap["vmag"].on else "off", "on" if self.cap["ifft"].on else "off",
            "on" if self.saver.on else "off", self.sent, self.dropped)

    # ------------------------------------------------------------------ 명령
    def handle_commands(self):
        while True:
            try:
                kind, text = self.from_term.get_nowait()
            except queue.Empty:
                return
            if kind == "quit":
                raise TdcStop()
            if kind == "rtt_in":
                self.rtt.queue_tx(text.encode("utf-8"))
            elif kind == "cmd":
                tdc_command(self, text)
            elif kind == "dmic_inject":
                self.inject_request(text)          # DMIC 창의 주입 조작 (결정_D76)
            elif kind == "link":
                self.link_request(text)            # 터미널의 연결 해제, 연결 버튼

    def link_request(self, onoff):
        """"off": J-Link 를 닫고 다시 연결하지 않는다. "on": 다시 연결한다.
        켜 둔 기능 (capture, 주입) 은 disconnect 가 타깃에서 끄고, 다시 연결하면 이어서 시작한다"""
        if onoff == "off":
            self.hold = True
            self.disconnect()
            self.term("status", "연결 해제됨")
            self.term("rtt_note", "연결 해제됨")
        else:
            self.hold = False
            self.retry_now = True

    # ------------------------------------------------------------------ 기능
    def start_capture(self, what):
        cap = self.cap[what]
        blk = self.bound[TDC_CAP_ID[what]]
        # 펌웨어는 블록의 enable 이 1 인 동안만 그 블록의 함수를 부른다. 블록을 처음 상태로 두고 enable 을 1 로 쓴다 (초기화는 PC).
        # 주입 중이면 DMIC 버퍼에 주입 샘플이 있어 처음 상태로 돌리지 않고 enable 만 1 로 둔다.
        # 그런 경로는 셋이다: 다시 연결한 뒤, 펌웨어 재초기화 뒤 (둘 다 바로 뒤에 주입을 다시 시작한다),
        # 켠 채로 capture dmic on 을 다시 칠 때
        if what == "dmic" and self.inj.on:
            blk.m.dmic_enable.put(self.jl, 1)
        else:
            cap.start(self.jl, blk)
        cap.on = True
        self.last_dcrdr = tdc_read_word(self.jl, TDC_DCRDR)
        getattr(self.saver, "open_" + what)()
        if what == "dmic":
            self.inject_state()

    def stop_capture(self, what):
        """가져오기 끄기: enable 0. 펌웨어가 그 블록의 함수를 부르지 않게 된다."""
        cap = self.cap[what]
        bid = TDC_CAP_ID[what]
        if self.jl is not None and bid in self.bound:
            cap.stop(self.jl, self.bound[bid])
        cap.on = False

    # ------------------------------------------------------------------ 주입 (DMIC 의 옵션, 결정_D74, D76)
    def start_inject(self, source):
        first = self.inj.start(self.jl, self.bound[TDC_ID_DMIC], source)
        self.last_dcrdr = tdc_read_word(self.jl, TDC_DCRDR)
        self.show_inject(first)

    def stop_inject(self):
        """주입 끄기. DMIC 기록이 다시 돈다."""
        if self.jl is not None and TDC_ID_DMIC in self.bound:
            self.inj.stop(self.jl, self.bound[TDC_ID_DMIC])
        self.inj.on = False
        self.inject_state()

    def inject_request(self, req):
        """DMIC 창의 주입 조작. req: None 끄기, ("sine", 주파수), ("wav", 경로)."""
        if req is None:
            if self.inj.on:
                self.stop_inject()
                self.reply("주입 끔")
            else:
                self.inject_state()
            return
        if self.jl is None or TDC_ID_DMIC not in self.bound or not self.cap["dmic"].on:
            self.inject_state("주입: 할 수 없다 (연결, DMIC 블록, capture dmic 을 확인)")
            return
        kind, arg = req
        try:
            if kind == "sine" and arg in TDC_SINE_FREQS:
                source = TdcSine(arg)
            elif kind == "wav":
                source = TdcWavSource(arg if os.path.isabs(arg) else os.path.join(self.cfg["data_dir"], arg))
            else:
                raise TdcInjectError("모르는 원천 %r" % (req,))
        except Exception as e:                  # 원천 파일 문제 (없음, WAV 아님, 형식). 연결은 그대로 둔다
            self.inject_state("주입: %s" % e)
            return
        self.start_inject(source)
        self.reply("주입 켬: %s" % source.name)
        self.inject_state()

    def inject_state(self, error=None):
        """DMIC 창에 주입 상태를 알린다 (버튼, 상태 글, 파형 제목). 오류는 터미널에도 한 줄."""
        if error:
            self.reply(error)
        name = self.inj.source.name if self.inj.on else None
        self.to_window("dmic", ("dmic_state", {"inject": name, "error": error, "data_dir": self.cfg["data_dir"]}))

    def show_inject(self, filled):
        """주입한 샘플을 DMIC 창과 저장으로 (결정_D69, D71)."""
        if self.cap["dmic"].on:
            for samples, silent in filled:
                self.saver.dmic(samples)
                self.to_window("dmic", ("dmic", (samples, silent)))

    def service(self):
        """DCRDR 이 바뀌었을 때: 켠 블록의 flag 를 보고 처리한다 (결정_D40, D41).
        주입 중에는 DMIC 버퍼를 주입이 쓰므로 DMIC 가져오기를 하지 않고, DMIC 창과 저장에는 넣은 샘플을 보낸다 (결정_D69)."""
        jl = self.jl
        t_start = time.perf_counter()
        if self.inj.on and TDC_ID_DMIC in self.bound:
            t0 = time.perf_counter()
            filled = self.inj.service(jl, self.bound[TDC_ID_DMIC])
            if filled:
                self.perf.add("inject", time.perf_counter() - t0)
            self.show_inject(filled)
        elif self.cap["dmic"].on and TDC_ID_DMIC in self.bound:
            t0 = time.perf_counter()
            got = self.cap["dmic"].take_all(jl, self.bound[TDC_ID_DMIC])
            if got:
                self.perf.add("dmic", time.perf_counter() - t0)
            for data, miss in got:
                samples = tdc_dmic_time_order(data)
                self.saver.dmic(samples)
                self.to_window("dmic", ("dmic", (samples, miss)))
        if self.cap["vmag"].on and TDC_ID_VMAG in self.bound:
            t0 = time.perf_counter()
            got = self.cap["vmag"].take_all(jl, self.bound[TDC_ID_VMAG])
            if got:
                self.perf.add("vmag", time.perf_counter() - t0)
            for data, miss in got:
                frames = tdc_vmag_frames(data)
                self.saver.vmag(frames)
                self.to_window("vmag", ("frames", frames))
        if self.cap["ifft"].on and TDC_ID_IFFT in self.bound:
            t0 = time.perf_counter()
            got = self.cap["ifft"].take_all(jl, self.bound[TDC_ID_IFFT])
            if got:
                self.perf.add("ifft", time.perf_counter() - t0)
            for data, miss in got:
                # 기준과 출력은 같은 위치의 16 샘플 묶음이 같은 1 ms 다. 묶음 안은 DMIC 처럼 [0] 이 가장 최근이라 뒤집는다
                ref = tdc_dmic_time_order(data["ref_buf"])
                out = tdc_dmic_time_order(data["out_buf"])
                self.saver.ifft(ref, out)
                self.to_window("ifft", ("ifft", (ref, out, data["mode_cnt"], miss)))
        self.perf.add("service", time.perf_counter() - t_start)

    def summary(self):
        """종합 로그 (결정_D64, D77). 그 간격에 놓친 샘플이 있는 것만 낸다. 놓친 것이 없으면 줄을 내지 않는다."""
        parts = []
        if self.cap["dmic"].on:
            _n, m = self.cap["dmic"].reset_interval()
            if self.inj.on:
                _n, m = self.inj.reset_interval()
                if m:
                    parts.append("dmic 주입 무음 %d ms" % m)
            elif m:
                parts.append("dmic 놓침 %d ms" % m)
        for key in ("vmag", "ifft"):
            if self.cap[key].on:
                _n, m = self.cap[key].reset_interval()
                if m:
                    parts.append("%s 놓침 %d ms" % (key, m))
        if parts:
            self.term("log", "[%d s] %s\n" % (self.log_s, " | ".join(parts)))

    # ------------------------------------------------------------------ 연결
    def bind(self):
        self.bound, self.bind_lines = tdc_bind(self.jl, self.cfg["header_addr"])
        for s in self.bind_lines:
            self.reply(s)
        self.magic = tdc_read_magic(self.jl, self.cfg["header_addr"])
        # 지난 도구가 주입을 끄지 못하고 끝났으면 펌웨어에 주입이 켜진 채 남아 DMIC 기록이 멈춰 있다. 끈다 (결정_D76)
        if not self.inj.on and TDC_ID_DMIC in self.bound and self.bound[TDC_ID_DMIC].m.dmic_inj_enable.get(self.jl) != 0:
            self.inj.stop(self.jl, self.bound[TDC_ID_DMIC])
            self.reply("주입이 켜진 채 남아 있어 껐다 (지난 도구가 끄지 못함)")
        # 가져오기도 같다: 켜 두지 않았는데 enable 이 1 이면 끈다 (펌웨어가 쓰지 않는 블록을 돌리지 않게)
        for key, bid, _name in TDC_CAPS:
            if not self.cap[key].on and bid in self.bound and getattr(self.bound[bid].m, key + "_enable").get(self.jl) != 0:
                self.cap[key].stop(self.jl, self.bound[bid])
                self.reply("capture %s 이 켜진 채 남아 있어 껐다 (지난 도구가 끄지 못함)" % key)
        # 켜 둔 기능을 다시 시작한다 (재연결, 펌웨어 재초기화 뒤)
        for key, bid, _name in TDC_CAPS:
            if self.cap[key].on:
                if bid in self.bound:
                    self.start_capture(key)
                else:
                    self.cap[key].on = False
                    self.reply("capture %s off (블록 사용 불가)" % key)
        if self.inj.on:
            if self.cap["dmic"].on and TDC_ID_DMIC in self.bound:
                self.start_inject(self.inj.source)
                self.reply("주입 다시 시작 (%s)" % self.inj.source.name)
            else:
                self.inj.on = False
                self.reply("주입 끔 (DMIC 블록 사용 불가)")
            self.inject_state()

    def connect(self):
        self.jl = self.link.open()
        self.term("rtt_note", "연결됨 %s" % self.link.describe())
        try:
            self.rtt.start(self.jl)
        except TdcRttError as e:
            self.term("rtt_note", "RTT: %s" % e)
        self.term("status", "연결됨 %s" % self.link.describe())
        self.bind()

    def watch(self):
        jl = self.jl
        if not jl.target_connected():
            raise ConnectionError("타깃 무응답")
        try:
            if self.rtt.running:
                if self.rtt.check(jl):
                    self.term("rtt_note", "RTT 제어블록 재초기화 감지 -> RTT 다시 시작")
            else:
                self.rtt.start(jl)
                self.term("rtt_note", "RTT 시작")
        except TdcRttError:
            pass
        magic = tdc_read_magic(jl, self.cfg["header_addr"])
        if magic != self.magic:
            if magic == TDC_MAGIC:
                self.reply("디버그 블록 다시 보임 -> header 다시 읽기")
                self.bind()
            else:
                self.bound = {}
                self.reply("디버그 블록 사라짐 (magic 0x%06X, 펌웨어 재초기화 중일 수 있다)" % magic)
            self.magic = magic
        # 펌웨어가 디버그 블록을 다시 초기화하면 (standby 복귀) enable 이 0 으로 돌아간다. 초기화가 짧아 magic 이
        # 사라진 것을 놓칠 수 있으므로, 켜 둔 블록의 enable 을 되읽어 0 이면 다시 시작한다
        for key, bid, _name in TDC_CAPS:
            if self.cap[key].on and bid in self.bound and getattr(self.bound[bid].m, key + "_enable").get(jl) == 0:
                self.reply("펌웨어 재초기화 감지 -> capture %s 다시 시작" % key)
                self.start_capture(key)
                if key == "dmic" and self.inj.on:
                    self.start_inject(self.inj.source)
                    self.reply("주입 다시 시작 (%s)" % self.inj.source.name)

    def disconnect(self):
        if self.jl is not None:
            try:
                if self.inj.on and TDC_ID_DMIC in self.bound:
                    self.inj.stop(self.jl, self.bound[TDC_ID_DMIC])
                    self.inj.on = True        # 다시 연결하면 이어서 시작한다
                for key, bid, _name in TDC_CAPS:
                    if self.cap[key].on and bid in self.bound:
                        self.cap[key].stop(self.jl, self.bound[bid])    # enable 0. on 은 그대로라 다시 연결하면 이어서 시작한다
            except Exception:
                pass
            self.rtt.stop(self.jl)
        self.link.close()
        self.jl = None
        self.bound = {}

    # ------------------------------------------------------------------ 루프
    def loop(self):
        cfg = self.cfg
        now = time.perf_counter()
        next_rtt = next_watch = now
        next_log = now + self.log_s
        prev = now
        self.last_dcrdr = tdc_read_word(self.jl, TDC_DCRDR)
        while not self.stop_evt.is_set():
            self.handle_commands()
            if self.jl is None:
                return
            if self.any_on():
                v = tdc_read_word(self.jl, TDC_DCRDR)
                if v != self.last_dcrdr:
                    self.last_dcrdr = v
                    self.service()
            now = time.perf_counter()
            if now >= next_rtt:
                t0 = time.perf_counter()
                text = self.rtt.pump(self.jl)
                self.perf.add("rtt", time.perf_counter() - t0)
                if text:
                    self.term("rtt", text)
                next_rtt = now + cfg["rtt_poll_ms"] / 1000.0
            if now >= next_watch:
                self.watch()
                next_watch = now + cfg["watch_ms"] / 1000.0
            if now >= next_log:
                self.summary()
                next_log = now + self.log_s
            self.loop_max_gap = max(self.loop_max_gap, now - prev)
            self.perf.add("loop", now - prev)
            prev = now
            time.sleep(cfg["poll_ms"] / 1000.0)

    def run(self):
        self.reply(TDC_HELP.rstrip("\n"))
        try:
            while not self.stop_evt.is_set():
                try:
                    while self.hold and not self.stop_evt.is_set():     # 연결 해제 중: 명령만 받는다
                        self.handle_commands()
                        time.sleep(0.05)
                    self.retry_now = False
                    self.connect()
                    self.loop()
                except TdcStop:
                    raise
                except Exception as e:           # 연결, 통신 문제: 닫고 다시 연결
                    self.disconnect()
                    if self.hold:                # 닫는 중에 난 오류: 해제된 채로 둔다
                        continue
                    self.term("status", "끊김: %s (%.1f s 뒤 다시)" % (e, self.cfg["reconnect_s"]))
                    self.term("rtt_note", "끊김: %s (%.1f s 뒤 다시)" % (e, self.cfg["reconnect_s"]))
                    end = time.perf_counter() + self.cfg["reconnect_s"]
                    while time.perf_counter() < end and not self.stop_evt.is_set() and not self.hold and not self.retry_now:
                        self.handle_commands()
                        time.sleep(0.05)
        except TdcStop:
            pass
        finally:
            if self.jl is not None and self.inj.on and TDC_ID_DMIC in self.bound:
                try:
                    self.inj.stop(self.jl, self.bound[TDC_ID_DMIC])     # 도구 종료 때 주입을 끈다 (결정_D69)
                except Exception:
                    pass
            self.saver.close_all()
            if self.selftest:
                self.print_selftest()
            self.disconnect()

    def print_selftest(self):
        d, v, f = self.cap["dmic"], self.cap["vmag"], self.cap["ifft"]
        print("selftest main: dmic 버퍼 %d 놓침 %d ms | vmag 버퍼 %d 놓침 %d ms | ifft 버퍼 %d 놓침 %d ms | 주입 채움 %d 무음 %d ms | "
              "write 명령 뒤 타깃 쓰기 %d 회 | 저장 %s | 루프 최대 간격 %.1f ms" % (
                  d.total_buf, d.total_missed, v.total_buf, v.total_missed, f.total_buf, f.total_missed,
                  self.inj.total_fill, self.inj.total_silent,
                  self.user_write_calls, [p.replace("\\", "/").split("/")[-1] for p in self.saver.names],
                  self.loop_max_gap * 1000.0), flush=True)


def tdc_main_process(cfg, fake, to_term, from_term, to_dmic, to_vmag, to_ifft, stop_evt, selftest):
    """main 프로세스 시작 함수 (multiprocessing 대상이라 모듈 최상위에 둔다)."""
    if fake:
        from ..link.tdc_fake_link import TdcFakeLink
        link = TdcFakeLink(cfg)
    else:
        from ..link.tdc_link import TdcLink
        link = TdcLink(cfg)
    TdcMain(cfg, link, to_term, from_term, {"dmic": to_dmic, "vmag": to_vmag, "ifft": to_ifft}, stop_evt, selftest).run()
