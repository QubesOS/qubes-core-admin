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
	mkdir \
		$(DESTDIR)$(PYTHON_QUBESPATH)/vm \
		$(DESTDIR)$(PYTHON_QUBESPATH)/storage \
		$(DESTDIR)$(PYTHON_QUBESPATH)/tools \
		$(DESTDIR)$(PYTHON_QUBESPATH)/ext \
		$(DESTDIR)$(PYTHON_QUBESPATH)/tests \
		$(DESTDIR)$(PYTHON_QUBESPATH)/tests/vm \
		$(DESTDIR)$(PYTHON_QUBESPATH)/tests/tools

	cp \
		__init__.py* \
		_pluginloader.py* \
		config.py* \
		dochelpers.py* \
		events.py* \
		log.py* \
		plugins.py* \
		rngdoc.py* \
		utils.py* \
		$(DESTDIR)$(PYTHON_QUBESPATH)

	cp \
		vm/__init__.py* \
		vm/adminvm.py* \
		vm/appvm.py* \
		vm/dispvm.py* \
		vm/hvm.py* \
		vm/netvm.py* \
		vm/proxyvm.py* \
		vm/qubesvm.py* \
		vm/templatehvm.py* \
		vm/templatevm.py* \
		$(DESTDIR)$(PYTHON_QUBESPATH)/vm

	cp \
		storage/__init__.py* \
		storage/xen.py* \
		$(DESTDIR)$(PYTHON_QUBESPATH)/storage

	cp \
		tools/__init__.py* \
		tools/qvm_ls.py* \
		$(DESTDIR)$(PYTHON_QUBESPATH)/tools

	cp ext/__init__.py* $(DESTDIR)$(PYTHON_QUBESPATH)/ext

	cp \
		tests/__init__.py* \
		tests/events.py* \
		tests/init.py* \
		tests/run.py* \
		$(DESTDIR)$(PYTHON_QUBESPATH)/tests

	cp \
		tests/vm/__init__.py* \
		tests/vm/init.py* \
		tests/vm/adminvm.py* \
		tests/vm/qubesvm.py* \
		$(DESTDIR)$(PYTHON_QUBESPATH)/tests/vm

	cp \
		tests/tools/__init__.py* \
		tests/tools/qvm_ls.py* \
		$(DESTDIR)$(PYTHON_QUBESPATH)/tests/tools
