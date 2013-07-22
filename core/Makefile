OS ?= Linux

PYTHON_QUBESPATH = $(PYTHON_SITEPATH)/qubes
SETTINGS_SUFFIX = $(BACKEND_VMM)-$(OS)

all:
	python -m compileall .
	python -O -m compileall .

install:
ifndef PYTHON_SITEPATH
	$(error PYTHON_SITEPATH not defined)
endif
	mkdir -p $(DESTDIR)$(PYTHON_QUBESPATH)
	cp qubes.py $(DESTDIR)$(PYTHON_QUBESPATH)
	cp qubes.py[co] $(DESTDIR)$(PYTHON_QUBESPATH)
	cp qubesutils.py $(DESTDIR)$(PYTHON_QUBESPATH)
	cp qubesutils.py[co] $(DESTDIR)$(PYTHON_QUBESPATH)
	cp guihelpers.py $(DESTDIR)$(PYTHON_QUBESPATH)
	cp guihelpers.py[co] $(DESTDIR)$(PYTHON_QUBESPATH)
	cp notify.py $(DESTDIR)$(PYTHON_QUBESPATH)
	cp notify.py[co] $(DESTDIR)$(PYTHON_QUBESPATH)
	cp backup.py $(DESTDIR)$(PYTHON_QUBESPATH)
	cp backup.py[co] $(DESTDIR)$(PYTHON_QUBESPATH)
ifneq ($(BACKEND_VMM),)
	test -r settings-$(SETTINGS_SUFFIX).py && \
		cp settings-$(SETTINGS_SUFFIX).py $(DESTDIR)$(PYTHON_QUBESPATH)/settings.py
	test -r settings-$(SETTINGS_SUFFIX).pyc && \
		cp settings-$(SETTINGS_SUFFIX).pyc $(DESTDIR)$(PYTHON_QUBESPATH)/settings.pyc
	test -r settings-$(SETTINGS_SUFFIX).pyo && \
		cp settings-$(SETTINGS_SUFFIX).pyo $(DESTDIR)$(PYTHON_QUBESPATH)/settings.pyo
endif
