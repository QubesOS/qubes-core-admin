#define _GNU_SOURCE
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <malloc.h>
#include <stdlib.h>
#include <unistd.h>
#include <stdarg.h>

static void fix_display()
{
	setenv("DISPLAY", ":0", 1);
}

static void produce_message(char * type, const char *fmt, va_list args)
{
	char *kdialog_msg;
	char buf[1024];
	(void) vsnprintf(buf, sizeof(buf), fmt, args);
	asprintf(&kdialog_msg, "%s: %s: %s (error type: %s)",
		 program_invocation_short_name, type, buf, strerror(errno));
	fprintf(stderr, "%s", kdialog_msg);
	switch (fork()) {
	case -1:
		exit(1);	//what else
	case 0:
		fix_display();
		execlp("kdialog", "kdialog", "--sorry", kdialog_msg, NULL);
		exit(1);
	default:;
	}
}

void gui_fatal(const char *fmt, ...)
{
	va_list args;
	va_start(args, fmt);
	produce_message("Fatal error", fmt, args);
	va_end(args);
	exit(1);
}

void gui_nonfatal(const char *fmt, ...)
{
	va_list args;
	va_start(args, fmt);
	produce_message("Information", fmt, args);
	va_end(args);
}
