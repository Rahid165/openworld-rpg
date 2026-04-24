"""
Entity-Component System (ECS)
Every game object is an Entity with attached Components.
"""

from __future__ import annotations
import uuid
from typing import Dict, Type, TypeVar, Optional, List

T = TypeVar("T", bound="Component")

# ─── Base Component ───────────────────────────────────────────────────────────

class Component:
    """Base class for all components."""
    def __init__(self):
        self.entity: Optional["Entity"] = None

    def update(self, dt: float):
        pass

    def on_attach(self):
        """Called when this component is added to an entity."""
        pass

# ─── Entity ───────────────────────────────────────────────────────────────────

class Entity:
    """
    A container of components. Has no logic of its own.
    """
    def __init__(self, name: str = "Entity"):
        self.id: str = str(uuid.uuid4())[:8]
        self.name: str = name
        self.alive: bool = True
        self._components: Dict[type, Component] = {}
        self.tags: set = set()

    # ── Component management ──────────────────────────────────────────────────

    def add(self, component: Component) -> "Entity":
        component.entity = self
        self._components[type(component)] = component
        component.on_attach()
        return self

    def get(self, component_type: Type[T]) -> Optional[T]:
        return self._components.get(component_type)

    def has(self, component_type: Type[T]) -> bool:
        return component_type in self._components

    def remove(self, component_type: Type[T]) -> Optional[T]:
        return self._components.pop(component_type, None)

    def update(self, dt: float):
        for comp in list(self._components.values()):
            comp.update(dt)

    def destroy(self):
        self.alive = False

    def __repr__(self):
        return f"Entity({self.name}:{self.id})"


# ─── Entity Manager ───────────────────────────────────────────────────────────

class EntityManager:
    """Central registry for all entities in the game."""

    def __init__(self):
        self._entities: Dict[str, Entity] = {}

    def add(self, entity: Entity) -> Entity:
        self._entities[entity.id] = entity
        return entity

    def remove(self, entity: Entity):
        self._entities.pop(entity.id, None)

    def get(self, eid: str) -> Optional[Entity]:
        return self._entities.get(eid)

    def all(self) -> List[Entity]:
        return [e for e in self._entities.values() if e.alive]

    def with_component(self, component_type: Type[T]) -> List[Entity]:
        return [e for e in self.all() if e.has(component_type)]

    def with_tag(self, tag: str) -> List[Entity]:
        return [e for e in self.all() if tag in e.tags]

    def cleanup_dead(self):
        dead = [eid for eid, e in self._entities.items() if not e.alive]
        for eid in dead:
            del self._entities[eid]

    def update(self, dt: float):
        for entity in list(self._entities.values()):
            if entity.alive:
                entity.update(dt)
        self.cleanup_dead()

    def clear(self):
        self._entities.clear()
