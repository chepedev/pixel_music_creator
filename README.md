
# Music Creator

A procedural, seamlessly-looping chiptune background music generator. Pure
Python 3 standard library — no dependencies, no audio libraries, no
internet access required.

Give it a mood and a seed and it writes a 44.1 kHz / 16-bit / mono `.wav`
loop built from three layers: a randomized lead melody, a fixed bass
groove, and (for some moods) a quiet sparkle arpeggio. The same seed
always produces the exact same file, so you can find a melody you like
and reproduce it forever — or share the seed with someone else and they'll
get byte-identical output.

[`tracks/music_warm_42.wav`](tracks/music_warm_42.wav) is included as a
sample of the output (`--mood warm --seed 42`, the script's own defaults)
— Play here: 


https://github.com/user-attachments/assets/24480f23-a493-4535-bd73-ba967a303ead



## Requirements

- Python 3.8+ (stdlib only — no `pip install` needed)

## Usage

```bash
python3 make_music.py --mood warm --seed 42
```

This writes `music_warm_42.wav` to the current directory and prints a
summary of what it generated.

### Options

| Flag      | Description                                                                                                   | Default              |
| --------- | -------------------------------------------------------------------------------------------------------------- | --------------------- |
| `--mood`  | `calm`, `driving`, `eerie`, `warm`, or a comma-separated mix (see below)                                        | `warm`                |
| `--seed`  | Integer seed for the melody. Same seed = identical file. Omit to get a random one (it's printed so you can keep it). | random                |
| `--bpm`   | Tempo in beats per minute                                                                                       | `105`                 |
| `--bars`  | Total bars in the loop                                                                                          | `8`                   |
| `--out`   | Output path                                                                                                     | `music_<mood>_<seed>.wav` |

### Examples

Generate a specific track and pick a name:

```bash
python3 make_music.py --mood driving --seed 42 --bpm 105 --bars 8 --out music_battle.wav
```

Let the mood and seed roll randomly, just to explore:

```bash
python3 make_music.py --mood eerie
```

Mix multiple moods into one song, evenly splitting `--bars` across them:

```bash
python3 make_music.py --mood driving,warm,driving --bars 12
```

Pin exact bar counts per section instead of splitting evenly:

```bash
python3 make_music.py --mood driving:4,warm:4,driving:4
```

Sections change mood on the bar line (lead, bass, and sparkle all switch
together), and the whole multi-section song still loops back to its first
section seamlessly.

## Moods

- **warm** — gentle triangle-wave lead, sparse major-scale melody, sparkle arpeggio
- **driving** — square-wave lead, busier rhythm, punchier bass groove
- **eerie** — sine-wave lead, sparse and dissonant, long droning bass
- **calm** — soft triangle lead, very sparse, sparkle arpeggio

Each mood has its own scale, waveform, rest probability, note-length
palette, and bass pattern — see `MOODS` in `make_music.py` for the exact
parameters if you want to tweak or add a mood.

## How the loop works

Every note is rendered with a short attack and an exponential decay, then
summed into a fixed-length circular buffer. Any decay tail that spills
past the end of the buffer wraps around and lands back at the start, so
the file loops with no clicks and no fades needed — just play it back
with looping enabled.

The whole file is then mastered to a target loudness (RMS-normalized,
with a peak ceiling so it never clips).

## Regenerating the sample tracks

Everything in `tracks/` and `fav/` besides the one committed sample is
gitignored, since every file is fully reproducible from the script plus
its mood/seed/bpm/bars. To regenerate any of them, just re-run the
command with the same parameters — the filenames follow
`music_<mood>_<seed>.wav` (or `..._x2.wav` for a doubled `--bars` run),
so the parameters are usually recoverable from the filename itself.
