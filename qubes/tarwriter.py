#!/usr/bin/python2
# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2016 Marek Marczykowski-Górecki
#                               <marmarek@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
import argparse
import functools
import subprocess
import tarfile
import io

BUF_SIZE = 409600


class TarSparseInfo(tarfile.TarInfo):
    def __init__(self, name="", sparsemap=None):
        super(TarSparseInfo, self).__init__(name)
        if sparsemap is not None:
            self.type = tarfile.GNUTYPE_SPARSE
            self.sparsemap = list(sparsemap)
            # compact size
            self.size = functools.reduce(lambda x, y: x+y[1], sparsemap, 0)
        else:
            self.sparsemap = []

    @property
    def realsize(self):
        if len(self.sparsemap):
            return self.sparsemap[-1][0] + self.sparsemap[-1][1]
        else:
            return self.size

    def sparse_header_chunk(self, index):
        if index < len(self.sparsemap):
            return ''.join([
                tarfile.itn(self.sparsemap[index][0], 12, tarfile.GNU_FORMAT),
                tarfile.itn(self.sparsemap[index][1], 12, tarfile.GNU_FORMAT),
            ])
        else:
            return '\0' * 12 * 2

    def get_gnu_header(self):
        '''Part placed in 'prefix' field of posix header'''

        parts = [
            tarfile.itn(self.mtime, 12, tarfile.GNU_FORMAT),  # atime
            tarfile.itn(self.mtime, 12, tarfile.GNU_FORMAT),  # ctime
            tarfile.itn(0, 12, tarfile.GNU_FORMAT),  # offset
            tarfile.stn('', 4),  # longnames
            '\0',  # unused_pad2
        ]
        parts += [self.sparse_header_chunk(i) for i in range(4)]
        parts += [
            '\1' if len(self.sparsemap) > 4 else '\0',  # isextended
            tarfile.itn(self.realsize, 12, tarfile.GNU_FORMAT),  # realsize
        ]
        return ''.join(parts)

    def get_info(self, encoding, errors):
        info = super(TarSparseInfo, self).get_info(encoding, errors)
        # place GNU extension into
        info['prefix'] = self.get_gnu_header()
        return info

    def tobuf(self, format=tarfile.DEFAULT_FORMAT, encoding=tarfile.ENCODING,
            errors="strict"):
        # pylint: disable=redefined-builtin
        header_buf = super(TarSparseInfo, self).tobuf(format, encoding, errors)
        if len(self.sparsemap) > 4:
            return header_buf + ''.join(self.create_ext_sparse_headers())
        else:
            return header_buf

    def create_ext_sparse_headers(self):
        for ext_hdr in range(4, len(self.sparsemap), 21):
            sparse_parts = [self.sparse_header_chunk(i) for i in
                range(ext_hdr, ext_hdr+21)]
            sparse_parts += '\1' if ext_hdr+21 < len(self.sparsemap) else '\0'
            yield tarfile.stn(''.join(sparse_parts), 512)


def get_sparse_map(input_file):
    '''
    Return map of the file where actual data is present, ignoring zero-ed
    blocks. Last entry of the map spans to the end of file, even if that part is
    zero-size (when file ends with zeros).

    This function is performance critical.

    :param input_file: io.File object
    :return: iterable of (offset, size)
    '''
    zero_block = bytearray(tarfile.BLOCKSIZE)
    buf = bytearray(BUF_SIZE)
    in_data_block = False
    data_block_start = 0
    buf_start_offset = 0
    while True:
        buf_len = input_file.readinto(buf)
        if not buf_len:
            break
        for offset in range(0, buf_len, tarfile.BLOCKSIZE):
            if buf[offset:offset+tarfile.BLOCKSIZE] == zero_block:
                if in_data_block:
                    in_data_block = False
                    yield (data_block_start,
                        buf_start_offset+offset-data_block_start)
            else:
                if not in_data_block:
                    in_data_block = True
                    data_block_start = buf_start_offset+offset
        buf_start_offset += buf_len
    if in_data_block:
        yield (data_block_start, buf_start_offset-data_block_start)
    else:
        # always emit last slice to the input end - otherwise extracted file
        # will be truncated
        yield (buf_start_offset, 0)


def copy_sparse_data(input_stream, output_stream, sparse_map):
    '''Copy data blocks from input to output according to sparse_map

    :param input_stream: io.IOBase input instance
    :param output_stream: io.IOBase output instance
    :param sparse_map: iterable of (offset, size)
    '''

    buf = bytearray(BUF_SIZE)

    for chunk in sparse_map:
        input_stream.seek(chunk[0])
        left = chunk[1]
        while left:
            if left > BUF_SIZE:
                read = input_stream.readinto(buf)
                output_stream.write(buf[:read])
            else:
                buf_trailer = input_stream.read(left)
                read = len(buf_trailer)
                output_stream.write(buf_trailer)
            left -= read
            if not read:
                raise Exception('premature EOF')

def finalize(output):
    '''Write EOF blocks'''
    output.write('\0' * 512)
    output.write('\0' * 512)

def main(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--override-name', action='store', dest='override_name',
        help='use this name in tar header')
    parser.add_argument('--use-compress-program', default=None,
        metavar='COMMAND', action='store', dest='use_compress_program',
        help='Filter data through COMMAND.')
    parser.add_argument('input_file',
        help='input file name')
    parser.add_argument('output_file', default='-', nargs='?',
        help='output file name')
    args = parser.parse_args(args)
    input_file = io.open(args.input_file, 'rb')
    sparse_map = list(get_sparse_map(input_file))
    header_name = args.input_file
    if args.override_name:
        header_name = args.override_name
    tar_info = TarSparseInfo(header_name, sparse_map)
    if args.output_file == '-':
        output = io.open('/dev/stdout', 'wb')
    else:
        output = io.open(args.output_file, 'wb')
    if args.use_compress_program:
        compress = subprocess.Popen([args.use_compress_program],
            stdin=subprocess.PIPE, stdout=output)
        output = compress.stdin
    else:
        compress = None
    output.write(tar_info.tobuf(tarfile.GNU_FORMAT))
    copy_sparse_data(input_file, output, sparse_map)
    finalize(output)
    input_file.close()
    output.close()
    if compress is not None:
        compress.wait()
        return compress.returncode
    return 0

if __name__ == '__main__':
    main()
