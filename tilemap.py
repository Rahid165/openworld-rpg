"""
Tile map system and pure-Python procedural terrain generation.
"""

from __future__ import annotations

import math
import os
import random
from typing import Dict, List, Optional, Tuple

import pygame

from constants import *


class TileDef:
    def __init__(self, tid: int, name: str, color: Tuple[int, int, int],
                 solid: bool = False, water: bool = False,
                 friction: float = 1.0):
        self.tid = tid
        self.name = name
        self.color = color
        self.solid = solid
        self.water = water
        self.friction = friction


TILE_DEFS: Dict[int, TileDef] = {
    TILE_GRASS: TileDef(TILE_GRASS, "Grass", COL_GRASS, False),
    TILE_DIRT: TileDef(TILE_DIRT, "Dirt", COL_DIRT, False, friction=0.85),
    TILE_WATER: TileDef(TILE_WATER, "Water", COL_WATER, True, water=True),
    TILE_SAND: TileDef(TILE_SAND, "Sand", COL_SAND, False, friction=0.7),
    TILE_STONE: TileDef(TILE_STONE, "Stone", COL_STONE, False, friction=0.9),
    TILE_MUD: TileDef(TILE_MUD, "Mud", COL_MUD, False, friction=0.5),
    TILE_SNOW: TileDef(TILE_SNOW, "Snow", COL_SNOW, False, friction=0.6),
    TILE_DEEP_WATER: TileDef(TILE_DEEP_WATER, "Deep Water", COL_WATER_DEEP, True, water=True),
    TILE_RIVER_BANK: TileDef(TILE_RIVER_BANK, "River Bank", COL_RIVER_BANK, False),
}

TILE_VARIANTS: Dict[int, List[Tuple[int, int, int]]] = {
    TILE_GRASS: [COL_GRASS, COL_GRASS2, (58, 105, 50), (65, 115, 58)],
    TILE_STONE: [COL_STONE, COL_STONE2, (120, 120, 130)],
    TILE_WATER: [COL_WATER, (45, 110, 170), (35, 90, 150)],
    TILE_SAND: [COL_SAND, (185, 168, 118), (200, 185, 135)],
}


class Tilemap:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.tiles: List[List[int]] = [[TILE_GRASS] * width for _ in range(height)]
        self._variant: List[List[int]] = [[0] * width for _ in range(height)]
        self._tile_surface: Optional[pygame.Surface] = None
        self._dirty = True

    def get(self, tx: int, ty: int) -> int:
        if 0 <= tx < self.width and 0 <= ty < self.height:
            return self.tiles[ty][tx]
        return TILE_WATER

    def set(self, tx: int, ty: int, tile_id: int):
        if 0 <= tx < self.width and 0 <= ty < self.height:
            self.tiles[ty][tx] = tile_id
            self._dirty = True

    def is_solid(self, tx: int, ty: int) -> bool:
        return TILE_DEFS[self.get(tx, ty)].solid

    def is_passable_rect(self, rect: pygame.Rect) -> bool:
        left = rect.left // TILE_SIZE
        right = (rect.right - 1) // TILE_SIZE
        top = rect.top // TILE_SIZE
        bottom = (rect.bottom - 1) // TILE_SIZE
        for ty in range(top, bottom + 1):
            for tx in range(left, right + 1):
                if self.is_solid(tx, ty):
                    return False
        return True

    def get_tile_def(self, tx: int, ty: int) -> TileDef:
        return TILE_DEFS.get(self.get(tx, ty), TILE_DEFS[TILE_GRASS])

    def _bake(self):
        surf = pygame.Surface((self.width * TILE_SIZE, self.height * TILE_SIZE))
        for ty in range(self.height):
            for tx in range(self.width):
                tid = self.tiles[ty][tx]
                tdef = TILE_DEFS.get(tid, TILE_DEFS[TILE_GRASS])
                variants = TILE_VARIANTS.get(tid)
                color = variants[self._variant[ty][tx] % len(variants)] if variants else tdef.color
                rect = pygame.Rect(tx * TILE_SIZE, ty * TILE_SIZE, TILE_SIZE, TILE_SIZE)
                pygame.draw.rect(surf, color, rect)
                pygame.draw.rect(surf, (0, 0, 0, 15), rect, 1)
        self._tile_surface = surf
        self._dirty = False

    def draw(self, surface: pygame.Surface, camera_x: int, camera_y: int,
             view_w: int, view_h: int):
        if self._dirty or self._tile_surface is None:
            self._bake()
        src_rect = pygame.Rect(camera_x, camera_y, view_w, view_h)
        surface.blit(self._tile_surface, (0, 0), src_rect)

    def save(self, path: str):
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            for row in self.tiles:
                handle.write("".join(f"{t:1x}" for t in row) + "\n")

    @classmethod
    def load(cls, path: str) -> "Tilemap":
        with open(path, "r", encoding="utf-8") as handle:
            lines = [line.rstrip("\n") for line in handle if line.strip()]
        height = len(lines)
        width = max(len(line) for line in lines) if lines else 0
        tilemap = cls(width, height)
        for ty, line in enumerate(lines):
            for tx, char in enumerate(line):
                try:
                    tilemap.tiles[ty][tx] = int(char, 16)
                except ValueError:
                    tilemap.tiles[ty][tx] = TILE_GRASS
        tilemap._generate_variants()
        return tilemap

    def _generate_variants(self):
        for ty in range(self.height):
            for tx in range(self.width):
                self._variant[ty][tx] = (tx * 7 + ty * 13) % 4


class FractalNoise2D:
    def __init__(self, seed: int):
        self.seed = seed

    def sample(self, x: float, y: float, octaves: int = 4,
               persistence: float = 0.5, lacunarity: float = 2.0) -> float:
        value = 0.0
        amplitude = 1.0
        frequency = 1.0
        total_amplitude = 0.0

        for octave in range(octaves):
            value += self._value_noise(x * frequency, y * frequency, octave) * amplitude
            total_amplitude += amplitude
            amplitude *= persistence
            frequency *= lacunarity

        if total_amplitude == 0:
            return 0.0
        return value / total_amplitude

    def _value_noise(self, x: float, y: float, octave: int) -> float:
        x0 = math.floor(x)
        y0 = math.floor(y)
        x1 = x0 + 1
        y1 = y0 + 1
        sx = self._smooth_step(x - x0)
        sy = self._smooth_step(y - y0)

        n00 = self._hash_value(x0, y0, octave)
        n10 = self._hash_value(x1, y0, octave)
        n01 = self._hash_value(x0, y1, octave)
        n11 = self._hash_value(x1, y1, octave)

        ix0 = self._lerp(n00, n10, sx)
        ix1 = self._lerp(n01, n11, sx)
        return self._lerp(ix0, ix1, sy)

    def _hash_value(self, ix: int, iy: int, octave: int) -> float:
        n = ix * 374761393 + iy * 668265263 + self.seed * 1446647 + octave * 1013904223
        n = (n ^ (n >> 13)) * 1274126177
        n = n ^ (n >> 16)
        return ((n & 0xFFFFFFFF) / 0xFFFFFFFF) * 2.0 - 1.0

    @staticmethod
    def _lerp(a: float, b: float, t: float) -> float:
        return a + (b - a) * t

    @staticmethod
    def _smooth_step(t: float) -> float:
        return t * t * (3.0 - 2.0 * t)


class MapGenerator:
    def __init__(self, seed: Optional[int] = None):
        self.seed = seed if seed is not None else random.randint(0, 99999)
        self.noise = FractalNoise2D(self.seed)

    def generate(self, width: int = MAP_WIDTH, height: int = MAP_HEIGHT) -> Tilemap:
        tilemap = Tilemap(width, height)
        rng = random.Random(self.seed)

        height_map = [[0.0] * width for _ in range(height)]
        moisture_map = [[0.0] * width for _ in range(height)]
        temperature_map = [[0.0] * width for _ in range(height)]

        h_scale = 5.2 / max(1, min(width, height))
        m_scale = 7.4 / max(1, min(width, height))
        t_scale = 3.3 / max(1, min(width, height))

        for ty in range(height):
            for tx in range(width):
                base_h = self.noise.sample(tx * h_scale, ty * h_scale, octaves=5, persistence=0.5, lacunarity=2.1)
                detail_h = self.noise.sample(tx * h_scale * 2.1 + 23.5, ty * h_scale * 2.1 + 11.4,
                                             octaves=3, persistence=0.55, lacunarity=2.3)
                moisture = self.noise.sample(tx * m_scale + 91.1, ty * m_scale + 18.7,
                                             octaves=4, persistence=0.52, lacunarity=2.0)
                temperature = self.noise.sample(tx * t_scale - 47.9, ty * t_scale + 73.2,
                                                octaves=3, persistence=0.6, lacunarity=1.8)
                radial = self._radial_falloff(tx, ty, width, height)

                height_map[ty][tx] = ((base_h * 0.7) + (detail_h * 0.3) + 1.0) * 0.5 - radial * 0.18
                moisture_map[ty][tx] = (moisture + 1.0) * 0.5
                temperature_map[ty][tx] = (temperature + 1.0) * 0.5

        for ty in range(height):
            for tx in range(width):
                h_value = height_map[ty][tx]
                moisture = moisture_map[ty][tx]
                temperature = temperature_map[ty][tx]

                if h_value < 0.28:
                    tid = TILE_DEEP_WATER
                elif h_value < 0.36:
                    tid = TILE_WATER
                elif h_value < 0.42:
                    tid = TILE_SAND
                elif h_value < 0.48:
                    tid = TILE_RIVER_BANK if moisture > 0.48 else TILE_DIRT
                elif h_value < 0.72:
                    if temperature < 0.18 and h_value > 0.58:
                        tid = TILE_SNOW
                    elif moisture > 0.72:
                        tid = TILE_MUD
                    elif moisture < 0.25:
                        tid = TILE_DIRT
                    else:
                        tid = TILE_GRASS
                else:
                    tid = TILE_STONE if temperature > 0.14 else TILE_SNOW

                tilemap.tiles[ty][tx] = tid

        self._carve_rivers(tilemap, rng, height_map)
        self._add_shorelines(tilemap)
        tilemap._generate_variants()
        return tilemap

    def _radial_falloff(self, tx: int, ty: int, width: int, height: int) -> float:
        cx = width * 0.5
        cy = height * 0.5
        dx = (tx - cx) / max(1.0, cx)
        dy = (ty - cy) / max(1.0, cy)
        return min(1.0, math.sqrt(dx * dx + dy * dy))

    def _carve_rivers(self, tilemap: Tilemap, rng: random.Random, height_map: List[List[float]]):
        width = tilemap.width
        height = tilemap.height
        num_rivers = rng.randint(2, 4)

        for _ in range(num_rivers):
            attempts = 0
            while attempts < 120:
                sx = rng.randint(4, width - 5)
                sy = rng.randint(4, height - 5)
                if height_map[sy][sx] > 0.63:
                    break
                attempts += 1
            else:
                continue

            cx = float(sx)
            cy = float(sy)
            river_width = rng.randint(1, 2)

            for _step in range(900):
                tx = int(cx)
                ty = int(cy)
                if not (0 <= tx < width and 0 <= ty < height):
                    break

                for dy in range(-river_width, river_width + 1):
                    for dx in range(-river_width, river_width + 1):
                        nx = tx + dx
                        ny = ty + dy
                        if 0 <= nx < width and 0 <= ny < height:
                            tilemap.tiles[ny][nx] = TILE_WATER if height_map[ny][nx] >= 0.25 else TILE_DEEP_WATER

                best_h = height_map[ty][tx]
                best_move = (0, 0)
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if dx == 0 and dy == 0:
                            continue
                        nx = int(cx + dx)
                        ny = int(cy + dy)
                        if 0 <= nx < width and 0 <= ny < height:
                            if height_map[ny][nx] < best_h:
                                best_h = height_map[ny][nx]
                                best_move = (dx, dy)

                if best_move == (0, 0):
                    best_move = (rng.choice([-1, 0, 1]), rng.choice([-1, 0, 1]))

                cx += best_move[0] + rng.uniform(-0.22, 0.22)
                cy += best_move[1] + rng.uniform(-0.22, 0.22)

                if not (0 <= int(cx) < width and 0 <= int(cy) < height):
                    break
                if height_map[int(cy)][int(cx)] < 0.29:
                    break

    def _add_shorelines(self, tilemap: Tilemap):
        width = tilemap.width
        height = tilemap.height
        for ty in range(height):
            for tx in range(width):
                tid = tilemap.tiles[ty][tx]
                if tid not in (TILE_GRASS, TILE_DIRT, TILE_MUD, TILE_SNOW):
                    continue
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        nx = tx + dx
                        ny = ty + dy
                        if 0 <= nx < width and 0 <= ny < height:
                            neighbour = tilemap.tiles[ny][nx]
                            if neighbour in (TILE_WATER, TILE_DEEP_WATER):
                                tilemap.tiles[ty][tx] = TILE_SAND if tid != TILE_SNOW else TILE_RIVER_BANK
                                break
                    else:
                        continue
                    break
