# PyInstaller hook for numpy to prevent CPU dispatcher tracer issue
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hiddenimports = collect_submodules('numpy')
datas = collect_data_files('numpy')
