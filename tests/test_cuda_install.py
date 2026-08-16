# Moon Begin
import zipfile

import pytest

from service.app import pipeline


def test_cuda_wheel_extraction_writes_runtime_files_without_pip(tmp_path):
    wheel = tmp_path / "runtime.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("nvidia/cublas/bin/cublas64_12.dll", b"dll")
        archive.writestr("nvidia_cublas_cu12-1.0.dist-info/METADATA", b"metadata")
    events = []
    pipeline._extract_cuda_wheels([wheel], tmp_path / "installed", lambda *args: events.append(args), 10)
    assert (tmp_path / "installed" / "nvidia/cublas/bin/cublas64_12.dll").read_bytes() == b"dll"
    assert events


def test_cuda_wheel_extraction_rejects_path_traversal(tmp_path):
    wheel = tmp_path / "unsafe.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("../outside.dll", b"unsafe")
    with pytest.raises(RuntimeError, match="不安全文件路径"):
        pipeline._extract_cuda_wheels([wheel], tmp_path / "installed", lambda *_: None, 1)
    assert not (tmp_path / "outside.dll").exists()
# Moon End
