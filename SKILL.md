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
    --motion expressive \
    --loop \
    --output output.webm
```

## Parameters

| Parameter | Values | Default | Notes |
|-----------|--------|---------|-------|
| `image_path` | PNG/JPG/WEBP path | (required) | |
| `--prompt` | string | (required) | Describe the animation |
| `--type` | `character`, `background` | `character` | character = transparent, background = full frame |
| `--method` | `auto`, `chromakey`, `sam3` | `auto` | auto = chromakey if RGBA or solid-color bg, SAM3 only if complex bg |
| `--model` | `kling`, `minimax` | `kling` | kling = best quality, minimax = faster |
| `--subject` | string | `"character"` | SAM3 segmentation prompt (only for `--method sam3`) |
| `--motion` | `auto`, `subtle`, `normal`, `expressive`, `dynamic` | `auto` | Controls animation intensity via cfg_scale. auto = `normal` for characters, `expressive` for backgrounds |
| `--duration` | `5`, `10` | `5` | Seconds |
| `--loop` | flag | **on** for backgrounds, off for characters | Seamless loop (Kling only). Use `--no-loop` to disable |
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

## Motion Presets

| Preset | cfg_scale | Best for | Prompt style |
|--------|-----------|----------|-------------|
| `subtle` | 0.3 | Logos, UI elements, gentle shimmer | "subtle glow", "faint sparkle" |
| `normal` | 0.5 | Stationary characters, idle animation | "blinks slowly, tiny head nod" |
| `expressive` | 0.7 | Characters with clear gestures, backgrounds | "breathes deeply, looks around, smiles" |
| `dynamic` | 0.9 | Action poses, dancing, waving, jumping | "waves excitedly, bounces up and down" |

If the animation comes out too subtle, bump up `--motion` one level (e.g., `normal` -> `expressive`).

## Prompt Best Practices

- **Stationary characters**: Always include "stays perfectly still in place, no walking, no movement, stationary, no zoom, no camera movement"
- **More motion**: Use action verbs and `--motion expressive` or `--motion dynamic`: "breathes deeply, blinks eyes, looks around curiously, smiles warmly"
- **Subtle motions**: Use `--motion subtle` or `--motion normal`: "blinks eyes slowly, tiny head nod"
- Example (normal): `"cute cartoon hamster blinks eyes slowly, smiles, tiny head nod, stays perfectly still in place, stationary"`
- Example (expressive): `"cute cartoon hamster breathes deeply, blinks eyes, looks around, shifts weight, stays in place, stationary"`

## Workflow

1. Get image path and animation prompt from user
2. Determine transparency approach:
   - **RGBA PNG character/sprite** -> auto-chromakey (default, best quality)
   - **JPG/WEBP with solid-color background** (green screen, etc.) -> auto-detects bg color, chromakeys it out directly
   - **JPG/WEBP with complex background** -> `--method sam3` with `--subject` describing the character
   - **Logo / UI / static-edge asset** (edges don't move) -> `--mask <same_image.png>`
   - **Background/scene** -> `--type background`
   - **Ambiguous** -> ask the user
3. For `--method sam3`, set `--subject` to describe what SAM3 should segment
4. Choose motion level based on desired animation intensity (default `auto` is usually fine)
5. Default to `--loop` for game sprites and ad assets
6. Verify `REPLICATE_API_TOKEN` is set
7. Run `animate.py`
8. If animation is too subtle, re-run with `--motion expressive` or `--motion dynamic`
9. Report output path and file size

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

### Video Background Scaling (Landscape Bug Fix)

Video textures can have **different dimensions** from the original static image (backgrounds cap at 1080p, characters at 720p). Also, video textures can briefly report their size as **0** while decoding frames. Both cause black bars or flickering on orientation change.

**Always** use the known video dimensions as constants (from the script's output log) instead of reading them from the texture at runtime:

```typescript
// Known video dimensions from animate.py output log
const VIDEO_W = 960;
const VIDEO_H = 960;

// Scale to cover screen — never read width/height from the video texture
public resize(width: number, height: number, scale: number): void {
  const bgScale = Math.max(width / (VIDEO_W * scale), height / (VIDEO_H * scale)) * 1.1;
  this.background.scale.set(bgScale);
}
```

This avoids both issues:
- No dimension mismatch (you know the exact output size)
- No division-by-zero when the video briefly reports 0x0 during frame decode

## VP9 Alpha Encoding Requirements

For transparent WebM output, these FFmpeg flags are **required**:
- `-pix_fmt yuva420p` — YUVA pixel format with alpha channel
- `-auto-alt-ref 0` — disables alt-ref frames (required for alpha, otherwise encoder drops alpha)
- `-metadata:s:v:0 alpha_mode=1` — signals the container has alpha

Input mask PNGs **must** be RGBA format (alpha=0 for transparent, alpha=255 for opaque). The script auto-converts non-RGBA inputs and warns if alpha is flat.

## Technical Details

For implementation details (chromakey color selection, SAM3 post-processing, dimension matching, mask FFmpeg two-step process, known limitations), see [references/technical.md](references/technical.md).
