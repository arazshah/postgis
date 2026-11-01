"""موسیقی ملایم بی‌کلام برای ویدیوهای راهنما: پد آکورد (لا‌مینور، فا، دو، سل) و آرپژ نرم؛ خروجی WAV استریو.
python music.py خروجی.wav ثانیه"""
import sys
import wave

import numpy as np

out, secs = sys.argv[1], float(sys.argv[2])
sr = 44100
t = np.arange(int(sr * secs)) / sr
chords = [(220.00, 261.63, 329.63), (174.61, 220.00, 261.63), (261.63, 329.63, 392.00), (196.00, 246.94, 293.66)]
bar = 4.0
sig = np.zeros_like(t)
for i in range(int(secs // bar) + 1):
    a, b = int(i * bar * sr), min(len(t), int((i + 1) * bar * sr))
    if a >= len(t):
        break
    tt = t[a:b] - t[a]
    env = np.minimum(1, tt / 0.9) * np.minimum(1, (bar - tt) / 0.9)
    for f in chords[i % 4]:
        sig[a:b] += env * 0.11 * (np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(2 * np.pi * f * 2 * tt))
    for k in range(8):  # آرپژ هشتایی
        s0 = int(k * 0.5 * sr)
        n = min(int(0.9 * sr), b - a - s0)
        if n <= 0:
            continue
        f = chords[i % 4][k % 3] * 2
        tn = np.arange(n) / sr
        sig[a + s0:a + s0 + n] += 0.07 * np.exp(-tn * 4.5) * np.sin(2 * np.pi * f * tn)
sig *= np.minimum(1, t / 2) * np.minimum(1, (secs - t) / 3)
sig = sig / max(1e-9, np.abs(sig).max()) * 0.5
delay = int(0.27 * sr)  # اکوی استریو
lt, rt = sig.copy(), sig.copy()
lt[delay:] += 0.35 * sig[:-delay]
rt[delay * 2:] += 0.3 * sig[:-delay * 2]
pcm = (np.stack([lt, rt], 1) / 1.4 * 32767).astype("<i2")
with wave.open(out, "wb") as w:
    w.setnchannels(2), w.setsampwidth(2), w.setframerate(sr)
    w.writeframes(pcm.tobytes())
