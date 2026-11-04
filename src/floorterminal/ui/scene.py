"""Retained canvas scene: reuse Tcl items and update only changed attributes.

Views can describe a complete frame without deleting/reallocating hundreds of
native objects. The pool never exceeds the current frame, owns visible image
references, and restores stacking after a structural change.
"""

from dataclasses import dataclass


@dataclass
class SceneItem:
    identifier: int
    kind: str
    coordinates: tuple
    options: dict
    raster_key: object = None


class CanvasScene:
    def __init__(self, create, coordinates, configure, delete, raise_item):
        self.create = create
        self.coordinates = coordinates
        self.configure = configure
        self.delete = delete
        self.raise_item = raise_item
        self.items = []
        self.active = False
        self.position = 0
        self.restack = False

    def begin(self):
        self.position = 0
        self.active = True
        self.restack = False

    def current_raster(self, key):
        if self.active and self.position < len(self.items):
            item = self.items[self.position]
            if item.raster_key == key:
                return item.options.get("image")
        return None

    def draw(self, kind, coordinates, options, raster_key=None):
        coordinates = tuple(coordinates)
        old = self.items[self.position] if self.position < len(self.items) else None
        # Different option sets can leave inherited Tk defaults on a reused
        # item. Recreate only that slot instead of guessing those defaults.
        if old is None or old.kind != kind or old.options.keys() != options.keys():
            identifier = self.create(kind, coordinates, options)
            item = SceneItem(identifier, kind, coordinates, dict(options), raster_key)
            if old is not None:
                self.delete(old.identifier)
                self.items[self.position] = item
            else:
                self.items.append(item)
            self.restack = True
        else:
            item = old
            if item.coordinates != coordinates:
                self.coordinates(item.identifier, *coordinates)
                item.coordinates = coordinates
            changes = {
                key: value
                for key, value in options.items()
                if item.options[key] != value
            }
            if changes:
                self.configure(item.identifier, **changes)
                item.options = dict(options)
            item.raster_key = raster_key
        self.position += 1
        return item.identifier

    def end(self):
        for item in self.items[self.position :]:
            self.delete(item.identifier)
        del self.items[self.position :]
        if self.restack:
            for item in self.items:
                self.raise_item(item.identifier)
        self.active = False

    def clear(self):
        self.items.clear()
        self.active = False
        self.position = 0
