int write_all(int fd, void *buf, int size);
int read_all(int fd, void *buf, int size);
int copy_fd_all(int fdout, int fdin);
void set_nonblock(int fd);
void set_block(int fd);
