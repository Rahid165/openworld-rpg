import math
import os
import random
from collections import deque

import pygame

from components import (
    AIController,
    Collider,
    Container,
    DroppedItem,
    Health,
    Interactable,
    Inventory,
    ItemStack,
    PlantComponent,
    PlayerStats,
    SpriteRenderer,
    StructureComponent,
    Transform,
)
from constants import *
from ecs import Entity, EntityManager
from items import ITEMS, LOOT_TABLES, RECIPES
from tilemap import MapGenerator


class Game:
    def __init__(self, screen, clock):
        self.screen = screen
        self.clock = clock
        self.running = True
        self.font = pygame.font.SysFont("consolas", 18)
        self.small_font = pygame.font.SysFont("consolas", 14)
        self.big_font = pygame.font.SysFont("consolas", 28, bold=True)
        self.asset_cache = {}
        self.sprite_path_cache = {}
        self.last_seed = random.randint(1000, 999999)
        self.npc_profiles = self._build_npc_profiles()
        self.game_mode = "main_menu"
        self.menu_seed_text = str(self.last_seed)
        self.menu_buttons = {}
        self._reset_game_world(self.last_seed)

    def _reset_game_world(self, seed=None):
        if seed is not None:
            self.last_seed = seed
        self.show_inventory = False
        self.show_crafting = False
        self.message = "WASD move  SHIFT sprint  SPACE attack  E interact  Right click place"
        self.message_timer = 8.0
        self.harvest_target = None
        self.harvest_hint = ""
        self.camera_x = 0.0
        self.camera_y = 0.0
        self.mouse_slot_refs = []
        self.recipe_click_refs = []
        self.cursor_stack = None
        self.recipe_order = list(RECIPES.keys())
        self.selected_recipe_index = 0
        self.craft_search_text = ""
        self.craft_search_active = False
        self.craft_search_rect = None
        self.pending_attack = False
        self.attack_cooldown = 0.0
        self.craft_output_rect = None
        self.inventory_panel_rect = None
        self.hover_stack = None
        self.open_container_entity = None
        self.container_panel_rect = None
        self.selected_item_label = ""
        self.selected_item_label_timer = 0.0
        self.time_of_day = 0.30
        self.day_cycle_speed = 1 / 240.0
        self.zombie_spawn_timer = 4.0
        self.instant_interact_cooldown = 0.0
        self.trade_interact_cooldown = 0.0
        self.trade_popups = []
        self.recipe_scroll_offset = 0
        self.villages = []
        self._frame_cache_token = 0
        self._cached_all_entities = []
        self._cached_npcs = []
        self._cached_combatants = []
        self._cached_combatants_by_tag = {}
        self._cached_structure_entities = []
        self._cached_openable_doors = []
        self._cached_drops = []
        self._cached_interactables = []
        self._cached_colliders = []
        self._cached_solid_structure_colliders = []
        self._cached_solid_structure_rects = []
        self._cached_blocked_tiles = set()
        self._cached_structure_positions = set()
        self._structure_cache_dirty = True

        self.tilemap = self._create_world()
        self.world = EntityManager()
        self.player = self._create_player()
        self.world.add(self.player)
        self._spawn_world_nodes()
        self._spawn_villages()
        self._spawn_npcs()
        self._update_camera(force_center=True)
        self._refresh_frame_caches()

    def _create_world(self):
        return MapGenerator(self.last_seed).generate(MAP_WIDTH, MAP_HEIGHT)

    def _player_is_dead(self):
        health = getattr(self, "player", None).get(Health) if hasattr(self, "player") else None
        return bool(health and health.hp <= 0)

    def _start_or_restart_game(self, seed=None):
        if seed is None:
            seed = self.last_seed
        self.menu_seed_text = str(seed)
        self._reset_game_world(seed)
        self.game_mode = "playing"

    def _return_to_main_menu(self):
        self.pending_attack = False
        self.show_inventory = False
        self.show_crafting = False
        self._close_open_container()
        self.game_mode = "main_menu"
        self.message_timer = 0.0

    def _toggle_pause(self):
        if self.game_mode == "playing":
            self.pending_attack = False
            self.game_mode = "paused"
            self._close_inventory_views()
        elif self.game_mode == "paused":
            self.game_mode = "playing"

    def _menu_seed_value(self):
        text = self.menu_seed_text.strip()
        if not text:
            return random.randint(1000, 999999)
        return max(0, min(999999999, int(text)))

    def _set_dead_state(self):
        self.pending_attack = False
        self._close_inventory_views()
        self.game_mode = "dead"

    def _build_npc_profiles(self):
        return {
            "passive": {
                "color": COL_NPC_PASSIVE,
                "shape": "circle",
                "health": 40,
                "detect_range": 180,
                "attack_range": 34,
                "label": "Passive Creature",
            },
            "neutral": {
                "color": COL_NPC_NEUTRAL,
                "shape": "diamond",
                "health": 55,
                "detect_range": 220,
                "attack_range": 34,
                "label": "Neutral Creature",
            },
            "hostile": {
                "color": COL_NPC_HOSTILE,
                "shape": "diamond",
                "health": 70,
                "detect_range": 280,
                "attack_range": 42,
                "label": "Hostile Creature",
            },
            "villager_farmer": {
                "color": (192, 164, 92),
                "shape": "rect",
                "health": 72,
                "detect_range": 160,
                "attack_range": 26,
                "label": "Farmer",
                "role": "farmer",
                "stock": {"berry_seed": 4, "wheat_seed": 6, "hoe_wood": 1, "wood": 2},
                "trade_offer": "2 wood -> 4 berries / 1 stone -> mixed village seeds",
            },
            "villager_crafter": {
                "color": (110, 145, 185),
                "shape": "rect",
                "health": 74,
                "detect_range": 160,
                "attack_range": 26,
                "label": "Crafter",
                "role": "crafter",
                "stock": {"bread": 1, "wood": 4, "stone": 4, "fiber": 3, "hoe_wood": 1},
                "trade_offer": "3 wheat -> 1 bread / 3 wood + 2 fiber -> 1 hoe",
            },
            "police": {
                "color": (60, 105, 170),
                "shape": "rect",
                "health": 120,
                "detect_range": 300,
                "attack_range": 54,
                "label": "Village Guard",
                "role": "guard",
                "stock": {"sword_wood": 1},
                "trade_offer": "Protection and patrols",
            },
            "zombie": {
                "color": (84, 146, 88),
                "shape": "rect",
                "health": 85,
                "detect_range": 320,
                "attack_range": 42,
                "label": "Zombie",
                "role": "zombie",
                "stock": {},
                "trade_offer": "",
            },
        }

    def _sprite_path(self, *parts):
        key = tuple(parts)
        if key in self.sprite_path_cache:
            return self.sprite_path_cache[key]
        direct = os.path.join(SPRITE_DIR, *parts)
        if os.path.exists(direct):
            resolved = direct
        elif parts:
            flat = os.path.join(SPRITE_DIR, "_".join(parts))
            if os.path.exists(flat):
                resolved = flat
            elif parts and os.path.splitext(parts[-1])[1]:
                resolved = direct
            else:
                resolved = direct + ".png"
        else:
            resolved = direct
        self.sprite_path_cache[key] = resolved
        return resolved

    def _load_image(self, path, size):
        key = (path, size)
        if key in self.asset_cache:
            return self.asset_cache[key]
        if not path or not os.path.exists(path):
            self.asset_cache[key] = None
            return None
        try:
            image = pygame.image.load(path).convert_alpha()
            image = pygame.transform.smoothscale(image, size)
        except pygame.error:
            image = None
        self.asset_cache[key] = image
        return image

    def _refresh_frame_caches(self):
        self._frame_cache_token += 1
        all_entities = self.world.all()
        self._cached_all_entities = all_entities
        self._cached_npcs = []
        self._cached_combatants = []
        self._cached_combatants_by_tag = {}
        structure_entities = []
        openable_doors = []
        drops = []
        interactables = []
        colliders = []

        for entity in all_entities:
            ai = entity.get(AIController)
            if ai:
                self._cached_npcs.append(entity)
                self._cached_combatants.append(entity)
                for tag in entity.tags:
                    self._cached_combatants_by_tag.setdefault(tag, []).append(entity)
            structure = entity.get(StructureComponent)
            if structure:
                structure_entities.append(entity)
                if structure.openable:
                    openable_doors.append(entity)
            if entity.get(DroppedItem):
                drops.append(entity)
            if entity.get(Interactable):
                interactables.append(entity)
            if entity.get(Collider):
                colliders.append(entity)

        if self.player.alive:
            self._cached_combatants.append(self.player)
            for tag in self.player.tags:
                self._cached_combatants_by_tag.setdefault(tag, []).append(self.player)
        if len(structure_entities) != len(self._cached_structure_entities):
            self._structure_cache_dirty = True
        self._cached_structure_entities = structure_entities
        self._cached_openable_doors = openable_doors
        self._cached_drops = drops
        self._cached_interactables = interactables
        self._cached_colliders = colliders
        if self._structure_cache_dirty:
            self._rebuild_structure_collision_cache()

    def _rebuild_structure_collision_cache(self):
        self._cached_solid_structure_colliders = []
        self._cached_solid_structure_rects = []
        self._cached_blocked_tiles = set()
        self._cached_structure_positions = set()
        for entity in self._cached_structure_entities:
            if not entity.alive:
                continue
            structure = entity.get(StructureComponent)
            transform = entity.get(Transform)
            collider = entity.get(Collider)
            if structure and transform:
                self._cached_structure_positions.add((int(transform.x), int(transform.y)))
            if structure and collider and structure.blocks_movement():
                rect = collider.get_rect()
                self._cached_solid_structure_colliders.append(collider)
                self._cached_solid_structure_rects.append(rect)
                left = rect.left // TILE_SIZE
                right = (rect.right - 1) // TILE_SIZE
                top = rect.top // TILE_SIZE
                bottom = (rect.bottom - 1) // TILE_SIZE
                for ty in range(top, bottom + 1):
                    for tx in range(left, right + 1):
                        self._cached_blocked_tiles.add((tx, ty))
        self._structure_cache_dirty = False

    def _current_npcs(self):
        return self._cached_npcs

    def _current_combatants(self):
        return self._cached_combatants

    def _solid_structure_colliders(self):
        return self._cached_solid_structure_colliders

    def _solid_structure_rects(self):
        return self._cached_solid_structure_rects

    def _find_spawn(self):
        center_x = self.tilemap.width // 2
        center_y = self.tilemap.height // 2
        best = (center_x, center_y)
        best_dist = float("inf")
        for ty in range(self.tilemap.height):
            for tx in range(self.tilemap.width):
                if self.tilemap.get(tx, ty) in SOLID_TILES:
                    continue
                score = abs(tx - center_x) + abs(ty - center_y)
                if score < best_dist:
                    best = (tx, ty)
                    best_dist = score
        return best[0] * TILE_SIZE, best[1] * TILE_SIZE

    def _create_player(self):
        px, py = self._find_spawn()
        player = Entity("Player")
        player.tags.update({"player", "combatant"})
        player.add(Transform(px, py))
        player.add(Collider(34, 26, 15, PLAYER_FOOTPRINT - 30))
        player.add(SpriteRenderer(
            COL_PLAYER,
            PLAYER_WIDTH,
            PLAYER_HEIGHT,
            "rect",
            LAYER_CHARACTERS,
            sprite_path=self._sprite_path("entities", "player.png"),
        ))
        player.add(Health(PLAYER_MAX_HP))
        player.add(PlayerStats())
        inventory = Inventory()
        inventory.add_item("wood", 10)
        inventory.add_item("berry", 5)
        inventory.add_item("stone", 6)
        inventory.add_item("fiber", 6)
        inventory.add_item("axe_wood", 1)
        inventory.add_item("pickaxe_wood", 1)
        inventory.add_item("hoe_wood", 1)
        inventory.add_item("sword_wood", 1)
        player.add(inventory)
        self._show_selected_item_name(inventory.get_selected())
        return player

    def _spawn_world_nodes(self):
        counts = {
            "berry_bush": 28,
            "mushroom_cluster": 16,
            "flower_patch": 18,
            "reed_patch": 12,
            "tree": 34,
            "stone_outcrop": 18,
            "coal_vein": ORE_COAL_COUNT,
            "iron_vein": ORE_IRON_COUNT,
        }
        valid_tiles = {
            "berry_bush": {TILE_GRASS, TILE_DIRT},
            "mushroom_cluster": {TILE_GRASS, TILE_MUD, TILE_DIRT},
            "flower_patch": {TILE_GRASS, TILE_DIRT},
            "reed_patch": {TILE_SAND, TILE_RIVER_BANK, TILE_MUD},
            "tree": {TILE_GRASS, TILE_DIRT},
            "stone_outcrop": {TILE_STONE, TILE_DIRT, TILE_GRASS},
            "coal_vein": {TILE_STONE, TILE_DIRT},
            "iron_vein": {TILE_STONE},
        }
        sizes = {
            "tree": TREE_WIDTH,
            "stone_outcrop": 52,
            "coal_vein": 50,
            "iron_vein": 50,
        }

        for node_type, amount in counts.items():
            for _ in range(amount):
                size = sizes.get(node_type, 36)
                pos = self._random_open_position(valid_tiles[node_type], size, TILE_SIZE * 3)
                if pos:
                    self.world.add(self._create_resource_node(node_type, *pos))

        self._spawn_ruins()

    def _spawn_ruins(self):
        for _ in range(3):
            origin = self._random_open_position({TILE_GRASS, TILE_DIRT, TILE_STONE}, TILE_SIZE * 2, TILE_SIZE * 4)
            if not origin:
                continue
            ox, oy = origin
            for dy in range(2):
                for dx in range(3):
                    if dy in (0, 1) and dx in (0, 2):
                        self.world.add(self._create_structure("wall_stone", ox + dx * TILE_SIZE, oy + dy * TILE_SIZE))
            self.world.add(self._create_structure("door_wood", ox + TILE_SIZE, oy + TILE_SIZE))
            self._spawn_drop("coal", random.randint(1, 3), ox + TILE_SIZE, oy)

    def _area_is_buildable(self, tile_x, tile_y, width_tiles, height_tiles, allowed_tiles, minimum_player_distance=0):
        if tile_x < 1 or tile_y < 1:
            return False
        if tile_x + width_tiles >= self.tilemap.width - 1 or tile_y + height_tiles >= self.tilemap.height - 1:
            return False

        center = pygame.Vector2(
            (tile_x + width_tiles * 0.5) * TILE_SIZE,
            (tile_y + height_tiles * 0.5) * TILE_SIZE,
        )
        player_transform = self.player.get(Transform) if hasattr(self, "player") else None
        if player_transform and center.distance_to(pygame.Vector2(player_transform.x, player_transform.y)) < minimum_player_distance:
            return False

        for village in self.villages:
            if center.distance_to(village["center"]) < TILE_SIZE * 14:
                return False

        for ty in range(tile_y, tile_y + height_tiles):
            for tx in range(tile_x, tile_x + width_tiles):
                if self.tilemap.get(tx, ty) not in allowed_tiles:
                    return False
        return True

    def _clear_area_for_village(self, tile_x, tile_y, width_tiles, height_tiles):
        area_rect = pygame.Rect(tile_x * TILE_SIZE, tile_y * TILE_SIZE, width_tiles * TILE_SIZE, height_tiles * TILE_SIZE)
        for entity in self.world.all():
            if entity is self.player:
                continue
            collider = entity.get(Collider)
            transform = entity.get(Transform)
            if collider:
                overlaps = collider.get_rect().colliderect(area_rect)
            elif transform:
                overlaps = area_rect.collidepoint(int(transform.x), int(transform.y))
            else:
                overlaps = False
            if overlaps:
                entity.destroy()

    def _choose_village_plot_plans(self, total_plots):
        templates = {
            "wheat": {"seed_item": "wheat_seed", "plant_type": "wheat_crop", "produce_item": "wheat", "name": "Wheat"},
            "berry": {"seed_item": "berry_seed", "plant_type": "berry_bush", "produce_item": "berry", "name": "Berries"},
        }
        wheat_count = random.randint(max(4, total_plots // 3), max(5, (total_plots * 2) // 3))
        berry_count = max(0, total_plots - wheat_count)
        plans = [dict(templates["wheat"]) for _ in range(wheat_count)]
        plans.extend(dict(templates["berry"]) for _ in range(berry_count))
        random.shuffle(plans)
        return plans

    def _build_village_farmland(self, base_x, base_y, plot_plans):
        farm_plots = []
        plot_offsets = []
        for start_x, start_y, width, height in ((0, 5, 4, 4), (12, 5, 4, 4)):
            for row in range(height):
                for col in range(width):
                    plot_offsets.append((start_x + col, start_y + row))
        for index, (offset_x, offset_y) in enumerate(plot_offsets):
            plot_x = base_x + offset_x * TILE_SIZE
            plot_y = base_y + offset_y * TILE_SIZE
            plot_plan = dict(plot_plans[index % len(plot_plans)])
            soil = self._create_structure("farmland", plot_x, plot_y)
            self.world.add(soil)
            crop = self._create_resource_node(plot_plan["plant_type"], plot_x, plot_y)
            crop_plant = crop.get(PlantComponent)
            crop_plant.growth_stage = random.randint(GROWTH_SEED, GROWTH_MATURE)
            self.world.add(crop)
            farm_plots.append({
                "soil": soil,
                "crop": crop,
                "plot_pos": pygame.Vector2(plot_x, plot_y),
                "work_pos": pygame.Vector2(plot_x, plot_y + 10),
                "seed_item": plot_plan["seed_item"],
                "plant_type": plot_plan["plant_type"],
                "produce_item": plot_plan["produce_item"],
                "crop_name": plot_plan["name"],
            })
        return farm_plots

    def _build_village_storage(self, base_x, base_y):
        chest_x = base_x + TILE_SIZE * 7
        chest_y = base_y + TILE_SIZE * 6
        chest = self._create_structure("chest_wood", chest_x, chest_y)
        self.world.add(chest)
        return chest

    def _prime_village_storage(self, village):
        chest = village.get("storage_chest")
        if not chest or not chest.alive:
            return
        container = chest.get(Container)
        if not container:
            return
        wheat_plots = sum(1 for plot in village["farm_plots"] if plot["seed_item"] == "wheat_seed")
        berry_plots = sum(1 for plot in village["farm_plots"] if plot["seed_item"] == "berry_seed")
        for item_id, qty in (
            ("wheat_seed", max(4, wheat_plots + 2)),
            ("berry_seed", max(3, berry_plots + 1)),
            ("wheat", 4),
            ("berry", 4),
            ("bread", 2),
        ):
            self._add_to_container(container, item_id, qty)

    def _spawn_villages(self):
        village_width = 16
        village_height = 15
        village_id = 0
        attempts = 0
        while village_id < 2 and attempts < 1000:
            attempts += 1
            tile_x = random.randint(1, self.tilemap.width - village_width - 2)
            tile_y = random.randint(1, self.tilemap.height - village_height - 2)
            if not self._area_is_buildable(tile_x, tile_y, village_width, village_height, {TILE_GRASS, TILE_DIRT, TILE_SAND, TILE_MUD, TILE_RIVER_BANK}, TILE_SIZE * 12):
                continue
            self._clear_area_for_village(tile_x, tile_y, village_width, village_height)
            center_x = tile_x * TILE_SIZE
            center_y = tile_y * TILE_SIZE
            total_plots = 32
            plot_plans = self._choose_village_plot_plans(total_plots)
            village_bounds = pygame.Rect(center_x, center_y, village_width * TILE_SIZE, village_height * TILE_SIZE)
            village = {
                "id": village_id,
                "center": pygame.Vector2(center_x + TILE_SIZE * 8, center_y + TILE_SIZE * 7),
                "radius": TILE_SIZE * 10,
                "bounds": village_bounds,
                "bed_spots": [],
                "home_slots": [],
                "farm_plots": self._build_village_farmland(center_x, center_y, plot_plans),
                "seed_types": sorted({plot["seed_item"] for plot in plot_plans}),
                "craft_spots": [
                    pygame.Vector2(center_x + TILE_SIZE * 6, center_y + TILE_SIZE * 5),
                    pygame.Vector2(center_x + TILE_SIZE * 9, center_y + TILE_SIZE * 5),
                    pygame.Vector2(center_x + TILE_SIZE * 9, center_y + TILE_SIZE * 8),
                    pygame.Vector2(center_x + TILE_SIZE * 6, center_y + TILE_SIZE * 8),
                ],
                "patrol_points": [
                    pygame.Vector2(center_x + TILE_SIZE * 2, center_y + TILE_SIZE * 7),
                    pygame.Vector2(center_x + TILE_SIZE * 8, center_y + TILE_SIZE * 2),
                    pygame.Vector2(center_x + TILE_SIZE * 13, center_y + TILE_SIZE * 7),
                    pygame.Vector2(center_x + TILE_SIZE * 8, center_y + TILE_SIZE * 12),
                ],
            }
            self.villages.append(village)
            village["storage_chest"] = self._build_village_storage(center_x, center_y)
            self._prime_village_storage(village)

            for house_origin in [
                (center_x + TILE_SIZE, center_y),
                (center_x + TILE_SIZE * 11, center_y),
                (center_x + TILE_SIZE * 6, center_y + TILE_SIZE * 11),
            ]:
                for home_slot in self._build_house(*house_origin):
                    village["bed_spots"].append(home_slot["bed"])
                    village["home_slots"].append(home_slot)

            spawn_plan = [
                ("villager_farmer", (TILE_SIZE * 6, TILE_SIZE * 4)),
                ("villager_farmer", (TILE_SIZE * 9, TILE_SIZE * 4)),
                ("villager_crafter", (TILE_SIZE * 6, TILE_SIZE * 7)),
                ("villager_crafter", (TILE_SIZE * 9, TILE_SIZE * 7)),
                ("police", (TILE_SIZE * 8, TILE_SIZE * 9)),
            ]
            farmer_slot = 0
            crafter_slot = 0
            for idx, (ai_type, offset) in enumerate(spawn_plan):
                home_slot = village["home_slots"][idx % len(village["home_slots"])] if village["home_slots"] else None
                work_points = None
                farm_plots = None
                idle_route = []
                work_pause_range = (0.2, 0.45)
                if ai_type == "villager_farmer":
                    farm_plots = [plot for plot_index, plot in enumerate(village["farm_plots"]) if plot_index % 2 == farmer_slot]
                    idle_route = [
                        pygame.Vector2(center_x + TILE_SIZE * 5, center_y + TILE_SIZE * 6),
                        pygame.Vector2(center_x + TILE_SIZE * 7, center_y + TILE_SIZE * 6),
                        pygame.Vector2(center_x + TILE_SIZE * 9, center_y + TILE_SIZE * 6),
                    ]
                    work_pause_range = (0.1, 0.3)
                    farmer_slot += 1
                elif ai_type == "villager_crafter":
                    work_points = [point for point_index, point in enumerate(village["craft_spots"]) if point_index % 2 == crafter_slot]
                    idle_route = list(village["craft_spots"])
                    work_pause_range = (0.12, 0.28)
                    crafter_slot += 1
                elif ai_type == "police":
                    work_points = list(village["patrol_points"])
                    idle_route = list(village["patrol_points"])
                    work_pause_range = (0.08, 0.2)
                npc = self._create_npc(
                    ai_type,
                    center_x + offset[0],
                    center_y + offset[1],
                    village_id=village_id,
                    home_pos=home_slot["bed"] if home_slot else None,
                    sleep_path=home_slot["path"] if home_slot else None,
                    farm_plots=farm_plots,
                    work_points=work_points,
                    storage_chest=village["storage_chest"],
                    village_bounds=village_bounds,
                    idle_route=idle_route,
                    work_pause_range=work_pause_range,
                    home_bounds=home_slot["house_rect"] if home_slot else None,
                )
                self.world.add(npc)
            village_id += 1

    def _build_house(self, base_x, base_y):
        width = 4
        height = 4
        bed_slots = []
        house_rect = pygame.Rect(base_x, base_y, width * TILE_SIZE, height * TILE_SIZE)
        door_col = width // 2 - 1
        door_x = base_x + door_col * TILE_SIZE
        doorway_outside = pygame.Vector2(door_x, base_y + (height - 1) * TILE_SIZE + 6)
        doorway_inside = pygame.Vector2(door_x, base_y + (height - 2) * TILE_SIZE + 6)
        for row in range(height):
            for col in range(width):
                wx = base_x + col * TILE_SIZE
                wy = base_y + row * TILE_SIZE
                if row == height - 1 and col == door_col:
                    self.world.add(self._create_structure("door_wood", wx, wy))
                elif row in (0, height - 1) or col in (0, width - 1):
                    self.world.add(self._create_structure("wall_wood", wx, wy))
        for col in (1, 2):
            bed_x = base_x + col * TILE_SIZE
            bed_y = base_y + TILE_SIZE
            self.world.add(self._create_structure("bed", bed_x, bed_y))
            bed_point = pygame.Vector2(bed_x, bed_y + 6)
            bed_slots.append({
                "bed": bed_point,
                "path": [doorway_outside, doorway_inside, bed_point],
                "house_rect": house_rect.copy(),
            })
        return bed_slots

    def _spawn_npcs(self):
        self._spawn_npc_group("passive", NPC_PASSIVE_COUNT, {TILE_GRASS, TILE_DIRT, TILE_MUD})
        self._spawn_npc_group("neutral", NPC_NEUTRAL_COUNT, {TILE_GRASS, TILE_DIRT, TILE_STONE})
        self._spawn_npc_group("hostile", max(2, NPC_HOSTILE_COUNT - 2), {TILE_GRASS, TILE_DIRT, TILE_STONE, TILE_MUD})

    def _spawn_npc_group(self, ai_type, count, valid_tiles):
        for _ in range(count):
            pos = self._random_open_position(valid_tiles, 36, TILE_SIZE * 5)
            if pos:
                self.world.add(self._create_npc(ai_type, *pos))

    def _random_open_position(self, allowed_tiles, size, minimum_player_distance):
        player_transform = self.player.get(Transform) if hasattr(self, "player") else None
        world_width = self.tilemap.width * TILE_SIZE
        world_height = self.tilemap.height * TILE_SIZE
        for _ in range(400):
            tx = random.randint(1, self.tilemap.width - 2)
            ty = random.randint(1, self.tilemap.height - 2)
            if self.tilemap.get(tx, ty) not in allowed_tiles:
                continue
            world_x = tx * TILE_SIZE + TILE_SIZE // 2 - size // 2
            world_y = ty * TILE_SIZE + TILE_SIZE - size
            if world_x < 0 or world_y < 0 or world_x + size > world_width or world_y + size > world_height:
                continue
            if player_transform and math.hypot(world_x - player_transform.x, world_y - player_transform.y) < minimum_player_distance:
                continue
            if self._position_occupied(world_x, world_y, size, size):
                continue
            return world_x, world_y
        return None

    def _position_occupied(self, x, y, width, height):
        rect = pygame.Rect(int(x), int(y), width, height)
        collider_entities = self._cached_colliders if self._cached_colliders else self.world.all()
        for entity in collider_entities:
            collider = entity.get(Collider)
            structure = entity.get(StructureComponent)
            if collider and (not structure or structure.blocks_movement()):
                if collider.get_rect().colliderect(rect):
                    return True
        return False

    def _create_resource_node(self, node_type, x, y):
        entity = Entity(node_type)
        entity.tags.update({"resource", node_type})
        entity.add(Transform(x, y))
        sprite_path = self._sprite_path("entities", f"{node_type}.png")

        if node_type == "tree":
            entity.add(Collider(44, 24, 42, TREE_FOOTPRINT - 28))
            entity.add(SpriteRenderer(COL_TREE_LEAVES, TREE_WIDTH, TREE_HEIGHT, "circle", LAYER_PLANTS, sprite_path))
            plant = PlantComponent("tree", GROWTH_FULL, [TILE_GRASS, TILE_DIRT])
            interact = Interactable("Chop tree", 1.0)
        elif node_type == "stone_outcrop":
            entity.add(Collider(44, 30, 6, 22))
            entity.add(SpriteRenderer(COL_STONE, 56, 52, "diamond", LAYER_PLANTS, sprite_path))
            plant = PlantComponent("stone_outcrop", GROWTH_FULL, [TILE_STONE, TILE_DIRT, TILE_GRASS])
            interact = Interactable("Mine stone", 1.0)
        elif node_type == "coal_vein":
            entity.add(Collider(42, 28, 6, 20))
            entity.add(SpriteRenderer((70, 70, 78), 54, 50, "diamond", LAYER_PLANTS, sprite_path))
            plant = PlantComponent("coal_vein", GROWTH_FULL, [TILE_STONE, TILE_DIRT])
            interact = Interactable("Mine coal", 1.15)
        elif node_type == "iron_vein":
            entity.add(Collider(42, 28, 6, 20))
            entity.add(SpriteRenderer((120, 120, 125), 54, 50, "diamond", LAYER_PLANTS, sprite_path))
            plant = PlantComponent("iron_vein", GROWTH_FULL, [TILE_STONE])
            interact = Interactable("Mine iron", 1.25)
        elif node_type == "wheat_crop":
            entity.add(Collider(24, 24, 18, 36))
            entity.add(SpriteRenderer(COL_WHEAT, 30, 46, "rect", LAYER_PLANTS, sprite_path))
            plant = PlantComponent("wheat_crop", GROWTH_FULL, [TILE_GRASS, TILE_DIRT])
            interact = Interactable("Harvest wheat", 0.45)
        elif node_type == "reed_patch":
            entity.add(Collider(28, 28, 4, 6))
            entity.add(SpriteRenderer(COL_REED, 24, 36, "rect", LAYER_PLANTS, sprite_path))
            plant = PlantComponent("reed_patch", GROWTH_FULL, [TILE_SAND, TILE_RIVER_BANK, TILE_MUD])
            interact = Interactable("Cut reeds", 0.65)
        elif node_type == "flower_patch":
            entity.add(Collider(28, 28, 4, 6))
            entity.add(SpriteRenderer(COL_FLOWER, 24, 24, "circle", LAYER_PLANTS, sprite_path))
            plant = PlantComponent("flower_patch", GROWTH_FULL, [TILE_GRASS, TILE_DIRT])
            interact = Interactable("Gather flowers", 0.45)
        elif node_type == "mushroom_cluster":
            entity.add(Collider(28, 28, 4, 8))
            entity.add(SpriteRenderer(COL_MUSHROOM, 24, 22, "circle", LAYER_PLANTS, sprite_path))
            plant = PlantComponent("mushroom_cluster", GROWTH_FULL, [TILE_GRASS, TILE_MUD, TILE_DIRT])
            interact = Interactable("Gather mushrooms", 0.45)
        else:
            entity.add(Collider(30, 30, 3, 5))
            entity.add(SpriteRenderer(COL_BERRY_BUSH, 30, 30, "circle", LAYER_PLANTS, sprite_path))
            plant = PlantComponent("berry_bush", GROWTH_FULL, [TILE_GRASS, TILE_DIRT])
            interact = Interactable("Harvest berries", 0.55)

        entity.add(plant)
        entity.add(interact)
        return entity

    def _create_npc(self, ai_type, x, y, village_id=None, home_pos=None, sleep_path=None, farm_plots=None, work_points=None,
                    storage_chest=None, village_bounds=None, idle_route=None, work_pause_range=None, home_bounds=None):
        profile = self.npc_profiles[ai_type]
        entity = Entity(profile["label"])
        entity.tags.update({"npc", ai_type, "combatant"})
        if ai_type.startswith("villager"):
            entity.tags.add("villager")
            entity.tags.add("trader")
        if ai_type == "police":
            entity.tags.update({"police", "trader"})
        if ai_type == "zombie":
            entity.tags.add("undead")
        entity.add(Transform(x, y))
        entity.add(Collider(28, 24, 4, 10))
        entity.add(SpriteRenderer(
            profile["color"],
            36,
            42,
            profile["shape"],
            LAYER_CHARACTERS,
            sprite_path=self._sprite_path("entities", f"{ai_type}_creature.png"),
        ))
        entity.add(Health(profile["health"]))
        ai = AIController(
            ai_type=ai_type,
            detect_range=profile["detect_range"],
            attack_range=profile["attack_range"],
        )
        ai.home_pos = pygame.Vector2(home_pos) if home_pos else pygame.Vector2(x, y)
        ai.home_bounds = home_bounds.copy() if home_bounds else None
        ai.state_timer = random.uniform(0.2, 1.5)
        ai.wander_dir = pygame.Vector2(random.uniform(-1, 1), random.uniform(-1, 1))
        ai.role = profile.get("role", ai_type)
        ai.village_id = village_id
        ai.display_name = profile["label"]
        ai.stock = dict(profile.get("stock", {}))
        ai.trade_offer = profile.get("trade_offer", "")
        ai.activity_timer = random.uniform(1.0, 3.0)
        ai.trade_timer = random.uniform(1.0, 3.0)
        ai.home_radius = TILE_SIZE * 5 if village_id is not None else TILE_SIZE * 8
        ai.sleep_path = [pygame.Vector2(point) for point in (sleep_path or [])]
        ai.sleep_path_index = 0
        ai.sleeping = False
        ai.farm_plots = list(farm_plots or [])
        ai.work_points = [pygame.Vector2(point) for point in (work_points or [])]
        ai.work_index = 0
        ai.storage_chest = storage_chest
        ai.village_bounds = village_bounds.copy() if village_bounds else None
        ai.idle_route = [pygame.Vector2(point) for point in (idle_route or ai.work_points)]
        ai.last_pos = pygame.Vector2(x, y)
        if work_pause_range:
            ai.work_pause_range = work_pause_range
        if ai_type in {"villager_farmer", "villager_crafter", "police"}:
            ai.max_hunger = VILLAGER_MAX_HUNGER
            ai.hunger = random.uniform(VILLAGER_MAX_HUNGER * 0.55, VILLAGER_MAX_HUNGER)
            ai.hunger_drain = VILLAGER_HUNGER_DRAIN_RATE
        entity.add(ai)
        return entity

    def _create_structure(self, structure_type, x, y):
        entity = Entity(structure_type)
        entity.tags.update({"structure", structure_type})
        item = ITEMS.get(structure_type, {"color": COL_FARMLAND})
        entity.add(Transform(x, y))

        if structure_type == "door_wood":
            entity.add(Collider(TILE_SIZE - 20, TILE_SIZE - 14, 10, 8))
            entity.add(SpriteRenderer(item["color"], TILE_SIZE - 8, TILE_SIZE, "rect", LAYER_PLANTS,
                                      sprite_path=self._sprite_path("entities", "door_wood.png")))
            entity.add(StructureComponent("door_wood", solid=True, openable=True))
            entity.add(Interactable("Toggle door", 0.0))
        elif structure_type == "chest_wood":
            entity.add(Collider(TILE_SIZE - 18, TILE_SIZE - 24, 9, 20))
            entity.add(SpriteRenderer(item["color"], TILE_SIZE - 4, TILE_SIZE - 12, "rect", LAYER_PLANTS,
                                      sprite_path=self._sprite_path("entities", "chest_wood.png")))
            entity.add(StructureComponent("chest_wood", solid=True))
            entity.add(Container(max_slots=24))
            entity.add(Interactable("Open chest", 0.0))
        elif structure_type == "farmland":
            entity.add(SpriteRenderer(COL_FARMLAND, TILE_SIZE - 2, TILE_SIZE - 6, "rect", LAYER_DETAIL,
                                      sprite_path=self._sprite_path("entities", "farmland.png")))
            entity.add(StructureComponent("farmland", solid=False))
        elif structure_type == "bed":
            entity.add(Collider(TILE_SIZE - 14, 18, 7, TILE_SIZE - 28))
            entity.add(SpriteRenderer(item["color"], TILE_SIZE - 6, TILE_SIZE - 18, "rect", LAYER_PLANTS,
                                      sprite_path=self._sprite_path("entities", "bed.png")))
            entity.add(StructureComponent("bed", solid=False))
        elif structure_type == "campfire":
            entity.add(Collider(34, 24, 12, 24))
            entity.add(SpriteRenderer(item["color"], 52, 42, "diamond", LAYER_PLANTS,
                                      sprite_path=self._sprite_path("entities", "campfire.png")))
            entity.add(StructureComponent("campfire", solid=False, station="campfire"))
        elif structure_type == "furnace":
            entity.add(Collider(44, 34, 10, 18))
            entity.add(SpriteRenderer(item["color"], 60, 60, "rect", LAYER_PLANTS,
                                      sprite_path=self._sprite_path("entities", "furnace.png")))
            entity.add(StructureComponent("furnace", solid=True, station="furnace"))
        elif structure_type == "wall_stone":
            entity.add(Collider(TILE_SIZE - 8, TILE_SIZE - 14, 4, 8))
            entity.add(SpriteRenderer(item["color"], TILE_SIZE, TILE_SIZE, "rect", LAYER_PLANTS,
                                      sprite_path=self._sprite_path("entities", "wall_stone.png")))
            entity.add(StructureComponent("wall_stone", solid=True))
        else:
            entity.add(Collider(TILE_SIZE - 8, TILE_SIZE - 14, 4, 8))
            entity.add(SpriteRenderer(item["color"], TILE_SIZE, TILE_SIZE, "rect", LAYER_PLANTS,
                                      sprite_path=self._sprite_path("entities", "wall_wood.png")))
            entity.add(StructureComponent("wall_wood", solid=True))
        return entity

    def run(self):
        while self.running:
            dt = min(self.clock.tick(FPS) / 1000.0, 0.05)
            self._handle_events()
            self._update(dt)
            self._draw()

    def _handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                continue
            if self.game_mode == "main_menu":
                self._handle_main_menu_event(event)
            elif self.game_mode == "paused":
                self._handle_paused_event(event)
            elif self.game_mode == "dead":
                self._handle_dead_event(event)
            else:
                self._handle_gameplay_event(event)

    def _handle_main_menu_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.running = False
            elif event.key == pygame.K_RETURN:
                self._start_or_restart_game(self._menu_seed_value())
            elif event.key == pygame.K_BACKSPACE:
                self.menu_seed_text = self.menu_seed_text[:-1]
            elif event.key == pygame.K_r:
                self.menu_seed_text = str(random.randint(1000, 999999))
            elif event.unicode and event.unicode.isdigit():
                self.menu_seed_text = (self.menu_seed_text + event.unicode)[:9]
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._handle_overlay_click(event.pos)

    def _handle_paused_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key in {pygame.K_ESCAPE, pygame.K_p}:
                self._toggle_pause()
            elif event.key == pygame.K_r:
                self._start_or_restart_game(self.last_seed)
            elif event.key == pygame.K_m:
                self._return_to_main_menu()
            elif event.key == pygame.K_q:
                self.running = False
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._handle_overlay_click(event.pos)

    def _handle_dead_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key in {pygame.K_RETURN, pygame.K_r}:
                self._start_or_restart_game(self.last_seed)
            elif event.key == pygame.K_m:
                self._return_to_main_menu()
            elif event.key == pygame.K_q:
                self.running = False
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._handle_overlay_click(event.pos)

    def _handle_gameplay_event(self, event):
        if event.type == pygame.KEYDOWN:
            if self.show_inventory and self.craft_search_active and event.key == pygame.K_BACKSPACE:
                self.craft_search_text = self.craft_search_text[:-1]
                self._clamp_recipe_selection()
                return
            if self.show_inventory and self.craft_search_active and event.unicode and event.unicode.isprintable() and not event.unicode.isspace():
                self.craft_search_text += event.unicode.lower()
                self._clamp_recipe_selection()
                return
            if event.key == pygame.K_ESCAPE:
                if self.show_inventory:
                    self._close_inventory_views()
                else:
                    self._toggle_pause()
            elif event.key == pygame.K_p:
                self._toggle_pause()
            elif event.key == pygame.K_i:
                self.show_inventory = not self.show_inventory
                self.show_crafting = self.show_inventory
                self.craft_search_active = self.show_inventory
                if not self.show_inventory:
                    self._close_inventory_views()
                else:
                    self.open_container_entity = None
            elif pygame.K_1 <= event.key <= pygame.K_9:
                self.player.get(Inventory).selected_hotbar = event.key - pygame.K_1
                self._show_selected_item_name(self.player.get(Inventory).get_selected())
            elif event.key == pygame.K_f:
                self._eat_selected_food()
            elif event.key == pygame.K_q:
                self._drop_selected_item()
            elif event.key == pygame.K_SPACE and not self._player_is_dead():
                self.pending_attack = True
            elif event.key == pygame.K_RETURN:
                crafted = self._craft_selected_recipe()
                self._set_message(f"Crafted {crafted}" if crafted else "That recipe is not craftable yet")
            elif event.key == pygame.K_UP:
                self.selected_recipe_index = max(0, self.selected_recipe_index - 1)
                self._clamp_recipe_selection()
            elif event.key == pygame.K_DOWN:
                self.selected_recipe_index += 1
                self._clamp_recipe_selection()
            elif event.key == pygame.K_r:
                self.last_seed = random.randint(1000, 999999)
                self.menu_seed_text = str(self.last_seed)
                self._set_message(f"Current generated map seed: {self.last_seed}")
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                self._handle_left_click(event.pos)
            elif event.button == 3 and not self.show_inventory and not self._player_is_dead():
                self._place_selected_structure()
            elif event.button == 4:
                self.selected_recipe_index = max(0, self.selected_recipe_index - 1)
                self._clamp_recipe_selection()
            elif event.button == 5:
                self.selected_recipe_index += 1
                self._clamp_recipe_selection()

    def _handle_overlay_click(self, pos):
        for action, rect in self.menu_buttons.items():
            if rect.collidepoint(pos):
                if action == "start":
                    self._start_or_restart_game(self._menu_seed_value())
                elif action == "random_seed":
                    self.menu_seed_text = str(random.randint(1000, 999999))
                elif action == "resume":
                    self._toggle_pause()
                elif action == "restart":
                    self._start_or_restart_game(self.last_seed)
                elif action == "main_menu":
                    self._return_to_main_menu()
                elif action == "quit":
                    self.running = False
                break

    def _update(self, dt):
        self.message_timer = max(0.0, self.message_timer - dt)
        self.attack_cooldown = max(0.0, self.attack_cooldown - dt)
        self.selected_item_label_timer = max(0.0, self.selected_item_label_timer - dt)
        self.instant_interact_cooldown = max(0.0, self.instant_interact_cooldown - dt)
        self.trade_interact_cooldown = max(0.0, self.trade_interact_cooldown - dt)
        self.harvest_hint = ""
        if self.game_mode == "playing" and self._player_is_dead():
            self._set_dead_state()
        if self.game_mode != "playing":
            self.pending_attack = False
            return
        self._update_trade_popups(dt)
        self._sync_open_container()
        self._refresh_frame_caches()
        self._update_world_simulation(dt)
        self._update_player(dt)
        self._update_npcs(dt)
        self.world.update(dt)
        if self._player_is_dead():
            self._set_dead_state()
            return
        self._update_structures()
        self._handle_pickups()
        self._update_interactions()
        self._update_camera()

    def _update_world_simulation(self, dt):
        self.time_of_day = (self.time_of_day + dt * self.day_cycle_speed) % 1.0
        self._update_villager_economy(dt)
        self._update_zombie_spawns(dt)

    def _is_night(self):
        return self.time_of_day >= 0.72 or self.time_of_day <= 0.22

    def _update_player(self, dt):
        keys = pygame.key.get_pressed()
        transform = self.player.get(Transform)
        collider = self.player.get(Collider)
        stats = self.player.get(PlayerStats)
        health = self.player.get(Health)

        if health.hp <= 0:
            self.pending_attack = False
            return

        move = pygame.Vector2(
            float(keys[pygame.K_d] or keys[pygame.K_RIGHT]) - float(keys[pygame.K_a] or keys[pygame.K_LEFT]),
            float(keys[pygame.K_s] or keys[pygame.K_DOWN]) - float(keys[pygame.K_w] or keys[pygame.K_UP]),
        )
        if move.length_squared() > 0:
            move = move.normalize()
        sprinting = bool(keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]) and move.length_squared() > 0
        stats.set_sprint(sprinting)
        speed = PLAYER_SPEED * (SPRINT_MULT if stats.is_sprinting() else 1.0)
        self._move_entity(transform, collider, move.x * speed * dt, move.y * speed * dt)

        if self.pending_attack and self.attack_cooldown <= 0:
            self.pending_attack = False
            selected = self.player.get(Inventory).get_selected()
            self.attack_cooldown = max(0.22, 0.45 / max(0.5, selected.data.get("speed", 1.0) if selected else 1.0))
            self._player_attack()
        elif self.pending_attack and self.attack_cooldown > 0:
            self.pending_attack = False

    def _move_entity(self, transform, collider, dx, dy):
        if dx:
            original_x = transform.x
            transform.x += dx
            if self._blocked(collider.get_rect()):
                transform.x = original_x
        if dy:
            original_y = transform.y
            transform.y += dy
            if self._blocked(collider.get_rect()):
                transform.y = original_y
        max_x = self.tilemap.width * TILE_SIZE - PLAYER_FOOTPRINT
        max_y = self.tilemap.height * TILE_SIZE - PLAYER_FOOTPRINT
        transform.x = max(0, min(transform.x, max_x))
        transform.y = max(0, min(transform.y, max_y))

    def _blocked(self, rect):
        if not self.tilemap.is_passable_rect(rect):
            return True
        for structure_rect in self._solid_structure_rects():
            if structure_rect.colliderect(rect):
                return True
        return False

    def _player_attack(self):
        if self._player_is_dead():
            self.pending_attack = False
            return
        inventory = self.player.get(Inventory)
        selected = inventory.get_selected()
        damage = 8
        attack_range = 56
        if selected:
            damage = selected.data.get("damage", damage)
            attack_range = selected.data.get("attack_range", attack_range)
        player_transform = self.player.get(Transform)
        player_center = pygame.Vector2(
            player_transform.x + PLAYER_FOOTPRINT / 2,
            player_transform.y + PLAYER_FOOTPRINT - 18,
        )
        mouse_x, mouse_y = pygame.mouse.get_pos()
        aim_target = pygame.Vector2(mouse_x + self.camera_x, mouse_y + self.camera_y)
        aim_vector = aim_target - player_center
        if aim_vector.length_squared() == 0:
            aim_vector = pygame.Vector2(1, 0)
        aim_vector = aim_vector.normalize()

        in_range_targets = []
        for entity in self._current_npcs():
            if not entity.alive:
                continue
            npc_transform = entity.get(Transform)
            enemy_center = pygame.Vector2(npc_transform.x + 16, npc_transform.y + 18)
            to_enemy = enemy_center - player_center
            distance = to_enemy.length()
            if distance > attack_range:
                continue
            if to_enemy.length_squared() == 0:
                facing = 1.0
            else:
                direction = to_enemy.normalize()
                facing = aim_vector.dot(direction)
            danger_bias = 2 if entity.get(AIController).ai_type in {"hostile", "zombie"} else 1 if entity.get(AIController).ai_type in {"neutral", "passive"} else 0
            in_range_targets.append((facing, danger_bias, -distance, entity))

        best_target = None
        cone_targets = [entry for entry in in_range_targets if entry[0] >= 0.1]
        if cone_targets:
            best_target = max(cone_targets, key=lambda entry: (entry[1], entry[0], entry[2]))[3]
        elif in_range_targets:
            best_target = max(in_range_targets, key=lambda entry: (entry[1], entry[2]))[3]

        hit = False
        if best_target:
            health = best_target.get(Health)
            renderer = best_target.get(SpriteRenderer)
            ai = best_target.get(AIController)
            health.damage(damage)
            if renderer:
                renderer.flash_hurt()
            if ai.ai_type in {"passive", "neutral"}:
                ai.ai_type = "hostile"
                ai.detect_range = 280
                ai.state = AIController.STATE_CHASE
            if health.is_dead():
                self._drop_npc_loot(best_target)
            hit = True
        if selected and selected.durability is not None:
            inventory.use_durability(1)
        self._set_message("Attack landed" if hit else "Your swing hit air")

    def _update_villager_economy(self, dt):
        npc_entities = self._current_npcs()
        for entity in npc_entities:
            if not entity.alive:
                continue
            ai = entity.get(AIController)
            if not hasattr(ai, "activity_timer"):
                continue
            ai.activity_timer -= dt
            ai.trade_timer -= dt
            if ai.trade_task:
                partner = ai.trade_task.get("partner")
                if not partner or not partner.alive:
                    self._clear_trade_task(ai)

            if ai.ai_type in {"villager_farmer", "villager_crafter", "police"} and ai.hunger <= VILLAGER_EAT_THRESHOLD:
                self._villager_eat(ai)

            if ai.ai_type == "villager_farmer" and ai.activity_timer <= 0:
                ai.stock["fiber"] = ai.stock.get("fiber", 0) + random.randint(0, 1)
                ai.activity_timer = random.uniform(4.0, 6.5)

            if ai.ai_type == "villager_crafter" and ai.activity_timer <= 0:
                self._run_crafter_activity(ai)
                ai.activity_timer = random.uniform(4.5, 7.5)

        for village in self.villages:
            farmers = []
            crafters = []
            guards = []
            for entity in npc_entities:
                if not entity.alive:
                    continue
                ai = entity.get(AIController)
                if getattr(ai, "village_id", None) != village["id"]:
                    continue
                if ai.ai_type == "villager_farmer":
                    farmers.append(entity)
                elif ai.ai_type == "villager_crafter":
                    crafters.append(entity)
                elif ai.ai_type == "police":
                    guards.append(entity)
            self._schedule_village_trades(farmers, crafters, guards)

    def _run_crafter_activity(self, ai):
        if ai.stock.get("wheat", 0) >= 3 and ai.stock.get("bread", 0) < 3:
            ai.stock["wheat"] -= 3
            ai.stock["bread"] = ai.stock.get("bread", 0) + 1
        elif ai.stock.get("wood", 0) >= 3 and ai.stock.get("fiber", 0) >= 2 and ai.stock.get("hoe_wood", 0) < 2:
            ai.stock["wood"] -= 3
            ai.stock["fiber"] -= 2
            ai.stock["hoe_wood"] = ai.stock.get("hoe_wood", 0) + 1
        elif ai.stock.get("wood", 0) >= 2 and ai.stock.get("stone", 0) >= 2 and ai.stock.get("sword_wood", 0) < 2:
            ai.stock["wood"] -= 2
            ai.stock["stone"] -= 2
            ai.stock["sword_wood"] = ai.stock.get("sword_wood", 0) + 1
        elif ai.stock.get("wood", 0) >= 2 and ai.stock.get("fiber", 0) >= 2 and ai.stock.get("rope", 0) < 3:
            ai.stock["wood"] -= 2
            ai.stock["fiber"] -= 2
            ai.stock["rope"] = ai.stock.get("rope", 0) + 1

    def _schedule_village_trades(self, farmers, crafters, guards):
        for farmer in farmers:
            farmer_ai = farmer.get(AIController)
            if not self._ai_ready_for_trade(farmer_ai):
                continue
            crafter = self._nearest_trade_candidate(farmer, crafters)
            if not crafter:
                continue
            give_items, receive_items = self._build_farmer_trade(farmer_ai, crafter.get(AIController))
            if give_items:
                self._assign_villager_trade(farmer, crafter, give_items, receive_items)

        for crafter in crafters:
            crafter_ai = crafter.get(AIController)
            if not self._ai_ready_for_trade(crafter_ai):
                continue
            guard = self._nearest_trade_candidate(crafter, guards)
            if not guard:
                continue
            give_items = self._build_guard_trade(crafter_ai, guard.get(AIController))
            if give_items:
                self._assign_villager_trade(crafter, guard, give_items, [])

    def _ai_ready_for_trade(self, ai):
        return ai and ai.trade_timer <= 0 and not ai.trade_task

    def _nearest_trade_candidate(self, source_entity, candidates):
        valid = []
        source_transform = source_entity.get(Transform)
        if not source_transform:
            return None
        source_pos = pygame.Vector2(source_transform.x, source_transform.y)
        for candidate in candidates:
            if not candidate.alive or candidate is source_entity:
                continue
            ai = candidate.get(AIController)
            transform = candidate.get(Transform)
            if not ai or not transform or not self._ai_ready_for_trade(ai):
                continue
            valid.append((source_pos.distance_to(pygame.Vector2(transform.x, transform.y)), candidate))
        if not valid:
            return None
        valid.sort(key=lambda entry: entry[0])
        return valid[0][1]

    def _build_farmer_trade(self, farmer_ai, crafter_ai):
        give_items = []
        receive_items = []
        if farmer_ai.stock.get("wheat", 0) >= 3 and crafter_ai.stock.get("wheat", 0) < 6:
            give_items.append(("wheat", 3))
        elif farmer_ai.stock.get("berry", 0) >= 2 and crafter_ai.stock.get("berry", 0) < 5:
            give_items.append(("berry", 2))
        elif farmer_ai.stock.get("fiber", 0) >= 2 and crafter_ai.stock.get("fiber", 0) < 6:
            give_items.append(("fiber", 2))

        if not give_items:
            return [], []

        if crafter_ai.stock.get("bread", 0) >= 1 and farmer_ai.hunger < VILLAGER_EAT_THRESHOLD:
            receive_items.append(("bread", 1))
        elif crafter_ai.stock.get("hoe_wood", 0) >= 1 and farmer_ai.stock.get("hoe_wood", 0) < 1:
            receive_items.append(("hoe_wood", 1))
        return give_items, receive_items

    def _build_guard_trade(self, crafter_ai, guard_ai):
        if crafter_ai.stock.get("sword_wood", 0) >= 1 and guard_ai.stock.get("sword_wood", 0) < 1:
            return [("sword_wood", 1)]
        if crafter_ai.stock.get("bread", 0) >= 1 and guard_ai.hunger < VILLAGER_EAT_THRESHOLD:
            return [("bread", 1)]
        return []

    def _assign_villager_trade(self, giver_entity, receiver_entity, give_items, receive_items):
        giver_ai = giver_entity.get(AIController)
        receiver_ai = receiver_entity.get(AIController)
        giver_transform = giver_entity.get(Transform)
        receiver_transform = receiver_entity.get(Transform)
        meeting_point = pygame.Vector2(
            (giver_transform.x + receiver_transform.x) * 0.5,
            (giver_transform.y + receiver_transform.y) * 0.5,
        )
        giver_ai.trade_partner = receiver_entity
        receiver_ai.trade_partner = giver_entity
        giver_ai.trade_task = {
            "partner": receiver_entity,
            "meeting_point": meeting_point,
            "give": list(give_items),
            "receive": list(receive_items),
            "initiator": True,
        }
        receiver_ai.trade_task = {
            "partner": giver_entity,
            "meeting_point": meeting_point,
            "give": list(receive_items),
            "receive": list(give_items),
            "initiator": False,
        }

    def _clear_trade_task(self, ai, clear_partner=True):
        partner = ai.trade_partner if clear_partner else None
        ai.trade_partner = None
        ai.trade_task = None
        if clear_partner and partner and partner.alive:
            partner_ai = partner.get(AIController)
            if partner_ai and partner_ai.trade_partner is ai.entity:
                self._clear_trade_task(partner_ai, clear_partner=False)

    def _villager_eat(self, ai):
        for item_id in ("bread", "berry", "mushroom"):
            if ai.stock.get(item_id, 0) > 0:
                ai.stock[item_id] -= 1
                ai.eat(ITEMS.get(item_id, {}).get("food_restore", 10))
                return True
        chest = getattr(ai, "storage_chest", None)
        if not chest or not chest.alive:
            return False
        container = chest.get(Container)
        if not container:
            return False
        for item_id in ("bread", "berry"):
            if self._take_from_container(container, item_id, 1):
                ai.eat(ITEMS.get(item_id, {}).get("food_restore", 10))
                return True
        return False

    def _complete_villager_trade(self, initiator_ai):
        task = initiator_ai.trade_task
        if not task:
            return
        partner = task.get("partner")
        if not partner or not partner.alive:
            self._clear_trade_task(initiator_ai)
            return
        partner_ai = partner.get(AIController)
        any_transfer = False

        for item_id, qty in task.get("give", []):
            moved = self._transfer_stock(initiator_ai, partner_ai, item_id, qty)
            any_transfer = any_transfer or moved > 0
        for item_id, qty in task.get("receive", []):
            moved = self._transfer_stock(partner_ai, initiator_ai, item_id, qty)
            any_transfer = any_transfer or moved > 0

        initiator_ai.trade_timer = random.uniform(5.0, 8.0)
        partner_ai.trade_timer = random.uniform(5.0, 8.0)
        initiator_ai.state_timer = random.uniform(0.2, 0.45)
        partner_ai.state_timer = random.uniform(0.2, 0.45)
        self._clear_trade_task(initiator_ai)
        if any_transfer:
            initiator_ai.activity_timer = max(initiator_ai.activity_timer, 0.8)
            partner_ai.activity_timer = max(partner_ai.activity_timer, 0.8)

    def _transfer_stock(self, giver_ai, receiver_ai, item_id, requested_qty):
        moved = min(requested_qty, giver_ai.stock.get(item_id, 0))
        if moved <= 0:
            return 0
        giver_ai.stock[item_id] -= moved
        receiver_ai.stock[item_id] = receiver_ai.stock.get(item_id, 0) + moved
        self._spawn_trade_popup(giver_ai.entity, item_id, moved, positive=False)
        self._spawn_trade_popup(receiver_ai.entity, item_id, moved, positive=True)
        return moved

    def _update_zombie_spawns(self, dt):
        if not self._is_night():
            for entity in self._current_npcs():
                if not entity.alive:
                    continue
                ai = entity.get(AIController)
                if ai.ai_type == "zombie":
                    entity.destroy()
            self.zombie_spawn_timer = 3.0
            return

        self.zombie_spawn_timer -= dt
        current_zombies = [e for e in self._current_npcs() if e.alive and e.get(AIController).ai_type == "zombie"]
        if self.zombie_spawn_timer > 0 or len(current_zombies) >= 8:
            return

        self.zombie_spawn_timer = random.uniform(3.5, 6.0)
        spawn_origin = random.choice(self.villages)["center"] if self.villages else pygame.Vector2(self.player.get(Transform).x, self.player.get(Transform).y)
        for _ in range(40):
            angle = random.uniform(0, math.tau)
            radius = random.uniform(TILE_SIZE * 5, TILE_SIZE * 8)
            x = int(spawn_origin.x + math.cos(angle) * radius)
            y = int(spawn_origin.y + math.sin(angle) * radius)
            tx = max(1, min(self.tilemap.width - 2, x // TILE_SIZE))
            ty = max(1, min(self.tilemap.height - 2, y // TILE_SIZE))
            if self.tilemap.get(tx, ty) in SOLID_TILES:
                continue
            spawn_x = tx * TILE_SIZE
            spawn_y = ty * TILE_SIZE
            if self._position_occupied(spawn_x, spawn_y, 36, 36):
                continue
            self.world.add(self._create_npc("zombie", spawn_x, spawn_y))
            break

    def _entity_center(self, entity):
        transform = entity.get(Transform) if entity else None
        if not transform:
            return pygame.Vector2()
        collider = entity.get(Collider)
        if collider:
            rect = collider.get_rect()
            return pygame.Vector2(rect.centerx, rect.centery)
        return pygame.Vector2(transform.x + TILE_SIZE / 2, transform.y + TILE_SIZE / 2)

    def _villager_safe_inside_home(self, ai, entity, threat):
        if not threat or ai.ai_type not in {"villager_farmer", "villager_crafter"}:
            return False
        home_bounds = getattr(ai, "home_bounds", None)
        if not home_bounds:
            return False
        villager_center = self._entity_center(entity)
        if not home_bounds.inflate(-10, -10).collidepoint(villager_center):
            return False
        threat_center = self._entity_center(threat)
        return not home_bounds.inflate(12, 12).collidepoint(threat_center)

    def _npc_separation_vector(self, source_entity, neighbors, radius=34):
        source_center = self._entity_center(source_entity)
        push = pygame.Vector2()
        weight = 0.0
        source_ai = source_entity.get(AIController)
        source_partner = getattr(source_ai, "trade_partner", None) if source_ai else None

        for other in neighbors:
            if other is source_entity or not other.alive:
                continue
            other_ai = other.get(AIController)
            if not other_ai:
                continue
            if source_partner is other or getattr(other_ai, "trade_partner", None) is source_entity:
                continue
            delta = source_center - self._entity_center(other)
            dist_sq = delta.length_squared()
            if dist_sq >= radius * radius:
                continue
            if dist_sq <= 0.01:
                delta = self._random_direction()
                dist_sq = 1.0
            dist = math.sqrt(dist_sq)
            strength = (radius - dist) / radius
            push += delta.normalize() * strength
            weight += strength

        if weight <= 0:
            return pygame.Vector2()
        return push / weight

    def _recover_stuck_npc(self, ai):
        ai.path = []
        ai.path_index = 0
        ai.path_recalc_timer = 0.0
        ai.route_pause_timer = max(ai.route_pause_timer, 0.08)
        ai.state_timer = max(ai.state_timer, 0.08)
        if getattr(ai, "farm_plots", None):
            ai.work_index = (ai.work_index + 1) % max(1, len(ai.farm_plots))
        elif getattr(ai, "work_points", None):
            ai.work_index = (ai.work_index + 1) % max(1, len(ai.work_points))
        elif getattr(ai, "idle_route", None):
            ai.work_index = (ai.work_index + 1) % max(1, len(ai.idle_route))
        ai.wander_dir = self._random_direction()
        ai.stuck_timer = 0.0

    def _update_npcs(self, dt):
        player_transform = self.player.get(Transform)
        player_health = self.player.get(Health)
        player_center = pygame.Vector2(player_transform.x + PLAYER_FOOTPRINT / 2, player_transform.y + PLAYER_FOOTPRINT - 16)
        npc_entities = self._current_npcs()

        for entity in npc_entities:
            if not entity.alive:
                continue
            ai = entity.get(AIController)
            transform = entity.get(Transform)
            collider = entity.get(Collider)
            renderer = entity.get(SpriteRenderer)
            if not transform or not collider or not ai:
                continue

            npc_center = pygame.Vector2(transform.x + 18, transform.y + 26)
            to_player = player_center - npc_center
            distance = to_player.length()
            move = pygame.Vector2()
            nearest_threat = self._nearest_npc(entity, {"hostile", "zombie"}, max_range=220)
            if self._villager_safe_inside_home(ai, entity, nearest_threat):
                nearest_threat = None

            if ai.ai_type == "villager_farmer":
                if self._is_night() and ai.sleeping:
                    ai.state = AIController.STATE_IDLE
                    move = pygame.Vector2()
                elif nearest_threat:
                    ai.sleeping = False
                    ai.state = AIController.STATE_FLEE
                    threat_pos = pygame.Vector2(nearest_threat.get(Transform).x, nearest_threat.get(Transform).y)
                    flee_vec = npc_center - threat_pos
                    if flee_vec.length_squared() > 0:
                        move = flee_vec.normalize()
                elif self._is_night():
                    move = self._npc_follow_sleep_path(ai, transform)
                    if move.length_squared() == 0:
                        ai.state = AIController.STATE_IDLE
                    else:
                        ai.state = AIController.STATE_WANDER
                else:
                    ai.sleeping = False
                    ai.sleep_path_index = 0
                    trade_move = self._villager_trade_direction(ai, transform)
                    move = trade_move if trade_move is not None else self._farmer_work_direction(ai, transform)
            elif ai.ai_type == "villager_crafter":
                if self._is_night() and ai.sleeping:
                    ai.state = AIController.STATE_IDLE
                    move = pygame.Vector2()
                elif nearest_threat:
                    ai.sleeping = False
                    ai.state = AIController.STATE_FLEE
                    threat_pos = pygame.Vector2(nearest_threat.get(Transform).x, nearest_threat.get(Transform).y)
                    flee_vec = npc_center - threat_pos
                    if flee_vec.length_squared() > 0:
                        move = flee_vec.normalize()
                elif self._is_night():
                    move = self._npc_follow_sleep_path(ai, transform)
                else:
                    ai.sleeping = False
                    ai.sleep_path_index = 0
                    trade_move = self._villager_trade_direction(ai, transform)
                    move = trade_move if trade_move is not None else self._crafter_work_direction(ai, transform)
            elif ai.ai_type == "police":
                if not self._is_night():
                    ai.sleeping = False
                threat = self._nearest_npc(entity, {"hostile", "zombie"}, max_range=260)
                if threat:
                    ai.sleeping = False
                    ai.state = AIController.STATE_CHASE
                    threat_vec = pygame.Vector2(threat.get(Transform).x - transform.x, threat.get(Transform).y - transform.y)
                    if threat_vec.length() <= ai.attack_range + 10:
                        if ai._attack_cooldown <= 0:
                            threat.get(Health).damage(18)
                            ai._attack_cooldown = 0.6
                            threat_renderer = threat.get(SpriteRenderer)
                            if threat_renderer:
                                threat_renderer.flash_hurt()
                            if threat.get(Health).is_dead():
                                threat.destroy()
                        move = pygame.Vector2()
                    else:
                        move = self._npc_chase_direction(ai, transform, threat.get(Transform), threat_vec)
                    ai.sleep_path_index = 0
                elif self._is_night():
                    move = self._npc_follow_sleep_path(ai, transform)
                else:
                    ai.sleep_path_index = 0
                    trade_move = self._villager_trade_direction(ai, transform)
                    move = trade_move if trade_move is not None else self._villager_route_direction(ai, transform, 0.1, 0.3)
            elif ai.ai_type == "zombie":
                target = self._nearest_npc(entity, {"villager", "police", "player"}, max_range=320)
                if target is self.player or (target and "player" in target.tags):
                    target_transform = player_transform
                    target_health = player_health
                elif target:
                    target_transform = target.get(Transform)
                    target_health = target.get(Health)
                else:
                    target_transform = player_transform
                    target_health = player_health
                target_vec = pygame.Vector2(target_transform.x - transform.x, target_transform.y - transform.y)
                target_distance = target_vec.length()
                if target_distance <= ai.attack_range + 6:
                    if ai._attack_cooldown <= 0:
                        target_health.damage(10)
                        ai._attack_cooldown = 0.9
                    move = pygame.Vector2()
                elif target_distance > 0:
                    move = self._npc_chase_direction(ai, transform, target_transform, target_vec)
            elif ai.ai_type == "passive":
                if distance < 105:
                    ai.state = AIController.STATE_FLEE
                elif ai.state_timer <= 0:
                    ai.state = random.choice([AIController.STATE_IDLE, AIController.STATE_WANDER])
                    ai.state_timer = random.uniform(0.8, 2.4)
                    ai.wander_dir = self._random_direction()
                if ai.state == AIController.STATE_FLEE and distance > 165:
                    ai.state = AIController.STATE_WANDER
                if ai.state == AIController.STATE_FLEE and distance > 0:
                    move = -to_player.normalize()
                elif ai.state == AIController.STATE_WANDER:
                    move = ai.wander_dir
            elif ai.ai_type == "neutral":
                if distance < 58:
                    ai.state = AIController.STATE_FLEE
                elif distance < 160 and random.random() < 0.01:
                    ai.state = AIController.STATE_CHASE
                elif ai.state_timer <= 0:
                    ai.state = random.choice([AIController.STATE_IDLE, AIController.STATE_WANDER, AIController.STATE_CHASE])
                    ai.state_timer = random.uniform(1.0, 2.8)
                    ai.wander_dir = self._random_direction()
                if ai.state == AIController.STATE_FLEE and distance > 120:
                    ai.state = AIController.STATE_WANDER
                if ai.state == AIController.STATE_CHASE and 0 < distance < 170:
                    move = to_player.normalize()
                elif ai.state == AIController.STATE_FLEE and distance > 0:
                    move = -to_player.normalize()
                elif ai.state == AIController.STATE_WANDER:
                    move = ai.wander_dir
            else:
                if distance < ai.attack_range:
                    ai.state = AIController.STATE_ATTACK
                elif distance < ai.detect_range:
                    ai.state = AIController.STATE_CHASE
                elif ai.state_timer <= 0:
                    ai.state = random.choice([AIController.STATE_IDLE, AIController.STATE_WANDER])
                    ai.state_timer = random.uniform(1.0, 2.2)
                    ai.wander_dir = self._random_direction()

                if ai.state == AIController.STATE_ATTACK:
                    if ai._attack_cooldown <= 0 and distance < ai.attack_range + 8:
                        player_health.damage(8)
                        ai._attack_cooldown = 0.9
                        self._set_message("A hostile creature hit you")
                    if distance > ai.attack_range + 20:
                        ai.state = AIController.STATE_CHASE
                elif ai.state == AIController.STATE_CHASE and distance > 0:
                    move = self._npc_chase_direction(ai, transform, player_transform, to_player)
                elif ai.state == AIController.STATE_WANDER:
                    move = ai.wander_dir

            requested_move = pygame.Vector2(move)
            if ai.ai_type in {"villager_farmer", "villager_crafter", "police"}:
                separation = self._npc_separation_vector(entity, npc_entities, radius=32)
                if separation.length_squared() > 0:
                    if requested_move.length_squared() > 0:
                        move = requested_move * 1.25 + separation * 1.1
                    else:
                        move = separation

            if move.length_squared() > 0:
                move = move.normalize()
                if ai.ai_type == "zombie":
                    speed = NPC_SPEED * 0.92
                elif ai.ai_type == "police":
                    speed = NPC_SPEED * 1.18
                elif ai.ai_type.startswith("villager"):
                    speed = NPC_SPEED * 0.88
                else:
                    speed = NPC_SPEED * (1.15 if ai.ai_type == "hostile" else 0.9 if ai.ai_type == "passive" else 1.0)
                if ai.ai_type.startswith("villager") or ai.ai_type == "police":
                    self._open_nearby_doors(transform)
                before_pos = pygame.Vector2(transform.x, transform.y)
                self._move_entity(transform, collider, move.x * speed * dt, move.y * speed * dt)
                moved_dist = before_pos.distance_to(pygame.Vector2(transform.x, transform.y))
                if requested_move.length_squared() > 0 and moved_dist < 0.45:
                    ai.stuck_timer += dt
                    if ai.stuck_timer >= 0.3:
                        self._recover_stuck_npc(ai)
                else:
                    ai.stuck_timer = max(0.0, ai.stuck_timer - dt * 2.0)
            else:
                ai.stuck_timer = max(0.0, ai.stuck_timer - dt * 2.0)
            ai.last_pos.update(transform.x, transform.y)
            if renderer and ai.state in (AIController.STATE_ATTACK, AIController.STATE_CHASE):
                renderer.alpha = 255

    def _nearest_npc(self, source_entity, target_tags, max_range=220):
        source_transform = source_entity.get(Transform)
        source_pos = pygame.Vector2(source_transform.x, source_transform.y)
        best = None
        best_dist = max_range
        candidate_entities = []
        seen = set()
        for tag in target_tags:
            for entity in self._cached_combatants_by_tag.get(tag, []):
                if entity.id not in seen:
                    seen.add(entity.id)
                    candidate_entities.append(entity)
        for entity in candidate_entities:
            if not entity.alive:
                continue
            if entity is source_entity:
                continue
            transform = entity.get(Transform)
            if not transform:
                continue
            dist = source_pos.distance_to(pygame.Vector2(transform.x, transform.y))
            if dist < best_dist:
                best = entity
                best_dist = dist
        return best

    def _random_direction(self):
        direction = pygame.Vector2(random.uniform(-1, 1), random.uniform(-1, 1))
        return direction.normalize() if direction.length_squared() else pygame.Vector2(1, 0)

    def _npc_chase_direction(self, ai, transform, player_transform, to_player):
        start = self._entity_tile(transform)
        goal = self._entity_tile(player_transform)

        direct = to_player.normalize()
        if not self._path_blocked_between(start, goal):
            ai.path = []
            ai.path_index = 0
            return direct

        if ai.path_recalc_timer <= 0 or not ai.path or ai.path_index >= len(ai.path):
            ai.path = self._find_path(start, goal)
            ai.path_index = 0
            ai.path_recalc_timer = 1.0 if ai.ai_type.startswith("villager") else 0.75 if ai.ai_type == "police" else 0.5

        if not ai.path:
            ai.state_timer = max(ai.state_timer, 0.12)
            return pygame.Vector2()

        if ai.path_index < len(ai.path):
            target_tile = ai.path[ai.path_index]
            target_pos = pygame.Vector2(
                target_tile[0] * TILE_SIZE + TILE_SIZE / 2,
                target_tile[1] * TILE_SIZE + TILE_SIZE / 2,
            )
            npc_center = pygame.Vector2(transform.x + 18, transform.y + 26)
            vec = target_pos - npc_center
            if vec.length_squared() < 100:
                ai.path_index += 1
                if ai.path_index >= len(ai.path):
                    return direct
                target_tile = ai.path[ai.path_index]
                target_pos = pygame.Vector2(
                    target_tile[0] * TILE_SIZE + TILE_SIZE / 2,
                    target_tile[1] * TILE_SIZE + TILE_SIZE / 2,
                )
                vec = target_pos - npc_center
            if vec.length_squared() > 0:
                return vec.normalize()
        return pygame.Vector2()

    def _npc_move_toward_point(self, ai, transform, target_pos):
        target_transform = Transform(target_pos.x, target_pos.y)
        to_target = pygame.Vector2(target_pos.x - transform.x, target_pos.y - transform.y)
        if to_target.length_squared() == 0:
            return pygame.Vector2()
        return self._npc_chase_direction(ai, transform, target_transform, to_target)

    def _npc_follow_sleep_path(self, ai, transform):
        sleep_path = getattr(ai, "sleep_path", None) or []
        if not sleep_path:
            to_home = pygame.Vector2(ai.home_pos.x - transform.x, ai.home_pos.y - transform.y)
            if to_home.length_squared() <= 16:
                ai.sleeping = True
                transform.x = ai.home_pos.x
                transform.y = ai.home_pos.y
                return pygame.Vector2()
            ai.sleeping = False
            return self._npc_move_toward_point(ai, transform, ai.home_pos)

        while ai.sleep_path_index < len(sleep_path):
            target = sleep_path[ai.sleep_path_index]
            if pygame.Vector2(transform.x, transform.y).distance_to(target) <= 18:
                if ai.sleep_path_index == len(sleep_path) - 1:
                    ai.sleeping = True
                    transform.x = target.x
                    transform.y = target.y
                ai.sleep_path_index += 1
                continue
            ai.sleeping = False
            return self._npc_move_toward_point(ai, transform, target)
        ai.sleeping = True
        return pygame.Vector2()

    def _open_nearby_doors(self, transform, radius=28):
        probe = pygame.Rect(int(transform.x) - radius, int(transform.y) - radius, radius * 2 + TILE_SIZE, radius * 2 + TILE_SIZE)
        changed = False
        for entity in self._cached_openable_doors:
            structure = entity.get(StructureComponent)
            collider = entity.get(Collider)
            if not structure or not structure.openable or structure.is_open or not collider:
                continue
            if collider.get_rect().colliderect(probe):
                structure.is_open = True
                changed = True
        if changed:
            self._structure_cache_dirty = True

    def _villager_route_direction(self, ai, transform, pause_min, pause_max):
        work_points = getattr(ai, "work_points", None) or getattr(ai, "idle_route", None) or []
        if not work_points:
            if ai.state_timer <= 0:
                ai.state = AIController.STATE_WANDER
                ai.state_timer = random.uniform(1.0, 2.2)
                ai.wander_dir = self._random_direction()
            return ai.wander_dir if ai.state == AIController.STATE_WANDER else pygame.Vector2()

        if ai.state_timer > 0 or getattr(ai, "route_pause_timer", 0) > 0:
            return pygame.Vector2()

        target = work_points[ai.work_index % len(work_points)]
        if pygame.Vector2(transform.x, transform.y).distance_to(target) <= 20:
            ai.work_index = (ai.work_index + 1) % len(work_points)
            ai.route_pause_timer = random.uniform(pause_min, pause_max)
            return pygame.Vector2()
        return self._npc_move_toward_point(ai, transform, target)

    def _villager_trade_direction(self, ai, transform):
        task = getattr(ai, "trade_task", None)
        if not task:
            return None
        partner = task.get("partner")
        if not partner or not partner.alive:
            self._clear_trade_task(ai)
            return None
        partner_transform = partner.get(Transform)
        if not partner_transform:
            self._clear_trade_task(ai)
            return None

        partner_pos = pygame.Vector2(partner_transform.x, partner_transform.y)
        own_pos = pygame.Vector2(transform.x, transform.y)
        if own_pos.distance_to(partner_pos) <= 28:
            if task.get("initiator"):
                self._complete_villager_trade(ai)
            return pygame.Vector2()

        meeting_point = task.get("meeting_point") or (own_pos + partner_pos) * 0.5
        target = meeting_point if own_pos.distance_to(meeting_point) > 16 else partner_pos
        return self._npc_move_toward_point(ai, transform, target)

    def _crafter_work_direction(self, ai, transform):
        if self._crafter_should_store(ai):
            chest = getattr(ai, "storage_chest", None)
            if chest and chest.alive:
                chest_transform = chest.get(Transform)
                chest_pos = pygame.Vector2(chest_transform.x, chest_transform.y)
                if pygame.Vector2(transform.x, transform.y).distance_to(chest_pos) <= 24:
                    self._deposit_crafter_stock(ai)
                    ai.state_timer = random.uniform(0.12, 0.25)
                    return pygame.Vector2()
                return self._npc_move_toward_point(ai, transform, chest_pos)
        if self._crafter_needs_supplies(ai):
            chest = getattr(ai, "storage_chest", None)
            if chest and chest.alive:
                chest_transform = chest.get(Transform)
                chest_pos = pygame.Vector2(chest_transform.x, chest_transform.y)
                if pygame.Vector2(transform.x, transform.y).distance_to(chest_pos) <= 24:
                    self._withdraw_crafter_supplies(ai)
                    ai.state_timer = random.uniform(0.12, 0.25)
                    return pygame.Vector2()
                return self._npc_move_toward_point(ai, transform, chest_pos)
        return self._villager_route_direction(ai, transform, 0.15, 0.45)

    def _farmer_work_direction(self, ai, transform):
        farm_plots = [plot for plot in getattr(ai, "farm_plots", []) if plot.get("soil") and plot["soil"].alive]
        if not farm_plots:
            return self._villager_route_direction(ai, transform, 0.5, 1.1)

        if self._farmer_needs_seed_refill(ai):
            chest = getattr(ai, "storage_chest", None)
            if chest and chest.alive:
                chest_transform = chest.get(Transform)
                chest_pos = pygame.Vector2(chest_transform.x, chest_transform.y)
                if pygame.Vector2(transform.x, transform.y).distance_to(chest_pos) <= 24:
                    self._withdraw_farmer_supplies(ai)
                    ai.state_timer = random.uniform(0.15, 0.3)
                    return pygame.Vector2()
                return self._npc_move_toward_point(ai, transform, chest_pos)

        if self._farmer_should_store(ai):
            chest = getattr(ai, "storage_chest", None)
            if chest and chest.alive:
                chest_transform = chest.get(Transform)
                chest_pos = pygame.Vector2(chest_transform.x, chest_transform.y)
                if pygame.Vector2(transform.x, transform.y).distance_to(chest_pos) <= 24:
                    self._deposit_farmer_stock(ai)
                    ai.state_timer = random.uniform(0.15, 0.35)
                    return pygame.Vector2()
                return self._npc_move_toward_point(ai, transform, chest_pos)

        if ai.state_timer > 0:
            return pygame.Vector2()

        plot = farm_plots[ai.work_index % len(farm_plots)]
        target = plot["work_pos"]
        if pygame.Vector2(transform.x, transform.y).distance_to(target) <= 22:
            self._tend_farm_plot(ai, plot)
            ai.work_index = (ai.work_index + 1) % len(farm_plots)
            ai.state_timer = random.uniform(0.15, 0.35)
            return pygame.Vector2()
        return self._npc_move_toward_point(ai, transform, target)

    def _tend_farm_plot(self, ai, plot):
        crop = plot.get("crop")
        if crop is None or not crop.alive:
            seed_item = plot["seed_item"]
            if ai.stock.get(seed_item, 0) <= 0:
                return
            crop = self._create_resource_node(plot["plant_type"], int(plot["plot_pos"].x), int(plot["plot_pos"].y))
            crop_plant = crop.get(PlantComponent)
            crop_plant.growth_stage = GROWTH_SEED
            self.world.add(crop)
            plot["crop"] = crop
            ai.stock[seed_item] = max(0, ai.stock.get(seed_item, 0) - 1)
            return

        plant = crop.get(PlantComponent)
        if not plant:
            return
        if plant.harvested:
            crop.destroy()
            plot["crop"] = None
            return
        if plant.growth_stage < GROWTH_FULL:
            plant.growth_stage = min(GROWTH_FULL, plant.growth_stage + 1)
            return
        if plant.harvest():
            for item_id, qty in self._roll_loot(plot["plant_type"]):
                ai.stock[item_id] = ai.stock.get(item_id, 0) + qty
            crop.destroy()
            plot["crop"] = None

    def _farmer_needs_seed_refill(self, ai):
        needed_seed_types = {plot["seed_item"] for plot in getattr(ai, "farm_plots", [])}
        needs_food = ai.hunger < VILLAGER_EAT_THRESHOLD and ai.stock.get("bread", 0) < 1 and ai.stock.get("berry", 0) < 1
        return needs_food or any(ai.stock.get(seed_item, 0) < 2 for seed_item in needed_seed_types)

    def _farmer_should_store(self, ai):
        return (
            ai.stock.get("berry", 0) >= 6
            or ai.stock.get("wheat", 0) >= 6
            or ai.stock.get("berry_seed", 0) >= 8
            or ai.stock.get("wheat_seed", 0) >= 8
            or ai.stock.get("fiber", 0) >= 8
        )

    def _withdraw_farmer_supplies(self, ai):
        chest = getattr(ai, "storage_chest", None)
        if not chest or not chest.alive:
            return
        container = chest.get(Container)
        if not container:
            return
        for seed_item in sorted({plot["seed_item"] for plot in getattr(ai, "farm_plots", [])}):
            need = max(0, 4 - ai.stock.get(seed_item, 0))
            if need > 0:
                ai.stock[seed_item] = ai.stock.get(seed_item, 0) + self._take_from_container(container, seed_item, need)
        if ai.hunger < VILLAGER_EAT_THRESHOLD:
            ai.stock["bread"] = ai.stock.get("bread", 0) + self._take_from_container(container, "bread", 1)
            if ai.stock.get("bread", 0) < 1:
                ai.stock["berry"] = ai.stock.get("berry", 0) + self._take_from_container(container, "berry", 2)

    def _crafter_needs_supplies(self, ai):
        return (
            ai.stock.get("wheat", 0) < 3
            or ai.stock.get("wood", 0) < 3
            or ai.stock.get("stone", 0) < 2
            or ai.stock.get("fiber", 0) < 2
            or (ai.hunger < VILLAGER_EAT_THRESHOLD and ai.stock.get("bread", 0) < 1)
        )

    def _withdraw_crafter_supplies(self, ai):
        chest = getattr(ai, "storage_chest", None)
        if not chest or not chest.alive:
            return
        container = chest.get(Container)
        if not container:
            return
        for item_id, target_qty in (("wheat", 4), ("wood", 5), ("stone", 4), ("fiber", 4)):
            need = max(0, target_qty - ai.stock.get(item_id, 0))
            if need > 0:
                ai.stock[item_id] = ai.stock.get(item_id, 0) + self._take_from_container(container, item_id, need)
        if ai.hunger < VILLAGER_EAT_THRESHOLD:
            ai.stock["bread"] = ai.stock.get("bread", 0) + self._take_from_container(container, "bread", 1)
            if ai.stock.get("bread", 0) < 1:
                ai.stock["berry"] = ai.stock.get("berry", 0) + self._take_from_container(container, "berry", 2)

    def _crafter_should_store(self, ai):
        return (
            ai.stock.get("bread", 0) >= 2
            or ai.stock.get("rope", 0) >= 2
            or ai.stock.get("hoe_wood", 0) >= 2
            or ai.stock.get("sword_wood", 0) >= 1
        )

    def _deposit_crafter_stock(self, ai):
        chest = getattr(ai, "storage_chest", None)
        if not chest or not chest.alive:
            return
        container = chest.get(Container)
        if not container:
            return
        reserve_targets = {"bread": 1, "rope": 1, "hoe_wood": 1, "sword_wood": 0}
        for item_id, keep_qty in reserve_targets.items():
            qty = ai.stock.get(item_id, 0) - keep_qty
            if qty <= 0:
                continue
            leftover = self._add_to_container(container, item_id, qty)
            ai.stock[item_id] = keep_qty + leftover

    def _deposit_farmer_stock(self, ai):
        chest = getattr(ai, "storage_chest", None)
        if not chest or not chest.alive:
            return
        container = chest.get(Container)
        if not container:
            return
        for item_id in ("berry", "wheat", "berry_seed", "wheat_seed", "fiber"):
            qty = ai.stock.get(item_id, 0)
            if qty <= 0:
                continue
            leftover = self._add_to_container(container, item_id, qty)
            ai.stock[item_id] = leftover

    def _add_to_container(self, container, item_id, qty):
        item_data = ITEMS.get(item_id, {})
        max_stack = item_data.get("stack", MAX_STACK)

        for slot in container.inventory:
            if slot and slot.item_id == item_id and slot.qty < max_stack:
                added = min(qty, max_stack - slot.qty)
                slot.qty += added
                qty -= added
                if qty == 0:
                    return 0

        for index, slot in enumerate(container.inventory):
            if slot is None:
                added = min(qty, max_stack)
                container.inventory[index] = ItemStack(item_id, added)
                qty -= added
                if qty == 0:
                    return 0
        return qty

    def _take_from_container(self, container, item_id, qty):
        taken = 0
        for index, slot in enumerate(container.inventory):
            if not slot or slot.item_id != item_id:
                continue
            move = min(qty - taken, slot.qty)
            slot.qty -= move
            taken += move
            if slot.qty <= 0:
                container.inventory[index] = None
            if taken >= qty:
                break
        return taken

    def _spawn_trade_popup(self, entity, item_id, qty, positive=True):
        transform = entity.get(Transform) if entity else None
        if not transform:
            return
        self.trade_popups.append({
            "entity": entity,
            "item_id": item_id,
            "qty": qty,
            "positive": positive,
            "ttl": 1.0,
            "duration": 1.0,
            "rise": 0.0,
            "drift_x": random.randint(-12, 12),
            "world_pos": pygame.Vector2(transform.x, transform.y),
        })

    def _update_trade_popups(self, dt):
        active = []
        for popup in self.trade_popups:
            popup["ttl"] -= dt
            popup["rise"] += dt * 26
            entity = popup.get("entity")
            if entity and entity.alive:
                transform = entity.get(Transform)
                if transform:
                    popup["world_pos"] = pygame.Vector2(transform.x, transform.y)
            if popup["ttl"] > 0:
                active.append(popup)
        self.trade_popups = active

    def _entity_tile(self, transform):
        return (
            max(0, min(self.tilemap.width - 1, int((transform.x + TILE_SIZE / 2) // TILE_SIZE))),
            max(0, min(self.tilemap.height - 1, int((transform.y + TILE_SIZE / 2) // TILE_SIZE))),
        )

    def _path_blocked_between(self, start, goal):
        x0, y0 = start
        x1, y1 = goal
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy

        while True:
            if self._tile_is_blocked(x0, y0):
                return True
            if (x0, y0) == (x1, y1):
                return False
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy

    def _tile_is_blocked(self, tx, ty):
        if self.tilemap.is_solid(tx, ty):
            return True
        return (tx, ty) in self._cached_blocked_tiles

    def _find_path(self, start, goal):
        if start == goal:
            return []

        queue = deque([start])
        came_from = {start: None}
        directions = [(1, 0), (-1, 0), (0, 1), (0, -1)]

        while queue:
            current = queue.popleft()
            if current == goal:
                break
            for dx, dy in directions:
                nxt = (current[0] + dx, current[1] + dy)
                if nxt in came_from:
                    continue
                if not (0 <= nxt[0] < self.tilemap.width and 0 <= nxt[1] < self.tilemap.height):
                    continue
                if nxt != goal and self._tile_is_blocked(*nxt):
                    continue
                came_from[nxt] = current
                queue.append(nxt)

        if goal not in came_from:
            return []

        path = []
        node = goal
        while node and node != start:
            path.append(node)
            node = came_from[node]
        path.reverse()
        return path

    def _update_structures(self):
        for entity in self._cached_structure_entities:
            structure = entity.get(StructureComponent)
            renderer = entity.get(SpriteRenderer)
            transform = entity.get(Transform)
            if structure.openable and renderer:
                if structure.is_open and transform:
                    door_center = pygame.Vector2(transform.x + TILE_SIZE / 2, transform.y + TILE_SIZE / 2)
                    keep_open = False
                    for actor in [self.player] + self._current_npcs():
                        if not actor.alive:
                            continue
                        actor_transform = actor.get(Transform)
                        if actor_transform and door_center.distance_to(pygame.Vector2(actor_transform.x + 16, actor_transform.y + 16)) <= TILE_SIZE * 0.9:
                            keep_open = True
                            break
                    if not keep_open:
                        structure.is_open = False
                        self._structure_cache_dirty = True
                renderer.alpha = 180 if structure.is_open else 255

    def _handle_pickups(self):
        player_transform = self.player.get(Transform)
        inventory = self.player.get(Inventory)
        keys = pygame.key.get_pressed()
        player_pos = pygame.Vector2(player_transform.x + PLAYER_FOOTPRINT / 2, player_transform.y + PLAYER_FOOTPRINT - 16)

        for entity in self._cached_drops:
            item = entity.get(DroppedItem)
            transform = entity.get(Transform)
            drop_pos = pygame.Vector2(transform.x + 10, transform.y + 10)
            distance = player_pos.distance_to(drop_pos)
            if distance <= ITEM_PICKUP_RANGE:
                self.harvest_hint = f"E pick up {ITEMS[item.item_id]['name']}"
                if keys[pygame.K_e]:
                    leftover = inventory.add_item(item.item_id, item.qty)
                    if leftover == 0:
                        entity.destroy()
                        self._set_message(f"Picked up {ITEMS[item.item_id]['name']} x{item.qty}")
                    else:
                        item.qty = leftover
                        self._set_message("Inventory is full")

    def _selected_tool(self):
        return self.player.get(Inventory).get_selected()

    def _effective_harvest_time(self, entity, interact):
        selected = self._selected_tool()
        base = getattr(interact, "base_hold_time", interact.hold_time) or 0.2
        if not selected:
            return base

        plant = entity.get(PlantComponent)
        item = selected.data
        tags = set(item.get("harvest_tags", []))
        speed = item.get("speed", 1.0)
        power = item.get("harvest_power", 0)

        if plant:
            if plant.plant_type in ("tree",) and "tree" in tags:
                return max(0.22, base / (speed * max(1, power)))
            if plant.plant_type in ("stone_outcrop", "coal_vein", "iron_vein") and ("stone" in tags or "ore" in tags):
                if plant.plant_type == "iron_vein" and power < 2:
                    return base * 2.4
                return max(0.28, base / (speed * max(1, power)))
        return base

    def _can_harvest(self, entity):
        plant = entity.get(PlantComponent)
        selected = self._selected_tool()
        if not plant:
            return True
        if plant.plant_type == "iron_vein":
            return bool(selected and self._is_pickaxe(selected) and selected.data.get("harvest_power", 0) >= 2)
        if plant.plant_type in ("coal_vein", "stone_outcrop"):
            return bool(selected and self._is_pickaxe(selected))
        if plant.plant_type == "tree":
            return bool(selected and self._is_axe(selected))
        return True

    def _is_axe(self, stack):
        if not stack:
            return False
        family = stack.data.get("tool_family")
        if family:
            return family == "axe"
        return stack.item_id.startswith("axe_")

    def _is_pickaxe(self, stack):
        if not stack:
            return False
        family = stack.data.get("tool_family")
        if family:
            return family == "pickaxe"
        return stack.item_id.startswith("pickaxe_")

    def _close_inventory_views(self):
        self.show_inventory = False
        self.show_crafting = False
        self.craft_search_active = False
        self._close_open_container()

    def _close_open_container(self):
        if self.open_container_entity and self.open_container_entity.alive:
            container = self.open_container_entity.get(Container)
            if container:
                container.opened = False
        self.open_container_entity = None

    def _open_container(self, entity):
        container = entity.get(Container)
        if not container:
            return
        container.opened = True
        self.open_container_entity = entity
        self.show_inventory = True
        self.show_crafting = False
        self.craft_search_active = False

    def _container_is_accessible(self, entity):
        if not entity or not entity.alive:
            return False
        player_transform = self.player.get(Transform)
        target_transform = entity.get(Transform)
        if not player_transform or not target_transform:
            return False
        player_pos = pygame.Vector2(player_transform.x + PLAYER_FOOTPRINT / 2, player_transform.y + PLAYER_FOOTPRINT - 16)
        target_pos = pygame.Vector2(target_transform.x + TILE_SIZE / 2, target_transform.y + TILE_SIZE / 2)
        return player_pos.distance_to(target_pos) <= INTERACTION_RANGE + 18

    def _sync_open_container(self):
        if self.open_container_entity and (not self.show_inventory or not self._container_is_accessible(self.open_container_entity)):
            self._close_open_container()

    def _update_interactions(self):
        player_transform = self.player.get(Transform)
        keys = pygame.key.get_pressed()
        player_pos = pygame.Vector2(player_transform.x + PLAYER_FOOTPRINT / 2, player_transform.y + PLAYER_FOOTPRINT - 16)
        nearest = None
        nearest_dist = INTERACTION_RANGE
        trader = None
        trader_dist = INTERACTION_RANGE

        for entity in self._cached_interactables:
            interact = entity.get(Interactable)
            transform = entity.get(Transform)
            plant = entity.get(PlantComponent)
            structure = entity.get(StructureComponent)

            if plant and (plant.harvested or plant.growth_stage < GROWTH_MATURE):
                interact.stop_hold()
                continue

            target_pos = pygame.Vector2(transform.x + 20, transform.y + 20)
            distance = player_pos.distance_to(target_pos)
            if distance < nearest_dist:
                nearest = entity
                nearest_dist = distance

            if structure and structure.openable and distance <= INTERACTION_RANGE:
                self.harvest_hint = "E toggle door"

        for entity in self._cached_npcs:
            ai = entity.get(AIController)
            if ai.ai_type not in {"villager_farmer", "villager_crafter", "police"}:
                continue
            transform = entity.get(Transform)
            distance = player_pos.distance_to(pygame.Vector2(transform.x + 18, transform.y + 18))
            if distance < trader_dist:
                trader = entity
                trader_dist = distance

        if trader and (not nearest or trader_dist <= nearest_dist):
            ai = trader.get(AIController)
            self.harvest_hint = f"E trade with {ai.display_name}: {ai.trade_offer}"
            if keys[pygame.K_e] and self.trade_interact_cooldown <= 0:
                self._trade_with_npc(trader)
                self.trade_interact_cooldown = 0.35
            return

        if not nearest:
            if self.harvest_target and self.harvest_target.has(Interactable):
                self.harvest_target.get(Interactable).stop_hold()
            self.harvest_target = None
            return

        interact = nearest.get(Interactable)
        plant = nearest.get(PlantComponent)
        structure = nearest.get(StructureComponent)
        container = nearest.get(Container)

        if container:
            chest_open = nearest is self.open_container_entity
            self.harvest_hint = "E close chest" if chest_open else "E open chest"
            if keys[pygame.K_e] and self.instant_interact_cooldown <= 0:
                if chest_open:
                    self._close_open_container()
                    self._set_message("Chest closed")
                else:
                    self._open_container(nearest)
                    self._set_message("Chest opened")
                self.instant_interact_cooldown = 0.25
            return

        if structure and structure.openable:
            self.harvest_hint = "E toggle door"
            if keys[pygame.K_e] and self.instant_interact_cooldown <= 0:
                structure.toggle()
                self._structure_cache_dirty = True
                self._set_message("Door opened" if structure.is_open else "Door closed")
                self.instant_interact_cooldown = 0.18
            return

        label = interact.label
        if plant:
            label = f"{interact.label} ({GROWTH_NAMES[plant.growth_stage]})"
            if not self._can_harvest(nearest):
                self.harvest_hint = f"Need better tool to {plant.plant_type.replace('_', ' ')}"
                if self.harvest_target and self.harvest_target.has(Interactable):
                    self.harvest_target.get(Interactable).stop_hold()
                self.harvest_target = None
                return

        self.harvest_hint = f"Hold E to {label.lower()}"
        interact.hold_time = self._effective_harvest_time(nearest, interact)

        if not keys[pygame.K_e]:
            interact.stop_hold()
            self.harvest_target = nearest
            return

        if self.harvest_target is not nearest:
            if self.harvest_target and self.harvest_target.has(Interactable):
                self.harvest_target.get(Interactable).stop_hold()
            self.harvest_target = nearest
            interact.start_hold()
        else:
            interact.start_hold()

        if interact.hold_time == 0 or interact.is_complete():
            interact.stop_hold()
            self._harvest(nearest)

    def _trade_with_npc(self, npc_entity):
        ai = npc_entity.get(AIController)
        inventory = self.player.get(Inventory)

        if ai.ai_type == "villager_farmer":
            if inventory.count_item("wood") >= 2:
                inventory.remove_item("wood", 2)
                inventory.add_item("berry", 4)
                ai.stock["wood"] = ai.stock.get("wood", 0) + 2
                self._set_message("Farmer traded 4 berries for 2 wood")
            elif inventory.count_item("stone") >= 1:
                inventory.remove_item("stone", 1)
                inventory.add_item("berry_seed", 2)
                self._set_message("Farmer traded 2 berry seeds for 1 stone")
            else:
                self._set_message("Farmer wants wood or stone")
        elif ai.ai_type == "villager_crafter":
            if inventory.has_items({"wood": 2, "stone": 2}):
                inventory.remove_item("wood", 2)
                inventory.remove_item("stone", 2)
                inventory.add_item("rope", 1)
                self._set_message("Crafter traded 1 rope for wood and stone")
            elif inventory.has_items({"wood": 3, "fiber": 2}):
                inventory.remove_item("wood", 3)
                inventory.remove_item("fiber", 2)
                inventory.add_item("hoe_wood", 1)
                self._set_message("Crafter built you a wood hoe")
            else:
                self._set_message("Crafter wants wood, stone, or fiber")
        else:
            if inventory.count_item("berry") >= 2:
                inventory.remove_item("berry", 2)
                inventory.add_item("coal", 1)
                self._set_message("Guard traded patrol supplies for 1 coal")
            else:
                self._set_message("Guard says to bring berries for patrol fuel")

    def _harvest(self, entity):
        plant = entity.get(PlantComponent)
        if not plant or not plant.harvest():
            return
        transform = entity.get(Transform)
        renderer = entity.get(SpriteRenderer)
        if renderer:
            renderer.flash_hurt()
        for item_id, qty in self._roll_loot(plant.plant_type):
            self._spawn_drop(item_id, qty, transform.x + random.randint(-8, 8), transform.y + random.randint(-8, 8))
        selected = self._selected_tool()
        if selected and selected.durability is not None:
            self.player.get(Inventory).use_durability(1)
        self._set_message(f"Gathered {plant.plant_type.replace('_', ' ')}")

    def _roll_loot(self, table_name):
        drops = []
        for item_id, min_q, max_q, chance in LOOT_TABLES.get(table_name, []):
            if random.random() <= chance:
                drops.append((item_id, random.randint(min_q, max_q)))
        return drops

    def _drop_npc_loot(self, entity):
        ai = entity.get(AIController)
        transform = entity.get(Transform)
        for item_id, qty in self._roll_loot(f"{ai.ai_type}_creature"):
            self._spawn_drop(item_id, qty, transform.x + random.randint(-10, 10), transform.y + random.randint(-10, 10))
        entity.destroy()
        self._set_message(f"Defeated a {ai.ai_type} creature")

    def _spawn_drop(self, item_id, qty, x, y):
        for entity in self._cached_drops:
            if not entity.alive:
                continue
            drop = entity.get(DroppedItem)
            transform = entity.get(Transform)
            if not drop or not transform or drop.item_id != item_id:
                continue
            if pygame.Vector2(transform.x, transform.y).distance_to((x, y)) <= 28:
                drop.qty += qty
                drop._despawn_timer = DROP_DESPAWN_TIME
                return

        if len(self._cached_drops) >= WORLD_DROP_LIMIT and self._cached_drops:
            oldest = min(
                (entity for entity in self._cached_drops if entity.alive),
                key=lambda entity: entity.get(DroppedItem)._despawn_timer,
                default=None,
            )
            if oldest:
                oldest.destroy()

        entity = Entity(f"drop_{item_id}")
        entity.tags.add("drop")
        entity.add(Transform(x, y))
        entity.add(DroppedItem(item_id, qty))
        self.world.add(entity)
        self._cached_drops.append(entity)

    def _world_mouse_tile(self):
        mx, my = pygame.mouse.get_pos()
        world_x = mx + self.camera_x
        world_y = my + self.camera_y
        return int(world_x // TILE_SIZE), int(world_y // TILE_SIZE)

    def _place_selected_structure(self):
        inventory = self.player.get(Inventory)
        selected = inventory.get_selected()
        if not selected:
            return
        item = selected.data
        if item.get("tool_family") == "hoe":
            self._till_farmland(selected)
            return
        placeable = item.get("placeable")
        if not placeable:
            self._set_message("Selected item cannot be placed")
            return

        tx, ty = self._world_mouse_tile()
        x = tx * TILE_SIZE
        y = ty * TILE_SIZE
        player_transform = self.player.get(Transform)
        player_pos = pygame.Vector2(player_transform.x + PLAYER_FOOTPRINT / 2, player_transform.y + PLAYER_FOOTPRINT - 16)
        target_pos = pygame.Vector2(x + TILE_SIZE / 2, y + TILE_SIZE / 2)
        if player_pos.distance_to(target_pos) > BUILD_RANGE:
            self._set_message("Too far away to place that")
            return
        if self.tilemap.get(tx, ty) in SOLID_TILES:
            self._set_message("Cannot place on water")
            return
        if self._position_occupied(x, y, TILE_SIZE, TILE_SIZE):
            self._set_message("Something is already there")
            return

        structure = self._create_structure(placeable, x, y)
        self.world.add(structure)
        self._structure_cache_dirty = True
        selected.qty -= 1
        if selected.qty <= 0:
            inventory.hotbar[inventory.selected_hotbar] = None
        self._set_message(f"Placed {item['name']}")

    def _till_farmland(self, selected):
        tx, ty = self._world_mouse_tile()
        x = tx * TILE_SIZE
        y = ty * TILE_SIZE
        player_transform = self.player.get(Transform)
        player_pos = pygame.Vector2(player_transform.x + PLAYER_FOOTPRINT / 2, player_transform.y + PLAYER_FOOTPRINT - 16)
        target_pos = pygame.Vector2(x + TILE_SIZE / 2, y + TILE_SIZE / 2)
        if player_pos.distance_to(target_pos) > BUILD_RANGE:
            self._set_message("Too far away to till that soil")
            return
        if self.tilemap.get(tx, ty) not in {TILE_GRASS, TILE_DIRT}:
            self._set_message("Hoes work on grass or dirt")
            return
        if (x, y) in self._cached_structure_positions:
            self._set_message("That tile is already occupied")
            return
        self.world.add(self._create_structure("farmland", x, y))
        self._structure_cache_dirty = True
        if selected.durability is not None:
            self.player.get(Inventory).use_durability(1)
        self._set_message("Tilled farmland")

    def _update_camera(self, force_center=False):
        transform = self.player.get(Transform)
        feet_x = transform.x + PLAYER_FOOTPRINT / 2
        feet_y = transform.y + PLAYER_FOOTPRINT - 18
        player_screen_x = feet_x - self.camera_x
        player_screen_y = feet_y - self.camera_y
        target_x = self.camera_x
        target_y = self.camera_y
        if force_center:
            target_x = feet_x - SCREEN_WIDTH * 0.5
            target_y = feet_y - SCREEN_HEIGHT * 0.5
        else:
            left = SCREEN_WIDTH * 0.5 - CAMERA_DEADZONE_X
            right = SCREEN_WIDTH * 0.5 + CAMERA_DEADZONE_X
            top = SCREEN_HEIGHT * 0.5 - CAMERA_DEADZONE_Y
            bottom = SCREEN_HEIGHT * 0.5 + CAMERA_DEADZONE_Y
            if player_screen_x < left:
                target_x = feet_x - left
            elif player_screen_x > right:
                target_x = feet_x - right
            if player_screen_y < top:
                target_y = feet_y - top
            elif player_screen_y > bottom:
                target_y = feet_y - bottom
        self.camera_x += (target_x - self.camera_x) * CAMERA_LERP
        self.camera_y += (target_y - self.camera_y) * CAMERA_LERP
        max_camera_x = max(0, self.tilemap.width * TILE_SIZE - SCREEN_WIDTH)
        max_camera_y = max(0, self.tilemap.height * TILE_SIZE - SCREEN_HEIGHT)
        self.camera_x = max(0, min(self.camera_x, max_camera_x))
        self.camera_y = max(0, min(self.camera_y, max_camera_y))

    def _eat_selected_food(self):
        inventory = self.player.get(Inventory)
        selected = inventory.get_selected()
        if not selected:
            self._set_message("Select a food item in the hotbar first")
            return
        if selected.data.get("type") != ITEM_FOOD:
            self._set_message("That item is not edible")
            return
        self.player.get(PlayerStats).eat(selected.data.get("food_restore", 0))
        selected.qty -= 1
        if selected.qty <= 0:
            inventory.hotbar[inventory.selected_hotbar] = None
        self._set_message(f"Ate {selected.name}")

    def _drop_selected_item(self):
        inventory = self.player.get(Inventory)
        selected = inventory.get_selected()
        if not selected:
            return
        item_id = selected.item_id
        selected.qty -= 1
        if selected.qty <= 0:
            inventory.hotbar[inventory.selected_hotbar] = None
        player_transform = self.player.get(Transform)
        self._spawn_drop(item_id, 1, player_transform.x + 18, player_transform.y + PLAYER_FOOTPRINT - 18)
        self._set_message(f"Dropped {ITEMS[item_id]['name']}")

    def _selected_recipe(self):
        filtered = self._filtered_recipe_order()
        if not filtered:
            return None, None
        recipe_id = filtered[self.selected_recipe_index]
        return recipe_id, RECIPES[recipe_id]

    def _filtered_recipe_order(self):
        query = self.craft_search_text.strip().lower()
        if not query:
            return self.recipe_order
        filtered = []
        for recipe_id in self.recipe_order:
            recipe = RECIPES[recipe_id]
            haystack = " ".join([
                recipe["name"].lower(),
                recipe_id.lower(),
                " ".join(recipe["ingredients"].keys()).lower(),
            ])
            if query in haystack:
                filtered.append(recipe_id)
        return filtered

    def _clamp_recipe_selection(self):
        filtered = self._filtered_recipe_order()
        if not filtered:
            self.selected_recipe_index = 0
            self.recipe_scroll_offset = 0
        else:
            self.selected_recipe_index = max(0, min(self.selected_recipe_index, len(filtered) - 1))
            visible_count = 8
            max_offset = max(0, len(filtered) - visible_count)
            self.recipe_scroll_offset = max(0, min(self.recipe_scroll_offset, max_offset))
            if self.selected_recipe_index < self.recipe_scroll_offset:
                self.recipe_scroll_offset = self.selected_recipe_index
            elif self.selected_recipe_index >= self.recipe_scroll_offset + visible_count:
                self.recipe_scroll_offset = self.selected_recipe_index - visible_count + 1

    def _station_nearby(self, station_name):
        if station_name is None:
            return True
        player_transform = self.player.get(Transform)
        player_pos = pygame.Vector2(player_transform.x + PLAYER_FOOTPRINT / 2, player_transform.y + PLAYER_FOOTPRINT - 16)
        for entity in self._cached_structure_entities:
            structure = entity.get(StructureComponent)
            if structure.station != station_name:
                continue
            transform = entity.get(Transform)
            structure_pos = pygame.Vector2(transform.x + TILE_SIZE / 2, transform.y + TILE_SIZE / 2)
            if player_pos.distance_to(structure_pos) <= INTERACTION_RANGE + 25:
                return True
        return False

    def _can_craft(self, recipe):
        inventory = self.player.get(Inventory)
        return inventory.has_items(recipe["ingredients"]) and self._station_nearby(recipe["station"])

    def _craft_selected_recipe(self):
        recipe_id, recipe = self._selected_recipe()
        if not recipe_id:
            return None
        if not self._can_craft(recipe):
            return None
        inventory = self.player.get(Inventory)
        for item_id, qty in recipe["ingredients"].items():
            inventory.remove_item(item_id, qty)
        inventory.add_item(recipe_id, recipe["result_qty"])
        return recipe["name"]

    def _handle_left_click(self, pos):
        if self.craft_search_rect and self.craft_search_rect.collidepoint(pos):
            self.craft_search_active = True
            return
        for rect, ref in self.mouse_slot_refs:
            if rect.collidepoint(pos):
                slot_list, index = ref
                slot = slot_list[index]
                slot_list[index], self.cursor_stack = self.cursor_stack, slot
                self._show_selected_item_name(self.player.get(Inventory).get_selected())
                self.craft_search_active = False
                return
        for rect, index in self.recipe_click_refs:
            if rect.collidepoint(pos):
                self.selected_recipe_index = index
                self.craft_search_active = False
                return
        if self.craft_output_rect and self.craft_output_rect.collidepoint(pos):
            crafted = self._craft_selected_recipe()
            if crafted:
                self._set_message(f"Crafted {crafted}")
            self.craft_search_active = False

    def _draw(self):
        self.mouse_slot_refs = []
        self.recipe_click_refs = []
        self.menu_buttons = {}
        self.craft_output_rect = None
        self.inventory_panel_rect = None
        self.container_panel_rect = None
        self.craft_search_rect = None
        self.hover_stack = None
        self.screen.fill(COL_BG)
        self.tilemap.draw(self.screen, int(self.camera_x), int(self.camera_y), SCREEN_WIDTH, SCREEN_HEIGHT)
        self._draw_entities()
        self._draw_day_night_overlay()
        self._draw_ui()
        pygame.display.flip()

    def _draw_entities(self):
        drawables = []
        view_rect = pygame.Rect(int(self.camera_x) - 96, int(self.camera_y) - 128, SCREEN_WIDTH + 192, SCREEN_HEIGHT + 256)
        for entity in self._cached_all_entities:
            transform = entity.get(Transform)
            renderer = entity.get(SpriteRenderer)
            if renderer and transform:
                world_rect = pygame.Rect(int(transform.x), int(transform.y), renderer.width, renderer.height)
                if "player" in entity.tags:
                    world_rect.x += (PLAYER_FOOTPRINT - renderer.width) // 2
                    world_rect.y -= (renderer.height - PLAYER_FOOTPRINT)
                elif "tree" in entity.tags:
                    world_rect.x += (TREE_FOOTPRINT - renderer.width) // 2
                    world_rect.y -= (renderer.height - TREE_FOOTPRINT)
                if not view_rect.colliderect(world_rect):
                    continue
                drawables.append((renderer.layer, transform.y + TILE_SIZE, entity))
            elif entity.has(DroppedItem):
                if not view_rect.colliderect(pygame.Rect(int(transform.x), int(transform.y), 32, 32)):
                    continue
                drawables.append((LAYER_ITEMS, transform.y, entity))
        drawables.sort(key=lambda entry: (entry[0], entry[1]))

        for _, _, entity in drawables:
            transform = entity.get(Transform)
            renderer = entity.get(SpriteRenderer)
            if entity.has(DroppedItem):
                screen_x = int(transform.x - self.camera_x)
                screen_y = int(transform.y - self.camera_y)
            else:
                screen_x, screen_y = self._entity_screen_position(entity, transform, renderer)
            if entity.has(DroppedItem):
                self._draw_drop(entity, screen_x, screen_y)
                continue
            plant = entity.get(PlantComponent)
            structure = entity.get(StructureComponent)
            if plant and plant.harvested:
                pygame.draw.ellipse(self.screen, (40, 40, 40), pygame.Rect(screen_x + 10, screen_y + 36, 26, 12))
                continue
            if renderer:
                sprite = renderer._load_sprite()
                if structure and structure.openable and structure.is_open:
                    ghost = pygame.Surface((renderer.width, renderer.height), pygame.SRCALPHA)
                    if sprite is None:
                        self._draw_structure_fallback(ghost, pygame.Rect(0, 0, renderer.width, renderer.height), structure.structure_type)
                    else:
                        renderer.draw(ghost, 0, 0)
                    ghost.set_alpha(145)
                    self.screen.blit(ghost, (screen_x, screen_y))
                else:
                    if "player" in entity.tags and sprite is None:
                        self._draw_player_fallback(screen_x, screen_y)
                    elif ai := entity.get(AIController):
                        if ai.ai_type in {"villager_farmer", "villager_crafter", "police"} and sprite is None:
                            self._draw_npc_fallback(screen_x, screen_y, ai.ai_type)
                        else:
                            renderer.draw(self.screen, screen_x, screen_y)
                    elif plant:
                        if plant.plant_type == "tree" and sprite is None:
                            self._draw_tree_fallback(screen_x, screen_y, plant.size_scale())
                        else:
                            scale = plant.size_scale()
                            w = max(12, int(renderer.width * scale))
                            h = max(12, int(renderer.height * scale))
                            scaled = renderer.copy_scaled(w, h)
                            draw_x = screen_x + (renderer.width - w) // 2
                            draw_y = screen_y + (renderer.height - h)
                            scaled.draw(self.screen, draw_x, draw_y)
                    elif structure and sprite is None:
                        self._draw_structure_fallback(
                            self.screen,
                            pygame.Rect(screen_x, screen_y, renderer.width, renderer.height),
                            structure.structure_type,
                        )
                    else:
                        renderer.draw(self.screen, screen_x, screen_y)
                ai = entity.get(AIController)
                if ai and getattr(ai, "sleeping", False):
                    self._draw_sleep_indicator(screen_x, screen_y)

        self._draw_attack_ring()
        self._draw_held_item()
        self._draw_interaction_progress()
        self._draw_trade_popups()

    def _draw_player_fallback(self, screen_x, screen_y):
        self._draw_humanoid_fallback(
            screen_x,
            screen_y,
            skin_color=(228, 196, 164),
            hair_color=(76, 54, 38),
            torso_color=(78, 116, 188),
            leg_color=(48, 74, 120),
            accent_color=(214, 182, 62),
        )

    def _draw_npc_fallback(self, screen_x, screen_y, ai_type):
        palettes = {
            "villager_farmer": {
                "skin_color": (222, 190, 156),
                "hair_color": (94, 66, 42),
                "torso_color": (156, 126, 62),
                "leg_color": (94, 118, 58),
                "accent_color": (232, 214, 118),
            },
            "villager_crafter": {
                "skin_color": (232, 202, 170),
                "hair_color": (56, 50, 62),
                "torso_color": (86, 128, 162),
                "leg_color": (68, 84, 116),
                "accent_color": (194, 224, 240),
            },
            "police": {
                "skin_color": (218, 184, 148),
                "hair_color": (42, 44, 52),
                "torso_color": (54, 86, 150),
                "leg_color": (38, 54, 98),
                "accent_color": (224, 198, 96),
            },
        }
        self._draw_humanoid_fallback(screen_x, screen_y, **palettes.get(ai_type, palettes["villager_farmer"]))

    def _draw_humanoid_fallback(self, screen_x, screen_y, skin_color, hair_color, torso_color, leg_color, accent_color):
        shadow = pygame.Rect(screen_x + 9, screen_y + 84, 30, 10)
        pygame.draw.ellipse(self.screen, (0, 0, 0, 80), shadow)
        head = pygame.Rect(screen_x + 11, screen_y + 6, 26, 24)
        hair = pygame.Rect(screen_x + 10, screen_y + 3, 28, 9)
        body = pygame.Rect(screen_x + 12, screen_y + 30, 24, 38)
        legs = pygame.Rect(screen_x + 15, screen_y + 66, 18, 22)
        scarf = pygame.Rect(screen_x + 10, screen_y + 42, 28, 7)
        pygame.draw.rect(self.screen, skin_color, head, border_radius=8)
        pygame.draw.rect(self.screen, hair_color, hair, border_radius=5)
        pygame.draw.rect(self.screen, torso_color, body, border_radius=6)
        pygame.draw.rect(self.screen, leg_color, legs, border_radius=4)
        pygame.draw.rect(self.screen, accent_color, scarf, border_radius=3)
        pygame.draw.circle(self.screen, COL_BLACK, (screen_x + 20, screen_y + 18), 2)
        pygame.draw.circle(self.screen, COL_BLACK, (screen_x + 29, screen_y + 18), 2)
        pygame.draw.rect(self.screen, COL_BLACK, head, 2, border_radius=8)
        pygame.draw.rect(self.screen, COL_BLACK, body, 2, border_radius=6)
        pygame.draw.rect(self.screen, COL_BLACK, legs, 2, border_radius=4)

    def _draw_structure_fallback(self, surface, rect, structure_type):
        if structure_type == "wall_wood":
            pygame.draw.rect(surface, (128, 92, 54), rect, border_radius=4)
            for offset in (10, 24, 38, 52):
                pygame.draw.line(surface, (166, 126, 82), (rect.x + 6, rect.y + offset), (rect.right - 6, rect.y + offset), 2)
            pygame.draw.rect(surface, (68, 44, 24), rect, 3, border_radius=4)
        elif structure_type == "door_wood":
            pygame.draw.rect(surface, (116, 78, 42), rect, border_radius=4)
            inner = rect.inflate(-14, -8)
            pygame.draw.rect(surface, (148, 104, 60), inner, border_radius=4)
            pygame.draw.circle(surface, (214, 182, 62), (inner.right - 8, inner.centery), 3)
            pygame.draw.rect(surface, (58, 34, 18), rect, 3, border_radius=4)
        elif structure_type == "bed":
            frame = pygame.Rect(rect.x + 4, rect.y + rect.height - 18, rect.width - 8, 14)
            pillow = pygame.Rect(rect.x + 8, rect.y + 4, rect.width - 16, 12)
            blanket = pygame.Rect(rect.x + 8, rect.y + 16, rect.width - 16, rect.height - 28)
            pygame.draw.rect(surface, (92, 62, 38), frame, border_radius=3)
            pygame.draw.rect(surface, (230, 224, 206), pillow, border_radius=4)
            pygame.draw.rect(surface, (176, 62, 62), blanket, border_radius=4)
            pygame.draw.rect(surface, (52, 28, 22), rect, 2, border_radius=4)
        elif structure_type == "chest_wood":
            lid = pygame.Rect(rect.x + 4, rect.y + 6, rect.width - 8, rect.height // 2 - 2)
            base = pygame.Rect(rect.x + 4, rect.y + rect.height // 2, rect.width - 8, rect.height // 2 - 8)
            pygame.draw.rect(surface, (146, 108, 62), lid, border_radius=4)
            pygame.draw.rect(surface, (122, 86, 48), base, border_radius=4)
            band = pygame.Rect(rect.centerx - 4, rect.y + 8, 8, rect.height - 16)
            latch = pygame.Rect(rect.centerx - 6, rect.centery - 2, 12, 10)
            pygame.draw.rect(surface, (188, 160, 82), band, border_radius=2)
            pygame.draw.rect(surface, (206, 182, 92), latch, border_radius=2)
            pygame.draw.rect(surface, (68, 42, 24), rect.inflate(-6, -6), 2, border_radius=4)
        elif structure_type == "farmland":
            pygame.draw.rect(surface, COL_FARMLAND, rect, border_radius=3)
            for offset in (12, 28, 44):
                pygame.draw.line(surface, (78, 48, 26), (rect.x + 6, rect.y + offset), (rect.right - 6, rect.y + offset), 2)
            pygame.draw.rect(surface, (64, 38, 20), rect, 2, border_radius=3)
        elif structure_type == "campfire":
            center = (rect.centerx, rect.centery + 2)
            pygame.draw.line(surface, (92, 60, 30), (rect.x + 8, rect.bottom - 8), (rect.right - 8, rect.y + 14), 4)
            pygame.draw.line(surface, (92, 60, 30), (rect.right - 8, rect.bottom - 8), (rect.x + 8, rect.y + 14), 4)
            flame = [(center[0], rect.y + 4), (rect.right - 12, rect.bottom - 12), (rect.x + 12, rect.bottom - 12)]
            pygame.draw.polygon(surface, (238, 136, 36), flame)
            ember = [(center[0], rect.y + 12), (rect.right - 18, rect.bottom - 14), (rect.x + 18, rect.bottom - 14)]
            pygame.draw.polygon(surface, (255, 204, 84), ember)
        elif structure_type == "furnace":
            pygame.draw.rect(surface, (118, 118, 126), rect, border_radius=4)
            mouth = pygame.Rect(rect.x + 12, rect.y + 20, rect.width - 24, rect.height - 24)
            pygame.draw.rect(surface, (50, 50, 58), mouth, border_radius=4)
            pygame.draw.rect(surface, (62, 62, 70), pygame.Rect(rect.x + 14, rect.y + 8, rect.width - 28, 8), border_radius=3)
            pygame.draw.rect(surface, (42, 42, 48), rect, 3, border_radius=4)
        else:
            pygame.draw.rect(surface, (150, 110, 70), rect, border_radius=3)
            pygame.draw.rect(surface, (58, 40, 22), rect, 2, border_radius=3)

    def _draw_tree_fallback(self, screen_x, screen_y, scale):
        draw_width = max(24, int(TREE_WIDTH * scale))
        draw_height = max(48, int(TREE_HEIGHT * scale))
        draw_x = screen_x + (TREE_WIDTH - draw_width) // 2
        draw_y = screen_y + (TREE_HEIGHT - draw_height)

        trunk_w = max(12, int(draw_width * 0.22))
        trunk_h = max(24, int(draw_height * 0.38))
        trunk_x = draw_x + draw_width // 2 - trunk_w // 2
        trunk_y = draw_y + draw_height - trunk_h
        trunk_rect = pygame.Rect(trunk_x, trunk_y, trunk_w, trunk_h)
        pygame.draw.rect(self.screen, COL_TREE_TRUNK, trunk_rect, border_radius=3)
        pygame.draw.rect(self.screen, (55, 35, 20), trunk_rect, 2, border_radius=3)

        leaf_radius = max(18, int(draw_width * 0.23))
        centers = [
            (draw_x + draw_width // 2, draw_y + leaf_radius + 2),
            (draw_x + draw_width // 2 - leaf_radius, draw_y + leaf_radius + 12),
            (draw_x + draw_width // 2 + leaf_radius, draw_y + leaf_radius + 12),
            (draw_x + draw_width // 2, draw_y + leaf_radius + 24),
        ]
        colors = [COL_TREE_LEAVES2, COL_TREE_LEAVES, COL_TREE_LEAVES, COL_TREE_LEAVES2]
        for center, color in zip(centers, colors):
            pygame.draw.circle(self.screen, color, center, leaf_radius)
            pygame.draw.circle(self.screen, (24, 60, 24), center, leaf_radius, 2)

    def _draw_drop(self, entity, screen_x, screen_y):
        if not entity.alive:
            return
        drop = entity.get(DroppedItem)
        bob = int(drop._bob_y)
        pygame.draw.ellipse(self.screen, (0, 0, 0, 80), pygame.Rect(screen_x + 6, screen_y + 22, 22, 8))
        icon = self._item_icon(drop.item_id, (18, 18))
        rect = pygame.Rect(screen_x + 8, screen_y + 8 + bob, 18, 18)
        pygame.draw.rect(self.screen, COL_UI_SLOT, rect.inflate(4, 4), border_radius=5)
        if icon:
            self.screen.blit(icon, rect.topleft)
        else:
            pygame.draw.rect(self.screen, ITEMS.get(drop.item_id, {}).get("color", COL_DROP_ITEM), rect, border_radius=4)
        pygame.draw.rect(self.screen, COL_BLACK, rect, 2, border_radius=4)

    def _draw_attack_ring(self):
        if self.attack_cooldown <= 0.15:
            return
        transform = self.player.get(Transform)
        center = (int(transform.x - self.camera_x + PLAYER_FOOTPRINT / 2), int(transform.y - self.camera_y + PLAYER_FOOTPRINT - 18))
        pygame.draw.circle(self.screen, COL_YELLOW, center, 44, 2)

    def _draw_interaction_progress(self):
        if not self.harvest_target or not self.harvest_target.has(Interactable):
            return
        interact = self.harvest_target.get(Interactable)
        if interact.progress <= 0:
            return
        player_transform = self.player.get(Transform)
        screen_x = int(player_transform.x - self.camera_x + PLAYER_FOOTPRINT / 2 - 28)
        screen_y = int(player_transform.y - self.camera_y - (PLAYER_HEIGHT - PLAYER_FOOTPRINT) - 10)
        outer = pygame.Rect(screen_x, screen_y, 58, 8)
        inner = pygame.Rect(screen_x + 1, screen_y + 1, int(56 * interact.progress), 6)
        pygame.draw.rect(self.screen, COL_BLACK, outer)
        pygame.draw.rect(self.screen, COL_HUNGER_BAR, inner)

    def _draw_trade_popups(self):
        for popup in self.trade_popups:
            ratio = max(0.0, min(1.0, popup["ttl"] / popup["duration"]))
            alpha = int(255 * ratio)
            color = COL_GREEN if popup["positive"] else COL_RED
            text = self.small_font.render(f"{'+' if popup['positive'] else '-'}{popup['qty']}", True, color)
            text.set_alpha(alpha)
            world_pos = popup["world_pos"]
            screen_x = int(world_pos.x - self.camera_x + 18 + popup["drift_x"])
            screen_y = int(world_pos.y - self.camera_y - 20 - popup["rise"])
            bg = pygame.Surface((text.get_width() + 26, max(18, text.get_height()) + 6), pygame.SRCALPHA)
            bg.fill((18, 22, 18, min(180, alpha)))
            self.screen.blit(bg, (screen_x - 8, screen_y - 2))
            icon = self._item_icon(popup["item_id"], (14, 14))
            if icon:
                icon = icon.copy()
                icon.set_alpha(alpha)
                self.screen.blit(icon, (screen_x - 4, screen_y + 1))
            else:
                icon_rect = pygame.Rect(screen_x - 4, screen_y + 1, 14, 14)
                pygame.draw.rect(self.screen, ITEMS.get(popup["item_id"], {}).get("color", COL_WHITE), icon_rect, border_radius=3)
                pygame.draw.rect(self.screen, COL_BLACK, icon_rect, 1, border_radius=3)
            self.screen.blit(text, (screen_x + 14, screen_y))

    def _draw_sleep_indicator(self, screen_x, screen_y):
        text = self.small_font.render("Zz", True, COL_WHITE)
        shadow = self.small_font.render("Zz", True, COL_BLACK)
        x = screen_x + 18
        y = screen_y - 12
        self.screen.blit(shadow, (x + 1, y + 1))
        self.screen.blit(text, (x, y))

    def _draw_day_night_overlay(self):
        if not self._is_night():
            return
        darkness = 90 if self.time_of_day >= 0.82 or self.time_of_day <= 0.14 else 55
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((12, 20, 38, darkness))
        self.screen.blit(overlay, (0, 0))

    def _draw_ui(self):
        if self.game_mode == "playing":
            self._draw_stat_bars()
            self._draw_hotbar()
            self._draw_minimap_hint()
            if self.show_inventory:
                self._draw_inventory_panel()
                if self.open_container_entity:
                    self._draw_container_panel()
                else:
                    self._draw_crafting_panel(linked=True)
            if self.message_timer > 0:
                self._draw_message()
            if self.selected_item_label_timer > 0 and self.selected_item_label:
                self._draw_selected_item_label()
            if self.harvest_hint:
                text = self.font.render(self.harvest_hint, True, COL_WHITE)
                bg = pygame.Surface((text.get_width() + 16, text.get_height() + 10), pygame.SRCALPHA)
                bg.fill(COL_UI_BG)
                self.screen.blit(bg, (SCREEN_WIDTH // 2 - bg.get_width() // 2, SCREEN_HEIGHT - 106))
                self.screen.blit(text, (SCREEN_WIDTH // 2 - text.get_width() // 2, SCREEN_HEIGHT - 101))
            if self.cursor_stack:
                self._draw_cursor_stack()
            if self.hover_stack:
                self._draw_hover_tooltip(self.hover_stack)
        elif self.game_mode in {"paused", "dead"}:
            self._draw_stat_bars()
            self._draw_hotbar()
            self._draw_minimap_hint()
            if self.message_timer > 0:
                self._draw_message()

        if self.game_mode == "main_menu":
            self._draw_main_menu()
        elif self.game_mode == "paused":
            self._draw_pause_menu()
        elif self.game_mode == "dead":
            self._draw_death_menu()

    def _draw_stat_bars(self):
        stats = self.player.get(PlayerStats)
        health = self.player.get(Health)
        bars = [
            ("HP", health.hp / health.max_hp, COL_HP_BAR),
            ("Hunger", stats.hunger / PLAYER_MAX_HUNGER, COL_HUNGER_BAR),
            ("Stamina", stats.stamina / PLAYER_MAX_STAMINA, COL_STAMINA_BAR),
        ]
        x = 16
        y = 16
        for label, ratio, color in bars:
            pygame.draw.rect(self.screen, COL_BAR_BG, (x, y, 190, 18), border_radius=3)
            pygame.draw.rect(self.screen, color, (x, y, int(190 * max(0, ratio)), 18), border_radius=3)
            self.screen.blit(self.small_font.render(label, True, COL_WHITE), (x + 6, y + 2))
            y += 24

    def _draw_hotbar(self):
        inventory = self.player.get(Inventory)
        total_width = HOTBAR_SLOTS * (SLOT_SIZE + SLOT_PADDING) - SLOT_PADDING
        start_x = (SCREEN_WIDTH - total_width) // 2
        y = SCREEN_HEIGHT - SLOT_SIZE - HOTBAR_Y_OFFSET
        for i in range(HOTBAR_SLOTS):
            rect = pygame.Rect(start_x + i * (SLOT_SIZE + SLOT_PADDING), y, SLOT_SIZE, SLOT_SIZE)
            self._draw_minecraft_slot(rect, selected=(i == inventory.selected_hotbar))
            self.mouse_slot_refs.append((rect, (inventory.hotbar, i)))
            stack = inventory.hotbar[i]
            if stack:
                self._draw_stack(rect, stack)
                if rect.collidepoint(pygame.mouse.get_pos()):
                    self.hover_stack = stack
            self.screen.blit(self.small_font.render(str(i + 1), True, COL_WHITE), (rect.x + 4, rect.y + 2))

    def _draw_inventory_panel(self):
        inventory = self.player.get(Inventory)
        panel = pygame.Rect(24, SCREEN_HEIGHT - INV_PANEL_H - 34, INV_PANEL_W, INV_PANEL_H)
        self.inventory_panel_rect = panel
        self._draw_panel(panel, "Inventory")
        self.screen.blit(self.small_font.render("Player Storage", True, COL_UI_TEXT), (panel.x + 16, panel.y + 42))
        start_x = panel.x + 18
        hotbar_y = panel.bottom - SLOT_SIZE - 18
        grid_y = hotbar_y - 26 - INVENTORY_ROWS * (SLOT_SIZE + SLOT_PADDING)

        for row in range(inventory.rows):
            for col in range(inventory.cols):
                idx = row * inventory.cols + col
                rect = pygame.Rect(start_x + col * (SLOT_SIZE + SLOT_PADDING), grid_y + row * (SLOT_SIZE + SLOT_PADDING), SLOT_SIZE, SLOT_SIZE)
                self._draw_minecraft_slot(rect)
                self.mouse_slot_refs.append((rect, (inventory.slots, idx)))
                if inventory.slots[idx]:
                    self._draw_stack(rect, inventory.slots[idx])
                    if rect.collidepoint(pygame.mouse.get_pos()):
                        self.hover_stack = inventory.slots[idx]

        self.screen.blit(self.small_font.render("Hotbar", True, COL_UI_TEXT), (panel.x + 18, hotbar_y - 22))
        for col in range(HOTBAR_SLOTS):
            rect = pygame.Rect(start_x + col * (SLOT_SIZE + SLOT_PADDING), hotbar_y, SLOT_SIZE, SLOT_SIZE)
            self._draw_minecraft_slot(rect, selected=(col == inventory.selected_hotbar))
            self.mouse_slot_refs.append((rect, (inventory.hotbar, col)))
            if inventory.hotbar[col]:
                self._draw_stack(rect, inventory.hotbar[col])
                if rect.collidepoint(pygame.mouse.get_pos()):
                    self.hover_stack = inventory.hotbar[col]
        self.screen.blit(self.small_font.render("Left click moves stacks. Right click places blocks. E toggles doors.", True, COL_UI_TEXT),
                         (panel.x + 16, panel.bottom - 20))

    def _draw_container_panel(self):
        if not self.open_container_entity or not self.open_container_entity.alive:
            self._close_open_container()
            return
        container = self.open_container_entity.get(Container)
        if not container or not self.inventory_panel_rect:
            return

        cols = 6 if len(container.inventory) > 16 else 4
        rows = math.ceil(len(container.inventory) / cols)
        panel_w = cols * (SLOT_SIZE + SLOT_PADDING) + SLOT_PADDING * 2 + 28
        panel_h = rows * (SLOT_SIZE + SLOT_PADDING) + SLOT_PADDING * 2 + 88
        panel = pygame.Rect(self.inventory_panel_rect.right + 16, self.inventory_panel_rect.y + 18, panel_w, panel_h)
        self.container_panel_rect = panel
        self._draw_panel(panel, "Village Chest")
        self.screen.blit(self.small_font.render("Shared village storage", True, COL_UI_TEXT), (panel.x + 16, panel.y + 42))

        start_x = panel.x + 16
        start_y = panel.y + 70
        for index, stack in enumerate(container.inventory):
            col = index % cols
            row = index // cols
            rect = pygame.Rect(start_x + col * (SLOT_SIZE + SLOT_PADDING), start_y + row * (SLOT_SIZE + SLOT_PADDING), SLOT_SIZE, SLOT_SIZE)
            self._draw_minecraft_slot(rect)
            self.mouse_slot_refs.append((rect, (container.inventory, index)))
            if stack:
                self._draw_stack(rect, stack)
                if rect.collidepoint(pygame.mouse.get_pos()):
                    self.hover_stack = stack

        self.screen.blit(self.small_font.render("Left click moves stacks between inventories.", True, COL_UI_TEXT),
                         (panel.x + 16, panel.bottom - 20))

    def _draw_crafting_panel(self, linked=False):
        filtered = self._filtered_recipe_order()
        self._clamp_recipe_selection()
        recipe_id, recipe = self._selected_recipe()
        if not recipe_id:
            recipe_id = self.recipe_order[0]
            recipe = RECIPES[recipe_id]
        if linked and self.inventory_panel_rect:
            panel = pygame.Rect(self.inventory_panel_rect.right + 16, self.inventory_panel_rect.y - 36, CRAFT_PANEL_W, CRAFT_PANEL_H)
        else:
            panel = pygame.Rect(SCREEN_WIDTH - CRAFT_PANEL_W - 24, 24, CRAFT_PANEL_W, CRAFT_PANEL_H)
        self._draw_panel(panel, "Crafting")
        self.craft_search_rect = pygame.Rect(panel.x + 16, panel.y + 48, panel.width - 32, 28)
        pygame.draw.rect(self.screen, COL_UI_SLOT, self.craft_search_rect, border_radius=4)
        pygame.draw.rect(self.screen, COL_UI_SELECTED if self.craft_search_active else COL_UI_BORDER, self.craft_search_rect, 2, border_radius=4)
        search_label = self.craft_search_text if self.craft_search_text else "search crafts..."
        search_color = COL_WHITE if self.craft_search_text else COL_UI_TEXT
        self.screen.blit(self.small_font.render(search_label, True, search_color), (self.craft_search_rect.x + 8, self.craft_search_rect.y + 7))

        list_rect = pygame.Rect(panel.x + 16, panel.y + 84, 146, panel.height - 100)
        pygame.draw.rect(self.screen, COL_UI_SLOT, list_rect)
        pygame.draw.rect(self.screen, COL_UI_BORDER, list_rect, 2)

        list_y = list_rect.y + 8
        visible = filtered[self.recipe_scroll_offset:self.recipe_scroll_offset + 8]
        for idx, rid in enumerate(visible):
            recipe_rect = pygame.Rect(list_rect.x + 6, list_y + idx * 44, list_rect.width - 12, 38)
            absolute_index = self.recipe_scroll_offset + idx
            selected = absolute_index == self.selected_recipe_index
            pygame.draw.rect(self.screen, COL_UI_SELECTED if selected else COL_BG, recipe_rect)
            pygame.draw.rect(self.screen, COL_UI_BORDER, recipe_rect, 2)
            color = COL_WHITE if self._can_craft(RECIPES[rid]) else COL_UI_TEXT
            self.screen.blit(self.small_font.render(RECIPES[rid]["name"], True, color), (recipe_rect.x + 8, recipe_rect.y + 10))
            self.recipe_click_refs.append((recipe_rect, absolute_index))

        if not visible:
            self.screen.blit(self.small_font.render("No matching recipes", True, COL_UI_TEXT), (list_rect.x + 12, list_rect.y + 12))
        elif len(filtered) > len(visible):
            page_text = self.small_font.render(
                f"{self.recipe_scroll_offset + 1}-{self.recipe_scroll_offset + len(visible)} / {len(filtered)}",
                True,
                COL_UI_TEXT,
            )
            self.screen.blit(page_text, (list_rect.x + 8, list_rect.bottom - page_text.get_height() - 6))

        preview_x = list_rect.right + 22
        preview_y = panel.y + 86
        ingredients = list(recipe["ingredients"].items())
        for idx in range(CRAFT_PREVIEW_GRID * CRAFT_PREVIEW_GRID):
            col = idx % CRAFT_PREVIEW_GRID
            row = idx // CRAFT_PREVIEW_GRID
            rect = pygame.Rect(preview_x + col * (SLOT_SIZE + 10), preview_y + row * (SLOT_SIZE + 10), SLOT_SIZE, SLOT_SIZE)
            self._draw_minecraft_slot(rect)
            if idx < len(ingredients):
                item_id, qty = ingredients[idx]
                ingredient_stack = ItemStack(item_id, qty)
                self._draw_stack(rect, ingredient_stack)
                if rect.collidepoint(pygame.mouse.get_pos()):
                    self.hover_stack = ingredient_stack

        arrow = self.big_font.render("->", True, COL_UI_TITLE)
        self.screen.blit(arrow, (preview_x + 16, preview_y + CRAFT_PREVIEW_GRID * (SLOT_SIZE + 10) + 8))
        self.craft_output_rect = pygame.Rect(preview_x + 84, preview_y + CRAFT_PREVIEW_GRID * (SLOT_SIZE + 10) + 2, SLOT_SIZE, SLOT_SIZE)
        self._draw_minecraft_slot(self.craft_output_rect, selected=self._can_craft(recipe))
        recipe_stack = ItemStack(recipe_id, recipe["result_qty"])
        self._draw_stack(self.craft_output_rect, recipe_stack)
        if self.craft_output_rect.collidepoint(pygame.mouse.get_pos()):
            self.hover_stack = recipe_stack

        info_y = self.craft_output_rect.bottom + 20
        self.screen.blit(self.font.render(recipe["name"], True, COL_WHITE), (preview_x, info_y))
        station = recipe["station"] or "none"
        station_ready = self._station_nearby(recipe["station"])
        station_color = COL_GREEN if station_ready else COL_RED if recipe["station"] else COL_UI_TEXT
        self.screen.blit(self.small_font.render(f"Station: {station}", True, station_color), (preview_x, info_y + 26))
        self.screen.blit(self.small_font.render("Enter or click result slot to craft", True, COL_GREEN), (preview_x, info_y + 50))

    def _draw_minecraft_slot(self, rect, selected=False):
        face = (198, 198, 198) if selected else (139, 139, 139)
        pygame.draw.rect(self.screen, face, rect)
        pygame.draw.line(self.screen, COL_WHITE, rect.topleft, (rect.right - 1, rect.top), 2)
        pygame.draw.line(self.screen, COL_WHITE, rect.topleft, (rect.left, rect.bottom - 1), 2)
        pygame.draw.line(self.screen, (55, 55, 55), (rect.left, rect.bottom - 1), (rect.right - 1, rect.bottom - 1), 2)
        pygame.draw.line(self.screen, (55, 55, 55), (rect.right - 1, rect.top), (rect.right - 1, rect.bottom - 1), 2)
        pygame.draw.rect(self.screen, COL_UI_SLOT, rect.inflate(-6, -6))

    def _item_icon(self, item_id, size):
        return self._load_image(self._sprite_path("items", f"{item_id}.png"), size)

    def _draw_stack(self, rect, stack):
        icon = self._item_icon(stack.item_id, (rect.width - 14, rect.height - 14))
        if icon:
            self.screen.blit(icon, (rect.x + 7, rect.y + 7))
        else:
            self._draw_item_symbol(self.screen, rect.inflate(-18, -18), stack)
        qty = self.small_font.render(str(stack.qty), True, COL_WHITE)
        shadow = self.small_font.render(str(stack.qty), True, COL_BLACK)
        self.screen.blit(shadow, (rect.right - qty.get_width() - 3, rect.bottom - qty.get_height() - 2))
        self.screen.blit(qty, (rect.right - qty.get_width() - 4, rect.bottom - qty.get_height() - 3))
        if stack.durability is not None:
            ratio = max(0.0, min(1.0, stack.durability / max(1, stack.data.get("durability", 1))))
            bar = pygame.Rect(rect.x + 6, rect.bottom - 8, rect.width - 12, 4)
            pygame.draw.rect(self.screen, COL_BLACK, bar)
            color = COL_GREEN if ratio > 0.45 else COL_YELLOW if ratio > 0.2 else COL_RED
            pygame.draw.rect(self.screen, color, (bar.x + 1, bar.y + 1, max(1, int((bar.width - 2) * ratio)), 2))

    def _draw_cursor_stack(self):
        pos = pygame.mouse.get_pos()
        rect = pygame.Rect(pos[0] + 12, pos[1] + 12, SLOT_SIZE, SLOT_SIZE)
        self._draw_minecraft_slot(rect, selected=True)
        self._draw_stack(rect, self.cursor_stack)

    def _draw_item_symbol(self, surface, rect, stack):
        color = stack.data.get("color", COL_WHITE)
        item_type = stack.data.get("type")
        family = stack.data.get("tool_family")

        if item_type in (ITEM_TOOL, ITEM_WEAPON):
            handle = pygame.Rect(rect.centerx - 3, rect.y + rect.height // 3, 6, rect.height // 2)
            pygame.draw.rect(surface, (90, 60, 35), handle, border_radius=2)
            if family == "sword":
                blade = pygame.Rect(rect.centerx - 4, rect.y + 2, 8, rect.height - 10)
                pygame.draw.rect(surface, color, blade, border_radius=2)
                guard = pygame.Rect(rect.centerx - 10, rect.y + rect.height // 3, 20, 4)
                pygame.draw.rect(surface, (180, 150, 80), guard, border_radius=2)
            elif family == "pickaxe":
                head = pygame.Rect(rect.x + 3, rect.y + 4, rect.width - 6, 7)
                pygame.draw.rect(surface, color, head, border_radius=2)
                tip = [(rect.right - 5, rect.y + 4), (rect.right - 1, rect.y + 10), (rect.right - 8, rect.y + 10)]
                pygame.draw.polygon(surface, color, tip)
            elif family == "hoe":
                head = [(rect.x + 5, rect.y + 10), (rect.right - 4, rect.y + 10), (rect.right - 10, rect.y + 16), (rect.x + 5, rect.y + 16)]
                pygame.draw.polygon(surface, color, head)
            else:
                head = pygame.Rect(rect.centerx - 10, rect.y + 4, 20, 11)
                pygame.draw.rect(surface, color, head, border_radius=2)
            pygame.draw.rect(surface, COL_BLACK, rect, 2, border_radius=3)
            return

        pygame.draw.rect(surface, color, rect, border_radius=3)
        pygame.draw.rect(surface, COL_BLACK, rect, 2, border_radius=3)

    def _draw_held_item(self):
        selected = self.player.get(Inventory).get_selected()
        if not selected:
            return
        transform = self.player.get(Transform)
        item_rect = pygame.Rect(
            int(transform.x - self.camera_x + PLAYER_FOOTPRINT - 6),
            int(transform.y - self.camera_y - (PLAYER_HEIGHT - PLAYER_FOOTPRINT) + PLAYER_HEIGHT // 2),
            18,
            26,
        )
        icon = self._item_icon(selected.item_id, (item_rect.width, item_rect.height))
        if icon:
            self.screen.blit(icon, item_rect.topleft)
        else:
            self._draw_item_symbol(self.screen, item_rect, selected)

    def _draw_selected_item_label(self):
        alpha = int(255 * min(1.0, self.selected_item_label_timer / 1.2))
        text = self.font.render(self.selected_item_label, True, COL_WHITE)
        bg = pygame.Surface((text.get_width() + 18, text.get_height() + 10), pygame.SRCALPHA)
        bg.fill((20, 25, 20, min(220, alpha)))
        bg_x = SCREEN_WIDTH // 2 - bg.get_width() // 2
        bg_y = SCREEN_HEIGHT - SLOT_SIZE - HOTBAR_Y_OFFSET - 40
        text.set_alpha(alpha)
        self.screen.blit(bg, (bg_x, bg_y))
        self.screen.blit(text, (bg_x + 9, bg_y + 5))

    def _draw_hover_tooltip(self, stack):
        lines = [stack.name]
        description = stack.data.get("description")
        if description:
            lines.append(description)
        if stack.durability is not None:
            lines.append(f"Durability: {stack.durability}/{stack.data.get('durability', stack.durability)}")
        if "damage" in stack.data:
            lines.append(f"Damage: {stack.data['damage']}")
        if "harvest_power" in stack.data:
            lines.append(f"Harvest: {stack.data['harvest_power']}")

        rendered = [self.small_font.render(line, True, COL_WHITE if i == 0 else COL_UI_TEXT) for i, line in enumerate(lines)]
        width = max(text.get_width() for text in rendered) + 14
        height = sum(text.get_height() for text in rendered) + 12
        mx, my = pygame.mouse.get_pos()
        x = min(mx + 18, SCREEN_WIDTH - width - 8)
        y = min(my + 18, SCREEN_HEIGHT - height - 8)
        panel = pygame.Surface((width, height), pygame.SRCALPHA)
        panel.fill(COL_TOOLTIP_BG)
        self.screen.blit(panel, (x, y))
        pygame.draw.rect(self.screen, COL_UI_BORDER, pygame.Rect(x, y, width, height), 1, border_radius=4)
        ty = y + 6
        for text in rendered:
            self.screen.blit(text, (x + 7, ty))
            ty += text.get_height()

    def _show_selected_item_name(self, stack):
        self.selected_item_label = stack.name if stack else "Empty Hand"
        self.selected_item_label_timer = 1.2

    def _draw_minimap_hint(self):
        player_transform = self.player.get(Transform)
        tx = int((player_transform.x + PLAYER_FOOTPRINT / 2) // TILE_SIZE)
        ty = int((player_transform.y + PLAYER_FOOTPRINT - 18) // TILE_SIZE)
        tile_name = self.tilemap.get_tile_def(tx, ty).name
        phase = "Night" if self._is_night() else "Day"
        text = self.small_font.render(
            f"Tile: {tile_name}  {phase}  Seed: {self.last_seed}  PNG folder: {SPRITE_DIR}",
            True,
            COL_UI_TEXT,
        )
        self.screen.blit(text, (16, SCREEN_HEIGHT - 28))

    def _draw_main_menu(self):
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((8, 12, 10, 210))
        self.screen.blit(overlay, (0, 0))

        panel = pygame.Rect(SCREEN_WIDTH // 2 - 240, SCREEN_HEIGHT // 2 - 190, 480, 380)
        self._draw_panel(panel, "Verdant Wilds")
        subtitle = self.small_font.render("Choose a map seed, then start a new run.", True, COL_UI_TEXT)
        self.screen.blit(subtitle, (panel.x + 22, panel.y + 46))

        seed_rect = pygame.Rect(panel.x + 24, panel.y + 88, panel.width - 48, 42)
        pygame.draw.rect(self.screen, COL_UI_SLOT, seed_rect, border_radius=4)
        pygame.draw.rect(self.screen, COL_UI_SELECTED, seed_rect, 2, border_radius=4)
        seed_label = self.font.render(self.menu_seed_text or "Random", True, COL_WHITE)
        self.screen.blit(self.small_font.render("World Seed", True, COL_UI_TEXT), (seed_rect.x + 8, seed_rect.y - 18))
        self.screen.blit(seed_label, (seed_rect.x + 12, seed_rect.y + 10))

        info = [
            "Enter digits to set the seed",
            "Enter starts the game",
            "R rolls a random seed",
        ]
        for idx, line in enumerate(info):
            text = self.small_font.render(line, True, COL_UI_TEXT)
            self.screen.blit(text, (panel.x + 24, panel.y + 148 + idx * 20))

        self._draw_overlay_button("start", pygame.Rect(panel.x + 24, panel.y + 230, panel.width - 48, 42), "Start Game")
        self._draw_overlay_button("random_seed", pygame.Rect(panel.x + 24, panel.y + 282, panel.width - 48, 38), "Random Seed")
        self._draw_overlay_button("quit", pygame.Rect(panel.x + 24, panel.y + 330, panel.width - 48, 34), "Quit")

    def _draw_pause_menu(self):
        self._draw_overlay_menu(
            "Paused",
            "ESC or P resumes the game.",
            [
                ("resume", "Resume"),
                ("restart", "Restart World"),
                ("main_menu", "Main Menu"),
                ("quit", "Quit"),
            ],
        )

    def _draw_death_menu(self):
        self._draw_overlay_menu(
            "You Died",
            "Press Enter or click restart to try again.",
            [
                ("restart", "Restart World"),
                ("main_menu", "Main Menu"),
                ("quit", "Quit"),
            ],
        )

    def _draw_overlay_menu(self, title, subtitle, buttons):
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((10, 14, 14, 165))
        self.screen.blit(overlay, (0, 0))
        panel_h = 150 + len(buttons) * 52
        panel = pygame.Rect(SCREEN_WIDTH // 2 - 210, SCREEN_HEIGHT // 2 - panel_h // 2, 420, panel_h)
        self._draw_panel(panel, title)
        subtitle_text = self.small_font.render(subtitle, True, COL_UI_TEXT)
        self.screen.blit(subtitle_text, (panel.x + 22, panel.y + 48))
        for idx, (action, label) in enumerate(buttons):
            rect = pygame.Rect(panel.x + 24, panel.y + 88 + idx * 52, panel.width - 48, 40)
            self._draw_overlay_button(action, rect, label)

    def _draw_overlay_button(self, action, rect, label):
        self.menu_buttons[action] = rect
        hovered = rect.collidepoint(pygame.mouse.get_pos())
        fill = COL_UI_SELECTED if hovered else COL_UI_SLOT
        pygame.draw.rect(self.screen, fill, rect, border_radius=5)
        pygame.draw.rect(self.screen, COL_UI_BORDER, rect, 2, border_radius=5)
        text = self.font.render(label, True, COL_WHITE)
        self.screen.blit(text, (rect.centerx - text.get_width() // 2, rect.centery - text.get_height() // 2))

    def _entity_screen_position(self, entity, transform, renderer):
        screen_x = int(transform.x - self.camera_x)
        screen_y = int(transform.y - self.camera_y)

        if "player" in entity.tags:
            screen_x += (PLAYER_FOOTPRINT - renderer.width) // 2
            screen_y -= (renderer.height - PLAYER_FOOTPRINT)
        elif "tree" in entity.tags:
            screen_x += (TREE_FOOTPRINT - renderer.width) // 2
            screen_y -= (renderer.height - TREE_FOOTPRINT)

        return screen_x, screen_y

    def _draw_message(self):
        text = self.font.render(self.message, True, COL_WHITE)
        bg = pygame.Surface((text.get_width() + 18, text.get_height() + 12), pygame.SRCALPHA)
        bg.fill(COL_UI_BG)
        x = SCREEN_WIDTH // 2 - bg.get_width() // 2
        y = 16
        self.screen.blit(bg, (x, y))
        self.screen.blit(text, (x + 9, y + 6))

    def _draw_panel(self, rect, title):
        panel = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        panel.fill(COL_UI_BG)
        self.screen.blit(panel, rect.topleft)
        pygame.draw.rect(self.screen, COL_UI_BORDER, rect, 2, border_radius=8)
        self.screen.blit(self.big_font.render(title, True, COL_UI_TITLE), (rect.x + 14, rect.y + 8))

    def _set_message(self, message):
        self.message = message
        self.message_timer = 3.0
