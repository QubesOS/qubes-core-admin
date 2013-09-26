ifeq ($(PACKAGE_SET),dom0)
RPM_SPEC_FILES := $(addprefix rpm_spec/,core-dom0.spec core-dom0-doc.spec)
WIN_SOURCE_SUBDIRS := .
WIN_COMPILER := mingw
WIN_PACKAGE_CMD := make msi
endif
