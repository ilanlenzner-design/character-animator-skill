# Technical Reference

## Table of Contents
- [Seamless Looping](#seamless-looping)
- [SAM3 Video Segmentation](#sam3-video-segmentation)
- [Automatic Dimension Matching](#dimension-matching)
- [PNG Alpha Mask Deep-Dive](#mask-deep-dive)
- [VP9 Alpha Encoding](#vp9-alpha-encoding)
- [Known Limitations](#known-limitations)

## Seamless Looping

When `--loop` is enabled (Kling only), the script passes the same source image as both `start_image` and `end_image` to Kling v2.1 with `mode=pro`. This forces the AI to generate a video where the first and last frames match the original image, creating a seamless loop.

- **Without `--loop`**: Character may drift or change pose — visible jump on loop playback.
- **With `--loop`**: Character returns to original pose/position. Perfect for game sprites and ad assets.
- **Kling only**: MiniMax does not support `end_image`. Use `--model kling` for loops.

## SAM3 Video Segmentation

Character transparency uses SAM3 (Segment Anything Model 3) for video segmentation via `lucataco/sam3-video` on Replicate. This replaced the previous chromakey pipeline which had green fringe artifacts and failed on green-toned subjects.

**Pipeline**: Video → SAM3 `mask_only=True` → B&W mask video → FFmpeg `alphamerge` → VP9+alpha

**Key parameters**:
- `prompt`: Text describing the subject to segment (e.g. "character", "person", "animal")
- `mask_only=True`: Returns a black-and-white mask video (white = subject, black = background)
- `negative_prompt`: (optional) Text for objects to exclude from the mask

**Advantages over chromakey**:
- No green fringe artifacts — proper segmentation boundaries
- Works with any color subject (green foxes, foliage, etc.)
- Temporal consistency — SAM3 tracks objects across frames
- Simpler pipeline — no erosion, despill, or color correction needed

## Dimension Matching

The script reads source image dimensions via Pillow and outputs at the same size (capped at 720p). It renders 15% oversized then center-crops to absorb AI-generated zoom drift. All dimensions are forced even (VP9 requirement). No manual scaling needed.

## Mask Deep-Dive

The mask approach uses a two-step FFmpeg process (single-frame PNG + video `alphamerge` fails because the PNG stream ends after frame 1):

**Step 1** — Create mask video from PNG alpha:
```
ffmpeg -loop 1 -i mask.png -vf "alphaextract,scale=W:H" -t 10 -r 24 -c:v libx264 mask.mp4
```

**Step 2** — Merge mask video with generated video:
```
ffmpeg -i generated.mp4 -i mask.mp4 -filter_complex "[0:v]scale=W:H[vid];[vid][1:v]alphamerge[out]" -shortest output.webm
```

Output matches the mask PNG dimensions exactly. The `-shortest` flag ensures the output ends when the shorter stream (generated video) ends.

**Static edges constraint**: The mask is a single static shape applied to every frame. If the character's silhouette changes between frames, the mask clips moving parts. Use only for:
- Logos (static shape, internal animation like shine/glow)
- UI buttons/badges (static outline, internal pulse/shimmer)
- Objects with fixed boundaries (edges don't move)

Do NOT use `--mask` for characters that walk, wave, breathe visibly, or change their outline.

## VP9 Alpha Encoding

VP9 with alpha transparency requires specific FFmpeg flags or the alpha channel will be silently dropped:

| Flag | Purpose |
|------|---------|
| `-pix_fmt yuva420p` | YUVA pixel format — the `a` carries the alpha channel |
| `-auto-alt-ref 0` | **Required** — VP9 alt-ref frames don't support alpha. Without this, encoder silently drops alpha |
| `-metadata:s:v:0 alpha_mode=1` | WebM container metadata signaling alpha presence |

**Input frame requirements** (for mask mode):
- Must be RGBA PNG — `alpha=0` for transparent pixels, `alpha=255` for opaque
- RGB-only PNGs will produce an all-opaque mask (no cutout)
- The script auto-detects non-RGBA and converts, but warns if alpha has no variation

These flags are already set in all three alpha-encoding paths (character universal, character human, mask).

## Known Limitations

- **SAM3 prompt sensitivity**: The `--subject` prompt affects segmentation quality. Be specific (e.g. `"hamster"` not `"character"`) for best results.
- **Kling frame-filling**: Kling tends to expand subjects to fill the frame, especially logos/panels. Use `--mask` for logos to preserve the original shape.
- **MiniMax no looping**: MiniMax does not support `end_image`, so `--loop` is Kling-only.
- **Multi-subject scenes**: SAM3 may struggle if multiple similar objects are in frame. Use `negative_prompt` to exclude unwanted objects if needed.
