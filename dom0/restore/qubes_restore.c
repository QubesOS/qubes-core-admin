#define _GNU_SOURCE
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <signal.h>
#include <unistd.h>
#include <sys/time.h>
#include <sys/wait.h>
#include <syslog.h>
#include <xs.h>

int restore_domain(char *restore_file, char *conf_file, char *name) {
	int pid, status, domid;
	int pipe_fd[2];
	char buf[256];
	char *endptr;
	switch (pid = fork()) {
	case -1:
		perror("fork");
		exit(1);
	case 0:
		close(1);
		if (dup2(open("/dev/null", O_RDWR), 1)==-1) {
			perror("dup2 or open");
			exit(1);
		}
		execl("/usr/sbin/xl", "xl", "restore", conf_file, restore_file, NULL);
		perror("execl");
		exit(1);
	default:;
	}
	if (waitpid(pid, &status, 0) < 0) {
		perror("waitpid");
		exit(1);
	}
	if (status != 0) {
		fprintf(stderr, "Error starting VM\n");
		exit(1);
	}

	// read domid
	if (pipe(pipe_fd)==-1) {
		perror("pipe");
		exit(1);
	}
	switch (pid = fork()) {
	case -1:
		perror("fork");
		exit(1);
	case 0:
		close(1);
		if (dup2(pipe_fd[1], 1) == -1) {
			perror("dup2");
			exit(1);
		}
		execl("/usr/sbin/xl", "xl", "domid", name, NULL);
		perror("execl");
		exit(1);
	default:;
	}
	read(pipe_fd[0], buf, sizeof(buf)-1);
	buf[sizeof(buf)-1] = 0;
	domid = strtoul(buf, &endptr, 10);
	if (domid <= 0 || *endptr != '\n') {
		fprintf(stderr, "Cannot get DispVM xid\n");
		exit(1);
	}
	if (waitpid(pid, &status, 0) < 0) {
		perror("waitpid");
		exit(1);
	}
	if (status != 0) {
		fprintf(stderr, "Error getting DispVM xid\n");
		exit(1);
	}
	return domid;
}


char *gettime()
{
	static char retbuf[60];
	struct timeval tv;
	gettimeofday(&tv, NULL);
	snprintf(retbuf, sizeof(retbuf), "%lld.%lld",
		 (long long) tv.tv_sec, (long long) tv.tv_usec);
	return retbuf;
}

int actually_do_unlink = 1;
#define FAST_FLAG_PATH "/var/run/qubes/fast_block_attach"
void set_fast_flag()
{
	int fd = open(FAST_FLAG_PATH, O_CREAT | O_RDONLY, 0600);
	if (fd < 0) {
		perror("set_fast_flag");
		exit(1);
	}
	close(fd);
}

void rm_fast_flag()
{
	if (actually_do_unlink)
		unlink(FAST_FLAG_PATH);
}

#define BUFSIZE (512*1024)
void do_read(int fd)
{
	static char buf[BUFSIZE];
	int n;
	while ((n = read(fd, buf, BUFSIZE))) {
		if (n < 0) {
			perror("read savefile");
			exit(1);
		}
	}
}

void preload_cache(int fd)
{
	signal(SIGCHLD, SIG_IGN);
	switch (fork()) {
	case -1:
		perror("fork");
		exit(1);
	case 0:
		actually_do_unlink = 0;
		do_read(fd);
		fprintf(stderr, "time=%s, fs cache preload complete\n",
			gettime());
		exit(0);
	default:
		close(fd);
	}
}

void start_rexec(int domid)
{
	int pid, status;
	char dstr[40];
	snprintf(dstr, sizeof(dstr), "%d", domid);
	switch (pid = fork()) {
	case -1:
		perror("fork");
		exit(1);
	case 0:
		execl("/usr/lib/qubes/qrexec_daemon", "qrexec_daemon",
		      dstr, NULL);
		perror("execl");
		exit(1);
	default:;
	}
	if (waitpid(pid, &status, 0) < 0) {
		perror("waitpid");
		exit(1);
	}
}


void start_guid(int domid, int argc, char **argv)
{
	int i;
	char dstr[40];
	char *guid_args[argc + 1];
	snprintf(dstr, sizeof(dstr), "%d", domid);
	guid_args[0] = "qubes_guid";
	guid_args[1] = "-d";
	guid_args[2] = dstr;
	for (i = 3; i < argc; i++)
		guid_args[i] = argv[i];
	guid_args[argc] = NULL;
	execv("/usr/bin/qubes_guid", guid_args);
	perror("execv");
}

char *dispname_by_dispid(int dispid)
{
	static char retbuf[16];
	snprintf(retbuf, sizeof(retbuf), "disp%d", dispid);
	return retbuf;
}

char *build_dvm_ip(int netvm, int id)
{
	static char buf[256];
	snprintf(buf, sizeof(buf), "10.138.%d.%d", netvm, (id % 254) + 1);
	return buf;
}

#define NAME_PATTERN "/volatile.img"
// replaces the unique portions of the savefile with per-dvm values
// returns the name of VM the savefile was taken for 
// by looking for /.../vmname/volatile.img
// normally, it should be "templatename-dvm"
char *get_vmname_from_savefile(int fd)
{
	int buflen;
	static char buf[4096];
	char *name;
	char *slash;
	lseek(fd, 0, SEEK_SET);
	buflen = read(fd, buf, sizeof(buf) - 1);
	if (buflen < 0) {
		perror("read vm conf");
		exit(1);
	}
	buf[buflen] = 0;
	name = strstr(buf + 20, NAME_PATTERN);
	if (!name) {
		fprintf(stderr,
			"cannot find 'volatile.img' in savefile\n");
		exit(1);
	}
	*name = 0;
	slash = name - 1;
	while (slash[0] && slash[0] != '/')
		slash--;
	if (!*slash) {
		fprintf(stderr, "cannot find / in savefile\n");
		exit(1);
	}
	return slash + 1;
}

void fill_field(FILE *conf, char *field, int dispid, int netvm_id)
{
	if (!strcmp(field, "NAME")) {
		fprintf(conf, "%s", dispname_by_dispid(dispid));
	} else if (!strcmp(field, "MAC")) {
		fprintf(conf, "00:16:3e:7c:8b:%02x", dispid);
	} else if (!strcmp(field, "IP")) {
		fprintf(conf, "%s", build_dvm_ip(netvm_id, dispid));
	} else if (!strcmp(field, "UUID")) {
		// currently not present in conf file
		fprintf(conf, "064cd14c-95ad-4fc2-a4c9-cf9f522e5b%02x", dispid);
	} else {
		fprintf(stderr, "unknown field in vm conf: %s\n", field);
		exit(1);
	}
}

// modify the config file. conf = FILE of the new config,
// conf_templ - fd of config template
// pattern - pattern to search for
// val - string to replace pattern with
void fix_conffile(FILE *conf, int conf_templ, int dispid, int netvm_id)
{
	int buflen = 0, cur_len = 0;
	char buf[4096];
	char *bufpos = buf;
	char *pattern, *patternend;

	/* read config template */
	lseek(conf_templ, 0, SEEK_SET);
	while ((cur_len = read(conf_templ, buf+cur_len, sizeof(buf)-cur_len)) > 0) {
		buflen+=cur_len;
	}
	if (cur_len < 0) {
		perror("read vm conf");
		exit(1);
	}

	while ((pattern = index(bufpos, '%'))) {
		fwrite(bufpos, 1, pattern-bufpos, conf);
		if (ferror(conf)) {
			perror("write vm conf");
			exit(1);
		}
		patternend = index(pattern+1, '%');
		if (!patternend) {
			fprintf(stderr, "Unmatched '%%' in VM config\n");
			exit(1);
		}
		*patternend = '\0';
		fill_field(conf, pattern+1, dispid, netvm_id);
		bufpos = patternend+1;
	}
	while ((cur_len = fwrite(bufpos, 1, buflen-(bufpos-buf), conf)) > 0) {
		bufpos+=cur_len;
	}
	if (ferror(conf)) {
		perror("write vm conf");
		exit(1);
	}
}


void unpack_cows(char *name)
{
	char vmdir[4096];
	char tarfile[4096];
	int status;
	snprintf(vmdir, sizeof(vmdir), "/var/lib/qubes/appvms/%s", name);
	snprintf(tarfile, sizeof(tarfile),
		 "/var/lib/qubes/appvms/%s/saved_cows.tar", name);
	switch (fork()) {
	case -1:
		fprintf(stderr, "fork");
		exit(1);
	case 0:
		execl("/bin/tar", "tar", "-C", vmdir, "-Sxf",
		      tarfile, NULL);
		perror("execl");
		exit(1);
	default:
		wait(&status);
		if (WEXITSTATUS(status)) {
			fprintf(stderr, "tar exited with status=0x%x\n",
				status);
			exit(1);
		}
		fprintf(stderr, "time=%s, cows restored\n", gettime());

	}
}

void write_xs_single(struct xs_handle *xs, int domid, char *name,
		     char *val)
{
	char key[256];
	snprintf(key, sizeof(key), "/local/domain/%d/%s", domid, name);
	if (!xs_write(xs, XBT_NULL, key, val, strlen(val))) {
		fprintf(stderr, "xs_write");
		exit(1);
	}
}

void perm_xs_single(struct xs_handle *xs, int domid, char *name,
		     struct xs_permissions *perms, int nperms)
{
	char key[256];
	snprintf(key, sizeof(key), "/local/domain/%d/%s", domid, name);
	if (!xs_set_permissions(xs, XBT_NULL, key, perms, nperms)) {
		fprintf(stderr, "xs_set_permissions");
		exit(1);
	}
}

int get_netvm_id_from_name(char *name)
{
	int fd, n;
	char netvm_id[256];
	char netvm_id_path[256];
	snprintf(netvm_id_path, sizeof(netvm_id_path),
		 "/var/lib/qubes/appvms/%s/netvm_id.txt", name);
	fd = open(netvm_id_path, O_RDONLY);
	if (fd < 0) {
		perror("open netvm_id");
		exit(1);
	}
	n = read(fd, netvm_id, sizeof(netvm_id) - 1);
	close(fd);
	netvm_id[n] = 0;
	return atoi(netvm_id);
}

void setup_xenstore(int netvm_id, int domid, int dvmid, char *name)
{
	char val[256];
	struct xs_handle *xs = xs_daemon_open();
	struct xs_permissions perm[1];
	if (!xs) {
		perror("xs_daemon_open");
		exit(1);
	}

	write_xs_single(xs, domid, "qubes_ip",
			build_dvm_ip(netvm_id, dvmid));
	write_xs_single(xs, domid, "qubes_netmask", "255.255.0.0");
	snprintf(val, sizeof(val), "10.137.%d.1", netvm_id);
	write_xs_single(xs, domid, "qubes_gateway", val);
	snprintf(val, sizeof(val), "10.137.%d.254", netvm_id);
	write_xs_single(xs, domid, "qubes_secondary_dns", val);
	write_xs_single(xs, domid, "qubes_vm_type", "AppVM");
	write_xs_single(xs, domid, "qubes_restore_complete", "True");

	perm[0].id = domid;
	perm[0].perms = XS_PERM_NONE;
	perm_xs_single(xs, domid, "device", perm, 1);
	perm_xs_single(xs, domid, "memory", perm, 1);

	xs_daemon_close(xs);

}

int get_next_disposable_id()
{
	int seq = 0;
	int fd = open("/var/run/qubes/dispVM_seq", O_RDWR);
	if (fd < 0) {
		perror("open dispVM_seq");
		exit(1);
	}
	read(fd, &seq, sizeof(seq));
	seq++;
	lseek(fd, 0, SEEK_SET);
	write(fd, &seq, sizeof(seq));
	close(fd);
	return seq;
}

void write_varrun_domid(int domid, char *dispname, char *orig)
{
	FILE *f = fopen("/var/run/qubes/dispVM_xid", "w");
	if (!f) {
		perror("fopen dispVM_xid");
		exit(1);
	}
	fprintf(f, "%d\n%s\n%s\n", domid, dispname, orig);
	fclose(f);
}


void redirect_stderr()
{
	int fd = open("/var/log/qubes/qubes_restore.log",
		      O_CREAT | O_TRUNC | O_WRONLY, 0600);
	if (fd < 0) {
		syslog(LOG_DAEMON | LOG_ERR, "open qubes_restore.log");
		exit(1);
	}
	dup2(fd, 2);
}


int main(int argc, char **argv)
{
	int conf_templ, domid, dispid, netvm_id;
	FILE *conf;
	char *name;
	char confname[256];
	if (argc < 3) {
		fprintf(stderr,
			"usage: %s savefile conf_templ [guid args] \n", argv[0]);
		exit(1);
	}
	redirect_stderr();
	fprintf(stderr, "time=%s, starting\n", gettime());
	set_fast_flag();
	atexit(rm_fast_flag);
	conf_templ = open(argv[2], O_RDONLY);
	if (conf_templ < 0) {
		perror("fopen vm conf");
		exit(1);
	}
	dispid = get_next_disposable_id();
	name = get_vmname_from_savefile(conf_templ);
	netvm_id = get_netvm_id_from_name(name);
	snprintf(confname, sizeof(confname), "/tmp/qubes-dvm-%d.xl", dispid);
	conf = fopen(confname, "w");
	if (!conf) {
		perror("fopen new vm conf");
		exit(1);
	}
	fix_conffile(conf, conf_templ, dispid, netvm_id);
	close(conf_templ);
	fclose(conf);
//      printf("name=%s\n", name);
	unpack_cows(name);
//      no preloading for now, assume savefile in shm
//      preload_cache(fd);
	domid=restore_domain(argv[1], confname, dispname_by_dispid(dispid));
	write_varrun_domid(domid, dispname_by_dispid(dispid), name);
	fprintf(stderr,
		"time=%s, created domid=%d, creating xenstore entries\n",
		gettime(), domid);
	setup_xenstore(netvm_id, domid, dispid, name);
	fprintf(stderr, "time=%s, starting qubes_guid\n", gettime());
	rm_fast_flag();
	start_rexec(domid);
	start_guid(domid, argc, argv);
	return 0;
}
