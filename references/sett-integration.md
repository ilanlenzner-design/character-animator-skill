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
