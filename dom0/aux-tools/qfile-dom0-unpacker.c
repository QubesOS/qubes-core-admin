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

#define DEFAULT_MAX_UPDATES_BYTES (2L<<30)
#define DEFAULT_MAX_UPDATES_FILES 2048

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
	char *var;
	long long files_limit = DEFAULT_MAX_UPDATES_FILES;
	long long bytes_limit = DEFAULT_MAX_UPDATES_BYTES;

	if (argc < 3) {
		fprintf(stderr, "Invalid parameters, usage: %s user dir\n", argv[0]);
		exit(1);
	}

	if ((var=getenv("UPDATES_MAX_BYTES")))
		bytes_limit = atoll(var);
	if ((var=getenv("UPDATES_MAX_FILES")))
		files_limit = atoll(var);

	pipe(pipefds);

	uid = prepare_creds_return_uid(argv[1]);

	incoming_dir = argv[2];
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
		set_size_limit(bytes_limit, files_limit);
		do_unpack(pipefds[1]);
		exit(0);
	default:;
	}

	setuid(uid);
	close(pipefds[1]);
	wait_for_child(pipefds[0]);

	return 0;
}
