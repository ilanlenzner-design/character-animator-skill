---
name: character-animator
description: >
  Animate a character or background image into a mobile-optimized VP9 WebM video.
  Characters get alpha transparency; backgrounds get full-frame encoding.
  Uses Kling or MiniMax via Replicate for AI video generation, with AI background
  removal for characters. Output capped at 720p, low bitrate, optimized for mobile ads.
  Use when the user wants to (1) animate a character or sprite, (2) create a character
  animation with transparency, (3) animate a background image, (4) generate an animated
  video from a still image, (5) create a transparent video from a character image, or
  (6) mentions "animate character", "animate background", "character animation",
  "animate this image", "animated sprite", "transparent animation", "animate with alpha",
  "video from image", "make this character move", or "ad animation".
  Requires REPLICATE_API_TOKEN environment variable and FFmpeg installed.
---

# Character Animator

Animate a still image into a mobile-optimized VP9 WebM video. Characters get alpha transparency; backgrounds get full-frame encoding. Output is <=720p for mobile ads.

## Pipeline

**Character** (transparent output):
```
Image + Prompt → AI Video Gen → AI Background Removal → VP9 WebM + alpha (<=720p)
```

**Background** (full frame, no matting):
```
Image + Prompt → AI Video Gen → VP9 WebM encode (<=720p)
```

## Usage

```bash
REPLICATE_API_TOKEN=$REPLICATE_API_TOKEN python3 ~/.claude/skills/character-animator/scripts/animate.py \
    <image_path> \
    --prompt "description of animation" \
    --type character \
    --model kling \
    --matting universal \
    --duration 5 \
    --loop \
    --output output.webm
```

## Parameters

- `image_path` (required): Path to image (PNG, JPG, WEBP)
- `--prompt` (required): Describe the animation (e.g. "cute cartoon cat blinks eyes slowly, smiles, tiny head nod, stays perfectly still in place, no walking, no movement, stationary")
- `--type`: `character` (transparent output, default) or `background` (full frame, no bg removal)
- `--model`: `kling` (best quality, default) or `minimax` (faster)
- `--matting`: `universal` (any subject) or `human` (people only, better temporal consistency). Ignored when `--type background`.
- `--duration`: `5` or `10` seconds (default: 5)
- `--loop`: Enable seamless loop (Kling only). Uses `end_image == start_image` with `mode=pro` so the last frame matches the first frame. **Recommended for all character animations** that need to loop continuously (game sprites, ad assets).
- `--output`: Output path (default: `<input>-animated.webm`)

## Automatic Dimension Matching

The script automatically reads the source image dimensions using Pillow and outputs the video at the same size (capped at 720p). It renders 15% oversized then center-crops to absorb AI-generated zoom drift. No manual scaling needed.

## Seamless Looping (First Frame = Last Frame)

When `--loop` is enabled (Kling only), the script passes the same source image as both `start_image` and `end_image` to Kling v2.1. This forces the AI to generate a video where the first and last frames match the original image, creating a seamless loop when played back with `video.loop = true`. This requires Kling's `mode=pro` (automatically set by the script).

- **Without `--loop`**: The character may drift, walk, or change pose — the last frame won't match the first, causing a visible jump on loop.
- **With `--loop`**: The character returns to its original pose/position. Perfect for game sprites and ad assets that loop continuously.
- **Kling only**: MiniMax does not support `end_image`. If seamless looping is needed, use `--model kling`.

## Alpha Erosion (Green Fringe Removal)

For universal matting (chromakey path), the pipeline uses alpha erosion to eliminate green fringe artifacts:
1. Chromakey removes green background
2. Alpha channel is extracted and eroded by 1px (cuts off green edge pixels)
3. Eroded alpha is merged back with RGB
4. Color channel mixer removes residual green spill

## Asset Type Selection

- **Character**: Removes background → transparent VP9 WebM with alpha. Use for sprites, characters, objects that overlay on other content.
- **Background**: No background removal → full-frame VP9 WebM. Use for scene backgrounds, landscapes, environments.

## Matting Mode Selection (characters only)

- **Universal (RMBG)**: Use for non-human subjects — animals, creatures, objects, game characters. Uses `nateraw/video-background-remover` → FFmpeg chromakey.
- **Human (RVM)**: Use for people/human characters only. Uses `arielreplicate/robust_video_matting` for better temporal consistency and less flicker. Takes longer (2 API calls vs 1).

## Prompt Best Practices

- **Always include** "stays perfectly still in place, no walking, no movement, stationary" for characters that should not translate
- **Always include** "no zoom, no camera movement" to prevent AI zoom drift (the script also compensates with 15% oversized render + crop)
- **Describe subtle motions**: "blinks eyes slowly, smiles, tiny head nod" — small facial animations work best
- **Use `--loop` for game sprites and ad assets** — ensures seamless looping by matching first and last frames
- Example prompt: `"cute cartoon hamster blinks eyes slowly, smiles, tiny head nod, stays perfectly still in place, no walking, no movement, stationary"`

## Workflow

1. Ask user for the image path and animation prompt
2. Determine if the output needs background removal (alpha channel):
   - **Obvious character/sprite** (e.g. "animate this character", subject on plain/white bg): use `--type character`
   - **Obvious background/scene** (e.g. "animate this background", landscape, environment): use `--type background`
   - **Ambiguous** (e.g. "animate this image" with no context): **ask the user** — "Does this need background removal (transparent output), or should it keep the full frame?"
3. For characters, determine matting mode if not obvious:
   - Human/person in the image → `--matting human`
   - Anything else (creature, object, animal) → `--matting universal`
   - If unsure, ask
4. **Default to `--loop`** for character sprites and game assets (seamless looping is almost always desired)
5. Verify REPLICATE_API_TOKEN is set in environment
6. Run the animate.py script
7. Report the output path and file size
