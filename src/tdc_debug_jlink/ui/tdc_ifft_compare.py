# -*- coding: utf-8 -*-
"""
tdc_ifft_compare.py - IFFT 창의 비교 계산 (Tk, matplotlib 을 쓰지 않는다. numpy 만)

기준 (AGC 출력) 과 출력 (DAC 로 낸 것) 은 펌웨어가 같은 1 ms 의 16 샘플을 같은 위치에 쓴 것이다.
IFFT 오디오 모드의 출력은 기준보다 TDC_IFFT_DELAY 샘플 늦은 소리라, 출력[k] 의 짝은 기준[k - 지연] 이다.
지연이 버퍼 길이 (512) 와 달라 버퍼 단위로는 짝이 맞지 않는다. 그래서 버퍼를 이어 붙인 흐름에서 맞춘다.

이어짐이 끊기는 때 (그 뒤 지연만큼의 출력은 짝이 없거나 틀리다. 비교에서 뺀다):
  놓친 ms 가 있다, 버퍼 안에서 모드가 바뀌었다 (mode_cnt 가 0 도 32 도 아니다), 앞 버퍼와 모드가 다르다
  (IFFT 오디오 모드에 들어간 직후 31 ms 는 중첩 합산 버퍼가 0 에서 차오른다), 화면을 멈췄다가 다시 받는다.
값은 블록의 칸 값 그대로 둔다 (Q24.0, DAC 로 낼 때의 << 5 전).
"""

TDC_IFFT_DELAY = 496         # IFFT 오디오 모드의 기대 지연 (샘플). 1.5 tdc_ifft_audio.h: 32 번이 다 더해진 칸부터 나간다 (31 ms)
TDC_IFFT_MODE_FULL = 32      # mode_cnt 가 이 값이면 그 버퍼는 전부 IFFT 오디오 모드
TDC_IFFT_MEASURE_N = 4096    # 지연을 잴 때 쓰는 출력 샘플 수
TDC_IFFT_MAX_LAG = 640       # 재는 지연의 범위 (0 ~ 이 값, 샘플)
TDC_IFFT_PEAK_MIN = 0.5      # 상관 봉우리가 이보다 낮으면 잴 수 없음
TDC_IFFT_SECOND_MAX = 0.95   # 둘째 봉우리가 첫째의 이 비율 이상이면 잴 수 없음 (주기 신호: 사인)
TDC_IFFT_STATS_N = 16000     # 수치를 내는 구간 (최근 1 초의 출력)

TDC_IFFT_MODE_OFF = 0        # 기존 경로
TDC_IFFT_MODE_ON = 1         # IFFT 오디오 모드
TDC_IFFT_MODE_MIXED = 2      # 버퍼 안에서 바뀌었다


class TdcIfftCompare:
    def __init__(self, np, keep):
        """keep: 간직하는 샘플 수 (그리는 구간 + TDC_IFFT_MAX_LAG 이상)."""
        self.np = np
        self.keep = keep
        self.ref = np.zeros(keep)
        self.out = np.zeros(keep)
        self.since = np.zeros(keep, dtype=np.int64)     # 그 샘플이 끊긴 뒤 몇 번째인가
        self.mode_of = np.full(keep, TDC_IFFT_MODE_MIXED, dtype=np.int8)
        self.filled = 0
        self.run = 0                # 끊긴 뒤 이어진 샘플 수
        self.mode = None            # 마지막 버퍼의 모드
        self.broken = True          # 다음 버퍼는 끊긴 것으로 본다
        self.buffers = 0
        self.measured = None        # 잰 지연 (샘플). 잴 수 없으면 None
        self.measure_note = "대기"

    # ------------------------------------------------------------------ 받기
    def mark_break(self):
        """받지 못한 구간이 있다 (화면 멈춤 뒤)."""
        self.broken = True

    def feed(self, ref, out, mode_cnt, missed_ms):
        np = self.np
        r = np.asarray(ref, dtype=np.float64)
        o = np.asarray(out, dtype=np.float64)
        n = len(r)
        mode = (TDC_IFFT_MODE_OFF if mode_cnt == 0 else
                TDC_IFFT_MODE_ON if mode_cnt == TDC_IFFT_MODE_FULL else TDC_IFFT_MODE_MIXED)
        if self.broken or missed_ms or mode == TDC_IFFT_MODE_MIXED or mode != self.mode:
            self.run = 0
        self.broken = False
        if mode == TDC_IFFT_MODE_MIXED:
            since = np.zeros(n, dtype=np.int64)
        else:
            since = self.run + np.arange(n)
            self.run += n
        for arr, new in ((self.ref, r), (self.out, o), (self.since, since)):
            arr[:-n] = arr[n:]
            arr[-n:] = new
        self.mode_of[:-n] = self.mode_of[n:]
        self.mode_of[-n:] = mode
        self.filled = min(self.filled + n, self.keep)
        self.mode = mode
        self.buffers += 1
        self._measure()

    # ------------------------------------------------------------------ 지연
    def expected_delay(self):
        return TDC_IFFT_DELAY if self.mode == TDC_IFFT_MODE_ON else 0

    def _measure(self):
        """최근 출력 TDC_IFFT_MEASURE_N 샘플과 기준의 상관이 가장 큰 지연. 잴 수 없으면 None 과 이유."""
        np = self.np
        n, lag = TDC_IFFT_MEASURE_N, TDC_IFFT_MAX_LAG
        self.measured = None
        if self.mode == TDC_IFFT_MODE_MIXED or self.since[-n] < lag:
            self.measure_note = "대기"       # 이어진 샘플이 모자란다
            return
        o = self.out[-n:]
        r = self.ref[-(n + lag):]
        e_o = float(np.dot(o, o))
        if e_o <= 0.0:
            self.measure_note = "잴 수 없음 (출력 0)"
            return
        c = np.correlate(r, o, "valid")[::-1]               # c[d] = sum 출력[k] * 기준[k - d]
        cs = np.concatenate(([0.0], np.cumsum(r * r)))
        e_r = (cs[n:] - cs[:-n])[::-1]
        c = c / np.sqrt(np.maximum(e_r, 1e-12) * e_o)
        best = int(np.argmax(c))
        p1 = float(c[best])
        rest = np.ones(len(c), dtype=bool)
        rest[max(0, best - 2):best + 3] = False
        p2 = float(c[rest].max())
        if p1 < TDC_IFFT_PEAK_MIN:
            self.measure_note = "잴 수 없음 (닮지 않음)"
        elif p2 >= TDC_IFFT_SECOND_MAX * p1:
            self.measure_note = "잴 수 없음 (주기 신호)"
        else:
            self.measured = best
            self.measure_note = "%d" % best

    # ------------------------------------------------------------------ 그릴 것
    def view(self, n, delay, back=0):
        """(기준 n 샘플, 그 짝인 출력 n 샘플). 출력을 delay 만큼 당겨 같은 시간축에 놓는다.
        delay 0 이면 받은 그대로다. 오른쪽 끝은 가장 최근의 출력에서 back 샘플 앞이다."""
        k = self.keep - back
        return self.ref[k - delay - n:k - delay], self.out[k - n:k]

    # ------------------------------------------------------------------ 수치
    def stats(self, delay):
        """최근 TDC_IFFT_STATS_N 출력 가운데 비교할 수 있는 샘플의 수치. 없으면 None.
        비교할 수 있는 샘플: 지금 모드의 것이고, 끊긴 뒤 delay 샘플이 지난 것."""
        np = self.np
        if self.mode in (None, TDC_IFFT_MODE_MIXED):
            return None
        n = min(TDC_IFFT_STATS_N, self.filled, self.keep - delay)
        k = self.keep
        ok = (self.mode_of[k - n:] == self.mode) & (self.since[k - n:] >= delay)
        count = int(ok.sum())
        if count < 16:
            return None
        o = self.out[k - n:][ok]
        r = self.ref[k - delay - n:k - delay][ok]
        e_r = float(np.dot(r, r))
        if e_r <= 0.0:
            return {"count": count, "silent": True, "max_diff": float(np.max(np.abs(o - r)))}
        rms_r = np.sqrt(e_r / count)
        d = o - r
        g = float(np.dot(o, r)) / e_r                       # 최소제곱 크기
        d_fit = o - g * r

        def db(x):
            return 20.0 * np.log10(x) if x > 0 else float("-inf")

        return {"count": count, "silent": False,
                "gain_db": db(np.sqrt(float(np.dot(o, o)) / count) / rms_r),
                "err_db": db(np.sqrt(float(np.dot(d, d)) / count) / rms_r),
                "err_fit_db": db(np.sqrt(float(np.dot(d_fit, d_fit)) / count) / rms_r),
                "max_diff": float(np.max(np.abs(d)))}
