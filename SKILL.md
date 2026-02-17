---
name: character-animator
description: >
  Animate a character or background image into a mobile-optimized video.
  Outputs VP9 WebM (alpha transparency) and/or stacked-alpha H.264 MP4 (iOS-compatible).
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

Animate a still image into a mobile-optimized video (VP9 WebM or stacked-alpha H.264 MP4). Four pipelines:

| Mode | Use for | Transparency |
|------|---------|-------------|
| **Chromakey** (default for RGBA / solid-bg) | Characters, sprites | Auto — bakes key color, chromakeys out |
| **SAM3** (fallback) | Characters on complex backgrounds (JPG/WEBP) | AI segmentation |
| **Mask** | Logos, UI elements with static edges | Static PNG alpha shape |
| **Background** | Scenes, landscapes, environments | None (opaque) |

## Usage

```bash
REPLICATE_API_TOKEN=$REPLICATE_API_TOKEN python3 ~/.claude/skills/character-animator/scripts/animate.py \
    <image_path> \
    --prompt "description of animation" \
    --type character \
    --model kling \
    --duration 5 \
    --motion expressive \
    --format mp4 \
    --loop \
    --output output.mp4
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
| `--motion` | `auto`, `subtle`, `normal`, `expressive`, `dynamic` | `auto` | Animation intensity. auto = `normal` for characters, `expressive` for backgrounds |
| `--duration` | `5`, `10` | `5` | Seconds |
| `--loop` | flag | **on** for backgrounds, off for characters | Seamless loop (Kling only). Use `--no-loop` to disable |
| `--size` | `WxH` (e.g. `960x960`) | source dims | Output dimensions. Use for backgrounds that must match the ad size |
| `--mask` | PNG path | none | Static PNG alpha shape. **Static edges only** — logos, UI elements |
| `--format` | `webm`, `mp4`, `both` | `webm` | `mp4` = stacked-alpha H.264 (iOS+Android). `both` = outputs both files. **Always use `mp4` or `both` for playable ads** |
| `--output` | file path | `<input>-animated.<ext>` | Extension auto-set from `--format` |

## Workflow

1. Get image path and animation prompt from user
2. Determine transparency approach:
   - **RGBA PNG** -> auto-chromakey (best quality, no extra API call)
   - **JPG/WEBP with solid-color bg** (green screen, etc.) -> auto-detects, chromakeys directly
   - **JPG/WEBP with complex bg** -> `--method sam3` with `--subject` describing the character
   - **Logo / UI / static-edge asset** -> `--mask <same_image.png>`
   - **Background/scene** -> `--type background` (use `--size WxH` to match ad dimensions)
   - **Ambiguous** -> ask the user
3. **Choose output format** (`--format`):
   - **Playable ads / Sett projects** -> `--format mp4` (stacked-alpha H.264, works on iOS + Android)
   - **Desktop web only** -> `--format webm` (VP9+alpha, native transparency)
   - **Need both** -> `--format both` (outputs .webm + .mp4 side by side)
   - **When in doubt for ads** -> always use `mp4` (iOS Safari does NOT support VP9 alpha)
4. For `--method sam3`, set `--subject` to describe what to segment (be specific: `"hamster"` > `"character"`)
5. Choose motion level if needed (default `auto` is usually fine)
6. Default to `--loop` for game sprites and ad assets
7. Verify `REPLICATE_API_TOKEN` is set
8. Run `animate.py`
9. If animation is too subtle, re-run with `--motion expressive` or `--motion dynamic`
10. Report output path and file size
11. **For MP4 output**: remind that stacked-alpha videos need the `AlphaPackFilter` shader to render transparency (see [sett-integration.md](references/sett-integration.md#ios-transparency-stacked-alpha-h264)). The display height is **half** the actual video height.

## iOS / Cross-Platform Notes

- **iOS Safari does NOT support VP9 WebM alpha transparency** — transparent areas render as black
- The `--format mp4` option produces a **stacked-alpha H.264 MP4**: top half = RGB, bottom half = alpha as grayscale
- A GPU shader (GLSL) recombines them at render time — see `AlphaPackFilter` in [sett-integration.md](references/sett-integration.md)
- Stacked H.264 is typically **40-60% smaller** than VP9 WebM
- H.264 MP4 plays on **every** device, browser, and WebView

## Motion Presets

Controls Kling's `cfg_scale` — higher = more movement, lower = closer to source frame:

| Preset | cfg_scale | Use for |
|--------|-----------|---------|
| `subtle` | 0.3 | Logos, UI — minimal animation |
| `normal` | 0.5 | Stationary characters — gentle idle |
| `expressive` | 0.7 | Clear gestures, backgrounds |
| `dynamic` | 0.9 | Action: jumping, dancing, waving |

## Prompt Best Practices

- **Stationary characters**: Always append "stays perfectly still in place, no walking, no movement, stationary, no zoom, no camera movement"
- **More motion**: Use action verbs + `--motion expressive`/`dynamic`: "breathes deeply, blinks eyes, looks around curiously"
- **Subtle**: `--motion subtle`/`normal`: "blinks eyes slowly, tiny head nod"
- **Mask mode**: "shiny glint sweeps across", "faint sparkle" — internal animation only

## References

- **Technical details** (chromakey internals, SAM3 post-processing, VP9 encoding, mask FFmpeg two-step, known limitations): [references/technical.md](references/technical.md)
- **Sett playable ads integration** (base64 data URL workaround, PixiJS video textures, landscape scaling bug fix, **iOS stacked-alpha transparency**): [references/sett-integration.md](references/sett-integration.md)
