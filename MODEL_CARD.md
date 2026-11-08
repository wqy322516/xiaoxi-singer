# Model card — `xiaoxi_ft_e45_s74565.pth`

An RVC v2 (40 kHz) singing-voice model. It converts a **dry vocal performance** into a specific female timbre; it is not a text-to-speech system.

## Training

| | |
|---|---|
| Architecture | RVC v2, 40 kHz, f0-guided (RMVPE features), 768-dim HuBERT content encoder |
| Base | `f0G40k.pth` / `f0D40k.pth` (RVC v2 pretrained), fine-tuned |
| Fine-tune start | epoch 180 of an earlier run on a 5.6 k-slice corpus |
| Learning rate | 5e-5 (cosine-ish exponential decay, stepped once per epoch) |
| Batch | 4, one GPU, ~1 655 steps per epoch, ~1.2 steps/s |
| Stop point | **epoch 45** (step 74 565) — chosen by eval, not by budget |

### Data (≈6.6 h of isolated vocals, 6 621 slices of 3.7 s)

| source | slices | what it contributes |
|---|---|---|
| public Mandarin singing corpus (Opencpop) | 4 112 | clear diction, mid register, pop phrasing |
| M4Singer soprano subset | 1 494 (747 ×2 weight-free duplication avoided) | upper register, belted high notes |
| 10 hand-picked pop songs | 563 | modern Mandarin pop production, breathy detail |
| 4 "solid voice" singers (rock/power ballads) | 226 | chest-dominant high notes, the fix for a breathy drift |
| 4 powerhouse vocalists (張惠妹 / 黄绮珊 / 谭维维 / 韩红) | 226 | strong, forward placement; f0 p10/p50/p90 = 247 / 417 / 524 Hz |

All slices were quality-gated: voiced ratio ≥ 0.5, RMS ≥ 0.01, < 150 Hz energy ≤ 0.35 (throws out rumble and bleed).

## Evaluation

Everything below is measured on a fixed 40 s excerpt of a belted high-register passage, same post chain, same conversion settings, plus two full covers scored with a character-error-rate (CER) ASR check.

| checkpoint | spectral flux (max) | HNR p10 | HNR median | 4–10 kHz share | silence frames | 雨爱 CER |
|---|---|---|---|---|---|---|
| epoch 20 | 264.7 | 0.41 | 3.84 | 0.117 | 4.8 % | 56.7 % |
| epoch 30 | 197.2 | 0.66 | 2.96 | 0.115 | 4.9 % | — |
| epoch 35 | 189.3 | 0.53 | 3.78 | 0.136 | 5.4 % | — |
| **epoch 45** | **172.0** | **0.72** | **5.02** | **0.171** | 5.2 % | **54.8 %** |
| epoch 50 | 203.2 | 0.39 | 4.88 | 0.170 | 4.4 % | 63.0 % |

Interpretation: flux is transient harshness (lower = fewer "breaks"), HNR is harmonic-to-noise (higher = less airy/noisy), the 4–10 kHz share tracks diction clarity. Epoch 45 is the joint optimum; epoch 50 gives back everything it gained.

Reference points: the source singer's own dry vocal scores CER 52.1 % on the same ASR pipeline, so 54.8 % is within noise of the ceiling — this metric can no longer separate models here.

### Internal release rubric

| level | criteria | status |
|---|---|---|
| L1 demo | f0 MAE ≤ 0.15 st, turn error ≤ 0.55, flux ≤ 250, HNR p10 ≥ 0.40, silence ≥ 5 %, no dropped lines | passed |
| L2 publishable | flux ≤ 180, HNR p10 ≥ 0.55, silence ≥ 6 %, CER ≤ 1.6 × source CER, five genre checks, ABX > 70 % | 4/6 (silence 5.2 %, pitch MAE 0.209 was later fixed to 0.108 by disabling unnecessary clamping) |
| L3 commercial | — | not attempted |

## Failure modes

- **High notes still break occasionally.** Raising `protect` *worsens* this on transposed material: it preserves more of the source pitch contour, and the break happens where that contour is being stretched. Lower `protect` (0.4–0.5) or transpose less.
- **Sibilance blurs** as the model specializes. Measured as a monotone CER increase across later checkpoints in one ablation.
- **Spoken passages turn metallic** if left at default `protect`; hence the per-slice voicing detector (voicing 0.02–0.50 and median f0 < 270 Hz → protect 0.9).
- **Nothing survives a bad separation.** Residual instrumental bleed in the "vocal" stem is converted along with the voice.

## Intended use

Personal covers, research on singing-voice conversion, agents that need a singing voice. Not for impersonation, not for commercial release, not for training other voice models without consent.

## Provenance / licensing of data

The corpus mixes a public research singing dataset with commercially released songs. The resulting checkpoint is therefore **research-only**; the code in this repository is MIT, the checkpoint is not.
