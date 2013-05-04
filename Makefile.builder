ifeq ($(PACKAGE_SET),dom0)
RPM_SPEC_FILES := $(addprefix rpm_spec/,core-dom0.spec core-dom0-doc.spec)
endif
