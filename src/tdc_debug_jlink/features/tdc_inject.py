# -*- coding: utf-8 -*-
"""
tdc_inject.py - 주입 (DMIC 의 옵션. 설계 결정_D69, D71, D74, D76)

주입 샘플은 DMIC 블록의 더블 버퍼(dmic_buf0, dmic_buf1, 512 샘플씩)로 준다. DMIC 기록과 방향만 반대다.
  CFX: 1 ms 마다 dmic_buf[dmic_cur_buf][dmic_pos] 부터 16 샘플을 꺼내 믹서 결과 대신 쓴다.
       마이크에 입력 LPF (2-tap 이동평균) 가 걸릴 때 (맵 4 번, RTT f) 는 주입 샘플에도 CFX 가 같은 식으로 건다.
       512 를 다 꺼내면 그 버퍼의 dmic_buf_full 0, 다른 버퍼로 옮기며 알린다.
       꺼낼 버퍼가 비어 있으면 그 1 ms 는 무음, dmic_missing_cnt + 1, 그 자리에서 기다린다.
  PC:  알림마다 dmic_buf_full 이 0 인 버퍼를 모두 채우고 1 을 쓴다 (둘 다 비었으면 CFX 가 기다리는 버퍼부터).
       채운 뒤 dmic_missing_cnt 를 읽어 (0 이 아니면 0 을 쓴다) 그만큼 무음이 있었다고 본다. 늦은 동안만 무음이다.
시작:  dmic_inj_enable 0 -> dmic_buf_full 1, 1 (기록 멈춤) -> 2 ms -> 두 버퍼 채움 -> dmic_pos 0, dmic_cur_buf 0
       -> dmic_inj_enable 1 -> dmic_missing_cnt 0 (기록이 멈춘 동안 센 것을 버린다)
끄기:  dmic_buf_full 1, 1 -> dmic_inj_enable 0 -> 2 ms -> dmic_pos 0, dmic_cur_buf 0 -> dmic_buf_full 0, 0 (기록 다시)
       -> dmic_missing_cnt 0 (flag 를 푼 뒤에. 먼저 쓰면 풀기 전 1 ms 가 다시 세어진다)
  2 ms: CFX 가 그 1 ms 에 이미 읽은 값으로 기록이나 주입 함수 안에 있었을 수 있어 그 1 ms 가 끝나기를 기다린다.
주입 중에는 PC 가 DMIC 버퍼를 읽지 않는다 (읽고 0 을 쓰면 CFX 가 빈 버퍼 앞에서 무음으로 멈춘다).

샘플은 입력 FIFO 와 같은 단위 (24 비트, 최대 2^23), 시간 순서다 (CFX 가 16 개씩 FIFO 순서로 뒤집는다).
원천
  사인: PC 가 값을 만든다. 주파수는 TDC_SINE_FREQS 에서 고른다. 최대 TDC_SINE_PEAK (마이크 수준). 위상은 이어진다
  WAV:  16 kHz 모노 PCM. WAV 최대 = 2^23. 끝나면 처음부터 되풀이
"""

import math
import time
import wave

from ..blocks.tdc_blocks import TDC_DMIC_LEN

TDC_SINE_FREQS = (1000, 2000, 4000, 6000)     # 동료 DNN 펌웨어 내장 사인 표와 같은 4 개. DMIC 창 목록(ui/tdc_graph_common.py)과 같게 둔다
TDC_SINE_PEAK = 25166                         # 2^23 * 3146 / 2^20 (DNN td_dnn_cfx.c 의 마이크 수준, 약 -50 dBFS). src/tdc_wav_convert.py 의 TDC_MIC_PEAK 와 같게 둔다
TDC_FULL_SCALE = 1 << 23
TDC_FIFO_BLOCK = 16                           # 1 ms = 16 샘플. 무음 1 ms 를 0 16 개로 보인다 (결정_D71)
TDC_SILENT_SHOW_MS = 3000                     # 한 번에 0 으로 붙이는 무음의 최대 (ms). DMIC 파형 창(ui/tdc_graph_common.py TDC_DMIC_WAVE_SEC)과 같게 둔다
TDC_SETTLE_S = 0.002                         # 시작, 끄기에서 CFX 의 1 ms 가 끝나기를 기다리는 시간


class TdcInjectError(Exception):
    pass


class TdcSine:
    def __init__(self, freq):
        self.freq = freq
        self.phase = 0.0
        self.name = "사인 %g kHz" % (freq / 1000.0)

    def next(self, n):
        step = 2.0 * math.pi * self.freq / 16000.0
        out = []
        for _ in range(n):
            out.append(int(round(TDC_SINE_PEAK * math.sin(self.phase))))
            self.phase += step
        self.phase %= 2.0 * math.pi
        return out


class TdcWavSource:
    def __init__(self, path):
        with wave.open(path, "rb") as w:
            ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            raw = w.readframes(n)
        if ch != 1 or rate != 16000:
            raise TdcInjectError("WAV 는 16 kHz 모노만 (이 파일: %d Hz, %d 채널)" % (rate, ch))
        if width not in (1, 2, 3, 4) or n == 0:
            raise TdcInjectError("WAV 형식을 읽을 수 없다 (%d 바이트 샘플, %d 개)" % (width, n))
        bits = 8 * width
        samples = []
        for i in range(n):
            b = raw[i * width:(i + 1) * width]
            v = b[0] - 128 if width == 1 else int.from_bytes(b, "little", signed=True)
            samples.append(int(v * TDC_FULL_SCALE / (1 << (bits - 1))))
        self.samples = samples
        self.pos = 0
        self.name = "%s (%.2f s)" % (path.replace("\\", "/").split("/")[-1], n / 16000.0)

    def next(self, n):
        out = []
        while len(out) < n:
            take = min(n - len(out), len(self.samples) - self.pos)
            out += self.samples[self.pos:self.pos + take]
            self.pos = (self.pos + take) % len(self.samples)
        return out


class TdcInject:
    """DMIC 의 주입. DMIC 블록 하나로 한다 (결정_D74)."""

    def __init__(self):
        self.source = None
        self.on = False
        self.n_fill = 0            # 종합 로그 간격 동안 채운 버퍼 (512 샘플)
        self.silent = 0            # 같은 간격의 무음 (ms, dmic_missing_cnt)
        self.total_fill = 0
        self.total_silent = 0

    def start(self, jl, dmic, source):
        """시작 (순서는 이 파일 머리). 처음 채운 두 버퍼를 [(샘플, 0), (샘플, 0)] 으로 돌려준다."""
        d = dmic.m
        d.dmic_inj_enable.put(jl, 0)
        d.dmic_buf_full.write(jl, [1, 1])
        time.sleep(TDC_SETTLE_S)
        out = []
        for buf in (d.dmic_buf0, d.dmic_buf1):
            samples = source.next(TDC_DMIC_LEN)
            buf.write(jl, samples)
            out.append((samples, 0))
        d.dmic_pos.put(jl, 0)
        d.dmic_cur_buf.put(jl, 0)
        d.dmic_inj_enable.put(jl, 1)
        d.dmic_missing_cnt.put(jl, 0)
        self.source = source
        self.on = True
        self.n_fill = len(out)
        self.silent = 0
        self.total_fill += len(out)
        return out

    def service(self, jl, dmic):
        """알림 뒤에 부른다. 비어 있는 버퍼를 모두 채운다.
        돌려주는 것: 채운 순서대로 [(DMIC 창에 보낼 샘플, 그 앞 무음 ms)]. 채운 것이 없으면 [].
        무음이 있었으면 첫 샘플 앞에 무음 1 ms 마다 0 16 개를 붙인다 (TDC_SILENT_SHOW_MS 까지, 결정_D71)."""
        if not self.on:
            return []
        d = dmic.m
        f0, f1 = d.dmic_buf_full.read(jl)
        if f0 and f1:
            return []
        if not f0 and not f1:
            first = d.dmic_cur_buf.get(jl) & 1      # 둘 다 비었다 (PC 가 늦었다): CFX 가 기다리는 버퍼부터
            order = [first, 1 - first]
        elif not f0:
            order = [0]
        else:
            order = [1]
        out = []
        for w in order:
            samples = self.source.next(TDC_DMIC_LEN)
            (d.dmic_buf0 if w == 0 else d.dmic_buf1).write(jl, samples)
            d.dmic_buf_full.put(jl, 1, w)
            out.append((samples, 0))
        self.n_fill += len(order)
        self.total_fill += len(order)
        # 무음은 버퍼를 넘겨준 뒤에 읽는다 (그 뒤로는 CFX 가 세지 않는다. 기록 쪽 가져오기와 같은 모양)
        silent = d.dmic_missing_cnt.get(jl)
        if silent:
            d.dmic_missing_cnt.put(jl, 0)
            zeros = [0] * (TDC_FIFO_BLOCK * min(silent, TDC_SILENT_SHOW_MS))    # 0 은 파형 창 길이까지. 무음 ms 는 그대로 센다
            out[0] = (zeros + out[0][0], silent)
            self.silent += silent
            self.total_silent += silent
        return out

    def reset_interval(self):
        """종합 로그: (채운 버퍼 수, 그 간격의 무음 ms)."""
        n, s = self.n_fill, self.silent
        self.n_fill = 0
        self.silent = 0
        return n, s

    def stop(self, jl, dmic):
        """끄기 (순서는 이 파일 머리). DMIC 기록이 버퍼 0 처음부터, 놓침 0 부터 다시 돈다."""
        d = dmic.m
        d.dmic_buf_full.write(jl, [1, 1])
        d.dmic_inj_enable.put(jl, 0)
        time.sleep(TDC_SETTLE_S)
        d.dmic_pos.put(jl, 0)
        d.dmic_cur_buf.put(jl, 0)
        d.dmic_buf_full.write(jl, [0, 0])
        d.dmic_missing_cnt.put(jl, 0)
        self.on = False
