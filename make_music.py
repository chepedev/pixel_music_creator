#!/usr/bin/env python3
"""Procedural looping chiptune BGM generator — Python 3 stdlib only.

Writes 44.1 kHz / 16-bit / mono WAV loops built from three layers summed on
an 8-steps-per-bar eighth-note grid: a seeded random LEAD melody, a FIXED
per-bar BASS groove, and an optional quiet SPARKLE arpeggio. Every note is
rendered into the loop buffer with wrap-around accumulation, so decay tails
that spill past the end land back at the start — the file loops seamlessly
with no fades.

Usage:
    python3 make_music.py --mood driving --seed 42 --bpm 105 --bars 8 \
        --out music_battle.wav
    python3 make_music.py --mood driving,warm,driving --bars 12
    python3 make_music.py --mood driving:4,warm:4,driving:4

--mood also takes a comma-separated mix: the song plays each mood's section
in order (lead, bass groove, and sparkle all switch on the bar line) and the
whole thing still loops seamlessly back to the first section. Bare names
split --bars evenly; mood:N pins a section to exactly N bars.

The seed fully determines the melody: same seed = identical file. Omit
--seed to get a random one (it is printed so you can keep a tune you like).
"""

import argparse
import math
import os
import random
import struct
import wave

SR = 44100
STEPS_PER_BAR = 8  # eighth-note steps


def note(dur, midi, kind="square", duty=0.5, vol=0.5, attack=0.005, decay=8.0):
    """One note as a list of float samples: linear attack, exponential decay.

    dur is the full render length in seconds including the ringing tail;
    decay is the exponential rate in 1/s.
    """
    freq = 440.0 * 2.0 ** ((midi - 69) / 12.0)
    out = []
    for i in range(int(dur * SR)):
        t = i / SR
        ph = (t * freq) % 1.0
        if kind == "square":
            s = 1.0 if ph < duty else -1.0
        elif kind == "triangle":
            s = 4.0 * abs(ph - 0.5) - 1.0
        else:  # sine
            s = math.sin(2.0 * math.pi * ph)
        env = min(1.0, t / attack) if attack > 0 else 1.0
        env *= math.exp(-decay * t)
        out.append(s * env * vol)
    return out


# bass_pattern: semitone offsets from bass_root per step, None = rest. The
# bass is deliberately fixed — the constant groove is what makes the random
# lead feel intentional. lead_decay / bass_decay are total decay constants
# over the held length (converted to a per-second rate at call time), so
# short and long notes share the same pluck shape.
MOODS = {
    "warm": dict(
        scale=[0, 2, 4, 7, 9], root=72,
        lead_wave="triangle", lead_duty=0.5, rest_prob=0.34,
        lead_octaves=[-12, 0, 0, 12], lead_lengths=[1, 1, 2, 3],
        lead_vol=0.50, lead_attack=0.005, lead_decay=4.5,
        bass_root=36, bass_pattern=[0, None, 7, None, 4, None, 7, None],
        bass_wave="triangle", bass_duty=0.5, bass_hold=2,
        bass_vol=0.55, bass_decay=3.5, bass_tail=1.3,
        sparkle=True, sparkle_vol=0.16, rms_db=-16.0,
    ),
    "driving": dict(
        scale=[0, 2, 3, 5, 7, 8, 10], root=69,
        lead_wave="square", lead_duty=0.4, rest_prob=0.25,
        lead_octaves=[-12, 0, 0, 12], lead_lengths=[1, 1, 1, 2],
        lead_vol=0.36, lead_attack=0.004, lead_decay=5.0,
        bass_root=33, bass_pattern=[0, 0, 7, 0, 0, 0, 5, 7],
        bass_wave="square", bass_duty=0.5, bass_hold=1,
        bass_vol=0.50, bass_decay=3.2, bass_tail=1.3,
        sparkle=False, sparkle_vol=0.0, rms_db=-16.0,
    ),
    "eerie": dict(
        scale=[0, 3, 6, 7, 10], root=74,
        lead_wave="sine", lead_duty=0.5, rest_prob=0.62,
        lead_octaves=[-12, 0, 0, 12], lead_lengths=[2, 3, 4],
        lead_vol=0.50, lead_attack=0.010, lead_decay=3.0,
        bass_root=38, bass_pattern=[0] + [None] * 15,  # one drone per 2 bars
        bass_wave="triangle", bass_duty=0.5, bass_hold=16,
        bass_vol=0.42, bass_decay=2.2, bass_tail=2.0,  # long tail wraps the loop
        sparkle=False, sparkle_vol=0.0, rms_db=-19.0,  # quieter overall
    ),
    "calm": dict(
        scale=[0, 2, 4, 7, 9], root=72,
        lead_wave="triangle", lead_duty=0.5, rest_prob=0.55,
        lead_octaves=[0, 0, 12], lead_lengths=[1, 2, 2, 3],
        lead_vol=0.45, lead_attack=0.006, lead_decay=4.0,
        bass_root=36, bass_pattern=[0, None, None, None, 7, None, None, None],
        bass_wave="triangle", bass_duty=0.5, bass_hold=4,
        bass_vol=0.50, bass_decay=2.8, bass_tail=1.3,
        sparkle=True, sparkle_vol=0.13, rms_db=-16.0,
    ),
}


def lead_events(m, rng, start, end, clamp=False):
    """Seeded random melody as (start_step, midi, length_steps) tuples.

    With clamp=True notes are shortened so they never cross `end` — used at
    internal mood changes so one mood's scale never sustains over the next
    mood's bass. The final section is left unclamped so its last note can
    overrun and wrap into the loop start.
    """
    events, step = [], start
    while step < end:
        if rng.random() < m["rest_prob"]:
            step += 1
            continue
        midi = m["root"] + rng.choice(m["scale"]) + rng.choice(m["lead_octaves"])
        length = rng.choice(m["lead_lengths"])
        if clamp:
            length = min(length, end - step)
        events.append((step, midi, length))
        step += length
    return events


def parse_sections(spec, total_bars):
    """'driving,warm:2,driving' -> [(mood, bars), ...] played in order.

    Entries with an explicit ':bars' take exactly that many bars; bare
    entries split whatever remains of total_bars as evenly as possible
    (earlier sections get the leftover bar when it does not divide).
    """
    raw = []
    for tok in spec.split(","):
        name, _, count = tok.strip().partition(":")
        name = name.strip()
        if name not in MOODS:
            raise ValueError("unknown mood %r (choose from %s)"
                             % (name, ", ".join(sorted(MOODS))))
        if count:
            try:
                bars = int(count)
            except ValueError:
                raise ValueError("bad bar count in %r" % tok.strip())
            if bars < 1:
                raise ValueError("bar count must be >= 1 in %r" % tok.strip())
            raw.append([name, bars])
        else:
            raw.append([name, None])
    free = [r for r in raw if r[1] is None]
    if free:
        left = total_bars - sum(r[1] for r in raw if r[1] is not None)
        if left < len(free):
            raise ValueError("%d bare section(s) but only %d bar(s) left to "
                             "share; raise --bars or use mood:bars"
                             % (len(free), left))
        share, extra = divmod(left, len(free))
        for i, r in enumerate(free):
            r[1] = share + (1 if i < extra else 0)
    return [tuple(r) for r in raw]


def render_loop(sections, seed, bpm):
    """Render [(mood, bars), ...] into one circular buffer.

    Returns (buffer, rms_target_db). One shared rng walks the sections in
    order, so the seed fully determines the whole multi-mood song.
    """
    total_bars = sum(n for _, n in sections)
    total_steps = total_bars * STEPS_PER_BAR
    step_sec = 60.0 / bpm / 2.0
    loop_samples = int(round(total_steps * step_sec * SR))
    buf = [0.0] * loop_samples
    rng = random.Random(seed)

    # A single-mood file keeps that mood's loudness target; a mix masters to
    # -16 dBFS with quieter moods (eerie) pre-scaled down relative to that,
    # so per-mood loudness survives inside one normalized file.
    names = {name for name, _ in sections}
    file_rms = MOODS[sections[0][0]]["rms_db"] if len(names) == 1 else -16.0

    def place(step_idx, samples):
        start = int(round(step_idx * step_sec * SR))
        for i, s in enumerate(samples):
            buf[(start + i) % loop_samples] += s  # tails wrap to the start

    bar0 = 0
    for name, nbars in sections:
        m = MOODS[name]
        gain = 10.0 ** ((m["rms_db"] - file_rms) / 20.0)  # exactly 1.0 solo
        s0 = bar0 * STEPS_PER_BAR
        s1 = s0 + nbars * STEPS_PER_BAR
        last = s1 == total_steps

        # LEAD — the only randomized layer; the seed fully determines it.
        for step, midi, length in lead_events(m, rng, s0, s1, clamp=not last):
            hold = length * step_sec
            place(step, note(hold * 1.3, midi, m["lead_wave"], m["lead_duty"],
                             m["lead_vol"] * gain, m["lead_attack"],
                             m["lead_decay"] / hold))

        # BASS — fixed groove, restarting at the section start. Holds are
        # clamped to the section so e.g. eerie's 2-bar drone cannot sustain
        # loudly into the next mood (its quiet decay tail still bleeds over,
        # which smooths the transition).
        pattern = m["bass_pattern"]
        for base in range(s0, s1, len(pattern)):
            for pos, off in enumerate(pattern):
                if off is None or base + pos >= s1:
                    continue
                bhold = min(m["bass_hold"], s1 - (base + pos)) * step_sec
                place(base + pos,
                      note(bhold * m["bass_tail"], m["bass_root"] + off,
                           m["bass_wave"], m["bass_duty"], m["bass_vol"] * gain,
                           0.006, m["bass_decay"] / bhold))

        # SPARKLE — quiet high arpeggio on every other bar of the section.
        if m["sparkle"]:
            for b in range(1, nbars, 2):
                for k, off in enumerate([0, 4, 7, 9]):
                    place((bar0 + b) * STEPS_PER_BAR + 2 * k,
                          note(step_sec * 1.3, m["root"] + 12 + off, "sine", 0.5,
                               m["sparkle_vol"] * gain, 0.003, 4.0 / step_sec))
        bar0 += nbars
    return buf, file_rms


def master(buf, rms_db=-16.0, ceiling_db=-3.0):
    """Normalize to the target RMS, but never let the peak exceed the ceiling."""
    rms = math.sqrt(sum(x * x for x in buf) / len(buf))
    peak = max(abs(x) for x in buf)
    if rms <= 0.0 or peak <= 0.0:
        return buf
    gain = min(10.0 ** (rms_db / 20.0) / rms, 10.0 ** (ceiling_db / 20.0) / peak)
    return [x * gain for x in buf]


def write_wav(path, buf):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    pcm = [int(max(-1.0, min(1.0, x)) * 32767) for x in buf]
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(struct.pack("<%dh" % len(pcm), *pcm))


def main():
    ap = argparse.ArgumentParser(
        description="Generate a seamlessly looping chiptune WAV "
                    "(44.1 kHz, 16-bit, mono, stdlib only).")
    ap.add_argument("--mood", default="warm", metavar="SPEC",
                    help="one of %s, or a comma-separated mix played in "
                         "order, e.g. driving,warm,driving; add :bars for "
                         "exact section lengths (driving:4,warm:4,driving:4); "
                         "bare names split --bars evenly"
                         % ", ".join(sorted(MOODS)))
    ap.add_argument("--seed", type=int, default=None,
                    help="melody seed; same seed = identical file "
                         "(default: random, printed)")
    ap.add_argument("--bpm", type=float, default=105.0)
    ap.add_argument("--bars", type=int, default=8,
                    help="total bars, shared by bare mood sections "
                         "(default 8); ignored when every section has an "
                         "explicit :bars count")
    ap.add_argument("--out", default=None,
                    help="output path (default: music_<mood>_<seed>.wav)")
    args = ap.parse_args()
    if args.bpm <= 0 or args.bars < 1:
        ap.error("--bpm must be > 0 and --bars >= 1")
    try:
        sections = parse_sections(args.mood, args.bars)
    except ValueError as err:
        ap.error(str(err))

    seed = args.seed if args.seed is not None else random.randrange(1_000_000)
    label = "+".join(name for name, _ in sections)
    out = args.out or f"music_{label}_{seed}.wav"

    buf, rms_target = render_loop(sections, seed, args.bpm)
    buf = master(buf, rms_target)
    write_wav(out, buf)

    total_bars = sum(n for _, n in sections)
    print(f"mood={args.mood} seed={seed} bpm={args.bpm:g} bars={total_bars}")
    if len(sections) > 1:
        spans, bar = [], 1
        for name, n in sections:
            spans.append(f"{name} bars {bar}-{bar + n - 1}")
            bar += n
        print("sections: " + " | ".join(spans))
    print(f"wrote {out}: {len(buf) / SR:.6f} s, {len(buf)} samples, "
          f"44100 Hz 16-bit mono, seamless loop")


if __name__ == "__main__":
    main()
