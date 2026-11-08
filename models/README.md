# models/

Put an RVC v2 40k checkpoint here, e.g. `xiaoxi_ft_e45_s74565.pth`, and point
`XIAOXI_MODEL` at it (absolute path or relative to the repo root).

The checkpoint is intentionally not versioned: it is 55 MB and it is a voice.
Any RVC `.pth` works — this package only relies on the standard RVC v2 layout
(f0 40k, 768-dim HuBERT features).
