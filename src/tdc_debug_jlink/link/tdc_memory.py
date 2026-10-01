# -*- coding: utf-8 -*-
"""
tdc_memory.py - CM3 주소 32 비트 읽기, 쓰기

J-Link 는 Cortex-M3 에 붙으므로 주소는 모두 CM3 바이트 주소, 값은 32 비트다.
CFX 메모리(P 메모리 한 칸)는 CM3 에서 4 바이트로 보이고 값은 아래 24 비트다 (tdc_s24, tdc_u24).

사용자 쓰기 (명령 write)
  TDC_ALLOW_USER_WRITE 가 False 이면 tdc_user_write() 는 쓰지 않고 TdcWriteDisabled 를 낸다.
  타깃 메모리를 잘못 쓰면 펌웨어가 멈출 수 있어 기본은 막아 둔다. 켜려면 이 파일의 상수를 True 로 고친다.
  (ini 나 명령으로는 켤 수 없다.)
  도구가 기능으로 하는 쓰기(flag 지우기, 주입 버퍼 채우기)는 tdc_write_words() 를 쓰며 이 상수와 무관하다.

측정 (명령 perf)
  TDC_STATS 에 읽기, 쓰기 호출 수와 걸린 시간, 읽은 워드 수를 더한다. perf 가 읽고 0 으로 되돌린다.
"""

import time

TDC_ALLOW_USER_WRITE = False

TDC_DCRDR = 0xE000EDF8       # ARM CoreDebug->DCRDR. 펌웨어 CM3 ISR 이 알림마다 값을 바꾼다
TDC_MASK24 = 0xFFFFFF
TDC_MASK32 = 0xFFFFFFFF

TDC_STATS = {"read_n": 0, "read_s": 0.0, "read_words": 0, "write_n": 0, "write_s": 0.0}


def tdc_stats_reset():
    for k in TDC_STATS:
        TDC_STATS[k] = 0


class TdcWriteDisabled(Exception):
    """사용자 쓰기가 꺼져 있다."""


def tdc_read_words(jl, addr, count):
    """32 비트 워드 count 개 (부호 없는 정수)."""
    t0 = time.perf_counter()
    out = [int(v) & TDC_MASK32 for v in jl.memory_read32(addr, count)]
    TDC_STATS["read_n"] += 1
    TDC_STATS["read_s"] += time.perf_counter() - t0
    TDC_STATS["read_words"] += count
    return out


def tdc_read_word(jl, addr):
    return tdc_read_words(jl, addr, 1)[0]


def tdc_write_words(jl, addr, values):
    """도구 기능이 쓰는 쓰기. 음수는 32 비트 2 의 보수로."""
    t0 = time.perf_counter()
    jl.memory_write32(addr, [int(v) & TDC_MASK32 for v in values])
    TDC_STATS["write_n"] += 1
    TDC_STATS["write_s"] += time.perf_counter() - t0


def tdc_user_write(jl, addr, value):
    """사용자 명령 write. 꺼져 있으면 TdcWriteDisabled. 켜져 있으면 쓰고 되읽은 값을 돌려준다."""
    if not TDC_ALLOW_USER_WRITE:
        raise TdcWriteDisabled("write: 비활성 (tdc_memory.py TDC_ALLOW_USER_WRITE = False)")
    tdc_write_words(jl, addr, [value])
    return tdc_read_word(jl, addr)


def tdc_s24(v):
    """아래 24 비트를 부호 있는 정수로 (CFX int)."""
    v &= TDC_MASK24
    return v - 0x1000000 if v & 0x800000 else v


def tdc_u24(v):
    """아래 24 비트 (CFX unsigned int)."""
    return v & TDC_MASK24
