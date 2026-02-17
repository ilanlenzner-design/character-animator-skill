# Integrating into Sett Playable Ads

## WebM Import Workaround

The `@smoud/playable-scripts` webpack config does NOT support `.webm` imports. Encode as base64 data URL:

```bash
echo "export const VideoDataUrl = 'data:video/webm;base64,$(base64 -i output.webm)';" > src/VideoData.ts
```

Create a PixiJS video texture:
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

**esbuild constraint**: Does not support `!` non-null assertions. Use `=== null` checks and `as Type` casts instead.

For shared textures (e.g. logo used in multiple UI components), use a singleton pattern with `let sharedTexture: Texture | null = null`.

## Video Background Scaling (Landscape Bug Fix)

Video textures can have **different dimensions** from the original static image (backgrounds cap at 1080p, characters at 720p). Video textures can also briefly report size as **0** while decoding frames. Both cause black bars or flickering on orientation change.

**Always** use known video dimensions as constants (from the script's output log) instead of reading from the texture at runtime:

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

## iOS Transparency (Stacked-Alpha H.264)

**iOS Safari does NOT support VP9 WebM alpha transparency.** Transparent VP9 videos render with a black background on iPhone/iPad. This applies to all VP9+alpha WebM files, including those produced by this skill's chromakey and SAM3 pipelines.

### Solution: Stacked-Alpha H.264 MP4

Encode a single opaque H.264 MP4 where:
- **Top half** = original RGB video (with green/key-color background)
- **Bottom half** = alpha channel as grayscale (white = opaque, black = transparent)

A GPU shader recombines them at render time. H.264 MP4 plays on **every** device, browser, and WebView.

### Step 1: Generate Stacked-Alpha MP4

**Recommended**: Use the `--format mp4` flag in `animate.py` to generate the stacked-alpha MP4 directly:

```bash
REPLICATE_API_TOKEN=$REPLICATE_API_TOKEN python3 ~/.claude/skills/character-animator/scripts/animate.py \
    character.png --prompt "idle animation" --format mp4 --output character_stacked.mp4
```

This handles everything automatically: AI generation, background removal, and stacked-alpha encoding in one command.

**Manual conversion** (if you already have a VP9+alpha WebM):

```bash
ffmpeg -y -i character.webm \
  -filter_complex "[0:v]split[rgb][a];[a]alphaextract[amask];[rgb]format=rgb24,pad=iw:ih*2[padded];[padded][amask]overlay=0:h" \
  -c:v libx264 -preset veryslow -crf 26 -pix_fmt yuv420p -an \
  character_stacked.mp4
```

**File size**: Stacked H.264 is typically **40-60% smaller** than VP9 WebM (the grayscale alpha half compresses extremely well).

### Step 2: Create Base64 Data URL

```bash
echo "export const CharacterVideoDataUrl = \"data:video/mp4;base64,$(base64 -i character_stacked.mp4)\";" > src/CharacterVideo.ts
```

### Step 3: PixiJS Alpha-Unpack Shader (GPU)

Create a custom PIXI `Mesh` with a GLSL fragment shader that samples the top half for color and bottom half for alpha:

```typescript
// src/filters/AlphaPackFilter.ts
import { Mesh as PixiMesh, Geometry, Shader, Texture } from 'pixi.js';

const vertSrc = `
  precision mediump float;
  attribute vec2 aVertexPosition;
  attribute vec2 aTextureCoord;
  uniform mat3 translationMatrix;
  uniform mat3 projectionMatrix;
  varying vec2 vUvs;
  void main() {
    vUvs = aTextureCoord;
    gl_Position = vec4((projectionMatrix * translationMatrix * vec3(aVertexPosition, 1.0)).xy, 0.0, 1.0);
  }
`;

const fragSrc = `
  precision mediump float;
  varying vec2 vUvs;
  uniform sampler2D uSampler;
  void main() {
    vec2 colorUv = vec2(vUvs.x, vUvs.y * 0.5);
    vec2 alphaUv = vec2(vUvs.x, vUvs.y * 0.5 + 0.5);
    vec4 color = texture2D(uSampler, colorUv);
    float a = texture2D(uSampler, alphaUv).r;
    gl_FragColor = vec4(color.rgb * a, a);
  }
`;

export function createAlphaPackMesh(videoTexture: Texture, w: number, h: number): PixiMesh<Shader> {
  const hw = w / 2;
  const hh = h / 2;
  const geometry = new Geometry()
    .addAttribute('aVertexPosition', [-hw, -hh, hw, -hh, hw, hh, -hw, hh], 2)
    .addAttribute('aTextureCoord', [0, 0, 1, 0, 1, 1, 0, 1], 2)
    .addIndex([0, 1, 2, 0, 2, 3]);
  const shader = Shader.from(vertSrc, fragSrc, { uSampler: videoTexture });
  return new PixiMesh(geometry, shader);
}
```

### Step 4: Use in Game Code

```typescript
import { Texture } from 'pixi.js';
import { CharacterVideoDataUrl } from './CharacterVideo';
import { createAlphaPackMesh } from './filters/AlphaPackFilter';

const VIDEO_W = 200; // Character display width
const VIDEO_H = 200; // Character display height (half of actual video height)

const video = document.createElement('video');
video.src = CharacterVideoDataUrl;
video.loop = true;
video.muted = true;
video.playsInline = true;
video.preload = 'auto';
const texture = Texture.from(video, { resourceOptions: { autoPlay: true } });

// Use alpha-pack mesh instead of Sprite
const characterMesh = createAlphaPackMesh(texture, VIDEO_W, VIDEO_H);
container.addChild(characterMesh);
```

### Three.js Variant (ShaderMaterial)

For Three.js projects, use a custom `ShaderMaterial` with the same UV-splitting logic:

```typescript
import { ShaderMaterial, VideoTexture, PlaneGeometry, Mesh, DoubleSide } from 'three';

const alphaPackMaterial = new ShaderMaterial({
  uniforms: { uSampler: { value: videoTexture } },
  vertexShader: `
    varying vec2 vUv;
    void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
  `,
  fragmentShader: `
    uniform sampler2D uSampler;
    varying vec2 vUv;
    void main() {
      vec4 color = texture2D(uSampler, vec2(vUv.x, vUv.y * 0.5));
      float a = texture2D(uSampler, vec2(vUv.x, vUv.y * 0.5 + 0.5)).r;
      gl_FragColor = vec4(color.rgb * a, a);
    }
  `,
  transparent: true,
  side: DoubleSide
});
```

### When to Use Stacked-Alpha vs VP9

| Scenario | Format | Why |
|----------|--------|-----|
| iOS required (playable ads) | Stacked H.264 MP4 | VP9 alpha doesn't work on iOS Safari |
| Android/Chrome only | VP9 WebM | Smaller, native alpha support |
| Cross-platform playable ad | Stacked H.264 MP4 | Single file, works everywhere |
| Desktop web only | VP9 WebM | All modern desktop browsers support it |
