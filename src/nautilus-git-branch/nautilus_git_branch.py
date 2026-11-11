"""Quiet inline Git badges for Nautilus 4.x list views.

The provider is the supported loading entry point. Badge placement uses private
Nautilus widgets; see README.md for the compatibility contract.
"""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import weakref

import gi
import pygit2

gi.require_version("Gtk", "4.0")
gi.require_version("Nautilus", "4.1")
from gi.repository import Gio, GLib, GObject, Gtk, Nautilus, Pango


LOG = logging.getLogger(__name__)
BADGE_CLASS = "nautilus-git-branch-badge"
BRANCH_ICON = "\ue725"
TAG_ICON = "\uf02b"
COMMIT_ICON = "\ueafc"
CSS = b"""
.nautilus-git-branch-badge {
    color: alpha(@window_fg_color, 0.62);
    background-color: alpha(@window_fg_color, 0.045);
    border: 1px solid alpha(@window_fg_color, 0.16);
    border-radius: 5px;
    padding: 0px 6px;
    margin-left: 6px;
    font-size: 0.85em;
    font-weight: normal;
}
"""
# Low chroma accents, blended with the theme foreground for both light/dark UI.
for _name, _color in {
    "yellow": "#b59a48", "green": "#69996e", "blue": "#6b91b4",
    "red": "#b97b7b", "purple": "#a281b2", "pale": "#a6a2a0",
}.items():
    CSS += f"""
    .{BADGE_CLASS}.git-{_name} {{
        color: alpha(mix(@window_fg_color, {_color}, 0.72), 0.72);
        background-color: alpha({_color}, 0.075);
        border-color: alpha({_color}, 0.25);
    }}
    """.encode()


@dataclass(frozen=True)
class GitState:
    name: str
    kind: str = "branch"


LOADING = GitState("loading...", "loading")


def accent_for(state):
    if state.kind == "tag":
        return "pale"
    if state.kind == "commit":
        return "purple"
    if state.name in ("main", "master"):
        return "yellow"
    if state.name.startswith(("feat/", "feature/")):
        return "green"
    if state.name.startswith("release/"):
        return "blue"
    if state.name.startswith(("bugfix/", "hotfix/", "fix/")):
        return "red"
    return None


@dataclass(frozen=True)
class Snapshot:
    state: GitState | None = None
    # (path, is_directory); the root's .git marker is watched separately.
    watches: tuple = ()


def read_repository(path, detected=lambda: None):
    """Read a root's HEAD and watch locations, entirely on a worker thread.

    Only roots get badges, not every subdirectory inside a repository. libgit2
    resolves .git files itself, so linked worktrees and submodules also work.
    This function must only run on a worker thread.
    """
    repository = None
    watches = []
    try:
        if not os.path.exists(os.path.join(path, ".git")):
            return Snapshot()
        detected()
        marker = Path(path) / ".git"
        if marker.is_dir():
            watches.append((str(marker / "HEAD"), False))
        else:
            watches.append((str(marker), False))
        repository = pygit2.Repository(
            os.fspath(path), flags=pygit2.enums.RepositoryOpenFlag.NO_SEARCH
        )
        if repository.is_bare:
            return Snapshot()
        gitdir = Path(repository.path)
        common = gitdir
        commondir = gitdir / "commondir"
        if commondir.is_file():
            common = (gitdir / commondir.read_text().strip()).resolve()
        watches.extend([
            (str(gitdir / "HEAD"), False), (str(commondir), False),
            (str(common / "packed-refs"), False),
        ])
        symbolic = repository.lookup_reference("HEAD").target
        if isinstance(symbolic, str) and symbolic.startswith("refs/"):
            watches.append((str(common / symbolic), False))
        if repository.head_is_unborn:
            prefix = "refs/heads/"
            state = GitState(symbolic[len(prefix):]) if symbolic.startswith(prefix) else None
            return Snapshot(state, tuple(sorted(set(watches))))
        head = repository.head
        if repository.head_is_detached:
            # Tags only need inspection for detached HEAD, never for branches.
            tags = []
            for ref in repository.references.iterator(pygit2.enums.ReferenceFilter.TAGS):
                try:
                    if ref.peel(pygit2.Commit).id == head.target:
                        tags.append(ref.name.removeprefix("refs/tags/"))
                except (KeyError, ValueError, pygit2.GitError):
                    continue
            # Observe existing tag subdirectories, plus their parent for newly
            # created trees. Packed tag changes arrive through packed-refs.
            watches.append((str(common / "refs"), True))
            watches.append((str(common / "refs" / "tags"), True))
            for directory, _, _ in os.walk(common / "refs" / "tags"):
                watches.append((directory, True))
            state = GitState(sorted(tags)[0], "tag") if tags else GitState(str(head.target)[:7], "commit")
        else:
            state = GitState(head.shorthand)
        return Snapshot(state, tuple(sorted(set(watches))))
    except (OSError, ValueError, KeyError, pygit2.GitError):
        return Snapshot(watches=tuple(sorted(set(watches))))
    finally:
        if repository is not None:
            repository.free()


def read_branch(path):
    return read_repository(path).state


@dataclass
class CacheEntry:
    state: GitState | None = None
    known_repository: bool = False
    listeners: set = field(default_factory=set)
    monitors: list = field(default_factory=list)
    generation: int = 0
    debounce: int = 0
    watch_specs: tuple = ()


class BranchCache:
    """Event-driven lookups. No timers or disk reads for idle repositories."""

    def __init__(self, reader=read_repository, capacity=512):
        self.reader = reader
        self.capacity = capacity
        self.entries = OrderedDict()
        self.pending = {}
        self.queue = OrderedDict()
        self.closed = False
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="git-badge")

    def subscribe(self, path, listener):
        entry = self.entries.setdefault(path, CacheEntry())
        first = not entry.listeners
        entry.listeners.add(listener)
        self.entries.move_to_end(path)
        if first:
            # State may have changed while the folder was hidden.
            entry.state = LOADING if entry.known_repository else None
            if entry.known_repository:
                self._watch_marker(path, entry)
            self.invalidate(path)
        listener(entry.state)
        self._evict()

    def unsubscribe(self, path, listener):
        entry = self.entries.get(path)
        if entry is None:
            return
        entry.listeners.discard(listener)
        if not entry.listeners:
            entry.generation += 1
            self.queue.pop(path, None)
            self._cancel_monitors(entry)
            if entry.debounce:
                GLib.source_remove(entry.debounce)
                entry.debounce = 0
        self._evict()

    def _evict(self):
        if len(self.entries) <= self.capacity:
            return
        for path in list(self.entries):
            if len(self.entries) <= self.capacity:
                break
            if not self.entries[path].listeners and path not in self.pending:
                del self.entries[path]

    @staticmethod
    def _cancel_monitors(entry):
        for monitor in entry.monitors:
            monitor.cancel()
        entry.monitors.clear()
        entry.watch_specs = ()

    def _watch(self, path, entry, target, directory=False, marker_only=False):
        try:
            file = Gio.File.new_for_path(target)
            method = file.monitor_directory if directory else file.monitor_file
            monitor = method(Gio.FileMonitorFlags.WATCH_MOVES, None)
            def changed(_monitor, file, other, _event):
                if marker_only and not any(
                    item is not None and item.get_basename() == ".git" for item in (file, other)
                ):
                    return
                self.debounce(path)
            monitor.connect("changed", changed)
            entry.monitors.append(monitor)
        except GLib.Error:
            # Do not introduce polling on filesystems without file monitoring.
            LOG.debug("Could not monitor %s", target)

    def _watch_marker(self, path, entry):
        self._watch(path, entry, path, directory=True, marker_only=True)

    def debounce(self, path):
        entry = self.entries.get(path)
        if entry is not None and entry.listeners and not entry.debounce:
            def refresh():
                entry.debounce = 0
                self.invalidate(path)
                return GLib.SOURCE_REMOVE
            entry.debounce = GLib.timeout_add(80, refresh)

    def invalidate(self, path):
        entry = self.entries.get(path)
        if entry is None or not entry.listeners or self.closed:
            return
        entry.generation += 1
        self.queue[path] = entry.generation
        self._pump()

    def _pump(self):
        for path in list(self.queue):
            if len(self.pending) >= 2 or self.closed:
                break
            if path in self.pending:
                continue
            generation = self.queue.pop(path)
            def detected(path=path, generation=generation):
                GLib.idle_add(self._detected, path, generation)
            future = self.executor.submit(self.reader, path, detected)
            self.pending[path] = future
            future.add_done_callback(
                lambda future, path=path, generation=generation:
                GLib.idle_add(self._completed, path, generation, future)
            )

    def _detected(self, path, generation):
        entry = self.entries.get(path)
        if not self.closed and entry is not None and entry.generation == generation and entry.listeners:
            entry.known_repository = True
            if entry.state is None:
                self._publish(entry, LOADING)
        return GLib.SOURCE_REMOVE

    @staticmethod
    def _publish(entry, state):
        entry.state = state
        for listener in tuple(entry.listeners):
            listener(state)

    def _completed(self, path, generation, future):
        self.pending.pop(path, None)
        entry = self.entries.get(path)
        if not self.closed and entry is not None and entry.generation == generation and entry.listeners:
            try:
                snapshot = future.result()
            except Exception:
                LOG.exception("Git state lookup failed")
                snapshot = Snapshot()
            if entry.watch_specs != snapshot.watches:
                self._cancel_monitors(entry)
                if snapshot.state is not None or snapshot.watches:
                    self._watch_marker(path, entry)
                for target, directory in snapshot.watches:
                    self._watch(path, entry, target, directory)
                entry.watch_specs = snapshot.watches
                # Revalidate once after installing a changed watch set, closing
                # the gap between the initial disk read and monitor creation.
                self.invalidate(path)
            entry.known_repository = snapshot.state is not None or bool(snapshot.watches)
            self._publish(entry, snapshot.state)
        self._evict()
        self._pump()
        return GLib.SOURCE_REMOVE

    def close(self):
        self.closed = True
        for entry in self.entries.values():
            self._cancel_monitors(entry)
            if entry.debounce:
                GLib.source_remove(entry.debounce)
        self.queue.clear()
        self.executor.shutdown(wait=True, cancel_futures=True)


def descendants(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from descendants(child)
        child = child.get_next_sibling()


def property_value(obj, name):
    return obj.get_property(name) if obj is not None and obj.find_property(name) else None


def compact_list_cell(cell):
    view = property_value(cell, "view")
    size_spec = cell.find_property("icon-size")
    return (
        view is not None
        and GObject.type_name(view) == "NautilusListView"
        and size_spec is not None
        and property_value(cell, "icon-size") == size_spec.minimum
    )


def cell_path(cell):
    item = property_value(cell, "item")
    file = property_value(item, "file")
    if file is None or not isinstance(file, Nautilus.FileInfo):
        return None
    if not Nautilus.FileInfo.is_directory(file):
        return None
    location = Nautilus.FileInfo.get_location(file)
    return location.get_path() if location is not None else None


def badge_for(cell):
    """Attach only to the known horizontal filename row, never guess by text."""
    cached = getattr(cell, "_git_branch_badge", None)
    if cached is not None:
        return cached
    for widget in descendants(cell):
        if widget.has_css_class(BADGE_CLASS):
            cell._git_branch_badge = widget
            return widget
    for widget in descendants(cell):
        if not widget.has_css_class("column-name-labels-box"):
            continue
        row = widget.get_first_child()
        if not isinstance(row, Gtk.Box) or row.get_orientation() != Gtk.Orientation.HORIZONTAL:
            continue
        name = row.get_first_child()
        if not isinstance(name, Gtk.Label):
            continue
        badge = Gtk.Label(visible=False, valign=Gtk.Align.CENTER, can_target=False)
        badge.add_css_class(BADGE_CLASS)
        badge.set_ellipsize(Pango.EllipsizeMode.END)
        badge.set_max_width_chars(28)
        row.insert_child_after(badge, name)
        cell._git_branch_badge = badge
        return badge
    return None


def update_badge(badge, state):
    if state:
        icon = TAG_ICON if state.kind == "tag" else COMMIT_ICON if state.kind == "commit" else BRANCH_ICON
        label = f"detached {state.name}" if state.kind == "commit" else state.name
        text = state.name if state.kind == "loading" else f"{icon} {label}"
        if badge.get_text() != text:
            badge.set_text(text)  # Plain text: branch names are not markup.
            badge.set_tooltip_text(f"Git {state.kind}: {state.name}")
        accent = accent_for(state) if state.kind != "loading" else None
        previous = getattr(badge, "_git_accent", None)
        if previous != accent:
            if previous:
                badge.remove_css_class(f"git-{previous}")
            if accent:
                badge.add_css_class(f"git-{accent}")
            badge._git_accent = accent
    visible = bool(state)
    if badge.get_visible() != visible:
        badge.set_visible(visible)


class CellBinding:
    """Subscribe only while this recycled row is mapped at the eligible zoom."""

    def __init__(self, cell, cache):
        # Python wrappers can disappear while GTK still owns the native widget.
        # A GObject weak ref recreates the wrapper until the widget is destroyed.
        self.cell = cell.weak_ref()
        self.cache = cache
        self.path = None
        self.idle = 0
        self.item = None
        self.item_handler = 0
        for signal in ("map", "unmap", "notify::item", "notify::icon-size"):
            cell.connect(signal, self.changed)
        # Children can be attached later while Nautilus constructs a cell.
        self.children = cell.observe_children()
        reference = weakref.ref(self)
        def children_changed(*args):
            binding = reference()
            if binding is not None:
                binding.changed()
        self.children.connect("items-changed", children_changed)
        self.changed()

    def changed(self, *_):
        cell = self.cell()
        if self.item_handler:
            self.item.disconnect(self.item_handler)
            self.item = None
            self.item_handler = 0
        if self.path:
            self.cache.unsubscribe(self.path, self.render)
            self.path = None
        if cell is not None:
            badge = getattr(cell, "_git_branch_badge", None)
            if badge is not None:
                update_badge(badge, None)
            if not self.idle:
                self.idle = GLib.idle_add(self.bind)

    def bind(self):
        self.idle = 0
        cell = self.cell()
        if cell is None or not cell.get_mapped() or not compact_list_cell(cell):
            return GLib.SOURCE_REMOVE
        self.item = property_value(cell, "item")
        if self.item is not None and GObject.signal_lookup("file-changed", self.item.__gtype__):
            self.item_handler = self.item.connect("file-changed", self.file_changed)
        path = cell_path(cell)
        if path and badge_for(cell) is not None:
            self.path = path
            self.cache.subscribe(path, self.render)
        return GLib.SOURCE_REMOVE

    def file_changed(self, *_):
        cell = self.cell()
        if cell is not None and cell_path(cell) != self.path:
            self.changed()
        elif self.path:
            entry = self.cache.entries.get(self.path)
            if entry is not None and not entry.known_repository:
                # Nautilus notices directory metadata changes (e.g. git init).
                # Ordinary folders need neither their own monitors nor polling.
                self.cache.debounce(self.path)

    def render(self, state):
        cell = self.cell()
        if cell is not None and self.path:
            badge = getattr(cell, "_git_branch_badge", None)
            if badge is not None:
                update_badge(badge, state)


class BadgeController:
    def __init__(self):
        self.cache = BranchCache()
        self.css = Gtk.CssProvider()
        self.css.load_from_data(CSS)
        self.displays = set()
        self.windows = Gtk.Window.get_toplevels()
        self.windows.connect("items-changed", self.windows_changed)
        self.windows_changed(self.windows, 0, 0, self.windows.get_n_items())

    def windows_changed(self, model, position, _removed, added):
        for index in range(position, position + added):
            self.attach(model.get_item(index))

    def attach(self, widget):
        if getattr(widget, "_git_branch_watched", False):
            return
        widget._git_branch_watched = True
        if isinstance(widget, Gtk.Window):
            display = widget.get_display()
            if display not in self.displays:
                Gtk.StyleContext.add_provider_for_display(
                    display, self.css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
                self.displays.add(display)
        if GObject.type_name(widget) == "NautilusNameCell":
            widget._git_branch_binding = CellBinding(widget, self.cache)
            return
        if isinstance(widget, Gtk.GridView) or GObject.type_name(widget) in (
            "NautilusGridView", "NautilusLabelCell", "NautilusStarCell",
        ):
            return
        # Observe additions once, rather than walking the entire tree on a timer.
        # Weak refs avoid keeping closed windows and removed subtrees alive.
        reference = widget.weak_ref()
        model = widget.observe_children()
        widget._git_branch_children = model
        def added_children(model, position, _removed, added):
            if reference() is not None:
                for index in range(position, position + added):
                    self.attach(model.get_item(index))
        model.connect("items-changed", added_children)
        added_children(model, 0, 0, model.get_n_items())


_controller = None


class GitBranchExtension(GObject.GObject, Nautilus.InfoProvider):
    def __init__(self):
        super().__init__()
        global _controller
        if _controller is None:
            _controller = BadgeController()

    def update_file_info(self, file):
        return Nautilus.OperationResult.COMPLETE
