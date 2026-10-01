# -*- coding: utf-8 -*-
"""
tdc_capture.py - 더블 버퍼 가져오기 (DMIC, vMag 공통)

펌웨어 규칙 (1.5 tdc_debug_jlink.h 블록 정의 주석):
  main.c 는 블록의 enable 이 1 인 동안만 그 블록의 함수를 부른다 (0 이면 부르지 않는다. 초기값 0).
  CFX 는 buf_full 이 0 인 버퍼에 이어 쓰고, 차면 buf_full = 1, 다른 버퍼로 옮기며 알린다.
  두 버퍼가 모두 차 있으면 쓰지 않고 missing_cnt 를 1 늘린다 (1 = 1 ms).
PC:
  찬 버퍼 고르기 (둘 다 차면 지금 버퍼 번호 쪽이 먼저 찼다) -> 버퍼 읽기 -> buf_full 0 -> missing_cnt 읽고 0.
  PC 는 missing 을 읽은 즉시 0 으로 되돌리므로 읽은 값이 곧 방금 받은 버퍼 뒤의 공백(ms)이다.
  켜기: enable 0 -> 2 ms -> buf_full 0, 0, 위치 0, 버퍼 번호 0, missing_cnt 0 -> enable 1 (초기화는 PC 가 한다).
  끄기: enable 0.
"""

import time

TDC_SETTLE_S = 0.002         # enable 을 0 으로 쓴 뒤 CFX 의 그 1 ms 가 끝나기를 기다리는 시간

TDC_FIFO_BLOCK = 16          # 1 ms = 16 샘플
TDC_VMAG_BANDS = 32


def tdc_dmic_time_order(samples):
    """DMIC 버퍼는 16 샘플 묶음마다 FIFO 순서 (인덱스 0 이 가장 최근) 다. 묶음마다 뒤집어 시간 순서로."""
    out = []
    for i in range(0, len(samples), TDC_FIFO_BLOCK):
        out.extend(reversed(samples[i:i + TDC_FIFO_BLOCK]))
    return out


def tdc_vmag_frames(values):
    """vMag 버퍼 512 칸 -> 16 프레임 x 32 밴드."""
    return [values[i:i + TDC_VMAG_BANDS] for i in range(0, len(values), TDC_VMAG_BANDS)]


class TdcDoubleBuffer:
    """prefix 는 멤버 이름 앞부분 ("dmic" / "vmag"). cur 는 지금 버퍼 번호 멤버의 뒷부분, pos 는 버퍼 안 위치 멤버의 뒷부분
    (DMIC "cur_buf", "pos" / vMag "write_buf", "write_pos". DMIC 버퍼는 주입도 쓰므로 이름이 다르다, 설계 결정_D70)."""

    def __init__(self, prefix, cur, pos):
        self.p = prefix
        self.cur = cur
        self.pos = pos
        self.on = False
        self.n_buf = 0          # 종합 로그 간격 동안 받은 버퍼
        self.missed = 0         # 같은 간격의 놓침 (ms)
        self.total_buf = 0
        self.total_missed = 0

    def _m(self, blk, name):
        return getattr(blk.m, "%s_%s" % (self.p, name))

    def pick(self, jl, blk):
        """찬 버퍼 번호. 없으면 None."""
        f0, f1 = self._m(blk, "buf_full").read(jl)
        if f0 and f1:
            return self._m(blk, self.cur).get(jl) & 1
        return 0 if f0 else (1 if f1 else None)

    def take(self, jl, blk):
        """찬 버퍼 하나를 가져온다. (값 리스트, 놓친 ms) 또는 None."""
        w = self.pick(jl, blk)
        if w is None:
            return None
        data = self._m(blk, "buf%d" % w).read(jl)
        self._m(blk, "buf_full").put(jl, 0, w)
        miss_m = self._m(blk, "missing_cnt")
        miss = miss_m.get(jl)
        miss_m.put(jl, 0)
        self.n_buf += 1
        self.missed += miss
        self.total_buf += 1
        self.total_missed += miss
        return data, miss

    def take_all(self, jl, blk):
        """찬 버퍼를 모두 (많아야 2 개)."""
        out = []
        for _ in range(2):
            got = self.take(jl, blk)
            if got is None:
                break
            out.append(got)
        return out

    def start(self, jl, blk):
        """가져오기 켜기: 블록을 처음 상태로 두고 enable 1. enable 이 0 인 동안 펌웨어는 이 블록의 함수를 부르지 않는다."""
        self._m(blk, "enable").put(jl, 0)
        time.sleep(TDC_SETTLE_S)                    # CFX 가 그 1 ms 에 이미 함수 안에 있었을 수 있다
        self._m(blk, "buf_full").write(jl, [0, 0])
        self._m(blk, self.pos).put(jl, 0)
        self._m(blk, self.cur).put(jl, 0)
        self._m(blk, "missing_cnt").put(jl, 0)
        self._m(blk, "enable").put(jl, 1)
        self.n_buf = 0
        self.missed = 0

    def stop(self, jl, blk):
        """가져오기 끄기: enable 0."""
        self._m(blk, "enable").put(jl, 0)

    def reset_interval(self):
        n, m = self.n_buf, self.missed
        self.n_buf = 0
        self.missed = 0
        return n, m
