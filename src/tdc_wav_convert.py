# -*- coding: utf-8 -*-
"""
tdc_wav_convert.py - WAV 를 주입에 쓸 수 있는 모양 (16 kHz, 모노, 24 비트 PCM) 으로 바꾼다. J-Link 없이 혼자 돈다 (numpy 필요)

  python tdc_wav_convert.py 파일.wav [파일2.wav ...]    바꾼 파일은 tdc_wav_convert.py 가 있는 폴더의 data/ 에 <이름>_16k.wav 로 생긴다
  python tdc_wav_convert.py 파일.wav -o 결과.wav         바꾼 파일의 이름 (입력이 하나일 때). 폴더를 적으면 그 폴더에 만든다
  python tdc_wav_convert.py 파일.wav --peak -40         최대 크기를 -40 dBFS 로 맞춘다
  python tdc_wav_convert.py 파일.wav --keep-level       크기를 바꾸지 않는다
  python tdc_wav_convert.py                             파일을 고르는 창이 뜬다
tdc_wav_convert.bat 에 WAV 파일을 끌어다 놓아도 된다.

읽을 수 있는 WAV: PCM 8 / 16 / 24 / 32 비트, float 32 / 64 비트. 채널 수와 샘플 속도는 아무것이나.
하는 일
  채널     여러 채널은 평균해 하나로 만든다. 평균하면 소리가 지워지는 파일 (채널끼리 위상이 반대) 은 바꾸지 않는다
  속도     16 kHz 로 바꾼다. 8 kHz 와 입력 속도의 절반 가운데 낮은 쪽보다 높은 소리는 걸러 낸다
           (입력이 16 kHz 이상이면 7.4 kHz 까지 그대로, 8 kHz 부터 -80 dB)
  크기     최대가 TDC_MIC_PEAK (도구의 사인 원천과 같은 마이크 수준, 약 -50.5 dBFS) 가 되게 맞춘다
주입은 WAV 의 0 dBFS 를 입력 최대로 넣는다. 크기를 바꾸지 않으면 (--keep-level) 녹음한 크기 그대로 들어가
마이크 수준보다 훨씬 클 수 있다.
"""

import argparse
import math
import os
import struct
import sys
import wave

try:
    import numpy as np
except ImportError:
    sys.exit("numpy 가 없다. 설치: python -m pip install numpy")

HERE = os.path.dirname(os.path.abspath(__file__))
TDC_OUT_RATE = 16000                # 주입이 받는 샘플 속도 (Hz)
TDC_OUT_WIDTH = 3                   # 바꾼 파일의 샘플 크기 (바이트). 마이크 수준은 16 비트로 쓰면 최대 98 단계뿐이라 거칠다
TDC_FULL_SCALE = 1 << 23            # 24 비트의 최대 (주입의 입력 최대와 같다)
TDC_MIC_PEAK = 25166                # 마이크 수준. tdc_debug_jlink/features/tdc_inject.py 의 TDC_SINE_PEAK 와 같게 둔다
TDC_MIC_PEAK_DBFS = 20.0 * math.log10(TDC_MIC_PEAK / TDC_FULL_SCALE)
TDC_PEAK_MIN_DBFS = -120.0          # --peak 의 아래 끝. 이보다 작으면 24 비트에 남는 것이 없다
TDC_STOP_DB = 80.0                  # 속도를 바꿀 때 걸러 내는 깊이 (dB)
TDC_SINC_ZEROS = 64                 # 필터 길이 (sinc 의 0 을 지나는 횟수). 길수록 8 kHz 가까이까지 그대로 둔다
TDC_TABLE_MAX = 16 * 1024 * 1024    # 필터 표의 최대 칸 수 (128 MB). 흔한 샘플 속도는 수만 ~ 수십만 칸이다
TDC_CHUNK = 4096                    # 한 번에 계산하는 샘플 수 (메모리를 아끼려고 나눈다)
TDC_CANCEL_RATIO = 0.01             # 채널을 평균한 최대가 채널 최대의 이 비율보다 작으면 지워진 것으로 본다 (-40 dB)
TDC_WAVE_PCM, TDC_WAVE_FLOAT, TDC_WAVE_EXTENSIBLE = 1, 3, 0xFFFE


class TdcWavError(Exception):
    pass


def tdc_dbfs(amp):
    """크기 (1.0 = 0 dBFS) 를 dBFS 로"""
    return 20.0 * math.log10(amp) if amp > 0.0 else float("-inf")


def tdc_wav_read(path):
    """WAV 를 읽는다: (샘플 속도, -1 ~ 1 로 맞춘 값 [프레임, 채널], 정보 글).
    wave 모듈은 float 와 EXTENSIBLE 을 읽지 못해 (파이썬 3.11) RIFF 를 직접 읽는다"""
    with open(path, "rb") as f:
        head = f.read(12)
        if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            raise TdcWavError("WAV 파일이 아니다")
        fmt = data = None
        while fmt is None or data is None:
            chunk = f.read(8)
            if len(chunk) < 8:
                break
            size = struct.unpack("<I", chunk[4:])[0]
            # 크기가 실제보다 크게 적힌 파일 (녹음이 끊긴 파일, 크기 칸이 0xFFFFFFFF 인 파일) 은 있는 만큼만 읽는다
            left = max(0, os.fstat(f.fileno()).st_size - f.tell())
            if chunk[:4] == b"fmt ":
                fmt = f.read(min(size, left))
            elif chunk[:4] == b"data":
                data = f.read(min(size, left))
            else:
                f.seek(size, 1)
            if size & 1:
                f.seek(1, 1)                    # 덩어리는 짝수 바이트로 맞춰져 있다
    if fmt is None or len(fmt) < 16 or data is None:
        raise TdcWavError("WAV 의 형식 정보나 소리 데이터가 없다")
    tag, channels, rate, _bps, align, bits = struct.unpack("<HHIIHH", fmt[:16])
    if tag == TDC_WAVE_EXTENSIBLE and len(fmt) >= 26:
        tag = struct.unpack("<H", fmt[24:26])[0]        # 실제 형식은 SubFormat 의 앞 두 바이트
    if channels < 1 or rate < 1:
        raise TdcWavError("채널 수나 샘플 속도가 맞지 않다 (%d 채널, %d Hz)" % (channels, rate))
    # 샘플 하나의 바이트 수. blockAlign 으로 구한다 (24 비트를 4 바이트에 담은 파일이 있다). blockAlign 이 맞지 않으면 비트 수로 구한다
    width = (bits + 7) // 8
    if align % channels == 0 and align // channels >= width:
        width = align // channels
    if tag == TDC_WAVE_PCM and width in (1, 2, 3, 4):
        kind = "PCM %d 비트" % bits
    elif tag == TDC_WAVE_FLOAT and width in (4, 8):
        kind = "float %d 비트" % bits
    else:
        raise TdcWavError("읽을 수 없는 형식이다 (형식 번호 %d, 샘플 %d 바이트). PCM 과 float 만 된다" % (tag, width))
    frames = len(data) // (width * channels)
    if frames == 0:
        raise TdcWavError("소리 데이터가 없다")
    raw = data[:frames * width * channels]
    if tag == TDC_WAVE_FLOAT:
        x = np.frombuffer(raw, dtype="<f4" if width == 4 else "<f8").astype(np.float64)
    elif width == 1:
        x = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0     # 8 비트는 부호 없는 값
    elif width == 2:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    elif width == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        x = ((v ^ 0x800000) - 0x800000).astype(np.float64) / 8388608.0                   # 부호 확장
    else:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2147483648.0
    if not np.all(np.isfinite(x)):
        raise TdcWavError("소리 데이터에 숫자가 아닌 값 (NaN, inf) 이 있다")
    info = "%d Hz, %d 채널, %s, %.2f s" % (rate, channels, kind, frames / float(rate))
    return rate, x.reshape(frames, channels), info


def tdc_resample(x, rate_in, rate_out=TDC_OUT_RATE):
    """샘플 속도를 바꾼다 (창을 씌운 sinc 필터, 여러 위상). 새 속도와 옛 속도 가운데 낮은 쪽의 절반보다
    높은 소리는 걸러 낸다. 출력 n 번째는 입력의 n * rate_in / rate_out 자리다 (늦어지지 않는다)"""
    if rate_in == rate_out:
        return x.copy()
    g = math.gcd(rate_in, rate_out)
    up, down = rate_out // g, rate_in // g              # 출력 n 은 입력 n * down / up 자리
    nyquist = 0.5 * min(1.0, up / float(down))          # 남길 수 있는 가장 높은 주파수 (입력 샘플당 주기 수)
    # Kaiser 창: 걸러 내는 깊이가 TDC_STOP_DB 일 때 넘어가는 폭은 cutoff * k. 넘어가는 구간이 nyquist 에서 끝나게 cutoff 를 잡는다
    k = (TDC_STOP_DB - 7.95) / (14.36 * TDC_SINC_ZEROS)
    cutoff = nyquist / (1.0 + 0.5 * k)
    half = int(math.ceil(TDC_SINC_ZEROS / (2.0 * cutoff)))      # 필터의 한쪽 길이 (입력 샘플)
    if up * (2 * half + 1) > TDC_TABLE_MAX:
        # 16000 과 약수를 거의 나누지 않는 속도 (예: 96001 Hz) 나 깨진 머리글의 속도. 필터 표가 너무 커진다
        raise TdcWavError("이 샘플 속도 (%d Hz) 는 바꿀 수 없다" % rate_in)
    beta = 0.1102 * (TDC_STOP_DB - 8.7)
    taps = np.arange(-half, half + 1, dtype=np.float64)
    # 위상마다 필터 한 줄: table[p][j] = h(j - half - p / up). 위상이 많을 수 있어 나눠서 만든다
    table = np.empty((up, 2 * half + 1), dtype=np.float64)
    for start in range(0, up, TDC_CHUNK):
        phases = np.arange(start, min(start + TDC_CHUNK, up), dtype=np.float64) / up
        t = taps[None, :] - phases[:, None]
        window = np.i0(beta * np.sqrt(np.maximum(0.0, 1.0 - (t / half) ** 2))) / np.i0(beta)
        window[np.abs(t) > half] = 0.0
        rows = 2.0 * cutoff * np.sinc(2.0 * cutoff * t) * window
        table[start:start + len(phases)] = rows / rows.sum(axis=1, keepdims=True)   # 합을 1 로 (크기가 위상에 따라 흔들리지 않게)
    n_out = (len(x) * up + down - 1) // down
    padded = np.concatenate((np.zeros(half), x, np.zeros(half + 1)))
    out = np.empty(n_out, dtype=np.float64)
    offsets = np.arange(2 * half + 1)
    step = max(1, min(TDC_CHUNK, (4 * 1024 * 1024) // (2 * half + 1)))     # 필터가 길면 한 번에 계산하는 수를 줄인다
    for start in range(0, n_out, step):
        pos = np.arange(start, min(start + step, n_out), dtype=np.int64) * down
        base, phase = pos // up, pos % up
        out[start:start + len(pos)] = np.einsum("ij,ij->i", padded[base[:, None] + offsets[None, :]], table[phase])
    return out


def tdc_wav_convert(src, dst, peak_dbfs=TDC_MIC_PEAK_DBFS):
    """src 를 16 kHz, 모노, 24 비트 PCM 으로 바꿔 dst 에 쓴다. peak_dbfs 가 None 이면 크기를 바꾸지 않는다.
    돌려주는 것: {"info": 입력 정보 글, "sec": 출력 길이 (s), "in_dbfs": 바꾸기 전 최대, "out_dbfs": 바꾼 뒤 최대, "notes": 알릴 글}"""
    rate, x, info = tdc_wav_read(src)
    mono = x.mean(axis=1)
    each = float(np.max(np.abs(x)))
    if each > 0.0 and float(np.max(np.abs(mono))) < each * TDC_CANCEL_RATIO:
        raise TdcWavError("채널을 평균하면 소리가 지워진다 (채널끼리 위상이 반대). 한 채널짜리 파일로 만들어 다시 넣는다")
    y = tdc_resample(mono, rate)
    notes = []
    peak = float(np.max(np.abs(y)))
    if peak <= 0.0:
        gain = 1.0
        notes.append("소리가 없는 파일이다 (모두 0)")
    elif peak_dbfs is None:
        gain = 1.0
        if peak > 1.0:                                  # float WAV 나 속도를 바꾼 뒤의 넘침
            gain = 1.0 / peak
            notes.append("최대가 0 dBFS 를 넘어 %.1f dB 줄였다" % tdc_dbfs(peak))
    else:
        gain = 10.0 ** (peak_dbfs / 20.0) / peak
    samples = np.clip(np.rint(y * gain * TDC_FULL_SCALE), -TDC_FULL_SCALE, TDC_FULL_SCALE - 1).astype("<i4")
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    part = dst + ".part"                                # 다 쓴 뒤에 이름을 바꾼다 (쓰다 실패해도 반쪽 파일이 남지 않게)
    try:
        with wave.open(part, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(TDC_OUT_WIDTH)
            w.setframerate(TDC_OUT_RATE)
            w.writeframes(samples.view(np.uint8).reshape(-1, 4)[:, :TDC_OUT_WIDTH].tobytes())
        os.replace(part, dst)
    finally:
        if os.path.exists(part):
            os.remove(part)
    return {"info": info, "sec": len(samples) / float(TDC_OUT_RATE), "in_dbfs": tdc_dbfs(peak),
            "out_dbfs": tdc_dbfs(int(np.max(np.abs(samples))) / float(TDC_FULL_SCALE)), "notes": notes}


def tdc_out_path(src, out, single):
    """바꾼 파일의 경로. out 이 없으면 이 파일이 있는 폴더의 data/, .wav 로 끝나고 입력이 하나면 그 이름, 그 밖에는 폴더"""
    name = os.path.splitext(os.path.basename(src))[0] + "_16k.wav"
    if not out:
        return os.path.join(HERE, "data", name)
    if single and out.lower().endswith(".wav"):
        return out
    return os.path.join(out, name)


def tdc_same_path(path):
    """경로를 견주기 위한 모양 (절대 경로, Windows 에서는 대소문자와 / \\ 를 가리지 않는다)"""
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def tdc_level_text(result, peak_dbfs):
    """크기를 어떻게 했는지 알리는 한 줄"""
    if result["in_dbfs"] == float("-inf"):
        return "크기: 소리가 없다"
    if peak_dbfs is None:
        diff = result["out_dbfs"] - TDC_MIC_PEAK_DBFS
        return "크기: 그대로 (최대 %.1f dBFS. 마이크 수준 %.1f dBFS 보다 %.1f dB %s)" % (
            result["out_dbfs"], TDC_MIC_PEAK_DBFS, abs(diff), "크다" if diff > 0 else "작다")
    return "크기: 최대 %.1f -> %.1f dBFS 로 맞춤 (마이크 수준은 %.1f dBFS. 그대로 두려면 --keep-level)" % (
        result["in_dbfs"], result["out_dbfs"], TDC_MIC_PEAK_DBFS)


def tdc_pick_files():
    """파일을 고르는 창. 창을 띄울 수 없으면 빈 목록"""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        paths = filedialog.askopenfilenames(title="바꿀 WAV 파일", filetypes=[("WAV", "*.wav"), ("모든 파일", "*.*")])
        root.destroy()
        return list(paths)
    except Exception:
        return []


def tdc_arg_parser():
    p = argparse.ArgumentParser(description="WAV -> 16 kHz mono 24-bit PCM (for injection)")
    p.add_argument("files", nargs="*", help="바꿀 WAV 파일. 없으면 고르는 창이 뜬다")
    p.add_argument("-o", "--out", help="바꾼 파일의 이름 (입력이 하나일 때) 또는 폴더. 기본은 tdc_wav_convert.py 가 있는 폴더의 data/")
    level = p.add_mutually_exclusive_group()
    level.add_argument("--peak", type=float, metavar="dBFS",
                       help="최대 크기 (dBFS, %.0f ~ 0). 기본 %.1f (마이크 수준)" % (TDC_PEAK_MIN_DBFS, TDC_MIC_PEAK_DBFS))
    level.add_argument("--keep-level", action="store_true", help="크기를 바꾸지 않는다")
    return p


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")        # 콘솔이 낼 수 없는 글자가 파일 이름에 있어도 멈추지 않게
    args = tdc_arg_parser().parse_args(argv)
    if args.peak is not None and not TDC_PEAK_MIN_DBFS <= args.peak <= 0.0:     # nan 도 여기서 걸린다
        print("--peak 는 %.0f ~ 0 사이로 적는다 (dBFS)" % TDC_PEAK_MIN_DBFS)
        return 1
    peak_dbfs = None if args.keep_level else (args.peak if args.peak is not None else TDC_MIC_PEAK_DBFS)
    files = args.files or tdc_pick_files()
    if not files:
        print("바꿀 파일이 없다. 사용법: python tdc_wav_convert.py 파일.wav")
        return 1
    inputs = {tdc_same_path(f) for f in files}
    written = set()
    failed = 0
    for src in files:
        name = os.path.basename(src)
        dst = tdc_out_path(src, args.out, len(files) == 1)
        try:
            if os.path.isdir(src):
                raise TdcWavError("폴더다. WAV 파일을 넣는다")
            if tdc_same_path(dst) in inputs:
                raise TdcWavError("바꾼 파일의 이름이 입력 파일과 같다 (%s)" % os.path.basename(dst))
            if tdc_same_path(dst) in written:
                raise TdcWavError("이름이 같은 입력이 또 있다. %s 는 앞의 것으로 이미 만들었다" % os.path.basename(dst))
            existed = os.path.exists(dst)
            result = tdc_wav_convert(src, dst, peak_dbfs)
        except (TdcWavError, OSError, MemoryError) as e:
            failed += 1
            print("%s: 바꾸지 못했다 (%s)" % (name, "메모리가 모자란다" if isinstance(e, MemoryError) else e))
            continue
        written.add(tdc_same_path(dst))
        print("%s: %s" % (name, result["info"]))
        print("  -> %s%s" % (os.path.abspath(dst), "  (있던 파일을 덮어썼다)" if existed else ""))
        print("     16000 Hz, 모노, 24 비트, %.2f s" % result["sec"])
        print("     %s" % tdc_level_text(result, peak_dbfs))
        for s in result["notes"]:
            print("     %s" % s)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
