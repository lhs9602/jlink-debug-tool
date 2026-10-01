# -*- coding: utf-8 -*-
"""
run_tdc_debug_jlink.py - J-Link 디버그 도구 실행

  python run_tdc_debug_jlink.py                 실제 J-Link (tdc_debug_jlink.ini)
  python run_tdc_debug_jlink.py --ini 경로       다른 설정 파일
  python run_tdc_debug_jlink.py -h              옵션 목록

프로세스: main (J-Link, 창 없음) + 터미널 창 (이 프로세스) + 그래프 창 (capture ... on 때 하나씩).
J-Link 를 쓰는 다른 프로그램(RTT Viewer, IDE 디버거 등)과 동시에 쓰지 않는다.
"""

import argparse
import multiprocessing as mp
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TDC_QUEUE_MAX = 400          # 통로 길이. 넘으면 main 이 버린다
# 개발용 가짜 타깃 파일이 있을 때만 --fake, --selftest 를 만든다. 공유 저장소에는 이 파일을 올리지 않는다 (설계 결정_D81, D83)
TDC_HAS_FAKE = os.path.isfile(os.path.join(HERE, "tdc_debug_jlink", "link", "tdc_fake_link.py"))


def tdc_arg_parser():
    """명령 줄 옵션"""
    p = argparse.ArgumentParser(description="J-Link debug tool (RTT + pylink)")
    p.add_argument("--ini", default=os.path.join(HERE, "tdc_debug_jlink.ini"))
    if TDC_HAS_FAKE:
        p.add_argument("--fake", action="store_true", help="J-Link 없이 가짜 타깃")
        p.add_argument("--selftest", action="store_true", help="가짜 타깃으로 자동 점검 후 종료")
    return p


def main(argv=None):
    args = tdc_arg_parser().parse_args(argv)
    selftest = getattr(args, "selftest", False)
    fake = getattr(args, "fake", False) or selftest

    from tdc_debug_jlink.app.tdc_main_loop import tdc_main_process
    from tdc_debug_jlink.tdc_config import tdc_read_config
    from tdc_debug_jlink.ui.tdc_terminal import tdc_terminal_run

    cfg = tdc_read_config(args.ini)
    to_term = mp.Queue(TDC_QUEUE_MAX)
    from_term = mp.Queue(TDC_QUEUE_MAX)
    to_dmic = mp.Queue(TDC_QUEUE_MAX)
    to_vmag = mp.Queue(TDC_QUEUE_MAX)
    stop_evt = mp.Event()
    main_proc = mp.Process(target=tdc_main_process,
                           args=(cfg, fake, to_term, from_term, to_dmic, to_vmag, stop_evt, selftest), daemon=True)
    main_proc.start()
    tdc_terminal_run(to_term, from_term, to_dmic, to_vmag, main_proc, stop_evt, selftest,
                     " (가짜 타깃)" if fake else "")
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    sys.exit(main())
