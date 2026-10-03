"""Encode the approved imagegen keyframes as a small looping Workshop GIF.

Only format conversion, thumbnail resizing and GIF encoding occur here.
The artwork and lighting in both input frames were edited with imagegen.
Requires Pillow. Does not access Steam or modify software release files.
"""
from pathlib import Path
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]

def main():
    inputs = [Image.open(ROOT / 'workshop/assets' / name).convert('RGB')
              for name in ('cover-en.png', 'cover-en-bright.png')]
    assert inputs[0].size == inputs[1].size
    assert inputs[0].width == inputs[0].height
    assert ImageChops.difference(*inputs).getbbox(), 'Animation frames must differ'
    inputs[0].save(ROOT / 'workshop/cover.jpg', quality=90, optimize=True)
    target = ROOT / 'workshop/cover-en.gif'
    for size in (900, 800, 768, 700, 640):
        frames = [im.resize((size, size), Image.Resampling.LANCZOS) for im in inputs]
        palette = frames[1].quantize(colors=256)
        frames = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in frames]
        frames[0].save(target, save_all=True, append_images=frames[1:],
                       duration=[1100, 1100], loop=0, optimize=True, disposal=1)
        if target.stat().st_size < 900_000:
            break
    with Image.open(target) as result:
        assert result.n_frames == 2 and result.info['loop'] == 0
        assert result.width >= 640 and target.stat().st_size < 900_000
        print(f'{target.name}: {result.width}x{result.height}, {result.n_frames} frames, '
              f'{target.stat().st_size} bytes, 2.2s repeating light pulse')

if __name__ == '__main__':
    main()
