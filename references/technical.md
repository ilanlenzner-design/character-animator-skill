# Technical Reference

## Table of Contents
- [Seamless Looping](#seamless-looping)
- [Alpha Erosion (Green Fringe)](#alpha-erosion)
- [Automatic Dimension Matching](#dimension-matching)
- [PNG Alpha Mask Deep-Dive](#mask-deep-dive)
- [Known Limitations](#known-limitations)

## Seamless Looping

When `--loop` is enabled (Kling only), the script passes the same source image as both `start_image` and `end_image` to Kling v2.1 with `mode=pro`. This forces the AI to generate a video where the first and last frames match the original image, creating a seamless loop.

- **Without `--loop`**: Character may drift or change pose — visible jump on loop playback.
- **With `--loop`**: Character returns to original pose/position. Perfect for game sprites and ad assets.
- **Kling only**: MiniMax does not support `end_image`. Use `--model kling` for loops.

## Alpha Erosion

For universal matting (chromakey path), the pipeline uses alpha erosion to eliminate green fringe:
1. Chromakey removes green background (`0x00FF00`, similarity=0.28, blend=0.02)
2. Alpha channel extracted and eroded by 1px (kills green edge pixels)
3. Eroded alpha merged back with RGB
4. Color channel mixer removes residual green spill (`gg=0.8, gb=0.1, gr=0.1`)

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

## Known Limitations

- **Green-toned subjects**: Chromakey (universal matting) struggles with green characters (e.g. green eyes, foliage). Use `--mask` if edges are static, or `--matting human` if the subject is a person.
- **Fox-type characters**: Very green-toned cartoon animals may not produce clean transparency with any matting mode. Consider keeping as static PNG.
- **Kling frame-filling**: Kling tends to expand subjects to fill the frame, especially logos/panels. Use `--mask` for logos to preserve the original shape.
- **MiniMax no looping**: MiniMax does not support `end_image`, so `--loop` is Kling-only.
