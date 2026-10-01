# -*- coding: utf-8 -*-
"""
tdc_commands.py - pylink 터미널 명령 (main 프로세스에서 J-Link 스레드가 처리한다)

명령 하나를 받아 답 글을 main.reply() 로 낸다. J-Link 를 쓰는 명령은 연결되어 있을 때만.
막힌 블록을 쓰는 명령은 타깃에 읽거나 쓰지 않고 한 줄로 알린다 (설계 결정_D30).
"""

from ..link.tdc_memory import TdcWriteDisabled, tdc_read_words, tdc_user_write

TDC_HELP_PYLINK = (
    "[pylink 명령]\n"
    "  help                      이 목록\n"
    "  status                    연결, 블록, 켠 기능\n"
    "  read 주소 [개수]           32 비트 워드 읽기 (16 진). 예: read 0x21010000 4\n"
    "  write 주소 값              32 비트 한 워드 쓰기 (기본 비활성)\n"
    "  capture dmic on|off       DMIC 가져오기. 켜면 DMIC 창이 열리고, 창을 닫으면 꺼진다\n"
    "                            주입은 DMIC 창에서 켜고 끈다 (사인 1/2/4/6 kHz, WAV 16 kHz 모노)\n"
    "  capture vmag on|off       vMag 가져오기. 켜면 vMag 창이 열리고, 창을 닫으면 꺼진다\n"
    "  save on|off               가져온 데이터 파일 저장 (DMIC WAV, vMag CSV). 기본 off\n"
    "  log N                     종합 로그 간격 (초). 동작 중일 때만 나온다\n"
    "  perf                      측정: 루프, 알림 처리, J-Link 호출 시간 (지난 perf 뒤). 보고 나면 0 부터\n"
)

# RTT 명령은 펌웨어가 정한다 (도구는 누른 키를 그대로 보낸다). 아래 목록은 Sullivan 1.5 CM3 main.c 의
# RTT 입력 처리 (SEGGER_RTT_Read 뒤의 키 비교) 에서 옮겼다 (2026-10-01). 펌웨어의 키가 바뀌면 여기도 고친다
TDC_HELP_RTT = (
    "[RTT 명령]\n"
    "  0 ~ 9                     오디오 볼륨 (누른 숫자 + 1)\n"
    "  e                         모든 맵 지우기\n"
    "  l                         이벤트 로그 읽기\n"
    "  x                         데이터 로깅 오류 만들기\n"
    "  t                         무결성 오류 이벤트 로그 쓰기\n"
    "  f                         오디오 입력 LPF (2-tap 이동평균) 켜고 끄기. 맵 4 번은 항상 켠다\n"
    "  v                         vMag cos 가중 켜고 끄기\n"
    "  m                         지금 자극에 쓰는 맵 값 출력\n"
    "  d                         LPF 전후 16 샘플 덤프 요청 (1 차 IIR 빌드에서만)\n"
)

TDC_HELP = TDC_HELP_PYLINK + "\n" + TDC_HELP_RTT

TDC_ID_DMIC = 1
TDC_ID_VMAG = 2


def _num(s):
    return int(s, 0)


def tdc_command(main, line):
    words = line.split()
    if not words:
        return
    cmd = words[0].lower()
    try:
        handler = _HANDLERS.get(cmd)
        if handler is None:
            main.reply("%s: 없는 명령 (help)" % line)
            return
        handler(main, words, line)
    except (ValueError, IndexError):
        main.reply("%s: 형식이 맞지 않다 (help)" % line)


def _need_link(main, line):
    if main.jl is None:
        main.reply("%s: 연결 안 됨" % line)
        return False
    return True


def _need_block(main, bid, line):
    if not _need_link(main, line):
        return None
    blk = main.bound.get(bid)
    if blk is None:
        name = {TDC_ID_DMIC: "DMIC", TDC_ID_VMAG: "vMag"}[bid]
        main.reply("%s: %s(id %d) 사용 불가" % (line, name, bid))
    return blk


def _help(main, words, line):
    main.reply(TDC_HELP.rstrip("\n"))


def _status(main, words, line):
    main.reply(main.status_text())


def _read(main, words, line):
    addr = _num(words[1])
    count = _num(words[2]) if len(words) > 2 else 1
    if not 1 <= count <= main.cfg["read_max"]:
        main.reply("read: 개수는 1 ~ %d" % main.cfg["read_max"])
        return
    if addr % 4:
        main.reply("read: 주소는 4 의 배수")
        return
    if not _need_link(main, line):
        return
    vals = tdc_read_words(main.jl, addr, count)
    out = []
    for i in range(0, count, 4):
        out.append("0x%08X: %s" % (addr + 4 * i, " ".join("0x%08X" % v for v in vals[i:i + 4])))
    main.reply("\n".join(out))


def _write(main, words, line):
    addr, value = _num(words[1]), _num(words[2])
    if not _need_link(main, line):
        return
    before = getattr(main.jl, "write_calls", None)
    try:
        back = tdc_user_write(main.jl, addr, value)
        main.reply("0x%08X <- 0x%08X, 되읽음 0x%08X" % (addr, value & 0xFFFFFFFF, back))
    except TdcWriteDisabled as e:
        main.reply(str(e))
    if before is not None:
        main.user_write_calls += main.jl.write_calls - before


def _capture(main, words, line):
    what, onoff = words[1].lower(), words[2].lower()
    if what not in ("dmic", "vmag") or onoff not in ("on", "off"):
        raise ValueError
    if onoff == "off":
        if what == "dmic" and main.inj.on:
            main.stop_inject()                  # 주입은 DMIC 의 옵션이라 함께 끈다 (결정_D76)
            main.reply("주입 끔")
        main.stop_capture(what)                 # enable 0: 펌웨어가 그 블록의 함수를 부르지 않는다
        (main.saver.close_dmic if what == "dmic" else main.saver.close_vmag)()
        main.reply("capture %s off" % what)
        return
    blk = _need_block(main, TDC_ID_DMIC if what == "dmic" else TDC_ID_VMAG, line)
    if blk is None:
        return
    main.start_capture(what)
    main.reply("capture %s on" % what)
    main.term("open", what)


def _save(main, words, line):
    onoff = words[1].lower()
    if onoff == "on":
        main.saver.on = True
        opened = []
        if main.cap["dmic"].on:
            opened.append(main.saver.open_dmic())
        if main.cap["vmag"].on:
            opened.append(main.saver.open_vmag())
        opened = [p for p in opened if p]
        main.reply("save on" + ("" if not opened else ": " + ", ".join(opened)))
    elif onoff == "off":
        main.saver.on = False
        main.saver.close_all()
        main.reply("save off")
    else:
        raise ValueError


def _perf(main, words, line):
    main.reply(main.perf.report())


def _log(main, words, line):
    n = int(words[1])
    if n < 1:
        raise ValueError
    main.log_s = n
    main.reply("종합 로그 간격 %d 초" % n)


_HANDLERS = {"help": _help, "status": _status, "read": _read, "write": _write, "capture": _capture,
             "save": _save, "log": _log, "perf": _perf}
