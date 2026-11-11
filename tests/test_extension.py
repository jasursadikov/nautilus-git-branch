import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import nautilus_git_branch as extension
import gi
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, GObject, Gtk


def wait_for(predicate, timeout=4):
    deadline = time.monotonic() + timeout
    context = GLib.MainContext.default()
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        if predicate():
            return
        time.sleep(0.001)
    raise AssertionError("Timed out waiting for asynchronous update")


def run_for(seconds):
    deadline = time.monotonic() + seconds
    wait_for(lambda: time.monotonic() >= deadline, timeout=seconds + 1)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repository with spaces"
        self.repo.mkdir()
        self.git("init", "-b", "feature/quiet-badge")

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *args], stderr=subprocess.DEVNULL,
            env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull,
                 "GIT_CONFIG_NOSYSTEM": "1"}, text=True,
        ).strip()

    def commit(self):
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-m", "Initial")

    def test_unborn_branch_and_no_inherited_badges(self):
        self.assertEqual(extension.read_branch(self.repo), extension.GitState("feature/quiet-badge"))
        child = self.repo / "child"
        child.mkdir()
        self.assertIsNone(extension.read_branch(child))
        self.assertIsNone(extension.read_branch(self.root))

    def test_branch_switch_and_detached_head(self):
        self.commit()
        self.git("checkout", "-b", "another")
        self.assertEqual(extension.read_branch(self.repo), extension.GitState("another"))
        self.git("checkout", "--detach")
        self.assertEqual(extension.read_branch(self.repo),
                         extension.GitState(self.git("rev-parse", "--short", "HEAD"), "commit"))

    def test_worktree_gitfile(self):
        self.commit()
        worktree = self.root / "worktree"
        self.git("worktree", "add", "-b", "linked", str(worktree))
        self.assertTrue((worktree / ".git").is_file())
        self.assertEqual(extension.read_branch(worktree), extension.GitState("linked"))

    def test_git_environment_does_not_redirect_lookup(self):
        with patch.dict(os.environ, {"GIT_DIR": "/nonexistent", "GIT_WORK_TREE": "/"}):
            self.assertEqual(extension.read_branch(self.repo), extension.GitState("feature/quiet-badge"))

    def test_lookup_does_not_launch_git(self):
        with patch.object(subprocess, "Popen", side_effect=AssertionError("Unexpected subprocess")):
            self.assertEqual(extension.read_branch(self.repo), extension.GitState("feature/quiet-badge"))

    def test_unreadable_or_invalid_repositories_are_quiet(self):
        for error in [OSError(), ValueError(), KeyError(), extension.pygit2.GitError("Invalid repository")]:
            with self.subTest(error=error), patch.object(extension.pygit2, "Repository", side_effect=error):
                self.assertIsNone(extension.read_branch(self.repo))

    def test_corrupt_gitfile_is_quiet(self):
        (self.repo / ".git").rename(self.repo / "saved-git")
        (self.repo / ".git").write_text("not a gitfile\n")
        self.assertIsNone(extension.read_branch(self.repo))

    def test_lightweight_and_annotated_tags_when_detached(self):
        self.commit()
        self.git("tag", "v1")
        # A branch takes precedence over any tags pointing at its commit.
        self.assertEqual(extension.read_branch(self.repo).kind, "branch")
        self.git("checkout", "--detach", "v1")
        self.assertEqual(extension.read_branch(self.repo), extension.GitState("v1", "tag"))
        self.git("tag", "-d", "v1")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "-c", "tag.gpgsign=false", "tag", "-a", "v2", "-m", "Release")
        self.assertEqual(extension.read_branch(self.repo), extension.GitState("v2", "tag"))
        self.git("pack-refs", "--all")
        self.assertEqual(extension.read_branch(self.repo), extension.GitState("v2", "tag"))

    def test_filesystem_notifications_refresh_branch_and_tags(self):
        self.commit()
        cache = extension.BranchCache()
        self.addCleanup(cache.close)
        values = []
        cache.subscribe(str(self.repo), values.append)
        wait_for(lambda: values and values[-1] == extension.GitState("feature/quiet-badge"))
        self.assertIn(extension.LOADING, values)
        self.git("checkout", "-b", "fix/notifications")
        wait_for(lambda: values[-1] == extension.GitState("fix/notifications"))
        self.git("checkout", "--detach")
        wait_for(lambda: values[-1] is not None and values[-1].kind == "commit")
        self.git("tag", "nested/v3")
        wait_for(lambda: values[-1] == extension.GitState("nested/v3", "tag"))
        self.git("tag", "-d", "nested/v3")
        wait_for(lambda: values[-1] is not None and values[-1].kind == "commit")

    def test_worktree_head_notifications(self):
        self.commit()
        worktree = self.root / "worktree"
        self.git("worktree", "add", "-b", "linked", str(worktree))
        cache = extension.BranchCache()
        self.addCleanup(cache.close)
        values = []
        cache.subscribe(str(worktree), values.append)
        wait_for(lambda: values and values[-1] == extension.GitState("linked"))
        subprocess.run(["git", "-C", str(worktree), "checkout", "-b", "feat/worktree"],
                       check=True, capture_output=True)
        wait_for(lambda: values[-1] == extension.GitState("feat/worktree"))

    def test_unrelated_worktree_activity_does_not_reread_head(self):
        self.commit()
        reader = Mock(side_effect=extension.read_repository)
        cache = extension.BranchCache(reader=reader)
        self.addCleanup(cache.close)
        cache.subscribe(str(self.repo), lambda state: None)
        wait_for(lambda: not cache.pending and not cache.queue)
        count = reader.call_count
        (self.repo / "ordinary-file").write_text("work in progress")
        self.git("status", "--porcelain")
        run_for(0.2)
        self.assertEqual(reader.call_count, count)


class CacheTests(unittest.TestCase):
    def cache(self, **kwargs):
        cache = extension.BranchCache(**kwargs)
        self.addCleanup(cache.close)
        return cache

    def settle(self, cache):
        wait_for(lambda: not cache.pending and not cache.queue)

    def test_async_result_and_explicit_refresh(self):
        state = [extension.GitState("main")]
        cache = self.cache(reader=lambda _, detected: state[0] and extension.Snapshot(state[0]))
        values = []
        cache.subscribe("/nonexistent/repo", values.append)
        self.assertEqual(values, [None])
        self.settle(cache)
        self.assertEqual(values[-1], extension.GitState("main"))
        state[0] = extension.GitState("feature/new")
        cache.invalidate("/nonexistent/repo")
        self.settle(cache)
        self.assertEqual(values[-1], state[0])

    def test_cache_is_bounded_and_offscreen_results_discarded(self):
        cache = self.cache(reader=lambda _, detected: extension.Snapshot(extension.GitState("main")), capacity=2)
        for name in ["one", "two", "three"]:
            cache.subscribe(name, self.ignore)
            self.settle(cache)
            cache.unsubscribe(name, self.ignore)
        self.assertEqual(len(cache.entries), 2)
        self.assertFalse(cache.pending)

    @staticmethod
    def ignore(state):
        pass

    def test_no_periodic_repository_reads(self):
        reader = Mock(return_value=extension.Snapshot(extension.GitState("main")))
        cache = self.cache(reader=reader)
        cache.subscribe("/nonexistent/repo", self.ignore)
        self.settle(cache)
        reads = reader.call_count
        run_for(2.2)
        self.assertEqual(reader.call_count, reads)

    def test_worker_count_and_unsubscribe_cancel_waiting_work(self):
        import threading
        gate = threading.Event()
        cache = self.cache(reader=lambda *_: gate.wait(2) and extension.Snapshot())
        try:
            for index in range(20):
                cache.subscribe(f"/nonexistent/{index}", self.ignore)
            self.assertEqual(len(cache.pending), 2)
            self.assertEqual(len(cache.queue), 18)
            for index in range(20):
                cache.unsubscribe(f"/nonexistent/{index}", self.ignore)
            self.assertFalse(cache.queue)
        finally:
            gate.set()
        self.settle(cache)

    def test_reopening_known_repository_shows_loading(self):
        cache = self.cache(reader=lambda *_: extension.Snapshot(extension.GitState("main")))
        values = []
        cache.subscribe("/nonexistent/repo", values.append)
        self.settle(cache)
        cache.unsubscribe("/nonexistent/repo", values.append)
        cache.subscribe("/nonexistent/repo", values.append)
        self.assertEqual(values[-1], extension.LOADING)
        self.settle(cache)

    def test_stale_worker_result_cannot_overwrite_recycled_row(self):
        import threading
        started = threading.Event()
        gate = threading.Event()
        calls = []
        def reader(path, detected):
            calls.append(path)
            if len(calls) == 1:
                started.set()
                gate.wait(2)
                return extension.Snapshot(extension.GitState("old"))
            return extension.Snapshot(extension.GitState("current"))
        cache = self.cache(reader=reader)
        values = []
        cache.subscribe("/nonexistent/repo", values.append)
        self.assertTrue(started.wait(1))
        cache.unsubscribe("/nonexistent/repo", values.append)
        cache.subscribe("/nonexistent/repo", values.append)
        gate.set()
        self.settle(cache)
        self.assertNotIn(extension.GitState("old"), values)
        self.assertEqual(values[-1], extension.GitState("current"))

    def test_ordinary_directories_have_no_monitors(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = self.cache()
            cache.subscribe(directory, self.ignore)
            self.settle(cache)
            self.assertFalse(cache.entries[directory].monitors)

    def test_loading_is_delivered_before_slow_head_read_finishes(self):
        import threading
        gate = threading.Event()
        def reader(path, detected):
            detected()
            gate.wait(2)
            return extension.Snapshot(extension.GitState("main"))
        cache = self.cache(reader=reader)
        values = []
        cache.subscribe("/nonexistent/repo", values.append)
        try:
            wait_for(lambda: extension.LOADING in values)
            self.assertNotIn(extension.GitState("main"), values)
        finally:
            gate.set()
        self.settle(cache)
        self.assertEqual(values[-1], extension.GitState("main"))


class Model:
    def __init__(self, children):
        self.children = children
        self.callbacks = []

    def connect(self, _signal, callback):
        self.callbacks.append(callback)

    def get_n_items(self):
        return len(self.children)

    def get_item(self, index):
        return self.children[index]

    def append(self, child):
        self.children.append(child)
        for callback in self.callbacks:
            callback(self, len(self.children) - 1, 0, 1)


class Widget:
    def __init__(self, kind="GtkBox", children=()):
        self.kind = kind
        self.model = Model(list(children))
        self.observations = 0

    def observe_children(self):
        self.observations += 1
        return self.model

    def weak_ref(self):
        import weakref
        return weakref.ref(self)


class DiscoveryTests(unittest.TestCase):
    def test_native_owned_widget_still_discovers_rows_after_python_wrapper_expires(self):
        import gc
        import weakref
        owner = Gio.ListStore.new(GObject.Object)
        root = GObject.Object()
        root.kind = "GtkBox"
        model = Model([])
        root.observe_children = lambda: model
        owner.append(root)
        python_reference = weakref.ref(root)
        controller = extension.BadgeController.__new__(extension.BadgeController)
        controller.cache = Mock()
        with patch.object(extension.GObject, "type_name", side_effect=lambda widget: widget.kind) as type_name, \
             patch.object(extension, "CellBinding") as binding:
            controller.attach(root)
            # Mock call arguments must not keep the wrapper alive for the test.
            type_name.reset_mock()
            del root
            gc.collect()
            self.assertIsNone(python_reference())
            model.append(Widget("NautilusNameCell"))
            binding.assert_called_once()
        owner.remove_all()

    def test_native_owned_cell_binds_after_python_wrapper_expires(self):
        import gc
        import weakref
        owner = Gio.ListStore.new(GObject.Object)
        cell = GObject.Object()
        model = Model([])
        cell.observe_children = lambda: model
        cell.connect = Mock()
        cell.get_mapped = lambda: True
        owner.append(cell)
        python_reference = weakref.ref(cell)
        cache = Mock()
        with patch.object(extension.GLib, "idle_add", return_value=1):
            binding = extension.CellBinding(cell, cache)
        del cell
        gc.collect()
        self.assertIsNone(python_reference())
        with patch.object(extension, "compact_list_cell", return_value=True), \
             patch.object(extension, "property_value", return_value=None), \
             patch.object(extension, "cell_path", return_value="/repo"), \
             patch.object(extension, "badge_for", return_value=Mock()):
            binding.bind()
        cache.subscribe.assert_called_once_with("/repo", binding.render)
        owner.remove_all()

    def test_new_rows_discovered_by_signals_without_rewalking_tree(self):
        initial = Widget("NautilusNameCell")
        root = Widget(children=[initial])
        controller = extension.BadgeController.__new__(extension.BadgeController)
        controller.cache = Mock()
        with patch.object(extension.GObject, "type_name", side_effect=lambda widget: widget.kind), \
             patch.object(extension, "CellBinding") as binding:
            controller.attach(root)
            self.assertEqual(binding.call_count, 1)
            new_row = Widget("NautilusNameCell")
            root.model.append(new_row)
            self.assertEqual(binding.call_count, 2)
            controller.attach(root)
            self.assertEqual(binding.call_count, 2)
        self.assertEqual(root.observations, 1)
        self.assertEqual(initial.observations, 0)

    def test_grid_subtrees_are_never_observed(self):
        grid = Widget("NautilusGridView", [Widget()])
        controller = extension.BadgeController.__new__(extension.BadgeController)
        with patch.object(extension.GObject, "type_name", side_effect=lambda widget: widget.kind):
            controller.attach(grid)
        self.assertEqual(grid.observations, 0)


class FakeCell:
    def __init__(self, size=16, view="NautilusListView"):
        self.values = {"view": view, "icon-size": size}

    def find_property(self, name):
        if name in self.values:
            return type("Spec", (), {"minimum": 16})()

    def get_property(self, name):
        return self.values[name]


class EligibilityTests(unittest.TestCase):
    def test_only_minimum_list_size(self):
        with patch.object(extension.GObject, "type_name", side_effect=lambda value: value):
            self.assertTrue(extension.compact_list_cell(FakeCell()))
            self.assertFalse(extension.compact_list_cell(FakeCell(size=32)))
            self.assertFalse(extension.compact_list_cell(FakeCell(view="NautilusGridView")))
            self.assertFalse(extension.compact_list_cell(FakeCell(view=None)))


class BadgeUpdateTests(unittest.TestCase):
    def badge(self, text="", visible=False, accent=None):
        badge = Mock()
        badge.get_text.return_value = text
        badge.get_visible.return_value = visible
        badge._git_accent = accent
        return badge

    def test_branch_icon_and_plain_text(self):
        badge = self.badge()
        extension.update_badge(badge, extension.GitState("feature/<badge>&test"))
        badge.set_text.assert_called_once_with("\ue725 feature/<badge>&test")
        badge.set_visible.assert_called_once_with(True)

    def test_unchanged_badge_does_not_trigger_widget_updates(self):
        badge = self.badge("\ue725 main", True, "yellow")
        extension.update_badge(badge, extension.GitState("main"))
        badge.set_text.assert_not_called()
        badge.set_tooltip_text.assert_not_called()
        badge.set_visible.assert_not_called()
        badge.add_css_class.assert_not_called()
        badge.remove_css_class.assert_not_called()

    def test_empty_branch_hides_badge(self):
        badge = self.badge(visible=True)
        extension.update_badge(badge, None)
        badge.set_visible.assert_called_once_with(False)
        badge.set_text.assert_not_called()

    def test_loading_has_no_branch_icon_or_accent(self):
        badge = self.badge(accent="red")
        extension.update_badge(badge, extension.LOADING)
        badge.set_text.assert_called_once_with("loading...")
        badge.remove_css_class.assert_called_once_with("git-red")
        badge.add_css_class.assert_not_called()

    def test_requested_colors_and_icons(self):
        cases = [
            (extension.GitState("main"), "yellow", extension.BRANCH_ICON),
            (extension.GitState("master"), "yellow", extension.BRANCH_ICON),
            (extension.GitState("feat/a"), "green", extension.BRANCH_ICON),
            (extension.GitState("feature/a"), "green", extension.BRANCH_ICON),
            (extension.GitState("release/a"), "blue", extension.BRANCH_ICON),
            (extension.GitState("bugfix/a"), "red", extension.BRANCH_ICON),
            (extension.GitState("hotfix/a"), "red", extension.BRANCH_ICON),
            (extension.GitState("fix/a"), "red", extension.BRANCH_ICON),
            (extension.GitState("v1", "tag"), "pale", extension.TAG_ICON),
            (extension.GitState("aabbccd", "commit"), "purple", extension.COMMIT_ICON),
        ]
        for state, accent, icon in cases:
            with self.subTest(state=state):
                badge = self.badge()
                extension.update_badge(badge, state)
                badge.add_css_class.assert_called_once_with(f"git-{accent}")
                self.assertTrue(badge.set_text.call_args.args[0].startswith(icon + " "))

    def test_recycled_color_is_removed_for_ordinary_branches(self):
        badge = self.badge(accent="yellow")
        extension.update_badge(badge, extension.GitState("experiment"))
        badge.remove_css_class.assert_called_once_with("git-yellow")
        badge.add_css_class.assert_not_called()

    def test_theme_css_loads(self):
        provider = Gtk.CssProvider()
        errors = []
        provider.connect("parsing-error", lambda *args: errors.append(args))
        provider.load_from_data(extension.CSS)
        self.assertFalse(errors)


Gtk.init_check()


@unittest.skipUnless(Gdk.Display.get_default() is not None, "GTK display unavailable")
class WidgetTests(unittest.TestCase):
    def test_badge_placement_idempotency_and_plain_text(self):
        cell = Gtk.Box()
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        labels.add_css_class("column-name-labels-box")
        row = Gtk.Box()
        name = Gtk.Label(label="repository")
        row.append(name)
        labels.append(row)
        cell.append(labels)
        # A normal box stands in for the private Nautilus cell. Its two notify
        # signals are accepted by GObject even though the properties are private.
        badge = extension.badge_for(cell)
        binding = extension.CellBinding(cell, Mock())
        self.assertIsNotNone(badge)
        self.assertIs(name.get_next_sibling(), badge)
        self.assertIs(extension.badge_for(cell), badge)
        self.assertFalse(badge.get_visible())
        badge.set_text("feature/<badge>&test")
        self.assertFalse(badge.get_use_markup())
        badge.set_visible(True)
        cell.notify("visible")  # unrelated notification must not hide the badge
        self.assertTrue(badge.get_visible())
        cell.emit("notify::item", cell.find_property("visible"))
        self.assertFalse(badge.get_visible())
        badge.set_visible(True)
        cell.emit("notify::icon-size", cell.find_property("visible"))
        self.assertFalse(badge.get_visible())

    def test_unknown_layout_is_skipped(self):
        self.assertIsNone(extension.badge_for(Gtk.Box()))


if __name__ == "__main__":
    unittest.main()
