# -*- coding: utf-8 -*-
"""
tdc_header.py - header 읽기와 블록 판정 (설계 결정_D1~D5, D25~D30)

header: [0] magic 0x7DC001, [1] size (header 칸 수), [2..] 항목 {id, start, size, word_bytes}.
블록 k 시작 주소 = header 주소 + 4 * start. 블록 안: [0] table_size, [1..] 멤버 표 {offset, count}.
멤버 주소 = 블록 시작 + word_bytes * offset.

판정 (결정_D5): PC 가 적은 멤버(순번)가 펌웨어 표에 같은 칸 수로 있으면 일치. 펌웨어에만 있는 멤버는 무시.
보고 (결정_D27, D29): 쓸 수 없는 블록만 한 줄씩, 끝에 요약 한 줄. PC 가 모르는 id 는 무시.
"""

from ..link.tdc_memory import tdc_read_words, tdc_u24
from .tdc_block import TDC_BLOCK_CLASSES, TdcBound, TdcMember
from . import tdc_blocks  # noqa: F401  (블록 클래스 등록)

TDC_MAGIC = 0x7DC001
TDC_TABLE_MAX = 64           # 멤버 표 칸 수 상한 (이보다 크면 잘못 읽은 것으로 본다)
TDC_AREA_MAX_WORDS = 32768   # ARAM2/3 = 32,768 칸 (설계 6 절)


def tdc_read_magic(jl, base):
    return tdc_u24(tdc_read_words(jl, base, 1)[0])


def tdc_bind(jl, base):
    """(bound, lines). bound = {id: TdcBound}, lines = 알릴 줄들 (불가 블록 + 요약)."""
    head = [tdc_u24(v) for v in tdc_read_words(jl, base, 2)]
    if head[0] != TDC_MAGIC:
        return {}, ["디버그 블록 없음 (0x%08X 에 magic 없음, 읽은 값 0x%06X)" % (base, head[0])]
    size = head[1]
    n = (size - 2) // 4 if 2 <= size <= 2 + 4 * 64 else 0
    raw = [tdc_u24(v) for v in tdc_read_words(jl, base + 8, 4 * n)] if n else []
    entries = {}
    spans = []
    for k in range(n):
        bid, start, bsize, wbytes = raw[4 * k:4 * k + 4]
        entries.setdefault(bid, (start, bsize, wbytes))
        spans.append((start, start + bsize * max(wbytes, 1) // 4, bid))

    bad = set()
    spans.sort()
    for (s0, e0, b0), (s1, _e1, b1) in zip(spans, spans[1:]):
        if s1 < e0:
            bad.update((b0, b1))
    for s, e, b in spans:
        if s < size or e > TDC_AREA_MAX_WORDS:
            bad.add(b)

    bound = {}
    lines = []
    for cls in TDC_BLOCK_CLASSES:
        label = "%s(id %d)" % (cls.NAME, cls.ID)
        if cls.ID not in entries:
            lines.append("디버그 블록: %s 펌웨어에 없음" % label)
            continue
        start, _bsize, wbytes = entries[cls.ID]
        addr = base + 4 * start
        tsize = tdc_u24(tdc_read_words(jl, addr, 1)[0])
        if cls.ID in bad or wbytes not in (1, 2, 4) or not 0 < tsize <= TDC_TABLE_MAX or tsize % 2:
            lines.append("디버그 블록: %s 펌웨어 정보 이상" % label)
            continue
        table = [tdc_u24(v) for v in tdc_read_words(jl, addr + 4, tsize)]
        members = []
        ok = True
        for i, (name, elem, count) in enumerate(cls.MEMBERS):
            if 2 * i + 1 >= len(table) or table[2 * i + 1] != count:
                ok = False
                break
            members.append(TdcMember(name, elem, count, addr + wbytes * table[2 * i]))
        if not ok:
            lines.append("디버그 블록: %s PC 툴과 불일치" % label)
            continue
        bound[cls.ID] = TdcBound(cls, addr, members)
    lines.append("디버그 블록 요약: PC 툴 %d개 중 %d개 일치" % (len(TDC_BLOCK_CLASSES), len(bound)))
    return bound, lines
