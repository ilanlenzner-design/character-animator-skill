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
    --matting       Matting mode: universal | human (default: universal)
    --duration     Video duration: 5 | 10 seconds (default: 5)
    --output       Output file path (default: <input_name>-animated.webm)

Requires:
    - REPLICATE_API_TOKEN environment variable
    - FFmpeg installed on PATH
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time

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


def animate(image_path, prompt, model='kling', asset_type='character', matting='universal', duration=5, output_path=None, loop=False, mask_path=None):
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
    log("size", f"Source: {src_w}x{src_h} → Render: {oversized_w}x{oversized_h} → Crop: {crop_w}x{crop_h}")

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
            # Validate alpha channel has both transparent and opaque pixels
            alpha = mask_img.getchannel('A')
            extrema = alpha.getextrema()
            mask_img.close()
            if extrema[0] == extrema[1]:
                log("warn", f"Mask alpha is flat ({extrema[0]}) — no transparency variation. Output may lack cutout.")
            else:
                log("mask", f"RGBA mask OK — alpha range [{extrema[0]}, {extrema[1]}]")

    if mask_path:
        total = 3
    elif asset_type == 'background':
        total = 2
    elif matting == 'human':
        total = 4
    else:
        total = 3

    tmpdir = tempfile.mkdtemp(prefix="char-anim-")

    try:
        # ── Step 1: Generate video ──
        print(f"\n[1/{total}] Generating animation with {model}...")

        if model == 'kling':
            model_id = 'kwaivgi/kling-v2.1'
            params = {
                'prompt': prompt,
                'start_image': open(image_path, 'rb'),
                'duration': int(duration),
                'mode': 'standard',
                'negative_prompt': 'blurry, distorted, low quality, watermark',
                'cfg_scale': 0.5,
                'aspect_ratio': '16:9',
            }
            if loop:
                params['end_image'] = open(image_path, 'rb')
                params['mode'] = 'pro'
                log("loop", "Using start_image == end_image for seamless loop (mode=pro)")
        elif model == 'minimax':
            model_id = 'minimax/video-01'
            params = {
                'prompt': prompt,
                'first_frame_image': open(image_path, 'rb'),
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

        if mask_path:
            # ── MASK PATH: use original PNG alpha as mask ──
            mask_img = Image.open(mask_path)
            mask_w, mask_h = mask_img.size
            mask_img.close()
            log("mask", f"Mask input: {mask_w}x{mask_h}, format confirmed RGBA")
            # Make dimensions even for VP9
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

            print(f"\n[3/{total}] Masking video with PNG alpha → transparent VP9...")
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

        elif asset_type == 'background':
            # ── BACKGROUND PATH: no matting, encode for mobile ──
            print(f"\n[2/{total}] Encoding VP9 for mobile (<=720p)...")
            ffmpeg_cmd = [
                'ffmpeg', '-y', '-i', generated,
                '-vf', scale,
                '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuv420p',
                '-b:v', '600k', '-crf', '36', '-speed', '4', '-row-mt', '1', '-an',
                output_path,
            ]

        elif matting == 'human':
            # ── HUMAN CHARACTER PATH ──
            print(f"\n[2/{total}] Extracting alpha mask (human RVM)...")
            alpha_out = replicate.run(
                'arielreplicate/robust_video_matting:73d2128a371922d5d1abf0712a1d974be0e4e2358cc1218e4e34714767232bac',
                input={'input_video': open(generated, 'rb'), 'output_type': 'alpha-mask'}
            )
            alpha_path = os.path.join(tmpdir, 'alpha.mp4')
            download(get_url(alpha_out), alpha_path)
            log("done", "Alpha mask extracted!")

            print(f"\n[3/{total}] Extracting foreground...")
            fg_out = replicate.run(
                'arielreplicate/robust_video_matting:73d2128a371922d5d1abf0712a1d974be0e4e2358cc1218e4e34714767232bac',
                input={'input_video': open(generated, 'rb'), 'output_type': 'foreground-mask'}
            )
            fg_path = os.path.join(tmpdir, 'foreground.mp4')
            download(get_url(fg_out), fg_path)
            log("done", "Foreground extracted!")

            print(f"\n[4/{total}] Compositing transparent VP9 for mobile...")
            ffmpeg_cmd = [
                'ffmpeg', '-y',
                '-i', fg_path, '-i', alpha_path,
                '-filter_complex', f'[0:v][1:v]alphamerge,{scale}[merged]',
                '-map', '[merged]',
                '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p',
                '-auto-alt-ref', '0', '-b:v', '800k', '-crf', '35',
                '-speed', '4', '-row-mt', '1',
                '-metadata:s:v:0', 'alpha_mode=1', '-an',
                output_path,
            ]

        else:
            # ── UNIVERSAL CHARACTER PATH ──
            print(f"\n[2/{total}] Removing background (universal RMBG)...")
            bg_out = replicate.run(
                'nateraw/video-background-remover:ac5c138171b04413a69222c304f67c135e259d46089fc70ef12da685b3c604aa',
                input={'video': open(generated, 'rb')}
            )
            green_path = os.path.join(tmpdir, 'green.mp4')
            download(get_url(bg_out), green_path)
            log("done", "Background removed!")

            print(f"\n[3/{total}] Chromakey + alpha erosion to transparent VP9...")
            # Chromakey → split → erode alpha 1px to kill green fringe → merge back → despill → scale
            chroma_filter = (
                f'chromakey=0x00FF00:0.28:0.02,split[rgb][a];'
                f'[a]alphaextract,erosion=threshold0=255:threshold1=255:threshold2=255:threshold3=255[amask];'
                f'[rgb][amask]alphamerge,colorchannelmixer=gg=0.8:gb=0.1:gr=0.1,{scale}[out]'
            )
            ffmpeg_cmd = [
                'ffmpeg', '-y',
                '-i', green_path,
                '-filter_complex', chroma_filter,
                '-map', '[out]',
                '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p',
                '-auto-alt-ref', '0', '-b:v', '800k', '-crf', '35',
                '-speed', '4', '-row-mt', '1',
                '-metadata:s:v:0', 'alpha_mode=1', '-an',
                output_path,
            ]

        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            print(f"ERROR: FFmpeg failed:\n{result.stderr[-500:]}")
            sys.exit(1)

        size_mb = round(os.path.getsize(output_path) / (1024 * 1024), 2)
        print(f"\nDone! Output: {output_path} ({size_mb} MB)")
        print(f"Format: VP9 WebM with alpha transparency")
        return output_path

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Animate an image with AI for mobile ads')
    parser.add_argument('image', help='Path to image (PNG/JPG/WEBP)')
    parser.add_argument('--prompt', required=True, help='Animation prompt')
    parser.add_argument('--model', choices=['kling', 'minimax'], default='kling')
    parser.add_argument('--type', dest='asset_type', choices=['character', 'background'], default='character',
                        help='character = transparent output, background = full frame')
    parser.add_argument('--matting', choices=['universal', 'human'], default='universal')
    parser.add_argument('--duration', type=int, choices=[5, 10], default=5)
    parser.add_argument('--loop', action='store_true', help='Use start_image == end_image for seamless loop (Kling v2.5)')
    parser.add_argument('--mask', help='PNG with alpha channel to use as shape mask (skips AI bg removal)')
    parser.add_argument('--output', help='Output file path')
    args = parser.parse_args()

    animate(args.image, args.prompt, args.model, args.asset_type, args.matting, args.duration, args.output, args.loop, args.mask)
