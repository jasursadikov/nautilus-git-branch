# Nautilus Git Branch

![Nautilus Git Branch preview](img.png)

Quiet Git badges beside repository folder names in GNOME Files. Badges appear
**only in list view at the smallest icon size**, with a faint background, thin
outline and subdued colors that follow the desktop theme.

Choose list view with **Ctrl+2**, then press **Ctrl+minus** until the icons reach
minimum size. Repositories display `loading...` while their Git state is read.
Ordinary folders, remote locations, grid view and larger list rows stay blank.

| Git state | Accent | Badge |
| --- | --- | --- |
| `main`, `master` | Dim yellow | Branch |
| `feat/…`, `feature/…` | Dim green | Branch |
| `release/…` | Dim blue | Branch |
| `bugfix/…`, `hotfix/…`, `fix/…` | Dim red | Branch |
| Exact tag at detached HEAD | Pale | Tag |
| Untagged detached HEAD | Dim purple/magenta | Commit |
| Other branches | Neutral | Branch |

Install a Nerd Font containing these glyphs for the icons to render correctly.
An attached branch takes precedence over tags. Lightweight and annotated tags
are supported; if several match HEAD, the alphabetically first tag is shown.
An untagged detached HEAD displays `detached <short SHA>`.

## Install on Arch Linux

The package depends on Arch packages named `nautilus`, `nautilus-python` and
`python-pygit2`. Install the AUR dependencies with your preferred AUR helper,
then build and install this package:

```sh
git clone https://github.com/jasursadikov/nautilus-git-branch.git
cd nautilus-git-branch
makepkg -si
nautilus -q
```

The PKGBUILD installs the extension into
`/usr/share/nautilus-python/extensions/`. Reopen Files after installation. The
first release must be published with its `v1.0.0` tag before the versioned
source URLs used by the PKGBUILD are available.

If you previously installed a copy in your user extensions directory, remove
it to prevent it from shadowing the packaged version. To remove the package:

```sh
sudo pacman -Rns nautilus-git-branch
nautilus -q
```

## Behavior and compatibility

Only repository roots receive badges. Unborn branches, linked worktrees and
checked-out submodules are supported; ordinary repository subdirectories and
bare repositories are excluded. Long names are ellipsized and treated as plain
text, not markup.

Git metadata reads run through pygit2 on two workers. There are no Git
subprocesses, recurring widget scans or repository polling. Row lifecycle
signals discover and bind badges; filesystem notifications update visible
repositories after branch or tag changes. Notifications are coalesced over
80 ms. Hidden rows release their watches, and stale results cannot overwrite
recycled rows. Ordinary folders have no individual file monitors. On filesystems
without working notifications, reopening the folder refreshes the state.

**The inline badge adapter uses private Nautilus GTK widgets.** It targets the
Nautilus 51.1 layout and keeps per-folder zoom and multiple windows independent.
The public nautilus-python API cannot insert a styled badge into the filename
row. Nautilus upgrades may require adapter changes, and compatibility with all
Nautilus 4.x versions is not guaranteed. The adapter uses native GObject weak
references so tracking survives Python wrapper collection.

## License

The extension is licensed under [MIT](LICENSE).
