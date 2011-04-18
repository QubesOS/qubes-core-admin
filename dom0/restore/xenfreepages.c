#include <xenctrl.h>
#include <stdio.h>
#include <stdlib.h>
struct xen_sysctl_physinfo xphysinfo;
main()
{
#ifdef XENCTRL_HAS_XC_INTERFACE
	xc_interface *handle = xc_interface_open(NULL, NULL, 0);
	if (!handle) {
#else
	int handle = xc_interface_open();
	if (handle == -1) {
#endif
		perror("xc_interface_open");
		exit(1);
	}
	if (xc_physinfo(handle, &xphysinfo)) {
		perror("xc_physinfo");
		exit(1);
	}
	printf("%lld", xphysinfo.free_pages);
	return 0;
}
