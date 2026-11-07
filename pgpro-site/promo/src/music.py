"""موسیقی الکترونیک ۱۲۵ BPM برای کلیپ pgpro (کاملاً سنتز؛ بدون نمونه‌ی ضبط‌شده)."""
import numpy as np
from scipy import signal
from scipy.io import wavfile

SR = 44100
BPM = 125
BEAT = 60 / BPM
BAR = 4 * BEAT
TOTAL = 18 * BAR + 1.6
N = int(TOTAL * SR)
rng = np.random.default_rng(7)
L = np.zeros(N); R = np.zeros(N)


def idx(t): return int(round(t * SR))


def add(buf, t, x, gain=1.0):
    i = idx(t)
    if i >= len(buf): return
    x = x[: len(buf) - i]
    buf[i:i + len(x)] += x * gain


def add_st(t, x, g=1.0, pan=0.0):
    add(L, t, x, g * np.sqrt(0.5 * (1 - pan))); add(R, t, x, g * np.sqrt(0.5 * (1 + pan)))


def env_exp(n, tau): return np.exp(-np.arange(n) / (tau * SR))


def kick():
    n = idx(0.45); tt = np.arange(n) / SR
    f = 45 + 110 * np.exp(-tt / 0.03)
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) * env_exp(n, 0.16)
    click = rng.standard_normal(idx(0.004)) * 0.4
    x[: len(click)] += click
    return np.tanh(x * 1.6)


def hp(x, fc, order=2):
    b, a = signal.butter(order, fc / (SR / 2), "high"); return signal.lfilter(b, a, x)


def lp(x, fc, order=2):
    b, a = signal.butter(order, min(fc, SR / 2 - 100) / (SR / 2), "low"); return signal.lfilter(b, a, x)


def bp(x, lo, hi):
    b, a = signal.butter(2, [lo / (SR / 2), hi / (SR / 2)], "band"); return signal.lfilter(b, a, x)


def clap():
    n = idx(0.28); x = np.zeros(n)
    for k, d in enumerate((0, 0.011, 0.022)):
        m = idx(0.25); burst = rng.standard_normal(m) * env_exp(m, 0.006 if k < 2 else 0.07)
        x[idx(d): idx(d) + m] += burst[: n - idx(d)]
    return bp(x, 900, 5000) * 1.4


def hat(open_=False):
    n = idx(0.22 if open_ else 0.05)
    return hp(rng.standard_normal(n), 7000) * env_exp(n, 0.07 if open_ else 0.012)


def saw(freq, dur, detune=0.0):
    n = idx(dur); tt = np.arange(n) / SR
    return signal.sawtooth(2 * np.pi * freq * (1 + detune) * tt + rng.uniform(0, 6.28))


def supersaw(freqs, dur, voices=5, spread=0.012):
    n = idx(dur); x = np.zeros(n)
    for f in freqs:
        for v in range(voices):
            x += saw(f, dur, (v - (voices - 1) / 2) * spread / voices * 2)
    return x / (len(freqs) * voices)


def adsr(n, a=0.005, d=0.1, s=0.7, r=0.05):
    e = np.ones(n) * s; ai, di, ri = idx(a), idx(d), idx(r)
    e[:ai] = np.linspace(0, 1, ai); e[ai:ai + di] = np.linspace(1, s, len(e[ai:ai + di]))
    if ri: e[-ri:] *= np.linspace(1, 0, ri)
    return e


# آکوردها: Am – F – C – G (یک آکورد در هر میزان)
CH = [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (261.63, 329.63, 392.0), (196.0, 246.94, 293.66)]
ROOT = [55.0, 43.65, 65.41, 49.0]

# بخش‌ها (میزان): ۰-۱ مقدمه، ۲ دراپ، ۲-۱۱ کامل، ۱۲ بیلد، ۱۳-۱۴ دراپ دوم، ۱۵-۱۷ پایان
DRUMS = [b for b in range(2, 12)] + [13, 14]
side = np.ones(N)  # پمپ سایدچین


def duck(t):
    n = idx(BEAT); e = 1 - 0.75 * np.exp(-np.arange(n) / (0.09 * SR))
    i = idx(t); m = min(n, N - i); side[i:i + m] = np.minimum(side[i:i + m], e[:m])


for bar in range(18):
    t0 = bar * BAR
    if bar in DRUMS:
        for b in range(4):
            add_st(t0 + b * BEAT, kick(), 0.95); duck(t0 + b * BEAT)
            add_st(t0 + b * BEAT + BEAT / 2, hat(True), 0.16, 0.2)
            for s in (0.25, 0.75):
                add_st(t0 + b * BEAT + s * BEAT, hat(), 0.10, -0.3)
        for b in (1, 3):
            add_st(t0 + b * BEAT, clap(), 0.42)
    if bar in (0, 1):
        for k in range(16):
            add_st(t0 + k * BEAT / 4, hat(), 0.05 + 0.04 * (bar * 16 + k) / 32, 0.3)
    if bar == 15:
        add_st(t0, kick(), 1.0)

# پد سوپرسا با فیلتر باز شونده در مقدمه
pad_l = np.zeros(N); pad_r = np.zeros(N)
for bar in range(18):
    t0 = bar * BAR; ch = CH[bar % 4]
    dur = BAR + 0.15 if bar < 17 else BAR + 1.6
    x = supersaw([f / 2 for f in ch] + list(ch), dur, voices=5, spread=0.02)
    cut = 600 + 2600 * min(1, bar / 2) if bar < 2 else (3200 if bar not in (12,) else 1200 + 2400 * 0.5)
    if bar >= 15: cut = 2200 - 400 * (bar - 15)
    x = lp(x, min(cut, 2800), 4) * adsr(len(x), 0.02, 0.3, 0.8, 0.12)
    add(pad_l, t0, x, 0.32); add(pad_r, t0, np.roll(x, 300), 0.32)

# باس با پمپ
bass = np.zeros(N)
for bar in range(18):
    if bar < 2 or bar == 12 or bar > 15: continue
    t0 = bar * BAR; f = ROOT[bar % 4]
    for k in range(8):
        n_dur = BEAT / 2
        x = saw(f * (2 if k % 2 else 1), n_dur) * 0.6 + np.sin(2 * np.pi * f * np.arange(idx(n_dur)) / SR)
        x = lp(x, 900) * adsr(len(x), 0.004, 0.08, 0.7, 0.02)
        add(bass, t0 + k * n_dur, x, 0.42)

# آرپژ پلاک ۱۶تایی
arp_l = np.zeros(N); arp_r = np.zeros(N)
pattern = [0, 1, 2, 1, 2, 0, 1, 2, 0, 2, 1, 2, 0, 1, 2, 2]
for bar in range(18):
    if bar < 1 or bar == 12 or bar > 16: continue
    t0 = bar * BAR; ch = CH[bar % 4]
    for k in range(16):
        if bar == 1 and k < 8: continue
        f = ch[pattern[k]] * 2 * (2 if k in (7, 15) else 1)
        d = BEAT / 4
        n = idx(d * 1.6); tt = np.arange(n) / SR
        x = (signal.square(2 * np.pi * f * tt, 0.3) * 0.5 + signal.sawtooth(2 * np.pi * f * 1.005 * tt) * 0.5)
        x = lp(x, 3200, 4) * env_exp(n, 0.06)
        g = 0.11 if bar < 16 else 0.11 * (1 - k / 16)
        if k % 2: add(arp_r, t0 + k * d, x, g)
        else: add(arp_l, t0 + k * d, x, g)

# لید استب در بخش دوم (میزان ۸-۱۱ و ۱۳-۱۴)
lead = np.zeros(N)
for bar in list(range(8, 12)) + [13, 14]:
    t0 = bar * BAR; ch = CH[bar % 4]
    for pos in (0, 0.75, 1.5, 2.5, 3.0):
        x = supersaw([f * 2 for f in ch], BEAT * 0.45, voices=4, spread=0.03)
        x = lp(x, 4200, 4) * adsr(len(x), 0.003, 0.12, 0.35, 0.05)
        add(lead, t0 + pos * BEAT, x, 0.30)


# رایزر نویز و اسنیر رول
def riser(t, dur, g=0.35):
    n = idx(dur); x = rng.standard_normal(n); out = np.zeros(n); seg = idx(0.05)
    for i in range(0, n, seg):
        p = i / n; lo = 300 + 6000 * p ** 2
        out[i:i + seg] = bp(x[i:i + seg + 400], lo, min(lo * 2.2, 18000))[:len(out[i:i + seg])]
    tt = np.arange(n) / SR
    sweep = np.sin(2 * np.pi * np.cumsum(200 + 1400 * (tt / dur) ** 2) / SR) * 0.25
    add_st(t, (out + sweep) * np.linspace(0, 1, n) ** 2, g)


def snare_roll(t, dur):
    steps = [0.25, 0.25, 0.125, 0.125, 0.0625, 0.0625, 0.0625, 0.0625]
    tt = t; i = 0
    while tt < t + dur - 0.01:
        st = steps[min(i * len(steps) // 16, len(steps) - 1)] * BEAT * 2
        add_st(tt, clap(), 0.12 + 0.3 * (tt - t) / dur); tt += st; i += 1


def impact(t, g=0.9):
    n = idx(2.2); tt = np.arange(n) / SR
    boom = np.sin(2 * np.pi * np.cumsum(30 + 60 * np.exp(-tt / 0.08)) / SR) * env_exp(n, 0.5)
    crash = hp(rng.standard_normal(n), 3000) * env_exp(n, 0.45) * 0.35
    add_st(t, np.tanh((boom + crash) * 1.5), g)


riser(0.3, 2 * BAR - 0.3, 0.30)
snare_roll(1.5 * BAR, BAR / 2)
impact(2 * BAR)
riser(12 * BAR, BAR, 0.32); snare_roll(12 * BAR, BAR)
impact(13 * BAR, 0.8)
riser(14 * BAR + BAR / 2, BAR / 2, 0.25)
impact(15 * BAR, 1.0)
for b in range(2, 16, 4):
    if b not in (2,): impact(b * BAR, 0.25)

# میکس: سایدچین روی پد، باس، آرپ، لید
L += (pad_l + bass + arp_l * 1.0 + lead * 0.9) * side
R += (pad_r + bass + arp_r * 1.0 + lead * 0.9) * side
L += arp_r * 0.25 * side; R += arp_l * 0.25 * side

# ریورب ساده (کانولوشن با دم نویز)
ir_n = idx(1.1); ir = rng.standard_normal((2, ir_n)) * env_exp(ir_n, 0.28); ir[:, :idx(0.01)] = 0
ir = np.stack([lp(ir[0], 4500, 2), lp(ir[1], 4500, 2)])
wetL = signal.fftconvolve(L, ir[0])[:N] * 0.012; wetR = signal.fftconvolve(R, ir[1])[:N] * 0.012
L += wetL; R += wetR

mix = np.stack([L, R], 1)
mix = hp(mix.T, 28, 2).T
mix = lp(mix.T, 15000, 2).T
fade = np.ones(N); fn = idx(1.4); fade[-fn:] = np.linspace(1, 0, fn) ** 1.5
mix *= fade[:, None]
mix /= np.max(np.abs(mix)) + 1e-9
mix = np.tanh(mix * 1.8) / np.tanh(1.8) * 0.93
wavfile.write("music.wav", SR, (mix * 32767).astype(np.int16))
print("ok", round(TOTAL, 2), "s")
