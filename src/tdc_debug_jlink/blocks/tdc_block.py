# -*- coding: utf-8 -*-
"""
tdc_block.py - 블록 정의의 틀 (설계 결정_D31, D33, D36)

블록은 ctypes.Structure 모양으로 적는다. _fields_ 한 줄 = 펌웨어 멤버 표 한 항목 (같은 순서, 같은 크기).
table_size 와 멤버 표는 적지 않는다 (이 틀이 안다).

    class DmicLog(TdcBlock):
        ID = 1
        NAME = "DMIC"
        _fields_ = [("dmic_buf_full", pmem_int * 2), ("dmic_pos", pmem_int), ...]

자료형은 P 메모리 한 칸 기준: pmem_int (아래 24 비트, 부호 있음), pmem_uint (아래 24 비트).
CM3 에서는 한 칸이 4 바이트다. 이 두 타입과 그 배열 밖의 타입을 쓰면 클래스를 만들 때 오류가 난다.

연결 때 tdc_header 가 펌웨어 멤버 표로 주소를 채운 TdcBound 를 만든다. 사용:
    blk.m.dmic_pos.get(jl)                값 하나
    blk.m.dmic_buf0.read(jl)              배열 전체 (값 리스트)
    blk.m.dmic_buf_full.put(jl, 0, 1)     순번 1 에 0 쓰기
"""

import ctypes

from ..link.tdc_memory import tdc_read_words, tdc_s24, tdc_u24, tdc_write_words


class pmem_int(ctypes.c_int32):
    """P 메모리 한 칸, 부호 있는 24 비트."""


class pmem_uint(ctypes.c_uint32):
    """P 메모리 한 칸, 부호 없는 24 비트."""


TDC_BLOCK_CLASSES = []      # 정의한 블록 클래스가 자동으로 들어간다


def _tdc_field_info(name, ftype):
    """(원소 타입, 칸 수). 허용하지 않는 타입이면 TypeError."""
    if isinstance(ftype, type) and issubclass(ftype, ctypes.Array):
        elem, count = ftype._type_, ftype._length_
    else:
        elem, count = ftype, 1
    if elem not in (pmem_int, pmem_uint):
        raise TypeError("%s: 디버그 블록 멤버는 pmem_int, pmem_uint 와 그 배열만 쓴다 (%r)" % (name, ftype))
    return elem, count


class TdcBlock(ctypes.Structure):
    ID = None
    NAME = ""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.MEMBERS = [(name,) + _tdc_field_info(name, ftype) for name, ftype in cls.__dict__.get("_fields_", [])]
        if cls.ID is not None:
            TDC_BLOCK_CLASSES.append(cls)


class TdcMember:
    """주소가 채워진 멤버 하나."""

    def __init__(self, name, elem, count, addr):
        self.name = name
        self.count = count
        self.addr = addr
        self.conv = tdc_s24 if elem is pmem_int else tdc_u24

    def read(self, jl, start=0, n=None):
        n = self.count - start if n is None else n
        return [self.conv(v) for v in tdc_read_words(jl, self.addr + 4 * start, n)]

    def get(self, jl, index=0):
        return self.read(jl, index, 1)[0]

    def put(self, jl, value, index=0):
        tdc_write_words(jl, self.addr + 4 * index, [value])

    def write(self, jl, values, start=0):
        tdc_write_words(jl, self.addr + 4 * start, values)


class TdcBound:
    """판정을 통과한 블록. m.<멤버 이름> 으로 TdcMember 에 닿는다."""

    def __init__(self, cls, start_addr, members):
        self.cls = cls
        self.id = cls.ID
        self.name = cls.NAME
        self.addr = start_addr

        class _M:
            pass
        self.m = _M()
        for mem in members:
            setattr(self.m, mem.name, mem)
