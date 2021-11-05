# PyInstaller Extractor

Fork from https://github.com/extremecoders-re/pyinstxtractor  
Fix some bug, rebuild code.

Fixed Bugs: 
* fix pyc file magic header by Python version of the PyInstaller package, seen in [here](https://raw.githubusercontent.com/google/pytype/master/pytype/pyc/magic.py).

Known Problems:
* be attention, decompress pyz need the same Python version of the PyInstaller package.

## How to use
```
$ python pyinstxtractor.py -h
usage: pyinstxtractor.py [-h] [-o OUTPUT] [--extract_pyz] file_path

positional arguments:
  file_path             target file target_path

optional arguments:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
                        output target_path, default module location.
  --extract_pyz         try decompress pyz.
```
When use --extract_pyz, script will try to decompress pyz file, but must use the same Python version of the PyInstaller package.  
You can use a python decompiler on the pyc files within the extracted directory such like [Uncompyle6](https://github.com/rocky/python-uncompyle6/).
