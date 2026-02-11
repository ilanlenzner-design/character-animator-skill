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
    --output output.webm
```

## Parameters

- `image_path` (required): Path to image (PNG, JPG, WEBP)
- `--prompt` (required): Describe the animation (e.g. "character walks forward, hair flowing")
- `--type`: `character` (transparent output, default) or `background` (full frame, no bg removal)
- `--model`: `kling` (best quality, default) or `minimax` (faster)
- `--matting`: `universal` (any subject) or `human` (people only, better temporal consistency). Ignored when `--type background`.
- `--duration`: `5` or `10` seconds (default: 5)
- `--output`: Output path (default: `<input>-animated.webm`)

## Asset Type Selection

- **Character**: Removes background → transparent VP9 WebM with alpha. Use for sprites, characters, objects that overlay on other content.
- **Background**: No background removal → full-frame VP9 WebM. Use for scene backgrounds, landscapes, environments.

## Matting Mode Selection (characters only)

- **Universal (RMBG)**: Use for non-human subjects — animals, creatures, objects, game characters. Uses `nateraw/video-background-remover` → FFmpeg chromakey.
- **Human (RVM)**: Use for people/human characters only. Uses `arielreplicate/robust_video_matting` for better temporal consistency and less flicker. Takes longer (2 API calls vs 1).

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
4. Verify REPLICATE_API_TOKEN is set in environment
5. Run the animate.py script
6. Report the output path and file size
