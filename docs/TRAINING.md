# Reproducing the voice (training notes)

You do not need any of this to *use* the agent — it is here so the checkpoint is not a black box.

## 1. Data

Target: 4–7 h of **isolated, dry singing** in the timbre you want, plus a broad register spread. The shipped model used ≈6.6 h:

- a public Mandarin singing corpus (clear diction, mid register),
- the soprano subset of M4Singer (upper register),
- 18 hand-picked commercial songs, separated with MDX-Net `Kim_Vocal_2` (never spectral subtraction — it leaves audible artifacts that the model learns),
- 8 of those deliberately chosen for **power / chest-dominant** high notes, because a corpus of soft pop makes the model breathy.

Quality gate every 3.7 s slice:

```python
voiced_ratio >= 0.5      # else the slice is silence or bleed
rms >= 0.01
energy_below_150hz <= 0.35
```

Data mixing matters more than data volume. Adding 226 "solid voice" slices pulled harmonic-to-noise back from 2.96 to 3.78 in one checkpoint; weighting the *new* data ×2 (instead of cleaning it) made diction monotonically worse across four checkpoints.

## 2. Fine-tune

Start from a base model that already sings well, then fine-tune at a low LR — from scratch on 6 h gives a mushy voice.

```bash
python -m train.train \
  -e my_voice -sr 40k -f0 1 -bs 4 -g 0 \
  -te 80 -se 5 \
  -pg logs/base/G_<step>.pth -pd logs/base/D_<step>.pth \
  -l 0 -c 0 -sw 1 -v v2
```

Two knobs that mattered on an 8 GB laptop:

- `RVC_PREFETCH` 3 with `RVC_NUM_WORKERS=2`: 3.3 steps/s. Each worker costs ~2.7 GB of private commit on Windows, so more workers is not faster, it is a pagefile crash.
- save every 5 epochs (`-se 5`). The interesting region is a 5-epoch window around the peak; losing it to a crash costs hours.

## 3. Picking the checkpoint (this is the actual work)

Do **not** take the last epoch. Render a fixed 40 s excerpt of a hard passage at every checkpoint and measure:

| metric | how | direction |
|---|---|---|
| spectral flux (max) | frame-to-frame magnitude difference | lower = fewer breaks |
| HNR p10 / median | autocorrelation peak per frame | higher = less airy |
| 4–10 kHz energy share | band energy | tracks diction clarity |
| silence-frame ratio | frames below −45 dBFS | compare against the source |
| CER | Whisper on the rendered vocal vs. lyrics | lower = clearer; **must** be compared against the source vocal's own CER, not an absolute threshold |

For this voice the curve peaked at epoch 45 and regressed at 50 (flux 172 → 203, HNR p10 0.72 → 0.39). Two consecutive worse checkpoints is the signal to stop; more training is not automatically better.

## 4. Post-processing is not optional

Raw RVC output measured *cleaner* than the processed one in flatness and buzz — the processing exists to add back air and tame the noise floor, and every stage is a trade. The 4 kHz shelf was responsible for most of the audible "electric" quality; it ships at +3 dB and can be set to 0.
