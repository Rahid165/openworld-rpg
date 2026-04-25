"""
Game Components — attached to Entities to give them behaviour.
"""

from __future__ import annotations
import os
import math
import random
import pygame
from typing import Optional, List, Dict, Tuple

from ecs import Component
from constants import *
from items import ITEMS


# ─────────────────────────────────────────────────────────────────────────────
# Transform
# ─────────────────────────────────────────────────────────────────────────────

class Transform(Component):
    def __init__(self, x: float, y: float):
        super().__init__()
        self.x = float(x)
        self.y = float(y)

    @property
    def pos(self) -> pygame.Vector2:
        return pygame.Vector2(self.x, self.y)

    @pos.setter
    def pos(self, v: pygame.Vector2):
        self.x, self.y = v.x, v.y

    def tile_x(self) -> int:
        return int(self.x // TILE_SIZE)

    def tile_y(self) -> int:
        return int(self.y // TILE_SIZE)


# ─────────────────────────────────────────────────────────────────────────────
# Velocity / Physics
# ─────────────────────────────────────────────────────────────────────────────

class Velocity(Component):
    def __init__(self, dx: float = 0, dy: float = 0):
        super().__init__()
        self.dx = dx
        self.dy = dy


# ─────────────────────────────────────────────────────────────────────────────
# Collider
# ─────────────────────────────────────────────────────────────────────────────

class Collider(Component):
    def __init__(self, width: int, height: int, offset_x: int = 0, offset_y: int = 0):
        super().__init__()
        self.width  = width
        self.height = height
        self.offset_x = offset_x
        self.offset_y = offset_y

    def get_rect(self) -> pygame.Rect:
        t = self.entity.get(Transform)
        if not t:
            return pygame.Rect(0, 0, self.width, self.height)
        return pygame.Rect(
            int(t.x) + self.offset_x,
            int(t.y) + self.offset_y,
            self.width,
            self.height
        )


# ─────────────────────────────────────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────────────────────────────────────

class Health(Component):
    def __init__(self, max_hp: int):
        super().__init__()
        self.max_hp = max_hp
        self.hp     = float(max_hp)
        self._regen_rate  = 0.0
        self._hurt_timer  = 0.0

    def damage(self, amount: float):
        self.hp = max(0.0, self.hp - amount)
        self._hurt_timer = 0.4
        if self.hp == 0:
            self.entity.destroy()

    def heal(self, amount: float):
        self.hp = min(self.max_hp, self.hp + amount)

    def is_dead(self) -> bool:
        return self.hp <= 0

    def update(self, dt: float):
        if self._hurt_timer > 0:
            self._hurt_timer -= dt
        if self._regen_rate > 0:
            self.heal(self._regen_rate * dt)


# ─────────────────────────────────────────────────────────────────────────────
# Hunger / Stamina (Player-specific stats)
# ─────────────────────────────────────────────────────────────────────────────

class PlayerStats(Component):
    def __init__(self):
        super().__init__()
        self.hunger   = float(PLAYER_MAX_HUNGER)
        self.stamina  = float(PLAYER_MAX_STAMINA)
        self._stamina_regen_timer = 0.0
        self._sprint = False

    def is_sprinting(self) -> bool:
        return self._sprint and self.stamina > 0

    def set_sprint(self, val: bool):
        self._sprint = val

    def update(self, dt: float):
        # Hunger drains over time
        self.hunger = max(0, self.hunger - HUNGER_DRAIN_RATE * dt)
        if self.hunger == 0:
            h = self.entity.get(Health)
            if h:
                h.damage(2 * dt)

        # Stamina
        if self.is_sprinting():
            self.stamina = max(0, self.stamina - STAMINA_SPRINT_COST * dt)
            self._stamina_regen_timer = STAMINA_REGEN_DELAY
        else:
            if self._stamina_regen_timer > 0:
                self._stamina_regen_timer -= dt
            else:
                self.stamina = min(PLAYER_MAX_STAMINA, self.stamina + STAMINA_REGEN * dt)

    def eat(self, food_restore: float):
        self.hunger = min(PLAYER_MAX_HUNGER, self.hunger + food_restore)


# ─────────────────────────────────────────────────────────────────────────────
# Inventory
# ─────────────────────────────────────────────────────────────────────────────

class ItemStack:
    def __init__(self, item_id: str, qty: int = 1, durability: Optional[int] = None):
        self.item_id = item_id
        self.qty = qty
        data = ITEMS.get(item_id, {})
        if durability is not None:
            self.durability = durability
        elif "durability" in data:
            self.durability = data["durability"]
        else:
            self.durability = None

    @property
    def data(self) -> dict:
        return ITEMS.get(self.item_id, {})

    @property
    def name(self) -> str:
        return self.data.get("name", self.item_id)

    @property
    def max_stack(self) -> int:
        return self.data.get("stack", MAX_STACK)

    def copy(self) -> "ItemStack":
        return ItemStack(self.item_id, self.qty, self.durability)

    def __repr__(self):
        return f"ItemStack({self.item_id} x{self.qty})"


class Inventory(Component):
    def __init__(self, rows: int = INVENTORY_ROWS, cols: int = INVENTORY_COLS):
        super().__init__()
        self.rows = rows
        self.cols = cols
        self.slots: List[Optional[ItemStack]] = [None] * (rows * cols)
        self.hotbar: List[Optional[ItemStack]] = [None] * HOTBAR_SLOTS
        self.selected_hotbar: int = 0

    def _all_slots(self):
        """Yields (list_ref, index) for hotbar then main."""
        for i in range(HOTBAR_SLOTS):
            yield self.hotbar, i
        for i in range(len(self.slots)):
            yield self.slots, i

    def add_item(self, item_id: str, qty: int = 1, durability=None) -> int:
        """Returns leftover qty that couldn't be added."""
        data = ITEMS.get(item_id, {})
        max_s = data.get("stack", MAX_STACK)

        # Stack onto existing
        for lst, i in self._all_slots():
            if lst[i] and lst[i].item_id == item_id and lst[i].qty < max_s:
                can_add = min(qty, max_s - lst[i].qty)
                lst[i].qty += can_add
                qty -= can_add
                if qty == 0:
                    return 0

        # Find empty slot
        for lst, i in self._all_slots():
            if lst[i] is None:
                take = min(qty, max_s)
                lst[i] = ItemStack(item_id, take, durability)
                qty -= take
                if qty == 0:
                    return 0

        return qty  # leftover

    def remove_item(self, item_id: str, qty: int = 1) -> bool:
        """Remove qty of item_id. Returns True if successful."""
        available = self.count_item(item_id)
        if available < qty:
            return False
        remaining = qty
        for lst, i in self._all_slots():
            if lst[i] and lst[i].item_id == item_id:
                take = min(remaining, lst[i].qty)
                lst[i].qty -= take
                remaining -= take
                if lst[i].qty == 0:
                    lst[i] = None
                if remaining == 0:
                    return True
        return False

    def count_item(self, item_id: str) -> int:
        total = 0
        for lst, i in self._all_slots():
            if lst[i] and lst[i].item_id == item_id:
                total += lst[i].qty
        return total

    def has_items(self, requirements: Dict[str, int]) -> bool:
        return all(self.count_item(iid) >= qty for iid, qty in requirements.items())

    def get_selected(self) -> Optional[ItemStack]:
        return self.hotbar[self.selected_hotbar]

    def use_durability(self, amount: int = 1):
        sel = self.get_selected()
        if sel and sel.durability is not None:
            sel.durability -= amount
            if sel.durability <= 0:
                self.hotbar[self.selected_hotbar] = None

    def swap_slots(self, lst_a, i_a, lst_b, i_b):
        lst_a[i_a], lst_b[i_b] = lst_b[i_b], lst_a[i_a]


# ─────────────────────────────────────────────────────────────────────────────
# Renderer
# ─────────────────────────────────────────────────────────────────────────────

class SpriteRenderer(Component):
    def __init__(self, color: Tuple[int,int,int], w: int, h: int,
                 shape: str = "rect", layer: int = LAYER_CHARACTERS,
                 sprite_path: Optional[str] = None):
        super().__init__()
        self.color  = color
        self.width  = w
        self.height = h
        self.shape  = shape   # "rect", "circle", "diamond"
        self.layer  = layer
        self.sprite_path = sprite_path
        self.visible = True
        self.alpha   = 255
        self._hurt_flash = 0.0
        self._sprite_cache = None
        self._sprite_checked = False
        self._scaled_cache: Dict[Tuple[int, int], pygame.Surface] = {}

    def flash_hurt(self):
        self._hurt_flash = 0.25

    def update(self, dt: float):
        if self._hurt_flash > 0:
            self._hurt_flash -= dt

    def copy_scaled(self, width: int, height: int) -> "SpriteRenderer":
        scaled = SpriteRenderer(
            self.color,
            width,
            height,
            self.shape,
            self.layer,
            self.sprite_path,
        )
        scaled.visible = self.visible
        scaled.alpha = self.alpha
        scaled._hurt_flash = self._hurt_flash
        scaled._sprite_cache = self._sprite_cache
        scaled._sprite_checked = self._sprite_checked
        scaled._scaled_cache = self._scaled_cache
        return scaled

    def _load_sprite(self) -> Optional[pygame.Surface]:
        if not self.sprite_path:
            return None
        if self._sprite_checked:
            return self._sprite_cache
        self._sprite_checked = True
        if not os.path.exists(self.sprite_path):
            self._sprite_cache = None
            return None
        try:
            self._sprite_cache = pygame.image.load(self.sprite_path).convert_alpha()
        except pygame.error:
            self._sprite_cache = None
        return self._sprite_cache

    def draw(self, surface: pygame.Surface, x: int, y: int):
        if not self.visible:
            return
        color = (220, 60, 60) if self._hurt_flash > 0 else self.color
        rect = pygame.Rect(x, y, self.width, self.height)
        sprite = self._load_sprite()
        if sprite is not None:
            key = (self.width, self.height)
            scaled = self._scaled_cache.get(key)
            if scaled is None:
                scaled = pygame.transform.smoothscale(sprite, key)
                self._scaled_cache[key] = scaled
            if self._hurt_flash > 0:
                scaled = scaled.copy()
                overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
                overlay.fill((255, 70, 70, 80))
                scaled.blit(overlay, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)
            surface.blit(scaled, rect.topleft)
            return
        if self.shape == "circle":
            cx, cy = x + self.width//2, y + self.height//2
            r = min(self.width, self.height)//2
            pygame.draw.circle(surface, color, (cx, cy), r)
        elif self.shape == "diamond":
            cx, cy = x + self.width//2, y + self.height//2
            pts = [(cx, y), (x + self.width, cy), (cx, y + self.height), (x, cy)]
            pygame.draw.polygon(surface, color, pts)
        else:
            pygame.draw.rect(surface, color, rect)


# ─────────────────────────────────────────────────────────────────────────────
# NPC AI States
# ─────────────────────────────────────────────────────────────────────────────

class AIController(Component):
    """Simple state-machine AI for NPCs."""

    STATE_IDLE    = "idle"
    STATE_WANDER  = "wander"
    STATE_FLEE    = "flee"
    STATE_CHASE   = "chase"
    STATE_ATTACK  = "attack"

    def __init__(self, ai_type: str = "passive",
                 detect_range: float = 200, attack_range: float = 60):
        super().__init__()
        self.ai_type      = ai_type   # "passive", "neutral", "hostile"
        self.detect_range = detect_range
        self.attack_range = attack_range
        self.state        = self.STATE_IDLE
        self.state_timer  = 0.0
        self.wander_dir   = pygame.Vector2(0, 0)
        self.target       = None   # Entity ref
        self._attack_cooldown = 0.0
        self.home_pos     = None   # set after spawn
        self.path: List[Tuple[int, int]] = []
        self.path_recalc_timer = 0.0
        self.path_index = 0
        self.role = ai_type
        self.village_id = None
        self.display_name = ai_type
        self.stock: Dict[str, int] = {}
        self.trade_offer = ""
        self.activity_timer = 0.0
        self.trade_timer = 0.0
        self.home_radius = TILE_SIZE * 8
        self.sleep_path: List[pygame.Vector2] = []
        self.sleep_path_index = 0
        self.home_bounds = None
        self.sleeping = False
        self.farm_plots = []
        self.work_points: List[pygame.Vector2] = []
        self.work_index = 0
        self.storage_chest = None
        self.max_hunger = 0.0
        self.hunger = 0.0
        self.hunger_drain = 0.0
        self.trade_partner = None
        self.trade_task = None
        self.village_bounds = None
        self.work_pause_range = (0.4, 1.0)
        self.idle_route = []
        self.route_pause_timer = 0.0
        self.last_pos = pygame.Vector2()
        self.stuck_timer = 0.0

    def update(self, dt: float):
        self.state_timer -= dt
        if self._attack_cooldown > 0:
            self._attack_cooldown -= dt
        if self.path_recalc_timer > 0:
            self.path_recalc_timer -= dt
        if self.hunger_drain > 0 and self.max_hunger > 0:
            self.hunger = max(0.0, self.hunger - self.hunger_drain * dt)
            if self.hunger == 0:
                health = self.entity.get(Health)
                if health:
                    health.damage(1.5 * dt)
        if self.route_pause_timer > 0:
            self.route_pause_timer -= dt
        if self.stuck_timer > 0:
            self.stuck_timer = max(0.0, self.stuck_timer - dt * 0.25)

        # State machine handled by NPCSystem (needs world reference)
        # Just tick timers here

    def hunger_ratio(self) -> float:
        if self.max_hunger <= 0:
            return 1.0
        return max(0.0, min(1.0, self.hunger / self.max_hunger))

    def eat(self, food_restore: float):
        if self.max_hunger <= 0:
            return
        self.hunger = min(self.max_hunger, self.hunger + food_restore)


# ─────────────────────────────────────────────────────────────────────────────
# Interactable
# ─────────────────────────────────────────────────────────────────────────────

class Interactable(Component):
    def __init__(self, label: str = "Interact", hold_time: float = 0.0):
        super().__init__()
        self.label     = label
        self.hold_time = hold_time    # 0 = instant, >0 = hold duration
        self.base_hold_time = hold_time
        self._progress = 0.0
        self.is_holding = False
        self.on_interact = None  # callable(player_entity)

    def start_hold(self):
        self.is_holding = True

    def stop_hold(self):
        self.is_holding = False
        self._progress = 0.0

    def update(self, dt: float):
        if self.is_holding and self.hold_time > 0:
            self._progress += dt
        elif not self.is_holding:
            self._progress = max(0, self._progress - dt * 2)

    @property
    def progress(self) -> float:
        if self.hold_time == 0:
            return 1.0
        return min(1.0, self._progress / self.hold_time)

    def is_complete(self) -> bool:
        return self.progress >= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Harvestable Plant
# ─────────────────────────────────────────────────────────────────────────────

class PlantComponent(Component):
    def __init__(self, plant_type: str, growth_stage: int = GROWTH_FULL,
                 valid_tiles: Optional[List[int]] = None):
        super().__init__()
        self.plant_type  = plant_type
        self.growth_stage = growth_stage
        self.valid_tiles  = valid_tiles or [TILE_GRASS]
        self._growth_timer = 0.0
        self.harvested    = False   # True if recently harvested, regrows
        self._regrow_timer = 0.0
        self.loot_table   = plant_type  # key into LOOT_TABLES

    def update(self, dt: float):
        if self.harvested:
            self._regrow_timer -= dt
            if self._regrow_timer <= 0:
                self.harvested = False
                self.growth_stage = GROWTH_SEED
        elif self.growth_stage < GROWTH_FULL:
            self._growth_timer += dt
            target = GROWTH_TIMES.get(self.growth_stage, 999)
            if self._growth_timer >= target:
                self._growth_timer = 0
                self.growth_stage = min(GROWTH_FULL, self.growth_stage + 1)

    def harvest(self) -> bool:
        """Mark as harvested. Returns True if harvestable."""
        if self.harvested or self.growth_stage < GROWTH_MATURE:
            return False
        self.harvested = True
        self._regrow_timer = GROWTH_TIMES[GROWTH_YOUNG]   # time to start regrowing
        return True

    def size_scale(self) -> float:
        scales = {0: 0.25, 1: 0.40, 2: 0.60, 3: 0.80, 4: 1.0}
        return scales.get(self.growth_stage, 1.0)


# ─────────────────────────────────────────────────────────────────────────────
# Dropped Item
# ─────────────────────────────────────────────────────────────────────────────

class DroppedItem(Component):
    def __init__(self, item_id: str, qty: int = 1):
        super().__init__()
        self.item_id = item_id
        self.qty     = qty
        self._bob_timer = random.uniform(0, math.pi * 2)
        self._bob_y     = 0.0
        self._despawn_timer = DROP_DESPAWN_TIME

    def update(self, dt: float):
        self._bob_timer += dt * 2.5
        self._bob_y = math.sin(self._bob_timer) * 4
        self._despawn_timer -= dt
        if self._despawn_timer <= 0:
            self.entity.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# Chest / Container
# ─────────────────────────────────────────────────────────────────────────────

class Container(Component):
    def __init__(self, loot_table: str = "chest_common", max_slots: int = 20):
        super().__init__()
        self.loot_table = loot_table
        self.inventory: List[Optional[ItemStack]] = [None] * max_slots
        self.opened = False
        self._generated = False

    def generate_loot(self, loot_tables: dict):
        if self._generated:
            return
        self._generated = True
        table = loot_tables.get(self.loot_table, [])
        slot = 0
        for item_id, min_q, max_q, chance in table:
            if random.random() <= chance and slot < len(self.inventory):
                qty = random.randint(min_q, max_q)
                self.inventory[slot] = ItemStack(item_id, qty)
                slot += 1


class StructureComponent(Component):
    def __init__(self, structure_type: str, solid: bool = True,
                 openable: bool = False, station: Optional[str] = None):
        super().__init__()
        self.structure_type = structure_type
        self.solid = solid
        self.openable = openable
        self.station = station
        self.is_open = False

    def toggle(self):
        if self.openable:
            self.is_open = not self.is_open

    def blocks_movement(self) -> bool:
        if self.openable and self.is_open:
            return False
        return self.solid
