# -*- coding: utf-8 -*-
"""
tdc_debug_jlink - J-Link(pylink) 디버그 도구

폴더
  link/      J-Link 연결, 메모리, RTT. main 프로세스만 쓴다
  blocks/    디버그 블록 규약 (header, 블록 정의)
  features/  블록 기능 (DMIC, vMag, 주입)
  app/       main 프로세스 루프와 명령
  ui/        창 프로세스 (터미널, DMIC, vMag). J-Link 를 만지지 않는다 (link/ 를 import 하지 않는다)

실행은 src/run_tdc_debug_jlink.py
"""

TDC_VERSION = "0.1.0"
