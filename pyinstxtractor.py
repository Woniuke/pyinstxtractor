import argparse
import logging
import marshal
import os
import struct
import zlib
from collections import namedtuple
from importlib.util import MAGIC_NUMBER
from uuid import uuid4 as unique_name

PYC_MAGIC = {(1, 5): 20121, (1, 6): 50428, (2, 0): 50823, (2, 1): 60202, (2, 2): 60717, (2, 3): 62021, (2, 4): 62061,
             (2, 5): 62131, (2, 6): 62161, (2, 7): 62211, (3, 0): 3131, (3, 1): 3151, (3, 2): 3180, (3, 3): 3230,
             (3, 4): 3310, (3, 5): 3351, (3, 6): 3379, (3, 7): 3394, (3, 8): 3413, (3, 9): 3425, (3, 10): 3439}
PYINST20_COOKIE_SIZE = 24           # For pyinstaller 2.0
PYINST21_COOKIE_SIZE = 24 + 64      # For pyinstaller 2.1+
MAGIC = b'MEI\014\013\012\013\016'  # Magic number which identifies pyinstaller

CTOCEntry = namedtuple('CTOCEntry', ['position',
                                     'compressed_data_size',
                                     'uncompressed_data_size',
                                     'compress_flag',
                                     'type_compressed_data',
                                     'name'])

logger = logging.Logger('PyInstArchive')
logger_default = logging.StreamHandler()
logger_default.setFormatter(
    logging.Formatter('[*]%(funcName)s | %(asctime)s - %(levelname)s: %(message)s'))
logger_default.setLevel(logging.INFO)
logger.addHandler(logger_default)


class PyInstArchive:
    def __init__(self, target_path, output_path, extract_pyz=False):
        self.extraction_dir = output_path
        self.target_file_path = target_path
        self.target_fp = None
        self.target_file_size = None
        self.cookie_pos = None
        self.pyinstaller_ver = None
        self.overlay_size = None
        self.overlay_pos = None
        self.contents_table_pos = None
        self.contents_table_size = None
        self.toc_list = list()
        self.py_ver = None
        self.extract_pyz = extract_pyz

    def open(self):
        try:
            self.target_fp = open(self.target_file_path, 'rb')
            self.target_file_size = os.stat(self.target_file_path).st_size
        except Exception as e:
            logger.warning(f'Could not open {self.target_file_path}, {e}')
            if self.target_fp:
                self.target_fp.close()
            return False
        return True

    def close(self):
        self.target_fp.close()

    def check_file(self):
        logger.info('Processing {0}'.format(self.target_file_path))
        search_chunk_size = 0x2000
        end_pos = self.target_file_size
        self.cookie_pos = -1

        if end_pos < len(MAGIC):
            logger.warning('File is too short or truncated')
            return False

        while True:
            start_pos = end_pos - search_chunk_size if end_pos >= search_chunk_size else 0
            chunk_size = end_pos - start_pos
            if chunk_size < len(MAGIC):
                break
            self.target_fp.seek(start_pos, os.SEEK_SET)
            data = self.target_fp.read(chunk_size)
            offs = data.rfind(MAGIC)
            if offs != -1:
                self.cookie_pos = start_pos + offs
                break
            end_pos = start_pos + len(MAGIC) - 1
            if start_pos == 0:
                break

        if self.cookie_pos == -1:
            logger.warning('Missing cookie, unsupported pyinstaller version or not a pyinstaller archive')
            return False

        self.target_fp.seek(self.cookie_pos + PYINST20_COOKIE_SIZE, os.SEEK_SET)

        if b'python' in self.target_fp.read(64):
            logger.info('Pyinstaller version: 2.1+')
            self.pyinstaller_ver = 21  # pyinstaller 2.1+
        else:
            self.pyinstaller_ver = 20  # pyinstaller 2.0
            logger.info('Pyinstaller version: 2.0')
        return True

    def get_compress_archive_info(self):
        try:
            self.target_fp.seek(self.cookie_pos, os.SEEK_SET)
            if self.pyinstaller_ver == 20:
                magic, length_of_package, toc, toc_len, self.py_ver = \
                    struct.unpack('!8siiii', self.target_fp.read(PYINST20_COOKIE_SIZE))
            elif self.pyinstaller_ver == 21:
                magic, length_of_package, toc, toc_len, self.py_ver, py_libname = \
                    struct.unpack('!8siiii64s', self.target_fp.read(PYINST21_COOKIE_SIZE))
                logger.debug(f'py_libname: {py_libname}')
            else:
                raise Exception(f'Can not match pyinstaller version {self.pyinstaller_ver}')
        except Exception as e:
            logger.warning(f'The file is not a pyinstaller archive. {e}')
            return False

        logger.info('Python version: {0}'.format(self.py_ver))
        # Additional data after the cookie
        tail_bytes = self.target_file_size - self.cookie_pos - (
            PYINST20_COOKIE_SIZE if self.pyinstaller_ver == 20 else PYINST21_COOKIE_SIZE)
        # Overlay is the data appended at the end of the PE
        self.overlay_size = length_of_package + tail_bytes
        self.overlay_pos = self.target_file_size - self.overlay_size
        self.contents_table_pos = self.overlay_pos + toc
        self.contents_table_size = toc_len
        logger.info('length of package: {0} bytes'.format(length_of_package))
        return True

    def parse_toc(self):
        # Go to the table of contents
        self.target_fp.seek(self.contents_table_pos, os.SEEK_SET)
        parsed_len = 0
        # Parse table of contents
        while parsed_len < self.contents_table_size:
            entry_size, = struct.unpack('!i', self.target_fp.read(4))
            name_len = struct.calcsize('!iiiiBc')
            entry_pos, cmprsd_data_size, uncmprsd_data_size, cmprs_flag, type_cmprs_data, name = \
                struct.unpack(
                    '!iiiBc{0}s'.format(entry_size - name_len),
                    self.target_fp.read(entry_size - 4))

            name = name.decode('utf-8').rstrip('\0')
            if len(name) == 0:
                name = str(unique_name())
                logger.warning(f'Found an unnamed file in CArchive. Using random name {name}')

            self.toc_list.append(
                CTOCEntry(
                    self.overlay_pos + entry_pos,
                    cmprsd_data_size,
                    uncmprsd_data_size,
                    cmprs_flag,
                    type_cmprs_data,
                    name
                ))

            parsed_len += entry_size
        logger.info(f'Found {len(self.toc_list)} files in CArchive')

    def _write_raw_data(self, filepath, data):
        nm = filepath.replace('\\', os.path.sep).replace('/', os.path.sep).replace('..', '__')
        nm_dir = os.path.dirname(nm)
        if nm_dir != '' and not os.path.exists(nm_dir):  # Check if target_path exists, create if not
            os.makedirs(nm_dir)
        with open(nm, 'wb') as f:
            f.write(data)

    def extract_files(self):
        logger.info('Beginning extraction...please standby')
        if not os.path.exists(self.extraction_dir):
            os.mkdir(self.extraction_dir)

        os.chdir(self.extraction_dir)

        for entry in self.toc_list:
            base_path = os.path.dirname(entry.name)
            if base_path != '':
                # Check if target_path exists, create if not
                if not os.path.exists(base_path):
                    os.makedirs(base_path)

            self.target_fp.seek(entry.position, os.SEEK_SET)
            data = self.target_fp.read(entry.compressed_data_size)

            if entry.compress_flag == 1:
                data = zlib.decompress(data)
                # Malware may tamper with the uncompressed size
                # Comment out the assertion in such a case
                assert len(data) == entry.uncompressed_data_size  # Sanity Check

            if entry.type_compressed_data == b's':
                # s -> ARCHIVE_ITEM_PYSOURCE
                # Entry point are expected to be python scripts
                logger.info('Possible entry point: {0}.pyc'.format(entry.name))
                self._write_pyc(entry.name + '.pyc', data)

            elif entry.type_compressed_data == b'M' or entry.type_compressed_data == b'm':
                # M -> ARCHIVE_ITEM_PYPACKAGE
                # m -> ARCHIVE_ITEM_PYMODULE
                # packages and modules are pyc files with their header's intact
                self._write_pyc(entry.name + '.pyc', data)

            else:
                self._write_raw_data(entry.name, data)
                if self.extract_pyz and (entry.type_compressed_data == b'z' or entry.type_compressed_data == b'Z'):
                    with open(entry.name, 'rb') as f:
                        pyz_magic = f.read(4)
                        assert pyz_magic == b'PYZ\0'
                        pyc_magic = f.read(4)
                    if pyc_magic == MAGIC_NUMBER:
                        self._extract_pyz(entry.name)
                    else:
                        logger.warning('extract pyz must use same Python version!')

    def _write_pyc(self, filename, data):
        with open(filename, 'wb') as pyc_file:
            pyc_magic = PYC_MAGIC[(int(str(self.py_ver)[0]), int(str(self.py_ver)[1:]))]
            pyc_file.write(struct.pack("<H", pyc_magic))  # pyc magic
            if self.py_ver >= 37:  # PEP 552 -- Deterministic pycs
                pyc_file.write(b'\0' * 4)  # Bitfield
                pyc_file.write(b'\0' * 8)  # (Timestamp + size) || hash

            else:
                pyc_file.write(b'\0' * 4)  # Timestamp
                if self.py_ver >= 33:
                    pyc_file.write(b'\0' * 4)  # Size parameter added in Python 3.3
            pyc_file.write(data)

    def _extract_pyz(self, name):
        dir_name = name + '_extracted'
        # Create a directory for the contents of the pyz
        if not os.path.exists(dir_name):
            os.mkdir(dir_name)

        with open(name, 'rb') as f:
            f.seek(8, os.SEEK_SET)
            toc_position, = struct.unpack('!i', f.read(4))
            f.seek(toc_position, os.SEEK_SET)
            try:
                toc = marshal.load(f)
            except Exception as e:
                logger.warning(f'Unmarshalling FAILED. Cannot extract {name}. Extracting remaining files. {e}')
                return

            logger.info(f'Found {len(toc)} files in PYZ archive')

            # From pyinstaller 3.1+ toc is a list of tuples
            if type(toc) == list:
                toc = dict(toc)

            for key in toc.keys():
                (ispkg, pos, length) = toc[key]
                f.seek(pos, os.SEEK_SET)
                file_name = key
                try:
                    # for Python > 3.3 some keys are bytes object some are str object
                    file_name = file_name.decode('utf-8')
                except:
                    pass
                # Prevent writing outside dirName
                file_name = file_name.replace('..', '__').replace('.', os.path.sep)
                if ispkg == 1:
                    file_path = os.path.join(dir_name, file_name, '__init__.pyc')
                else:
                    file_path = os.path.join(dir_name, file_name + '.pyc')
                file_dir = os.path.dirname(file_path)
                if not os.path.exists(file_dir):
                    os.makedirs(file_dir)
                try:
                    data = f.read(length)
                    data = zlib.decompress(data)
                except Exception as e:
                    logger.warning(f'Failed to decompress {file_path}, probably encrypted. {e}.')
                    open(file_path + '.encrypted', 'wb').write(data)
                else:
                    self._write_pyc(file_path, data)


def main():
    parser = argparse.ArgumentParser('PyInstaller Extractor')
    parser.add_argument('file_path', type=str, help='target file target_path')
    parser.add_argument('-o', '--output', type=str, help='output target_path, default module location.')
    parser.add_argument('--extract_pyz', action='store_true', help='try decompress pyz.')
    args = parser.parse_args()

    target_file_path = args.file_path
    output_path = args.output

    if output_path is None:
        output_path = os.path.join(os.getcwd(), os.path.basename(target_file_path) + '_extracted')
    else:
        if not os.path.exists(output_path):
            os.mkdir(output_path)
        output_path = os.path.join(output_path, os.path.basename(target_file_path) + '_extracted')

    arch = PyInstArchive(target_file_path, output_path, args.extract_pyz)
    if arch.open():
        if arch.check_file():
            if arch.get_compress_archive_info():
                arch.parse_toc()
                arch.extract_files()
                arch.close()
        arch.close()


if __name__ == '__main__':
    main()
