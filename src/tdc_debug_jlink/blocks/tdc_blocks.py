# -*- coding: utf-8 -*-
"""
tdc_blocks.py - 블록 정의. 펌웨어(1.5 CFX tdc_debug_jlink.h, tdc_debug_jlink.c 의 tdc_debug_jlink_register)가 기준이다.

펌웨어 멤버 표 한 줄 = 여기 _fields_ 한 줄. 같은 순서, 같은 크기.
펌웨어가 dmic_buf[2][512] 를 두 줄(순번 4, 5)로 등록하므로 여기도 dmic_buf0, dmic_buf1 두 줄이다.
블록을 더하면 이 파일에 클래스 하나를 더한다 (자동 등록).
"""

from .tdc_block import TdcBlock, pmem_int, pmem_uint

TDC_DMIC_LEN = 512           # DMIC 버퍼 하나 (32 ms). 기록과 주입이 같이 쓴다 (설계 결정_D69, D74)
TDC_VMAG_BANDS = 32
TDC_VMAG_FRAMES = 16
TDC_VMAG_LEN = TDC_VMAG_BANDS * TDC_VMAG_FRAMES


class DmicLog(TdcBlock):
    ID = 1
    NAME = "DMIC"
    _fields_ = [
        ("dmic_buf_full", pmem_int * 2),
        ("dmic_pos", pmem_int),
        ("dmic_cur_buf", pmem_int),
        ("dmic_missing_cnt", pmem_uint),            # PC 가 늦은 1 ms (기록: 쓰지 못함, 주입: 무음)
        ("dmic_buf0", pmem_int * TDC_DMIC_LEN),     # 펌웨어 표 4 = dmic_buf[0]
        ("dmic_buf1", pmem_int * TDC_DMIC_LEN),     # 펌웨어 표 5 = dmic_buf[1]
        ("dmic_inj_enable", pmem_int),              # 펌웨어 표 6. PC: 1 주입, 0 기록
        ("dmic_enable", pmem_int),                  # 펌웨어 표 7 (맨 끝). PC: 1 사용, 0 사용 안 함 (0 이면 펌웨어가 DMIC 함수를 부르지 않는다)
    ]


class Vmag(TdcBlock):
    ID = 2
    NAME = "vMag"
    _fields_ = [
        ("vmag_buf_full", pmem_int * 2),
        ("vmag_write_pos", pmem_int),
        ("vmag_write_buf", pmem_int),
        ("vmag_missing_cnt", pmem_uint),
        ("vmag_buf0", pmem_int * TDC_VMAG_LEN),     # 16 프레임 x 32 밴드
        ("vmag_buf1", pmem_int * TDC_VMAG_LEN),
        ("vmag_enable", pmem_int),                  # 펌웨어 표 6 (맨 끝). PC: 1 사용, 0 사용 안 함 (0 이면 펌웨어가 vMag 함수를 부르지 않는다)
    ]
