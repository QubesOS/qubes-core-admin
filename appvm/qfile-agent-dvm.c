#define _GNU_SOURCE
#include <dirent.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <signal.h>
#include <fcntl.h>
#include <malloc.h>
#include <stdlib.h>
#include <ioall.h>
#include <unistd.h>
#include "dvm2.h"

//the below usage of "system" is smelly, but should be fine - input comes from the same vm
void fatal(char *msg)
{
	char *errcmd;
	asprintf(&errcmd, "DISPLAY=:0 kdialog --sorry 'qfile-agent-dvm: %s'", msg);
	system(errcmd);
	perror(msg);
	exit(1);
}

void nonfatal(char *msg)
{
	char *errcmd;
	asprintf(&errcmd, "DISPLAY=:0 kdialog --sorry 'qfile-agent-dvm: %s'", msg);
	system(errcmd);
	fprintf(stderr, "%s", msg);
}

void send_file(char *fname)
{
	char *base;
	int fd = open(fname, O_RDONLY);
	if (fd < 0)
		fatal("open file_to_be_edited");
	base = rindex(fname, '/');
	if (!base)
		base = fname;
	else
		base++;
	if (strlen(base) >= DVM_FILENAME_SIZE)
		base += strlen(base) - DVM_FILENAME_SIZE + 1;
	if (!write_all(1, base, DVM_FILENAME_SIZE))
		fatal("send filename");
	if (!copy_fd_all(1, fd))
		fatal("send file");
	close(1);
}

int copy_and_return_nonemptiness(int tmpfd)
{
	struct stat st;
	if (!copy_fd_all(tmpfd, 0))
		fatal("receiving file");
	if (fstat(tmpfd, &st))
		fatal("fstat");
	close(tmpfd);

	return st.st_size;
}

void recv_file_nowrite(char *fname)
{
	char *tempfile;
	char *errmsg;
	int tmpfd;

	asprintf(&tempfile, "/tmp/file_edited_in_dvm.XXXXXX");
	tmpfd = mkstemp(tempfile);
	if (tmpfd < 0)
		fatal("unable to create any temporary file, aborting");
	if (!copy_and_return_nonemptiness(tmpfd)) {
		unlink(tempfile);
		return;
	}
	asprintf(&errmsg,
		 "The file %s has been edited in Disposable VM and the modified content has been received, "
		 "but this file is in nonwritable directory and thus cannot be modified safely. The edited file has been "
		 "saved to %s", fname, tempfile);
	nonfatal(errmsg);
}

void actually_recv_file(char *fname, char *tempfile, int tmpfd)
{
	if (!copy_and_return_nonemptiness(tmpfd)) {
		unlink(tempfile);
		return;
	}
	if (rename(tempfile, fname))
		fatal("rename");
}

void recv_file(char *fname)
{
	int tmpfd;
	char *tempfile;
	asprintf(&tempfile, "%s.XXXXXX", fname);
	tmpfd = mkstemp(tempfile);
	if (tmpfd < 0)
		recv_file_nowrite(fname);
	else
		actually_recv_file(fname, tempfile, tmpfd);
}

void talk_to_daemon(char *fname)
{
	send_file(fname);
	recv_file(fname);
}

void process_spoolentry(char *entry_name)
{
	char *abs_spool_entry_name;
	int entry_fd;
	struct stat st;
	char *filename;
	int entry_size;
	asprintf(&abs_spool_entry_name, "%s/%s", DVM_SPOOL, entry_name);
	entry_fd = open(abs_spool_entry_name, O_RDONLY);
	unlink(abs_spool_entry_name);
	if (entry_fd < 0 || fstat(entry_fd, &st))
		fatal("bad dvm_entry");
	entry_size = st.st_size;
	filename = calloc(1, entry_size + DVM_FILENAME_SIZE);
	if (!filename)
		fatal("malloc");
	if (!read_all(entry_fd, filename, entry_size))
		fatal("read dvm entry");
	close(entry_fd);
	talk_to_daemon(filename);
}

void scan_spool(char *name)
{
	struct dirent *ent;
	DIR *dir = opendir(name);
	if (!dir)
		fatal("opendir");
	while ((ent = readdir(dir))) {
		char *fname = ent->d_name;
		if (!strcmp(fname, ".") || !strcmp(fname, ".."))
			continue;
		process_spoolentry(fname);
		break;
	}
	closedir(dir);
}

int main()
{
	signal(SIGPIPE, SIG_IGN);
	scan_spool(DVM_SPOOL);
	return 0;
}
