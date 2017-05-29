#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/un.h>


#define QUBESD_SOCKET "/var/run/qubesd.sock"

void write_wrapper(int fd, char *data, size_t len) {
    size_t written = 0;
    int ret;
    while (written < len) {
        ret = write(fd, data+written, len-written);
        if (ret == -1) {
            perror("write");
            exit(1);
        }
        written += ret;
    }
}

int main(int argc, char **argv) {
    char *source_domain = getenv("QREXEC_REMOTE_DOMAIN");
    char *target_domain = getenv("QREXEC_REQUESTED_TARGET");
    char *service_name = strrchr(argv[0], '/');
    int fd;
    char buf[4096];
    int read_ret;
    struct sockaddr_un qubesd_addr = {
        .sun_family = AF_UNIX,
        .sun_path = QUBESD_SOCKET,
    };

    if (service_name)
        service_name++;

    if (!source_domain || !target_domain || !service_name || argc > 2) {
        fprintf(stderr, "Usage: %s [service-argument]\n", argv[0]);
        fprintf(stderr, "\n");
        fprintf(stderr, "Expected environment variables:\n");
        fprintf(stderr, " - QREXEC_REMOTE_DOMAIN - source domain for the call\n");
        fprintf(stderr, " - QREXEC_REQUESTED_TARGET - target domain for the call\n");
        fprintf(stderr, "\n");
        fprintf(stderr, "Additionally, this program assumes being called with desired service name as argv[0] (use symlink)\n");
        return 1;
    }

    fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd == -1) {
        perror("socket");
        return 1;
    }

    if (connect(fd, (struct sockaddr *)&qubesd_addr, sizeof(qubesd_addr)) == -1) {
        perror("connect to qubesd");
        return 1;
    }

    // write parameters, including trailing zero as separator
    write_wrapper(fd, source_domain, strlen(source_domain) + 1);
    write_wrapper(fd, service_name, strlen(service_name) + 1);
    write_wrapper(fd, target_domain, strlen(target_domain) + 1);
    if (argc == 2)
        write_wrapper(fd, argv[1], strlen(argv[1]) + 1);
    else
        // empty argument
        write_wrapper(fd, "\0", 1);

    // now, read from stdin and write it to qubesd
    while ((read_ret = read(0, buf, sizeof(buf))) > 0)
        write_wrapper(fd, buf, read_ret);

    if (read_ret == -1) {
        perror("read from stdin");
        return 1;
    }

	// end of request, now let qubesd execute the action and return response
    shutdown(fd, SHUT_WR);

    // then, retrieve the response from qubesd and send it to stdout
    while ((read_ret = read(fd, buf, sizeof(buf))) > 0)
        write_wrapper(1, buf, read_ret);

    if (read_ret == -1) {
        perror("read from qubesd");
        return 1;
    }

    return 0;
}

