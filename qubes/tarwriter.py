#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2016 Marek Marczykowski-Górecki
#                               <marmarek@invisiblethingslab.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, see <https://www.gnu.org/licenses/>.
import argparse
import functools
import os
import subprocess
import tarfile
import io

BUF_SIZE = 409600

class TarSparseInfo(tarfile.TarInfo):
    def __init__(self, name="", sparsemap=None):
        super().__init__(name)
        if sparsemap is not None:
            self.type = tarfile.REGTYPE
            self.sparsemap = sparsemap
            self.sparsemap_buf = self.format_sparse_map()
            # compact size
            self.size = functools.reduce(lambda x, y: x+y[1], sparsemap,
                0) + len(self.sparsemap_buf)
            self.pax_headers['GNU.sparse.major'] = '1'
            self.pax_headers['GNU.sparse.minor'] = '0'
            self.pax_headers['GNU.sparse.name'] = name
            self.pax_headers['GNU.sparse.realsize'] = str(self.realsize)
            self.name = '{}/GNUSparseFile.{}/{}'.format(
                os.path.dirname(name), os.getpid(), os.path.basename(name))
        else:
            self.sparsemap = []
            self.sparsemap_buf = b''

    @property
    def realsize(self):
        if self.sparsemap:
            return self.sparsemap[-1][0] + self.sparsemap[-1][1]
        return self.size

    def format_sparse_map(self):
        sparsemap_txt = (str(len(self.sparsemap)) + '\n' +
            ''.join('{}\n{}\n'.format(*entry) for entry in self.sparsemap))
        sparsemap_txt_len = len(sparsemap_txt)
        if sparsemap_txt_len % tarfile.BLOCKSIZE:
            padding = '\0' * (tarfile.BLOCKSIZE -
                              sparsemap_txt_len % tarfile.BLOCKSIZE)
        else:
            padding = ''
        return (sparsemap_txt + padding).encode()

    def tobuf(self, format=tarfile.PAX_FORMAT, encoding=tarfile.ENCODING,
            errors="strict"):
        # pylint: disable=redefined-builtin
        header_buf = super().tobuf(format, encoding, errors)
        return header_buf + self.sparsemap_buf

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
                raise EOFError('premature EOF')

def finalize(output):
    '''Write EOF blocks'''
    output.write(b'\0' * 512)
    output.write(b'\0' * 512)

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
    with io.open(args.input_file, 'rb') as input_file:
        sparse_map = list(get_sparse_map(input_file))
        header_name = args.input_file
        if args.override_name:
            header_name = args.override_name
        tar_info = TarSparseInfo(header_name, sparse_map)
        with io.open(('/dev/stdout' if args.output_file == '-'
                      else args.output_file),
                     'wb') as output:
            if args.use_compress_program:
                # pylint: disable=consider-using-with
                compress = subprocess.Popen([args.use_compress_program],
                    stdin=subprocess.PIPE, stdout=output)
                output = compress.stdin
            else:
                compress = None
            output.write(tar_info.tobuf(tarfile.PAX_FORMAT))
            copy_sparse_data(input_file, output, sparse_map)
            finalize(output)
    if compress is not None:
        compress.stdin.close()
        compress.wait()
        return compress.returncode
    return 0

if __name__ == '__main__':
    main()
