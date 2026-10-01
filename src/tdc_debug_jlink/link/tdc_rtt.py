# -*- coding: utf-8 -*-
"""
tdc_rtt.py - SEGGER RTT (pylink rtt_*)

pylink rtt_* 는 RTT Viewer 와 같은 DLL 함수(JLINK_RTTERMINAL_*)를 부른다. rtt_start 뒤에는 DLL 이 타깃 버퍼를
따로 비워 두므로 rtt_read 를 조금 늦게 불러도 글이 버려지지 않는다.

제어블록 (SEGGER_RTT_CB): 0..15 acID "SEGGER RTT", 16 MaxNumUpBuffers, 20 MaxNumDownBuffers,
24.. aUp[] 24 바이트씩 (sName, pBuffer, SizeOfBuffer, WrOff, RdOff, Flags), 그 뒤 aDown[].
리셋이나 부트로더 -> 앱 전환이 있으면 제어블록이 다시 채워지므로 비교해서 RTT 를 다시 시작한다.
"""

import codecs
import time

TDC_RTT_ID = b"SEGGER RTT"
TDC_RTT_DOWN_CHUNK = 15      # 1.5 하향 버퍼 16 B, 링은 1 B 를 비워 두므로 15 B 씩
TDC_RTT_DESC_WORDS = 6


class TdcRttError(Exception):
    """RTT 시작 실패, 제어블록 이상."""


class TdcRtt:
    def __init__(self, cb_address, up=0, down=0):
        self.cb = cb_address
        self.up = up
        self.down = down
        self.snap = None
        self.tx = bytearray()
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.running = False

    def snapshot(self, jl, max_up=3, max_down=3):
        """제어블록의 이름과 채널 설명(pBuffer, size, flags). WrOff, RdOff 는 비교에서 뺀다."""
        words = jl.memory_read32(self.cb, TDC_RTT_DESC_WORDS + TDC_RTT_DESC_WORDS * (max_up + max_down))
        words = [int(w) & 0xFFFFFFFF for w in words]
        ident = b"".join(w.to_bytes(4, "little") for w in words[:4])[:len(TDC_RTT_ID)]
        descs = []
        for k in range(max_up + max_down):
            d = words[TDC_RTT_DESC_WORDS + TDC_RTT_DESC_WORDS * k:][:TDC_RTT_DESC_WORDS]
            descs.append((d[1], d[2], d[5]))
        return {"id": ident, "desc": descs}

    @staticmethod
    def _ok(snap):
        return snap["id"] == TDC_RTT_ID and snap["desc"][0][0] != 0 and snap["desc"][0][1] != 0

    def start(self, jl, timeout_s=1.0):
        snap = self.snapshot(jl)
        if not self._ok(snap):
            raise TdcRttError("RTT 제어블록 없음 (0x%08X, id=%r)" % (self.cb, snap["id"]))
        jl.rtt_start(self.cb)
        end = time.perf_counter() + timeout_s
        while jl.rtt_get_status().NumUpBuffers <= 0:
            if time.perf_counter() >= end:
                self.stop(jl)
                raise TdcRttError("RTT 제어블록을 %.1f s 안에 잡지 못했다 (0x%08X)" % (timeout_s, self.cb))
            time.sleep(0.02)
        self.snap = snap
        self.tx.clear()
        self.running = True

    def stop(self, jl):
        self.running = False
        try:
            jl.rtt_stop()
        except Exception:
            pass

    def check(self, jl):
        """제어블록이 바뀌었으면 RTT 를 다시 시작하고 True. 지워졌으면 멈추고 TdcRttError."""
        snap = self.snapshot(jl)
        if self.snap is None or snap == self.snap:
            return False
        self.stop(jl)
        if not self._ok(snap):
            raise TdcRttError("RTT 제어블록이 지워졌다")
        self.start(jl)
        return True

    def queue_tx(self, data):
        if self.running:
            self.tx += data

    def pump(self, jl):
        """보낼 키를 15 B 까지 쓰고, 받은 글을 문자열로 돌려준다 (없으면 빈 문자열)."""
        if not self.running:
            return ""
        if self.tx:
            n = jl.rtt_write(self.down, list(self.tx[:TDC_RTT_DOWN_CHUNK]))
            del self.tx[:max(0, int(n))]
        data = jl.rtt_read(self.up, 4096)
        if not data:
            return ""
        return self.decoder.decode(bytes(data))
