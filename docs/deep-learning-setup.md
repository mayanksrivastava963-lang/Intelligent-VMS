# Local deep learning environment

Use Python 3.12 and `services/ai_engine/.venv` for this Windows workstation.
VS Code is configured to use this interpreter. Open a new terminal after changing
the interpreter; existing terminals can still have the old root `.venv` active.
In notebooks, select `Intelligent VMS (Python 3.12 CUDA)` or this environment's
Python 3.12 interpreter.

From the repository root (PowerShell):

```powershell
.\services\ai_engine\.venv\Scripts\Activate.ps1
python scripts/check_deep_learning.py
python services/ai_engine/detection/detector.py
python -m jupyterlab
```

Activation is optional: use `services/ai_engine/.venv/Scripts/python.exe` directly
if PowerShell blocks activation. Do not change machine execution policy.

To recreate the environment with an installed Python 3.12:

```powershell
py -3.12 -m venv services/ai_engine/.venv
.\services\ai_engine\.venv\Scripts\python.exe -m pip install torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cu128
.\services\ai_engine\.venv\Scripts\python.exe -m pip install -r services/ai_engine/requirements.txt
.\services\ai_engine\.venv\Scripts\python.exe -m pip check
.\services\ai_engine\.venv\Scripts\python.exe scripts/check_deep_learning.py
```

The NVIDIA RTX 3050 has 4 GB VRAM. Start with small YOLO models, batch sizes of
1–4, and mixed precision; reduce image size or batch size if memory runs out.
PyTorch wheels include the CUDA runtime; the CUDA version shown by `nvidia-smi`
is the driver's supported version, and need not match the wheel's CUDA 12.8.

The exact installed Windows/Python 3.12 versions are saved in
`services/ai_engine/requirements-win-py312.lock.txt`. To reproduce those versions,
install CUDA PyTorch using the command above, then install that lock file instead
of the general requirements file.

The installed stack covers PyTorch/torchvision, Ultralytics YOLO, timm,
Transformers/Accelerate, OpenCV, scientific/data tools, notebooks, TensorBoard,
ONNX export and CPU ONNX Runtime, plus FastAPI and pytest. ONNX Runtime here is
CPU-only; GPU execution is verified through PyTorch. Model weights and datasets
are downloaded separately as needed. TensorFlow GPU requires a separate WSL2
setup on modern Windows and is not included in this PyTorch environment.
