# -*- coding: utf-8 -*-
"""
tdc_link.py - J-Link 열기, 닫기

순서 (pylink-square): JLink(lib) -> open(serial_no) -> set_tif(SWD) -> connect(chip, speed).
코어를 멈추거나 리셋하지 않는다.
JLink 객체(DLL 로드)는 한 번만 만들어 재시도마다 다시 쓴다. 재시도마다 새로 만들면 종료 때 pylink JLink.__del__ 에서
access violation 이 난 사례가 있다 (2026-09-23 실기, examples/pylink_template/tdc_pylink/tdc_rtt.py 80-84 행 기록).
"""


class TdcLinkError(Exception):
    """연결 단계의 문제를 사람이 읽을 수 있는 말로."""


class TdcLink:
    """실제 J-Link. open() 은 연결된 JLink 객체를 돌려준다."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.jl = None
        self.serial = None

    def _new(self):
        import pylink
        dll = self.cfg.get("dll_path")
        lib = pylink.Library(dllpath=dll) if dll else None
        # pylink 가 DLL 로그를 logging 으로 흘리지 않게 한다
        return pylink.JLink(lib=lib, log=lambda s: None, detailed_log=lambda s: None, warn=lambda s: None)

    def _pick_serial(self):
        serial = self.cfg.get("serial")
        if serial:
            return int(serial)
        found = [int(e.SerialNumber) for e in self.jl.connected_emulators()]
        if len(found) == 1:
            return found[0]
        if not found:
            raise TdcLinkError("J-Link 가 없다. USB 연결과 드라이버를 확인한다")
        raise TdcLinkError("J-Link 가 %d 개다. ini [jlink] serial 로 고른다: %s" % (len(found), ", ".join(map(str, found))))

    def open(self):
        from pylink.enums import JLinkInterfaces
        from pylink.errors import JLinkException

        if self.jl is None:
            self.jl = self._new()
        self.serial = self._pick_serial()
        try:
            self.jl.open(serial_no=self.serial)
        except JLinkException as e:
            raise TdcLinkError("open(%d) 실패: %s (번호, 다른 프로그램이 J-Link 를 잡고 있는지)" % (self.serial, e))
        chip, speed, tif = self.cfg["chip"], self.cfg["speed_khz"], self.cfg["interface"]
        try:
            self.jl.set_tif({"SWD": JLinkInterfaces.SWD, "JTAG": JLinkInterfaces.JTAG}[tif.upper()])
            self.jl.connect(chip, speed=speed)
        except (JLinkException, KeyError) as e:
            self.close()
            raise TdcLinkError("connect(%s, %s kHz, %s) 실패: %s (보드 전원, SWD 배선)" % (chip, speed, tif, e))
        return self.jl

    def close(self):
        if self.jl is not None:
            try:
                self.jl.close()
            except Exception:
                pass

    def describe(self):
        return "S/N %s, %s kHz" % (self.serial, self.cfg["speed_khz"])
