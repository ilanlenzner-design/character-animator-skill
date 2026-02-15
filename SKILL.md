---
name: character-animator
description: >
  Animate a character or background image into a mobile-optimized VP9 WebM video.
  Characters get alpha transparency; backgrounds get full-frame encoding.
  Uses Kling or MiniMax via Replicate for AI video generation, with auto-chromakey
  or SAM3 segmentation for background removal. Output capped at 720p, optimized for mobile ads.
  Use when the user wants to (1) animate a character or sprite, (2) create a character
  animation with transparency, (3) animate a background image, (4) generate an animated
  video from a still image, (5) create a transparent video from a character image, or
  (6) mentions "animate character", "animate background", "character animation",
  "animate this image", "animated sprite", "transparent animation", "animate with alpha",
  "video from image", "make this character move", or "ad animation".
  Requires REPLICATE_API_TOKEN environment variable and FFmpeg installed.
---

# Character Animator

Animate a still image into a mobile-optimized VP9 WebM video (<=720p). Four pipelines:

| Mode | Pipeline | Use for |
|------|----------|---------|
| **Chromakey** (default for RGBA) | Scan image -> bake key color bg -> AI Video -> chromakey -> VP9+alpha | Characters/sprites with alpha channel (best quality) |
| **SAM3** (fallback for JPG/WEBP) | Image -> AI Video -> SAM3 segmentation -> VP9+alpha | Characters without alpha (JPG, WEBP) |
| **Mask** | Image -> AI Video -> PNG Alpha Mask -> VP9+alpha | Logos, UI elements with static edges |
| **Background** | Image -> AI Video -> VP9 encode | Scenes, landscapes, environments |

## Usage

```bash
REPLICATE_API_TOKEN=$REPLICATE_API_TOKEN python3 ~/.claude/skills/character-animator/scripts/animate.py \
    <image_path> \
    --prompt "description of animation" \
    --type character \
    --model kling \
    --duration 5 \
    --loop \
    --output output.webm
```

## Parameters

| Parameter | Values | Default | Notes |
|-----------|--------|---------|-------|
| `image_path` | PNG/JPG/WEBP path | (required) | |
| `--prompt` | string | (required) | Describe the animation |
| `--type` | `character`, `background` | `character` | character = transparent, background = full frame |
| `--method` | `auto`, `chromakey`, `sam3` | `auto` | auto = chromakey if RGBA, SAM3 if no alpha |
| `--model` | `kling`, `minimax` | `kling` | kling = best quality, minimax = faster |
| `--subject` | string | `"character"` | SAM3 segmentation prompt (only for `--method sam3`) |
| `--duration` | `5`, `10` | `5` | Seconds |
| `--loop` | flag | off | Seamless loop (Kling only). First frame = last frame via `end_image` |
| `--mask` | PNG path | none | Use PNG alpha as shape mask. Skips AI bg removal. **Static edges only** |
| `--output` | file path | `<input>-animated.webm` | |

## How Chromakey Works

When the source image has an alpha channel (RGBA PNG), the script automatically:
1. **Scans** the opaque pixels to find the color most distant from any pixel in the image
2. **Bakes** the character onto a flat background of that color (e.g., cyan for a green character)
3. **Generates** the AI video with the baked image as `start_image` (and `end_image` for loops)
4. **Chromakeys** the key color out with FFmpeg `chromakey` filter -> transparent VP9

This produces sharper edges, more consistent frames, and no flickering compared to SAM3.
No extra API call is needed (SAM3 is skipped entirely).

## Prompt Best Practices

- **Stationary characters**: Always include "stays perfectly still in place, no walking, no movement, stationary, no zoom, no camera movement"
- **Subtle motions work best**: "blinks eyes slowly, smiles, tiny head nod"
- Example: `"cute cartoon hamster blinks eyes slowly, smiles, tiny head nod, stays perfectly still in place, no walking, no movement, stationary"`

## Workflow

1. Get image path and animation prompt from user
2. Determine transparency approach:
   - **RGBA PNG character/sprite** -> auto-chromakey (default, best quality)
   - **JPG/WEBP character** (no alpha) -> `--method sam3` with `--subject` describing the character
   - **Logo / UI / static-edge asset** (edges don't move) -> `--mask <same_image.png>`
   - **Background/scene** -> `--type background`
   - **Ambiguous** -> ask the user
3. For `--method sam3`, set `--subject` to describe what SAM3 should segment
4. Default to `--loop` for game sprites and ad assets
5. Verify `REPLICATE_API_TOKEN` is set
6. Run `animate.py`
7. Report output path and file size

## Mask Mode Constraints

`--mask` applies a single static PNG alpha shape to every frame. Only use when edges are static:
- Logos (internal shine/glow, static outline)
- UI buttons/badges (internal pulse/shimmer)
- Objects with fixed boundaries

Do NOT use for characters that walk, wave, breathe visibly, or change their silhouette.

The mask PNG is usually the same as the source image. Must have alpha channel (RGBA).

```bash
python3 animate.py logo.png --prompt "shiny glint sweeps across" --mask logo.png --loop
```

## Integrating into Sett Playable Ads

The `@smoud/playable-scripts` webpack config does NOT support `.webm` imports. Use the **base64 data URL workaround**:

1. Encode the WebM as a base64 `.ts` module:
```bash
echo "export const VideoDataUrl = 'data:video/webm;base64,$(base64 -i output.webm)';" > src/VideoData.ts
```

2. Import and create a PixiJS video texture:
```typescript
import { VideoDataUrl } from './VideoData';
import { Texture } from 'pixi.js';

const video = document.createElement('video');
video.src = VideoDataUrl;
video.loop = true;
video.muted = true;
video.playsInline = true;
video.preload = 'auto';
const texture = Texture.from(video, { resourceOptions: { autoPlay: true } });
```

**Important**: esbuild (used by playable-scripts webpack) does not support `!` non-null assertions. Use `=== null` checks and `as Type` casts instead.

For shared textures (e.g. logo used in multiple UI components), use a singleton pattern with `let sharedTexture: Texture | null = null`.

## VP9 Alpha Encoding Requirements

For transparent WebM output, these FFmpeg flags are **required**:
- `-pix_fmt yuva420p` — YUVA pixel format with alpha channel
- `-auto-alt-ref 0` — disables alt-ref frames (required for alpha, otherwise encoder drops alpha)
- `-metadata:s:v:0 alpha_mode=1` — signals the container has alpha

Input mask PNGs **must** be RGBA format (alpha=0 for transparent, alpha=255 for opaque). The script auto-converts non-RGBA inputs and warns if alpha is flat.

## Technical Details

For implementation details (chromakey color selection, SAM3 post-processing, dimension matching, mask FFmpeg two-step process, known limitations), see [references/technical.md](references/technical.md).
