# -*- coding: utf-8 -*-
"""
tdc_config.py - ini 읽기와 기본값

ini 가 없거나 값이 비면 TDC_DEFAULTS 를 쓴다. 상대 경로(data_dir, out_dir)는 ini 파일 폴더 기준으로 바꾼다.
"""

import configparser
import os

TDC_DEFAULTS = {
    "serial": None,
    "dll_path": None,
    "chip": "Cortex-M3",
    "interface": "SWD",
    "speed_khz": 12000,               # 설계 결정_D46
    "header_addr": 0x21010000,        # 설계 결정_D35
    "rtt_cb": 0x20000000,
    "rtt_up": 0,
    "rtt_down": 0,
    "rtt_poll_ms": 10,
    "poll_ms": 1,
    "watch_ms": 100,
    "reconnect_s": 1.0,
    "log_s": 1,
    "read_max": 256,
    "data_dir": "data",
    "out_dir": "logs",
}

# (ini 절, ini 키, 설정 이름, 형)
_TDC_KEYS = (
    ("jlink", "serial", "serial", "int"),
    ("jlink", "dll_path", "dll_path", "str"),
    ("target", "chip", "chip", "str"),
    ("target", "interface", "interface", "str"),
    ("target", "speed_khz", "speed_khz", "int"),
    ("debug_block", "header_addr", "header_addr", "int"),
    ("rtt", "cb_address", "rtt_cb", "int"),
    ("rtt", "up_channel", "rtt_up", "int"),
    ("rtt", "down_channel", "rtt_down", "int"),
    ("rtt", "poll_ms", "rtt_poll_ms", "int"),
    ("loop", "poll_ms", "poll_ms", "int"),
    ("loop", "watch_ms", "watch_ms", "int"),
    ("loop", "reconnect_s", "reconnect_s", "float"),
    ("loop", "log_s", "log_s", "int"),
    ("loop", "read_max", "read_max", "int"),
    ("inject", "data_dir", "data_dir", "str"),
    ("save", "out_dir", "out_dir", "str"),
)


def tdc_read_config(path):
    """설정 dict. path 가 없으면 기본값만."""
    cfg = dict(TDC_DEFAULTS)
    base = os.path.dirname(os.path.abspath(path)) if path else os.getcwd()
    if path and os.path.isfile(path):
        p = configparser.ConfigParser(inline_comment_prefixes=(";", "#"), interpolation=None)
        with open(path, encoding="utf-8-sig") as f:
            p.read_file(f)
        for sect, key, name, kind in _TDC_KEYS:
            raw = p.get(sect, key, fallback="").strip()
            if not raw:
                continue
            if kind == "int":
                cfg[name] = int(raw, 0)
            elif kind == "float":
                cfg[name] = float(raw)
            else:
                cfg[name] = raw
    for name in ("data_dir", "out_dir"):
        if not os.path.isabs(cfg[name]):
            cfg[name] = os.path.join(base, cfg[name])
    cfg["read_max"] = max(1, min(int(cfg["read_max"]), 256))
    return cfg
