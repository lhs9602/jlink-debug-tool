# -*- coding: utf-8 -*-
"""
tdc_save.py - 가져온 데이터 파일 저장 (명령 save on|off, 기본 끔)

DMIC: WAV 16 kHz 모노 24 비트 (시간 순서로 되돌린 값). vMag: CSV (시각, 프레임 번호, 밴드 32 개).
IFFT: WAV 16 kHz 2 채널 24 비트 (채널 1 기준 = AGC 출력, 채널 2 출력 = DAC 로 낸 것. 받은 그대로, 지연을 맞추지 않는다).
      값은 DAC 로 낼 때처럼 << 5 하고 24 비트로 자른다.
파일은 가져오기를 켠 채 save on 을 할 때, 또는 save on 상태에서 가져오기를 켤 때 연다.
"""

import os
import time
import wave


class TdcSaver:
    def __init__(self, out_dir):
        self.out_dir = out_dir
        self.on = False
        self.wav = None
        self.csv = None
        self.ifft_wav = None
        self.vmag_n = 0
        self.names = []

    def _path(self, kind, ext):
        os.makedirs(self.out_dir, exist_ok=True)
        return os.path.join(self.out_dir, "%s_%s.%s" % (kind, time.strftime("%Y%m%d_%H%M%S"), ext))

    def open_dmic(self):
        if self.on and self.wav is None:
            path = self._path("dmic", "wav")
            self.wav = wave.open(path, "wb")
            self.wav.setnchannels(1)
            self.wav.setsampwidth(3)
            self.wav.setframerate(16000)
            self.names.append(path)
            return path
        return None

    def open_vmag(self):
        if self.on and self.csv is None:
            path = self._path("vmag", "csv")
            self.csv = open(path, "w", encoding="utf-8", newline="\n")
            self.csv.write("time_s,frame," + ",".join("b%d" % k for k in range(1, 33)) + "\n")
            self.vmag_n = 0
            self.names.append(path)
            return path
        return None

    def open_ifft(self):
        if self.on and self.ifft_wav is None:
            path = self._path("ifft", "wav")
            self.ifft_wav = wave.open(path, "wb")
            self.ifft_wav.setnchannels(2)
            self.ifft_wav.setsampwidth(3)
            self.ifft_wav.setframerate(16000)
            self.names.append(path)
            return path
        return None

    def ifft(self, ref, out):
        if self.ifft_wav is not None:
            lim = (1 << 23) - 1
            self.ifft_wav.writeframes(b"".join(
                (max(-lim - 1, min(lim, int(v) << 5)) & 0xFFFFFF).to_bytes(3, "little")
                for pair in zip(ref, out) for v in pair))

    def dmic(self, samples):
        if self.wav is not None:
            self.wav.writeframes(b"".join((int(v) & 0xFFFFFF).to_bytes(3, "little") for v in samples))

    def vmag(self, frames):
        if self.csv is not None:
            t = time.time()
            for f in frames:
                self.csv.write("%.3f,%d,%s\n" % (t, self.vmag_n, ",".join(str(int(v)) for v in f)))
                self.vmag_n += 1

    def close_dmic(self):
        if self.wav is not None:
            self.wav.close()
            self.wav = None

    def close_vmag(self):
        if self.csv is not None:
            self.csv.close()
            self.csv = None

    def close_ifft(self):
        if self.ifft_wav is not None:
            self.ifft_wav.close()
            self.ifft_wav = None

    def close_all(self):
        self.close_dmic()
        self.close_vmag()
        self.close_ifft()
