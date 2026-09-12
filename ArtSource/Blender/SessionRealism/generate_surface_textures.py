"""Deterministic PBR source maps for the FlyVisual SessionRealism material set.

UV contract (the generated PNG is written top-to-bottom, as required by PNG):
Blender/Unity UV ``v=0`` addresses the bottom scanline, so all pattern math below
uses ``v=0`` at the bottom.  Body v=.03-.45 is head/thorax/leg cuticle and
v=.52-.98 is the abdomen.  On that abdomen strip t=(v-.52)/.46 increases
from front to rear; u=.25 is dorsal and u=.75 is ventral.

Base color values are authored directly as sRGB.  Normal maps use OpenGL
tangent-space convention (+Y is up), and mask RGBA is metallic, AO, unused,
smoothness in linear data.  The module deliberately has no Pillow or bpy
dependency: Blender 4.2's bundled Python and numpy are sufficient.
"""

from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path

import numpy as np


SEED = 18473
BODY_SIZE = 2048
EYE_SIZE = 2048
WING_SIZE = 1024


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    """Return one checksummed PNG chunk without relying on an image library."""
    return (struct.pack(">I", len(payload)) + tag + payload +
            struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))


def _write_png(path: Path, image: np.ndarray) -> None:
    """Write an HxWx3 or HxWx4 uint8 PNG using filter type zero per scanline."""
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ValueError("PNG input must be uint8 HxWx3 or HxWx4")
    height, width, channels = image.shape
    color_type = 2 if channels == 3 else 6
    scanlines = b"".join(b"\x00" + image[row].tobytes() for row in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    data = (b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header) +
            _png_chunk(b"IDAT", zlib.compress(scanlines, level=6)) +
            _png_chunk(b"IEND", b""))
    path.write_bytes(data)


def _uv(size: int) -> tuple[np.ndarray, np.ndarray]:
    """Return broadcastable u and bottom-origin v coordinates at texel centres."""
    u = ((np.arange(size, dtype=np.float32) + 0.5) / size)[None, :]
    # Array row zero is the top PNG scanline; UV v=0 belongs to its final row.
    v = ((np.arange(size - 1, -1, -1, dtype=np.float32) + 0.5) / size)[:, None]
    return u, v


def _fract(value: np.ndarray) -> np.ndarray:
    return value - np.floor(value)


def _noise(u: np.ndarray, v: np.ndarray, detail: float = 1.0) -> np.ndarray:
    """Small deterministic value noise, suitable for restrained pigment variation."""
    return _fract(np.sin((u * (127.1 * detail) + v * (311.7 * detail) + SEED) *
                        12.9898) * 43758.5453)


def _smoothstep(lo: float, hi: float, value: np.ndarray) -> np.ndarray:
    t = np.clip((value - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _to_u8(image: np.ndarray) -> np.ndarray:
    return np.rint(np.clip(image, 0.0, 1.0) * 255.0).astype(np.uint8)


def _normal_from_slopes(slope_u: np.ndarray, slope_v: np.ndarray) -> np.ndarray:
    """Encode shallow OpenGL tangent-space slopes into an RGB normal map."""
    length = np.sqrt(1.0 + slope_u * slope_u + slope_v * slope_v)
    normal = np.empty((slope_u.shape[0], slope_u.shape[1], 3), dtype=np.float32)
    normal[..., 0] = 0.5 + 0.5 * (-slope_u / length)
    normal[..., 1] = 0.5 + 0.5 * (-slope_v / length)
    normal[..., 2] = 0.5 + 0.5 * (1.0 / length)
    return normal


def _body_maps(size: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build cuticle/abdomen maps; the abdominal bands follow UV t, not a tube stripe."""
    u, v = _uv(size)
    low = (np.sin(np.pi * 2.0 * (u * 2.1 + v * 1.4)) +
           0.65 * np.sin(np.pi * 2.0 * (u * 4.7 - v * 2.8) + 1.1)) / 1.65
    grain = _noise(u, v, 2.3) - 0.5
    cuticle_factor = 1.0 + 0.040 * low + 0.018 * grain

    cuticle = np.empty((size, size, 3), dtype=np.float32)
    cuticle[:] = np.asarray((0.50, 0.34, 0.15), dtype=np.float32) * cuticle_factor[..., None]

    t = np.clip((v - 0.52) / 0.46, 0.0, 1.0)
    segment_local = _fract(t * 5.75)
    theta = np.pi * 2.0 * u
    dorsal = 0.5 + 0.5 * np.sin(theta)  # u=.25 dorsal, u=.75 ventral.
    ventral_light = (1.0 - dorsal) * 0.055
    abdomen = np.empty_like(cuticle)
    abdomen[..., 0] = 0.465 + ventral_light + 0.017 * low + 0.010 * grain
    abdomen[..., 1] = 0.285 + ventral_light * 0.72 + 0.014 * low + 0.007 * grain
    abdomen[..., 2] = 0.112 + ventral_light * 0.32 + 0.007 * low + 0.004 * grain

    # The rear quarter of each tergite is brown, strongest on the dorsal plate.
    band = _smoothstep(0.75, 0.96, segment_local) * (0.25 + 0.75 * dorsal)
    abdomen *= (1.0 - 0.40 * band[..., None])
    # A gradual dark male-like posterior avoids a hard, tube-like end ring.
    posterior = _smoothstep(0.78, 0.995, t)
    posterior_tint = np.asarray((0.48, 0.35, 0.22), dtype=np.float32)
    abdomen = abdomen * (1.0 - posterior[..., None] * 0.76) + posterior[..., None] * posterior_tint * 0.04

    abdomen_area = (v >= 0.52) & (v <= 0.98)
    color = cuticle.copy()
    color[abdomen_area[:, 0]] = abdomen[abdomen_area[:, 0]]

    fine_u = 0.022 * np.sin(np.pi * 2.0 * (u * 52.0 + v * 17.0))
    fine_v = 0.018 * np.sin(np.pi * 2.0 * (u * 31.0 - v * 47.0) + 0.6)
    normal = _normal_from_slopes(fine_u + 0.008 * low, fine_v + 0.007 * grain)

    smoothness = 0.325 + 0.045 * low + 0.015 * grain
    smoothness = np.clip(smoothness, 0.25, 0.40)
    ao = np.clip(0.94 - 0.07 * band - 0.025 * np.abs(grain), 0.82, 0.98)
    mask = np.empty((size, size, 4), dtype=np.float32)
    mask[..., 0] = 0.0
    mask[..., 1] = ao
    mask[..., 2] = 0.0
    mask[..., 3] = smoothness
    base_color = np.empty((size, size, 4), dtype=np.float32)
    base_color[..., :3] = color
    base_color[..., 3] = 1.0
    return _to_u8(base_color), _to_u8(normal), _to_u8(mask)


def _eye_maps(size: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build dense, low-relief hexagonal ommatidia without bead-like facets."""
    u, v = _uv(size)
    columns, rows = 56.0, 34.0
    x = u * columns
    y = v * rows
    lower_row = np.floor(y)
    upper_row = lower_row + 1.0

    def distance_to_row(row: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        shifted_x = x - 0.5 * np.mod(row, 2.0)
        cell_x = np.round(shifted_x)
        dx = shifted_x - cell_x
        dy = (y - row) * 0.8660254
        return dx, dy, cell_x

    dx0, dy0, cx0 = distance_to_row(lower_row)
    dx1, dy1, cx1 = distance_to_row(upper_row)
    choose_upper = dx1 * dx1 + dy1 * dy1 < dx0 * dx0 + dy0 * dy0
    dx = np.where(choose_upper, dx1, dx0)
    dy = np.where(choose_upper, dy1, dy0)
    cell_x = np.where(choose_upper, cx1, cx0)
    cell_y = np.where(choose_upper, upper_row, lower_row)
    radius = np.sqrt(dx * dx + dy * dy)
    boundary = _smoothstep(0.425, 0.545, radius)

    # Fade relief toward the UV poles, where a flat cell grid would be conspicuous.
    pole_fade = np.sin(np.pi * v) ** 1.35
    cell_variation = _fract(np.sin(cell_x * 19.19 + cell_y * 71.73 + SEED) * 32517.37) - 0.5
    brightness = 1.0 + 0.045 * cell_variation - 0.055 * boundary
    base = np.empty((size, size, 3), dtype=np.float32)
    base[:] = np.asarray((0.56, 0.085, 0.065), dtype=np.float32) * brightness[..., None]

    # A small convexity per cell.  Values encode an intentionally shallow .1-.2 relief.
    slope_scale = 0.16 * (1.0 - boundary) * pole_fade
    normal = _normal_from_slopes(dx * slope_scale, dy * slope_scale)
    smoothness = np.clip(0.515 + 0.050 * cell_variation - 0.065 * boundary, 0.45, 0.58)
    ao = np.clip(0.965 - 0.105 * boundary, 0.84, 0.98)
    mask = np.empty((size, size, 4), dtype=np.float32)
    mask[..., 0] = 0.0
    mask[..., 1] = ao
    mask[..., 2] = 0.0
    mask[..., 3] = smoothness
    return _to_u8(base), _to_u8(normal), _to_u8(mask)


def _wing_maps(size: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build a lightly varied translucent membrane; veins remain geometry-owned."""
    u, v = _uv(size)
    fine = _noise(u, v, 1.8) - 0.5
    soft = (np.sin(np.pi * 2.0 * (u * 2.2 + v * 1.3)) +
            np.sin(np.pi * 2.0 * (u * 3.7 - v * 2.6) + 0.8)) * 0.5
    variation = 0.018 * fine + 0.010 * soft
    color = np.empty((size, size, 4), dtype=np.float32)
    color[..., :3] = np.asarray((0.80, 0.79, 0.74), dtype=np.float32) * (1.0 + variation[..., None])
    color[..., 3] = np.clip(0.25 + 0.030 * fine + 0.006 * soft, 0.22, 0.28)

    wrinkle_u = 0.018 * np.sin(np.pi * 2.0 * (u * 19.0 + v * 4.0))
    wrinkle_v = 0.014 * np.sin(np.pi * 2.0 * (u * 7.0 - v * 23.0) + 0.5)
    normal = _normal_from_slopes(wrinkle_u, wrinkle_v)
    mask = np.empty((size, size, 4), dtype=np.float32)
    mask[..., 0] = 0.0
    mask[..., 1] = np.clip(0.98 - 0.018 * np.abs(fine), 0.95, 0.99)
    mask[..., 2] = 0.0
    mask[..., 3] = np.clip(0.45 + 0.030 * fine + 0.015 * soft, 0.40, 0.50)
    return _to_u8(color), _to_u8(normal), _to_u8(mask)


def generate(output_dir: str | Path) -> list[Path]:
    """Generate the nine deterministic texture PNGs in *output_dir* and return them."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    body = _body_maps(BODY_SIZE)
    eye = _eye_maps(EYE_SIZE)
    wing = _wing_maps(WING_SIZE)
    jobs = (
        ("Body_BaseColor.png", body[0]), ("Body_Normal.png", body[1]), ("Body_Mask.png", body[2]),
        ("Eye_BaseColor.png", eye[0]), ("Eye_Normal.png", eye[1]), ("Eye_Mask.png", eye[2]),
        ("Wing_BaseColor.png", wing[0]), ("Wing_Normal.png", wing[1]), ("Wing_Mask.png", wing[2]),
    )
    paths: list[Path] = []
    for name, image in jobs:
        path = output / name
        _write_png(path, image)
        paths.append(path)
    return paths


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate deterministic FlyVisual PBR PNG textures.")
    parser.add_argument("output_dir", nargs="?", default=str(Path(__file__).with_name("GeneratedSurfaceTextures")))
    args = parser.parse_args()
    for generated_path in generate(args.output_dir):
        print(generated_path)
