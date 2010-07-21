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

char xmlrpc_header[] =
    "POST /RPC2 HTTP/1.0\r\n"
    "Host: \r\n"
    "User-Agent: xmlrpclib.py/1.0.1 (by www.pythonware.com)\r\n"
    "Content-Type: text/xml\r\n" "Content-Length: %d\r\n" "\r\n";
char xmlrpc_body_restore[] =
    "<?xml version='1.0'?>\n"
    "<methodCall>\n"
    "<methodName>xend.domain.restore</methodName>\n"
    "<params>\n"
    "<param>\n"
    "<value><string>%s</string></value>\n"
    "</param>\n"
    "<param>\n"
    "<value><boolean>0</boolean></value>\n"
    "</param>\n" "</params>\n" "</methodCall>\n";

char xmlrpc_body_setmem[] =
    "<?xml version='1.0'?>\n<methodCall>\n<methodName>xend.domain.setMemoryTarget</methodName>\n<params>\n<param>\n<value><string>%d</string></value>\n</param>\n<param>\n<value><int>%d</int></value>\n</param>\n</params>\n</methodCall>\n";

void send_raw(int fd, char *body)
{
	char *header;
	asprintf(&header, xmlrpc_header, strlen(body));
	if (write(fd, header, strlen(header)) != strlen(header)) {
		perror("write xend");
		exit(1);
	}
	if (write(fd, body, strlen(body)) != strlen(body)) {
		perror("write xend");
		exit(1);
	}
	shutdown(fd, SHUT_WR);
}


void send_req_restore(int fd, char *name)
{
	char *body;
	asprintf(&body, xmlrpc_body_restore, name);
	send_raw(fd, body);
}

void send_req_setmem(int fd, int domid, int mem)
{
	char *body;
	asprintf(&body, xmlrpc_body_setmem, domid, mem);
	send_raw(fd, body);
}

char *recv_resp(int fd)
{
#define RESPSIZE 65536
	static char buf[RESPSIZE];
	int total = 0;
	int n;
	for (;;) {
		n = read(fd, buf + total, RESPSIZE - total);
		if (n == 0) {
			buf[total] = 0;
			close(fd);
			return buf;
		}
		if (n < 0) {
			perror("xend read");
			exit(1);
		}
		total += n;
	}
}

void bad_resp(char *resp)
{
	fprintf(stderr, "Error; Xend response:\n%s\n", resp);
	exit(1);
}

int parse_resp(char *resp)
{
	char *domid;
	if (strstr(resp, "<fault>"))
		bad_resp(resp);
	if (!strstr(resp, "domid"))
		bad_resp(resp);
	domid = strstr(resp, "<int>");
	if (!domid)
		bad_resp(resp);
	return strtoul(domid + 5, NULL, 0);
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

int xend_connect()
{
	struct sockaddr_un server;
	int s;

	s = socket(AF_UNIX, SOCK_STREAM, 0);
	if (s < 0) {
		perror("socket af_unix");
		exit(1);
	}
	server.sun_family = AF_UNIX;
	strcpy(server.sun_path, "/var/run/xend/xmlrpc.sock");
	if (connect
	    (s, (struct sockaddr *) &server,
	     strlen(server.sun_path) + sizeof(server.sun_family))) {
		perror("connext xend");
		exit(1);
	}
	return s;
}

void start_guid(int domid, int argc, char **argv)
{
	int i;
	char dstr[40];
	char *guid_args[argc + 2];
	snprintf(dstr, sizeof(dstr), "%d", domid);
	guid_args[0] = "qubes_guid";
	guid_args[1] = "-d";
	guid_args[2] = dstr;
	for (i = 2; i < argc; i++)
		guid_args[i + 1] = argv[i];
	guid_args[argc + 1] = NULL;
	execv("/usr/bin/qubes_guid", guid_args);
	perror("execv");
}

void fix_savefile(int fd, char *buf, char *pattern, char *val)
{
	int i, len = strlen(val), origlen;
	char *bracket;
	char *loc = strstr(buf + 20, pattern) + strlen(pattern);
	if (!loc)
		return;
	bracket = index(loc, ')');
	if (!bracket)
		return;
	origlen = (long) bracket - (long) loc;
	if (origlen < len) {
		fprintf(stderr, "too long string %s\n", val);
		exit(1);
	}
	for (i = 0; i < origlen - len; i++)
		loc[i] = ' ';
	memcpy(loc + i, val, strlen(val));
	lseek(fd, (long) loc - (long) buf, SEEK_SET);
	write(fd, loc, origlen);
}


char * dispname_by_dispid(int dispid)
{
	static char retbuf[16];
	snprintf(retbuf, sizeof(retbuf), "disp%d", dispid);
	return retbuf;
}

#define NAME_PATTERN "/root-cow.img"
char *fix_savefile_and_get_vmname(int fd, int dispid)
{
	static char buf[4096];
	char *name;
	char *slash;
	char val[256];
	if (read(fd, buf, sizeof(buf)) != sizeof(buf)) {
		perror("read savefile");
		exit(1);
	}
	buf[sizeof(buf) - 1] = 0;
	snprintf(val, sizeof(val),
		 "064cd14c-95ad-4fc2-a4c9-cf9f522e5b%02x", dispid);
	fix_savefile(fd, buf, "(uuid ", val);
	fix_savefile(fd, buf, "(name ", dispname_by_dispid(dispid));
	snprintf(val, sizeof(val), "00:16:3e:7c:8b:%02x", dispid);
	fix_savefile(fd, buf, "(mac ", val);
	lseek(fd, 0, SEEK_SET);
	name = strstr(buf + 20, NAME_PATTERN);
	if (!name) {
		fprintf(stderr,
			"cannot find 'root-cow.img' in savefile\n");
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


void setup_xenstore(int domid, char *name)
{
	char val[256];
	char netvm_id_path[256];
	int fd, n;
	char netvm_id[256];
	struct xs_handle *xs = xs_daemon_open();
	if (!xs) {
		perror("xs_daemon_open");
		exit(1);
	}
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

	snprintf(val, sizeof(val), "10.%s.%d.%d", netvm_id,
		 domid / 254 + 200, (domid % 254) + 1);
	write_xs_single(xs, domid, "qubes_ip", val);
	write_xs_single(xs, domid, "qubes_netmask", "255.255.0.0");
	snprintf(val, sizeof(val), "10.%s.0.1", netvm_id);
	write_xs_single(xs, domid, "qubes_gateway", val);
	snprintf(val, sizeof(val), "10.%s.255.254", netvm_id);
	write_xs_single(xs, domid, "qubes_secondary_dns", val);
	write_xs_single(xs, domid, "qubes_vm_type", "AppVM");
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

void write_varrun_domid(int domid, char * dispname, char *orig)
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
	int fd =
	    open("/var/log/qubes/qubes_restore.log",
		 O_CREAT | O_TRUNC | O_WRONLY, 0600);
	if (fd < 0) {
		syslog(LOG_DAEMON | LOG_ERR, "open qubes_restore.log");
		exit(1);
	}
	dup2(fd, 2);
}


int main(int argc, char **argv)
{
	int fd, domid, dispid;
	char *resp;
	char *name;
	if (argc < 2) {
		fprintf(stderr, "usage: %s savefile [guid args] \n",
			argv[0]);
		exit(1);
	}
	redirect_stderr();
	fprintf(stderr, "time=%s, starting\n", gettime());
	set_fast_flag();
	atexit(rm_fast_flag);
	fd = open(argv[1], O_RDWR);
	if (fd < 0) {
		perror("open savefile");
		exit(1);
	}
	dispid = get_next_disposable_id();
	name = fix_savefile_and_get_vmname(fd, dispid);
//      printf("name=%s\n", name);
	unpack_cows(name);
//      no preloading for now, assume savefile in shm
//      preload_cache(fd);
	fd = xend_connect();
	send_req_restore(fd, argv[1]);
	resp = recv_resp(fd);
	domid = parse_resp(resp);
	write_varrun_domid(domid, dispname_by_dispid(dispid), name);
	fprintf(stderr,
		"time=%s, created domid=%d, executing set_mem 400\n",
		gettime(), domid);
	fd = xend_connect();
	send_req_setmem(fd, domid, 400);
	resp = recv_resp(fd);
//      printf("%s\n", resp);
	fprintf(stderr, "time=%s, creating xenstore entries\n", gettime());
	setup_xenstore(domid, name);
	fprintf(stderr, "time=%s, starting qubes_guid\n", gettime());
	rm_fast_flag();
	start_guid(domid, argc, argv);
	return 0;
}
