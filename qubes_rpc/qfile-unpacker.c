#define _GNU_SOURCE
#include <ioall.h>
#include <grp.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <pwd.h>
#include <sys/stat.h>
#include <string.h>
#include <unistd.h>
#include <sys/fsuid.h>
#include <gui-fatal.h>
#include <errno.h>
#include "filecopy.h"
#define INCOMING_DIR_ROOT "/home/user/incoming"
int prepare_creds_return_uid(char *username)
{
	struct passwd *pwd;
	pwd = getpwnam(username);
	if (!pwd) {
		perror("getpwnam");
		exit(1);
	}
	setenv("HOME", pwd->pw_dir, 1);
	setenv("USER", username, 1);
	setgid(pwd->pw_gid);
	initgroups(username, pwd->pw_gid);
	setfsuid(pwd->pw_uid);
	return pwd->pw_uid;
}

void wait_for_child(int statusfd)
{
	int status;
	if (read(statusfd, &status, sizeof status)!=sizeof status)
		gui_fatal("File copy error: Internal error reading status from unpacker");
	errno = status;
	switch (status) {
	case LEGAL_EOF: break;
	case 0: gui_fatal("File copy: Connection terminated unexpectedly"); break;
	case EINVAL: gui_fatal("File copy: Corrupted data from packer"); break;
	case EEXIST: gui_fatal("File copy: not overwriting existing file. Clean ~/incoming, and retry copy"); break;
	default: gui_fatal("File copy"); 
	}
}

extern void do_unpack(int);

int main(int argc, char ** argv)
{
	char *incoming_dir;
	int pipefds[2];
	int uid;
	char *remote_domain;

	pipe(pipefds);

	uid = prepare_creds_return_uid("user");

	remote_domain = getenv("QREXEC_REMOTE_DOMAIN");
	if (!remote_domain) {
		gui_fatal("Cannot get remote domain name");
		exit(1);
	}
	mkdir(INCOMING_DIR_ROOT, 0700);
	asprintf(&incoming_dir, "%s/from-%s", INCOMING_DIR_ROOT, remote_domain);
	mkdir(incoming_dir, 0700);
	if (chdir(incoming_dir))
		gui_fatal("Error chdir to %s", incoming_dir); 
	switch (fork()) {
	case -1:
		perror("fork");
		exit(1);
	case 0:
		if (chroot(incoming_dir)) //impossible
			gui_fatal("Error chroot to %s", incoming_dir);
		setuid(uid);
		close(pipefds[0]);
		do_unpack(pipefds[1]);
		exit(0);
	default:;
	}

	close(0);
	close(1);
	setuid(uid);
	close(pipefds[1]);
	wait_for_child(pipefds[0]);

	return 0;
}
