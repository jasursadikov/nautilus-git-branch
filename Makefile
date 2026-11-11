PYTHON ?= python3
DATA_HOME ?= $(HOME)/.local/share
EXTENSIONS_DIR = $(DATA_HOME)/nautilus-python/extensions
WHEELHOUSE ?=

.PHONY: install uninstall wheels test check srcinfo
install:
	$(PYTHON) tools/install.py --extensions-dir "$(DESTDIR)$(EXTENSIONS_DIR)" $(if $(WHEELHOUSE),--wheelhouse "$(WHEELHOUSE)")

wheels:
	$(PYTHON) -m pip download --only-binary=:all: --dest "$(or $(WHEELHOUSE),wheels)" -r requirements.txt

uninstall:
	rm -f "$(DESTDIR)$(EXTENSIONS_DIR)/nautilus_git_branch.py"
	rm -rf "$(DESTDIR)$(EXTENSIONS_DIR)/_nautilus_git_branch_vendor"

test:
	$(PYTHON) -m unittest discover -s tests -v

check: test
	$(PYTHON) -m py_compile nautilus_git_branch.py

srcinfo:
	makepkg --printsrcinfo > .SRCINFO
