"""موسیقی پرانرژی و بی‌کلام برای ویدیوهای راهنما: ضرب ۱۲۴، کیک، کلپ، های‌هت، بیس سینت با پمپ، آکورد کوتاه و آرپژ شانزدهم.
ساختار: دو میزان آغاز با بالا‌رفتن فیلتر و رایزر ← بدنه‌ی پرانرژی (هر ۸ میزان یک «برک» کوتاه) ← ضربه‌ی پایانی و محو.
python music.py خروجی.wav ثانیه"""
import sys
import wave

import numpy as np

SR = 44100
BPM = 124
BEAT = 60.0 / BPM
STEP = BEAT / 4  # شانزدهم
BAR = BEAT * 4
SEED = 7


def midi(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def lowpass(x, cutoff):
    """فیلتر تک‌قطبی؛ cutoff می‌تواند آرایه (همان طول x) باشد."""
    a = 1 - np.exp(-2 * np.pi * np.asarray(cutoff) / SR)
    a = np.broadcast_to(a, x.shape)
    # فیلتر بازگشتی با پنجره‌ی کوتاه؛ برای طول‌های کم سریع است
    out = np.empty_like(x)
    y = 0.0
    for i in range(len(x)):
        y += a[i] * (x[i] - y)
        out[i] = y
    return out


def highpass_noise(rng, n, k=1):
    x = rng.standard_normal(n)
    for _ in range(k):
        x = np.diff(x, prepend=0)
    return x


def put(buf, start, sig, gain=1.0):
    a = int(start * SR)
    if a >= len(buf) or a < 0:
        return
    b = min(len(buf), a + len(sig))
    buf[a:b] += gain * sig[: b - a]


def kick():
    t = np.arange(int(0.32 * SR)) / SR
    f = 48 + 110 * np.exp(-t * 28)
    ph = 2 * np.pi * np.cumsum(f) / SR
    click = np.exp(-t * 400) * 0.6
    return (np.sin(ph) * np.exp(-t * 9) + click)


def clap(rng):
    out = np.zeros(int(0.28 * SR))
    for off in (0.0, 0.012, 0.024):
        n = int(0.09 * SR)
        t = np.arange(n) / SR
        s = highpass_noise(rng, n) * np.exp(-t * 45)
        a = int(off * SR)
        out[a:a + n] += s
    t = np.arange(len(out)) / SR
    out += highpass_noise(rng, len(out)) * np.exp(-t * 18) * 0.35
    return out * 0.45


def hat(rng, open_=False):
    d = 0.22 if open_ else 0.05
    n = int(d * SR)
    t = np.arange(n) / SR
    return highpass_noise(rng, n, 2) * np.exp(-t * (14 if open_ else 90)) * 0.10


def bass_note(freq, dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    saw = 2 * ((t * freq) % 1.0) - 1
    sub = np.sin(2 * np.pi * freq * t)
    env = np.minimum(1, t / 0.004) * np.exp(-t * 5.5)
    cut = 180 + 900 * np.exp(-t * 14)
    return lowpass(saw * 0.6, cut) * env + sub * 0.55 * env


def pluck(freq, dur=0.32):
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = (np.sin(2 * np.pi * freq * t) + 0.45 * np.sin(2 * np.pi * freq * 2.005 * t)
         + 0.2 * np.sin(2 * np.pi * freq * 3.01 * t))
    return s * np.exp(-t * 11) * np.minimum(1, t / 0.002)


def stab(freqs, dur=0.34):
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for f in freqs:
        for det in (0.996, 1.0, 1.004):
            out += 2 * ((t * f * det) % 1.0) - 1
    env = np.minimum(1, t / 0.006) * np.exp(-t * 9)
    return lowpass(out / (3 * len(freqs)), 3200) * env


def riser(dur, rng):
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = highpass_noise(rng, n)
    env = (t / dur) ** 2.2
    return x * env * 0.25


# Am – F – C – G، هر آکورد یک میزان؛ (ریشه‌ی بیس، نوت‌های آکورد)
PROG = [
    (45, (57, 60, 64)),
    (41, (57, 60, 65)),
    (48, (55, 60, 64)),
    (43, (55, 59, 62)),
]


def render(secs):
    rng = np.random.default_rng(SEED)
    n = int(secs * SR)
    drums = np.zeros(n)
    bass = np.zeros(n)
    mel = np.zeros(n)
    fx = np.zeros(n)
    k, c, h, oh = kick(), clap(rng), hat(rng), hat(rng, True)
    end_t = secs - 3.0  # آغاز محو
    nbars = int(secs / BAR) + 1
    pump = np.ones(n)  # سایدچین: ضعیف‌شدن بیس/آکورد روی هر کیک
    pt = np.arange(int(0.24 * SR)) / SR
    pump_shape = 1 - 0.75 * np.exp(-pt * 14)

    for bar in range(nbars):
        t0 = bar * BAR
        if t0 >= secs:
            break
        root, chord = PROG[bar % 4]
        intro = bar < 2
        brk = (bar % 8 == 7) and not intro and t0 + BAR < end_t  # برک: بدون کیک و بیس
        last = t0 + BAR >= end_t
        for s16 in range(16):
            t = t0 + s16 * STEP
            if t >= secs:
                break
            beat_pos, sub = divmod(s16, 4)
            # --- طبل
            if not brk and not (intro and bar == 0):
                if sub == 0:
                    put(drums, t, k, 1.0)
                    a = int(t * SR)
                    seg = pump[a:a + len(pump_shape)]
                    seg *= pump_shape[: len(seg)] if len(seg) < len(pump_shape) else pump_shape
            if not brk and beat_pos in (1, 3) and sub == 0 and not intro:
                put(drums, t, c, 0.8)
            if not (intro and bar == 0):
                if sub == 2:
                    put(drums, t, oh if not intro else h, 0.9)
                elif sub in (1, 3) and not intro:
                    put(drums, t, h, 0.55 if sub == 1 else 0.8)
            # --- بیس: هشتایی روی «و» و ضرب اول، با جهش اکتاو
            if not brk and not intro:
                if s16 in (0, 3, 6, 8, 11, 14):
                    note = root + (12 if s16 in (6, 14) else 0)
                    put(bass, t, bass_note(midi(note), STEP * (2.4 if s16 in (0, 8) else 1.6)), 0.85)
            # --- آرپژ شانزدهم
            arp = [chord[0], chord[1], chord[2], chord[1] + 12]
            if (not intro or bar == 1) and not (brk and s16 % 2):
                f = midi(arp[(s16 % 4)] + 12)
                put(mel, t, pluck(f), 0.32 if not brk else 0.4)
            # --- ضربه‌ی آکورد روی «و» ی ضربه‌های ۲ و ۴ و سنکوپ
            if not intro and not brk and s16 in (2, 7, 10, 15):
                put(mel, t, stab([midi(x + 12) for x in chord]), 0.42)
        # برک: آکورد کشیده و رایزر
        if brk:
            pad = np.zeros(int(BAR * SR))
            tt = np.arange(len(pad)) / SR
            for x in chord:
                pad += np.sin(2 * np.pi * midi(x + 12) * tt) + 0.4 * np.sin(2 * np.pi * midi(x + 24) * tt)
            pad *= np.minimum(1, tt / 0.3) * 0.12
            put(mel, t0, pad, 1.0)
            put(fx, t0 + BAR * 0.5, riser(BAR * 0.5, rng), 1.0)
        if bar == 0:
            put(fx, 0, riser(min(BAR * 2, secs / 2), rng), 0.8)
        if last:
            break
    # ضربه‌ی پایانی و محو
    put(drums, max(0, secs - 1.6), k, 1.0)
    put(mel, max(0, secs - 1.6), stab([midi(x + 12) for x in PROG[0][1]], 1.4), 0.5)
    mix = (drums * 0.95 + (bass * 0.9 + mel * 0.75) * pump + fx)
    t = np.arange(n) / SR
    fade_in = np.minimum(1, t / 0.5)
    fade_out = np.minimum(1, np.maximum(0, (secs - t) / 1.2))
    mix *= fade_in * fade_out
    # فشرده‌سازی نرم و نرمال‌سازی (صدای زمینه، نه روی متن مرحله‌ها)
    mix = np.tanh(mix * 1.5) / np.tanh(1.5)
    mix = mix / max(1e-9, np.abs(mix).max()) * 0.5
    return mix


def main():
    out, secs = sys.argv[1], float(sys.argv[2])
    sig = render(secs)
    # استریو: همان سیگنال با اکوی کوتاه و تاخیر متفاوت برای عرض بیشتر
    d1, d2 = int(0.012 * SR), int(0.019 * SR)
    left, right = sig.copy(), sig.copy()
    left[d1:] += 0.18 * sig[:-d1]
    right[d2:] += 0.18 * sig[:-d2]
    pcm = (np.stack([left, right], 1) / 1.2 * 32767).astype("<i2")
    with wave.open(out, "wb") as w:
        w.setnchannels(2), w.setsampwidth(2), w.setframerate(SR)
        w.writeframes(pcm.tobytes())


if __name__ == "__main__":
    main()
