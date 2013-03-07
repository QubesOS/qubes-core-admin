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
#include <errno.h>
#include "filecopy.h"

#define DEFAULT_MAX_UPDATES_BYTES (2L<<30)
#define DEFAULT_MAX_UPDATES_FILES 2048

int prepare_creds_return_uid(char *username)
{
	struct passwd *pwd;
	// First try name
	pwd = getpwnam(username);
	if (!pwd) {
		// Then try UID
		pwd = getpwuid(atoi(username));
		if (!pwd) {
			perror("getpwuid");
			exit(1);
		}
	}
	setenv("HOME", pwd->pw_dir, 1);
	setenv("USER", pwd->pw_name, 1);
	setgid(pwd->pw_gid);
	initgroups(pwd->pw_name, pwd->pw_gid);
	setfsuid(pwd->pw_uid);
	return pwd->pw_uid;
}

extern int do_unpack(void);

int main(int argc, char ** argv)
{
	char *incoming_dir;
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

	uid = prepare_creds_return_uid(argv[1]);

	incoming_dir = argv[2];
	mkdir(incoming_dir, 0700);
	if (chdir(incoming_dir)) {
		fprintf(stderr, "Error chdir to %s", incoming_dir);
		exit(1);
	}
	if (chroot(incoming_dir)) {//impossible
		fprintf(stderr, "Error chroot to %s", incoming_dir);
		exit(1);
	}
	setuid(uid);
	set_size_limit(bytes_limit, files_limit);
	return do_unpack();
}
