# PyInstaller Extractor

Fork from https://github.com/extremecoders-re/pyinstxtractor  
Fix some bug, code rebuild.  
Bugs: 
* fix pyc file magic header by the right python version, seen in [this](https://raw.githubusercontent.com/google/pytype/master/pytype/pyc/magic.py).


## How to use
```
$ python pyinstxtractor.py -h
usage: PyInstaller Extractor [-h] [-o OUTPUT] [--extract_pyz] file_path

positional arguments:
  file_path             target file target_path

optional arguments:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
                        output target_path, default module location.
  --extract_pyz         try decompress pyz.
```
If use --extract_pyz, script will try to decompress pyz file, but must ues same version of Python.  
You can now use a python decompiler on the pyc files within the extracted directory such like [Uncompyle6](https://github.com/rocky/python-uncompyle6/).
