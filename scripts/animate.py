#!/usr/bin/env python3
"""
Character Animator Pipeline
Animates a character image using AI video generation, removes the background,
and outputs a VP9 WebM with alpha transparency.

Usage:
    python3 animate.py <image_path> --prompt "description of animation" [options]

Options:
    --prompt       Animation prompt (required)
    --model        Video model: kling | minimax (default: kling)
    --method       Transparency method: auto | chromakey | sam3 (default: auto)
    --subject      SAM3 segmentation prompt (only for --method sam3)
    --duration     Video duration: 5 | 10 seconds (default: 5)
    --output       Output file path (default: <input_name>-animated.webm)

Requires:
    - REPLICATE_API_TOKEN environment variable
    - FFmpeg installed on PATH
"""
import argparse
import math
import os
import shutil
import subprocess
import sys
import tempfile

try:
    import replicate
    import requests
    from PIL import Image
except ImportError:
    print("Installing required packages...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "replicate", "requests", "Pillow", "-q"])
    import replicate
    import requests
    from PIL import Image


def get_url(output):
    if hasattr(output, 'url'):
        return output.url
    elif isinstance(output, str):
        return output
    return str(output)


def download(url, dest):
    resp = requests.get(url, stream=True)
    resp.raise_for_status()
    with open(dest, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)


def log(step, msg):
    print(f"  [{step}] {msg}")


def find_key_color(image_path):
    """Scan an RGBA image and find the color most distant from any opaque pixel.
    Returns (r, g, b) tuple and the hex string for FFmpeg chromakey."""
    img = Image.open(image_path).convert('RGBA')
    pixels = img.getdata()
    opaque = [(r, g, b) for r, g, b, a in pixels if a > 128]
    img.close()

    if not opaque:
        return (0, 255, 255), '0x00FFFF'  # fallback cyan

    # Test candidate key colors and pick the one furthest from any pixel
    candidates = [
        (0, 255, 255),    # cyan
        (255, 0, 255),    # magenta
        (0, 0, 255),      # blue
        (255, 0, 0),      # red
        (255, 20, 147),   # hot pink
    ]

    best_color = None
    best_dist = -1

    for cr, cg, cb in candidates:
        min_dist = float('inf')
        for r, g, b in opaque:
            dist = math.sqrt((r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2)
            if dist < min_dist:
                min_dist = dist
        if min_dist > best_dist:
            best_dist = min_dist
            best_color = (cr, cg, cb)

    r, g, b = best_color
    hex_str = f'0x{r:02X}{g:02X}{b:02X}'
    return best_color, hex_str


def detect_solid_background(image_path, tolerance=30, min_edge_ratio=0.65):
    """Check if an RGB image has a solid-color background by sampling edge pixels.
    Returns (key_color, hex_str) if a dominant edge color is found, or (None, None)."""
    img = Image.open(image_path).convert('RGB')
    w, h = img.size
    pixels = img.load()

    # Sample all pixels along the 4 edges
    edge_pixels = []
    for x in range(w):
        edge_pixels.append(pixels[x, 0])           # top row
        edge_pixels.append(pixels[x, h - 1])       # bottom row
    for y in range(1, h - 1):
        edge_pixels.append(pixels[0, y])            # left column
        edge_pixels.append(pixels[w - 1, y])        # right column
    img.close()

    if not edge_pixels:
        return None, None

    # Find the most common edge color (within tolerance)
    # Group similar colors together
    from collections import Counter
    color_counts = Counter(edge_pixels)
    dominant_color, dominant_count = color_counts.most_common(1)[0]

    # Count how many edge pixels are within tolerance of the dominant color
    dr, dg, db = dominant_color
    close_count = 0
    for r, g, b in edge_pixels:
        dist = math.sqrt((r - dr) ** 2 + (g - dg) ** 2 + (b - db) ** 2)
        if dist <= tolerance:
            close_count += 1

    ratio = close_count / len(edge_pixels)
    if ratio >= min_edge_ratio:
        r, g, b = dominant_color
        hex_str = f'0x{r:02X}{g:02X}{b:02X}'
        return dominant_color, hex_str

    return None, None


def bake_background(image_path, key_color, dest_path):
    """Composite an RGBA image over a flat key-color background, save as RGB PNG."""
    char_img = Image.open(image_path).convert('RGBA')
    bg = Image.new('RGBA', char_img.size, (*key_color, 255))
    bg.paste(char_img, (0, 0), char_img)
    bg.convert('RGB').save(dest_path)
    char_img.close()
    bg.close()


def animate(image_path, prompt, model='kling', asset_type='character', method='auto',
            subject=None, duration=5, output_path=None, loop=None, mask_path=None):
    # Default: backgrounds always loop unless explicitly disabled
    if loop is None:
        loop = asset_type == 'background'

    if not os.environ.get('REPLICATE_API_TOKEN'):
        print("ERROR: REPLICATE_API_TOKEN environment variable is required")
        sys.exit(1)

    if not shutil.which('ffmpeg'):
        print("ERROR: FFmpeg is required but not found on PATH")
        sys.exit(1)

    if not os.path.exists(image_path):
        print(f"ERROR: Image not found: {image_path}")
        sys.exit(1)

    if output_path is None:
        base = os.path.splitext(os.path.basename(image_path))[0]
        output_path = os.path.join(os.path.dirname(os.path.abspath(image_path)), f"{base}-animated.webm")

    # Match output dimensions to source image (capped at 720p for mobile)
    # Render 15% oversized then center-crop to absorb AI-generated zoom drift
    src = Image.open(image_path)
    src_w, src_h = src.size
    has_alpha = src.mode == 'RGBA'
    if has_alpha:
        alpha = src.getchannel('A')
        alpha_range = alpha.getextrema()
        has_alpha = alpha_range[0] != alpha_range[1]  # flat alpha = no real transparency
    src.close()
    cap_w = min(src_w, 720)
    cap_h = min(src_h, 720)
    oversized_w = int(cap_w * 1.15)
    oversized_h = int(cap_h * 1.15)
    # Make dimensions even (required by VP9)
    oversized_w += oversized_w % 2
    oversized_h += oversized_h % 2
    crop_w = cap_w + (cap_w % 2)
    crop_h = cap_h + (cap_h % 2)
    scale = f'scale={oversized_w}:{oversized_h}:force_original_aspect_ratio=decrease,crop={crop_w}:{crop_h}'
    log("size", f"Source: {src_w}x{src_h} -> Render: {oversized_w}x{oversized_h} -> Crop: {crop_w}x{crop_h}")

    # Resolve auto method: chromakey if RGBA with alpha, solid-bg chromakey if detectable, else SAM3
    detected_bg = None
    if method == 'auto':
        if mask_path:
            method = 'mask'
        elif asset_type == 'background':
            method = 'background'
        elif has_alpha:
            method = 'chromakey'
        else:
            # No alpha -- check if image has a solid-color background we can chromakey directly
            detected_bg, detected_hex = detect_solid_background(image_path)
            if detected_bg is not None:
                method = 'chromakey'
                log("method", f"Auto-selected: chromakey (detected solid background {detected_hex})")
            else:
                method = 'sam3'
        if method != 'chromakey' or detected_bg is None:
            log("method", f"Auto-selected: {method}" + (" (image has alpha)" if method == 'chromakey' and has_alpha else ""))

    if mask_path and not os.path.exists(mask_path):
        print(f"ERROR: Mask image not found: {mask_path}")
        sys.exit(1)

    # Ensure mask PNG is RGBA with proper alpha channel
    if mask_path:
        mask_img = Image.open(mask_path)
        if mask_img.mode != 'RGBA':
            log("mask", f"Converting mask from {mask_img.mode} to RGBA...")
            mask_img = mask_img.convert('RGBA')
            mask_path_rgba = os.path.join(tempfile.mkdtemp(prefix="char-anim-mask-"), 'mask_rgba.png')
            mask_img.save(mask_path_rgba)
            mask_img.close()
            mask_path = mask_path_rgba
        else:
            alpha = mask_img.getchannel('A')
            extrema = alpha.getextrema()
            mask_img.close()
            if extrema[0] == extrema[1]:
                log("warn", f"Mask alpha is flat ({extrema[0]}) -- no transparency variation. Output may lack cutout.")
            else:
                log("mask", f"RGBA mask OK -- alpha range [{extrema[0]}, {extrema[1]}]")

    # Determine step count
    if method == 'background':
        total = 2
    elif method == 'chromakey':
        total = 2  # generate (with baked bg) + chromakey encode
    else:
        total = 3  # generate + SAM3/mask + encode

    tmpdir = tempfile.mkdtemp(prefix="char-anim-")

    try:
        # ── Chromakey: bake key color into source image before generation ──
        gen_image_path = image_path
        key_color = None
        key_hex = None

        if method == 'chromakey':
            if detected_bg is not None:
                # Solid background detected in RGB image -- use it directly as key color
                key_color = detected_bg
                key_hex = detected_hex
                log("key", f"Using detected background color: RGB{key_color} ({key_hex}) -- no baking needed")
            else:
                # RGBA image -- find best key color and bake it
                key_color, key_hex = find_key_color(image_path)
                log("key", f"Best key color: RGB{key_color} ({key_hex}) -- most distant from all character pixels")
                baked_path = os.path.join(tmpdir, 'baked_bg.png')
                bake_background(image_path, key_color, baked_path)
                gen_image_path = baked_path
                log("bake", f"Character composited onto {key_hex} background")

        # ── Step 1: Generate video ──
        print(f"\n[1/{total}] Generating animation with {model}...")

        if model == 'kling':
            model_id = 'kwaivgi/kling-v2.1'
            params = {
                'prompt': prompt,
                'start_image': open(gen_image_path, 'rb'),
                'duration': int(duration),
                'mode': 'standard',
                'negative_prompt': 'blurry, distorted, low quality, watermark',
                'cfg_scale': 0.5,
                'aspect_ratio': '16:9',
            }
            if loop:
                params['end_image'] = open(gen_image_path, 'rb')
                params['mode'] = 'pro'
                log("loop", "Using start_image == end_image for seamless loop (mode=pro)")
        elif model == 'minimax':
            model_id = 'minimax/video-01'
            params = {
                'prompt': prompt,
                'first_frame_image': open(gen_image_path, 'rb'),
                'prompt_optimizer': True,
            }
        else:
            print(f"ERROR: Unknown model: {model}")
            sys.exit(1)

        output = replicate.run(model_id, input=params)
        video_url = get_url(output)

        generated = os.path.join(tmpdir, 'generated.mp4')
        log("download", "Downloading generated video...")
        download(video_url, generated)
        log("done", "Animation generated!")

        if method == 'mask':
            # ── MASK PATH: use original PNG alpha as mask ──
            mask_img = Image.open(mask_path)
            mask_w, mask_h = mask_img.size
            mask_img.close()
            log("mask", f"Mask input: {mask_w}x{mask_h}, format confirmed RGBA")
            out_w = mask_w + (mask_w % 2)
            out_h = mask_h + (mask_h % 2)

            print(f"\n[2/{total}] Creating alpha mask video from {os.path.basename(mask_path)}...")
            mask_video = os.path.join(tmpdir, 'mask.mp4')
            mask_cmd = [
                'ffmpeg', '-y', '-loop', '1', '-i', mask_path,
                '-vf', f'alphaextract,scale={out_w}:{out_h}',
                '-t', '10', '-r', '24',
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                mask_video,
            ]
            result = subprocess.run(mask_cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                print(f"ERROR: Mask creation failed:\n{result.stderr[-500:]}")
                sys.exit(1)
            log("done", f"Mask video created ({out_w}x{out_h})")

            print(f"\n[3/{total}] Masking video with PNG alpha -> transparent VP9...")
            ffmpeg_cmd = [
                'ffmpeg', '-y',
                '-i', generated,
                '-i', mask_video,
                '-filter_complex', f'[0:v]scale={out_w}:{out_h}[vid];[vid][1:v]alphamerge[out]',
                '-map', '[out]',
                '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p',
                '-auto-alt-ref', '0', '-b:v', '800k', '-crf', '35',
                '-speed', '4', '-row-mt', '1',
                '-metadata:s:v:0', 'alpha_mode=1', '-an',
                '-shortest',
                output_path,
            ]

        elif method == 'background':
            # ── BACKGROUND PATH: no matting, encode for mobile ──
            print(f"\n[2/{total}] Encoding VP9 for mobile (<=720p)...")
            ffmpeg_cmd = [
                'ffmpeg', '-y', '-i', generated,
                '-vf', scale,
                '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuv420p',
                '-b:v', '600k', '-crf', '36', '-speed', '4', '-row-mt', '1', '-an',
                output_path,
            ]

        elif method == 'chromakey':
            # ── CHROMAKEY PATH: remove baked key color ──
            print(f"\n[2/{total}] Chromakey {key_hex} -> transparent VP9 ({crop_w}x{crop_h})...")
            ffmpeg_cmd = [
                'ffmpeg', '-y',
                '-i', generated,
                '-vf', f'scale={crop_w}:{crop_h},chromakey={key_hex}:0.15:0.1,format=yuva420p',
                '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p',
                '-auto-alt-ref', '0', '-b:v', '800k', '-crf', '35',
                '-speed', '4', '-row-mt', '1',
                '-metadata:s:v:0', 'alpha_mode=1', '-an',
                output_path,
            ]

        else:
            # ── SAM3 PATH: AI video segmentation (fallback for non-RGBA images) ──
            sam_prompt = subject or 'character'
            print(f"\n[2/{total}] Segmenting subject with SAM3 (prompt: '{sam_prompt}')...")
            sam_out = replicate.run(
                'lucataco/sam3-video:8cbab4c2a3133e679b5b863b80527f6b5c751ec7b33681b7e0b7c79c749df961',
                input={
                    'video': open(generated, 'rb'),
                    'prompt': sam_prompt,
                    'mask_only': True,
                }
            )
            mask_video_path = os.path.join(tmpdir, 'sam3_mask.mp4')
            download(get_url(sam_out), mask_video_path)
            log("done", "SAM3 mask extracted!")

            # Force both streams to exact same dimensions
            # tmix=frames=5 temporally smooths the mask to eliminate flicker
            # inflate x3 dilates the mask ~3px to recover edges SAM3 may have clipped
            exact_scale = f'scale={crop_w}:{crop_h}'
            print(f"\n[3/{total}] Alphamerge + VP9 encoding for mobile ({crop_w}x{crop_h})...")
            ffmpeg_cmd = [
                'ffmpeg', '-y',
                '-i', generated,
                '-i', mask_video_path,
                '-filter_complex',
                f'[0:v]{exact_scale}[vid];[1:v]{exact_scale},format=gray,tmix=frames=5,inflate,inflate,inflate[mask];[vid][mask]alphamerge,format=yuva420p[out]',
                '-map', '[out]',
                '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p',
                '-auto-alt-ref', '0', '-b:v', '800k', '-crf', '35',
                '-speed', '4', '-row-mt', '1',
                '-metadata:s:v:0', 'alpha_mode=1', '-an',
                '-shortest',
                output_path,
            ]

        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            print(f"ERROR: FFmpeg failed:\n{result.stderr[-500:]}")
            sys.exit(1)

        size_mb = round(os.path.getsize(output_path) / (1024 * 1024), 2)
        print(f"\nDone! Output: {output_path} ({size_mb} MB)")
        if asset_type == 'background':
            print(f"Format: VP9 WebM (opaque)")
        else:
            print(f"Format: VP9 WebM with alpha transparency")
        return output_path

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Animate an image with AI for mobile ads')
    parser.add_argument('image', help='Path to image (PNG/JPG/WEBP)')
    parser.add_argument('--prompt', required=True, help='Animation prompt')
    parser.add_argument('--model', choices=['kling', 'minimax'], default='kling')
    parser.add_argument('--method', choices=['auto', 'chromakey', 'sam3'], default='auto',
                        help='Transparency method: auto (chromakey if RGBA, else SAM3), chromakey, or sam3')
    parser.add_argument('--type', dest='asset_type', choices=['character', 'background'], default='character',
                        help='character = transparent output, background = full frame')
    parser.add_argument('--subject', default=None,
                        help='SAM3 segmentation prompt (e.g. "person", "animal", "car"). Default: "character"')
    parser.add_argument('--duration', type=int, choices=[5, 10], default=5)
    loop_group = parser.add_mutually_exclusive_group()
    loop_group.add_argument('--loop', action='store_true', default=None, dest='loop',
                            help='Force seamless loop (default for backgrounds)')
    loop_group.add_argument('--no-loop', action='store_false', dest='loop',
                            help='Disable looping (override default for backgrounds)')
    parser.add_argument('--mask', help='PNG with alpha channel to use as shape mask (skips AI bg removal)')
    parser.add_argument('--output', help='Output file path')
    args = parser.parse_args()

    animate(args.image, args.prompt, args.model, args.asset_type, args.method,
            args.subject, args.duration, args.output, args.loop, args.mask)
